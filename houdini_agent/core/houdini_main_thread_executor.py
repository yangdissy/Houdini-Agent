# -*- coding: utf-8 -*-
"""Lifecycle-safe Houdini main-thread tool execution."""

from __future__ import annotations

import queue
import threading
from itertools import count
from typing import Callable, Dict, List, Optional, Tuple


ToolResult = Dict[str, object]
ToolBatch = List[Tuple[str, dict]]
OPERATION_ID_KEY = "_ha_operation_id"


class HoudiniMainThreadExecutor:
    """Owns queueing state for Houdini tools dispatched to the Qt main thread."""

    _MUTATING_TOOLS = frozenset({
        "create_node", "create_nodes_batch", "create_wrangle_node",
        "delete_node", "rename_node", "set_node_parameter", "connect_nodes",
        "copy_node", "batch_set_parameters", "set_display_flag",
        "execute_python", "save_hip", "run_skill",
    })

    _COOK_TRIGGERING_TOOLS = frozenset({
        "connect_nodes", "set_display_flag", "set_node_parameter",
        "batch_set_parameters", "execute_python", "run_skill",
    })

    _COOK_BEFORE_READ_TOOLS = frozenset({
        "get_network_structure", "get_node_parameters", "list_children",
        "check_errors", "verify_network", "capture_viewport",
    })

    def __init__(
        self,
        emit_tool_request: Callable[[str, dict], None],
        emit_batch_request: Callable[[ToolBatch], None],
        result_queue: "queue.Queue",
        main_timeout: float = 120.0,
        batch_timeout: float = 60.0,
    ):
        self._emit_tool_request = emit_tool_request
        self._emit_batch_request = emit_batch_request
        self._result_queue = result_queue
        self._main_timeout = main_timeout
        self._batch_timeout = batch_timeout
        self._lock = threading.Lock()
        self._operation_ids = count(1)
        self._active_operation_id = None
        self._blocked = False
        self._shutdown = False

    def is_blocked(self) -> bool:
        return self._blocked

    def is_shutdown(self) -> bool:
        return self._shutdown

    def shutdown(self):
        with self._lock:
            self._shutdown = True
            self._blocked = True
            self._active_operation_id = None
            self._drain_results()

    def execute(self, tool_name: str, kwargs: dict) -> ToolResult:
        with self._lock:
            guard = self._guard_result(tool_name)
            if guard is not None:
                return guard

            operation_id = next(self._operation_ids)
            self._active_operation_id = operation_id
            self._drain_results()
            request_kwargs = dict(kwargs or {})
            request_kwargs[OPERATION_ID_KEY] = operation_id
            self._emit_tool_request(tool_name, request_kwargs)

            try:
                result = self._get_matching_result(operation_id, self._main_timeout)
                if self._active_operation_id == operation_id:
                    self._active_operation_id = None
                return result
            except queue.Empty:
                self._blocked = True
                self._active_operation_id = operation_id
                return {
                    "success": False,
                    "error": (
                        f"操作超时（{int(self._main_timeout)}秒）：Houdini 主线程可能仍在执行 {tool_name}。"
                        "为避免崩溃，后续 Houdini 工具执行已阻止；请停止当前 Agent 或重启面板后再继续。"
                    ),
                }

    def execute_batch(self, batch: ToolBatch) -> List[ToolResult]:
        with self._lock:
            guard = self._guard_result("batch")
            if guard is not None:
                return [guard for _ in batch]

            operation_id = next(self._operation_ids)
            self._active_operation_id = operation_id
            self._drain_results()
            request_batch = [
                (tool_name, self._with_operation_id(kwargs, operation_id))
                for tool_name, kwargs in batch
            ]
            self._emit_batch_request(request_batch)

            try:
                results = self._get_matching_result(operation_id, self._batch_timeout)
                if self._active_operation_id == operation_id:
                    self._active_operation_id = None
                if isinstance(results, list):
                    return results
                return [results] if isinstance(results, dict) else [
                    {"success": False, "error": "批量工具主线程执行返回了无效结果"}
                ]
            except queue.Empty:
                self._blocked = True
                self._active_operation_id = operation_id
                return [
                    {
                        "success": False,
                        "error": "批量工具执行超时：Houdini 主线程可能仍忙。为避免崩溃，后续 Houdini 工具执行已阻止。",
                    }
                    for _ in batch
                ]

    def run_in_main_thread(
        self,
        tool_name: str,
        kwargs: dict,
        execute_tool: Callable[[str, dict], ToolResult],
        cook_before_read: Callable[[], None],
        snapshot_network_children: Callable[[], dict],
        diff_network_children: Callable[[dict, dict], Optional[dict]],
        refresh_selection_baseline: Callable[[], None],
        self_tracking_tools,
        error_formatter: Callable[[Exception], str],
    ) -> ToolResult:
        result: ToolResult = {"success": False, "error": "Unknown error"}
        use_undo_group = tool_name in self._MUTATING_TOOLS

        self._set_manual_mode_for_cook_guard(tool_name)

        if tool_name in self._COOK_BEFORE_READ_TOOLS:
            cook_before_read()

        should_snapshot = (
            tool_name in self._MUTATING_TOOLS
            and tool_name not in self_tracking_tools
            and tool_name != "save_hip"
        )
        before_children = snapshot_network_children() if should_snapshot else {}

        try:
            if use_undo_group:
                use_undo_group = self._begin_undo_group(tool_name)

            result = execute_tool(tool_name, kwargs)
        except Exception as exc:
            result = {"success": False, "error": error_formatter(exc)}
        finally:
            if should_snapshot and result.get("success"):
                try:
                    after_children = snapshot_network_children()
                    changes = diff_network_children(before_children, after_children)
                    if changes:
                        result["_node_changes"] = changes
                except Exception:
                    pass

            if use_undo_group:
                self._end_undo_group()

            refresh_selection_baseline()

        return result

    def attach_result(self, operation_id, result):
        return {"operation_id": operation_id, "result": result}

    def _guard_result(self, tool_name: str):
        if self._shutdown:
            return {"success": False, "error": f"Houdini 主线程执行器已关闭，拒绝执行 {tool_name}"}
        if self._blocked:
            return {
                "success": False,
                "error": f"Houdini 主线程执行器处于阻塞状态，拒绝执行 {tool_name}，以避免崩溃。请重启面板后再继续。",
            }
        return None

    def _drain_results(self):
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

    @staticmethod
    def _with_operation_id(kwargs: dict, operation_id: int) -> dict:
        request_kwargs = dict(kwargs or {})
        request_kwargs[OPERATION_ID_KEY] = operation_id
        return request_kwargs

    def _get_matching_result(self, operation_id: int, timeout: float):
        while True:
            item = self._result_queue.get(timeout=timeout)
            if isinstance(item, dict) and "operation_id" in item and "result" in item:
                if item.get("operation_id") != operation_id:
                    continue
                return item.get("result")
            return item

    def _set_manual_mode_for_cook_guard(self, tool_name: str):
        if tool_name not in self._COOK_TRIGGERING_TOOLS:
            return
        try:
            import hou  # type: ignore
            if hou.updateModeSetting() != hou.updateMode.Manual:
                hou.setUpdateMode(hou.updateMode.Manual)
        except Exception:
            pass

    def _begin_undo_group(self, tool_name: str) -> bool:
        try:
            import hou  # type: ignore
            hou.undos.beginGroup(f"AI Agent: {tool_name}")
            return True
        except Exception:
            return False

    def _end_undo_group(self):
        try:
            import hou  # type: ignore
            hou.undos.endGroup()
        except Exception:
            pass
