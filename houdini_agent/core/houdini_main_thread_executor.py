# -*- coding: utf-8 -*-
"""Lifecycle-safe Houdini main-thread tool execution."""

from __future__ import annotations

import queue
import hashlib
import json
import sys
import threading
import time
import traceback
import uuid
from itertools import count
from typing import Callable, Dict, List, Optional, Tuple


ToolResult = Dict[str, object]
ToolBatch = List[Tuple[str, dict]]
OPERATION_ID_KEY = "_ha_operation_id"
RECEIPT_PROTOCOL_VERSION = 1


class HoudiniMainThreadExecutor:
    """Owns queueing state for Houdini tools dispatched to the Qt main thread."""

    def __init__(
        self,
        emit_tool_request: Callable[[str, dict], None],
        emit_batch_request: Callable[[ToolBatch], None],
        result_queue: "queue.Queue",
        main_timeout: float = 120.0,
        batch_timeout: float = 60.0,
        record_event: Optional[Callable[[dict], None]] = None,
        session_id_provider: Optional[Callable[[], str]] = None,
        identity_provider: Optional[Callable[[], dict]] = None,
        max_receipts: int = 32,
    ):
        self._emit_tool_request = emit_tool_request
        self._emit_batch_request = emit_batch_request
        self._result_queue = result_queue
        self._main_timeout = main_timeout
        self._batch_timeout = batch_timeout
        self._record_event_callback = record_event
        self._session_id_provider = session_id_provider
        self._identity_provider = identity_provider
        self._lock = threading.Lock()
        self._receipt_lock = threading.Lock()
        self._operation_ids = count(1)
        self._max_receipts = max(1, int(max_receipts))
        self._receipts = {}
        self._receipt_ids_by_correlation = {}
        self._active_operation_id = None
        self._blocked = False
        self._shutdown = False
        self._explicit_update_mode = None

    def set_explicit_update_mode(self, mode: Optional[str]) -> None:
        """Record the current run's explicit persistent update-mode intent."""
        normalized = str(mode or "").strip().lower()
        self._explicit_update_mode = normalized if normalized in {"auto", "manual"} else None

    def is_blocked(self) -> bool:
        return self._blocked

    def is_shutdown(self) -> bool:
        return self._shutdown

    def shutdown(self):
        with self._receipt_lock:
            for receipt in self._receipts.values():
                if receipt["state"] in {"accepted", "running"}:
                    self._update_receipt_locked(
                        receipt,
                        wait_status="owner_shutdown",
                        scene_consistency="unknown",
                    )
        with self._lock:
            self._shutdown = True
            self._blocked = True
            self._active_operation_id = None
            self._drain_results()
            self._record_event("main_thread_executor_shutdown", state="shutdown")

    def execute(self, tool_name: str, kwargs: dict) -> ToolResult:
        with self._lock:
            guard = self._guard_result(tool_name)
            if guard is not None:
                return guard

            operation_id = next(self._operation_ids)
            receipt = self._create_receipt(operation_id, tool_name, 1, kwargs)
            if receipt is None:
                return {"success": False, "error": "Operation receipt capacity reached; refusing new Houdini execution"}
            self._active_operation_id = operation_id
            self._drain_results()
            request_kwargs = dict(kwargs or {})
            request_kwargs[OPERATION_ID_KEY] = operation_id
            start = time.monotonic()
            self._record_event(
                "main_thread_execute_start",
                operation_id=operation_id,
                tool_name=tool_name,
                batch_size=1,
                timeout_seconds=self._main_timeout,
                args_keys=sorted(str(key) for key in request_kwargs.keys() if key != OPERATION_ID_KEY),
                state="executing",
            )
            self._update_receipt(operation_id, state="running")
            self._emit_tool_request(tool_name, request_kwargs)

            try:
                result = self._get_matching_result(operation_id, self._main_timeout)
                success = bool(isinstance(result, dict) and result.get("success"))
                self._update_receipt(
                    operation_id,
                    state="completed" if success else "failed",
                    success=success,
                    result_available=True,
                    thread_still_running=False,
                    scene_consistency="known",
                    error_code="" if success else "tool_failed",
                )
                if self._active_operation_id == operation_id:
                    self._active_operation_id = None
                self._record_event(
                    "main_thread_execute_result",
                    operation_id=operation_id,
                    tool_name=tool_name,
                    batch_size=1,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    success=bool(isinstance(result, dict) and result.get("success")),
                    state="idle",
                )
                result = self._attach_receipt_to_result(operation_id, result)
                return result
            except queue.Empty:
                self._blocked = True
                self._active_operation_id = operation_id
                self._record_event(
                    "main_thread_execute_timeout",
                    operation_id=operation_id,
                    tool_name=tool_name,
                    batch_size=1,
                    timeout_seconds=self._main_timeout,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    main_thread_stack=self._capture_main_thread_stack(),
                    thread_still_running=True,
                    scene_consistency="unknown",
                    state="blocked",
                )
                self._update_receipt(
                    operation_id,
                    wait_status="timed_out",
                    thread_still_running=True,
                    scene_consistency="unknown",
                )
                return self._attach_receipt_to_result(operation_id, {
                    "success": False,
                    "error": (
                        f"操作超时（{int(self._main_timeout)}秒）：Houdini 主线程可能仍在执行 {tool_name}。"
                        "为避免崩溃，后续 Houdini 工具执行已阻止；请停止当前 Agent 或重启面板后再继续。"
                    ),
                    "thread_still_running": True,
                    "scene_consistency": "unknown",
                })

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
            start = time.monotonic()
            self._record_event(
                "main_thread_execute_start",
                operation_id=operation_id,
                tool_name="batch",
                batch_size=len(batch),
                timeout_seconds=self._batch_timeout,
                args_keys=sorted({str(key) for _, kwargs in batch for key in (kwargs or {}).keys()}),
                state="executing",
            )
            self._emit_batch_request(request_batch)

            try:
                results = self._get_matching_result(operation_id, self._batch_timeout)
                if self._active_operation_id == operation_id:
                    self._active_operation_id = None
                self._record_event(
                    "main_thread_execute_result",
                    operation_id=operation_id,
                    tool_name="batch",
                    batch_size=len(batch),
                    duration_ms=int((time.monotonic() - start) * 1000),
                    success=True,
                    state="idle",
                )
                if isinstance(results, list):
                    return results
                return [results] if isinstance(results, dict) else [
                    {"success": False, "error": "批量工具主线程执行返回了无效结果"}
                ]
            except queue.Empty:
                self._blocked = True
                self._active_operation_id = operation_id
                self._record_event(
                    "main_thread_execute_timeout",
                    operation_id=operation_id,
                    tool_name="batch",
                    batch_size=len(batch),
                    timeout_seconds=self._batch_timeout,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    main_thread_stack=self._capture_main_thread_stack(),
                    thread_still_running=True,
                    scene_consistency="unknown",
                    state="blocked",
                )
                return [
                    {
                        "success": False,
                        "error": "批量工具执行超时：Houdini 主线程可能仍忙。为避免崩溃，后续 Houdini 工具执行已阻止。",
                        "thread_still_running": True,
                        "scene_consistency": "unknown",
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
        semantics = self._tool_semantics(tool_name)
        use_undo_group = semantics["undo"]

        self._set_manual_mode_for_cook_guard(tool_name, semantics["cook_triggering"])

        if semantics["cook_before_read"]:
            cook_before_read()

        should_snapshot = (
            semantics["mutating"]
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
        success = bool(isinstance(result, dict) and result.get("success"))
        self._update_receipt(
            operation_id,
            state="completed" if success else "failed",
            success=success,
            result_available=True,
            thread_still_running=False,
            scene_consistency="known",
            error_code="" if success else "tool_failed",
        )
        return {"operation_id": operation_id, "result": result}

    def get_operation_status(self, operation_id: str) -> Optional[dict]:
        with self._receipt_lock:
            receipt = self._receipts.get(str(operation_id or ""))
            return dict(receipt) if receipt is not None else None

    def list_operation_receipts(self, limit: int = 20) -> List[dict]:
        bounded_limit = min(100, max(1, int(limit)))
        with self._receipt_lock:
            receipts = sorted(self._receipts.values(), key=lambda item: item["updated_at"])
            return [dict(item) for item in receipts[-bounded_limit:]]

    def _create_receipt(
        self,
        correlation_id: int,
        tool_name: str,
        batch_size: int,
        arguments: Optional[dict] = None,
    ) -> Optional[dict]:
        with self._receipt_lock:
            terminal = sorted(
                (item for item in self._receipts.values() if item["state"] in {"completed", "failed"}),
                key=lambda item: item["updated_at"],
            )
            while len(self._receipts) >= self._max_receipts and terminal:
                expired = terminal.pop(0)
                self._receipts.pop(expired["operation_id"], None)
            if len(self._receipts) >= self._max_receipts:
                return None
            now = time.time()
            public_id = uuid.uuid4().hex
            session_id = "unknown"
            if self._session_id_provider is not None:
                try:
                    session_id = str(self._session_id_provider() or "unknown")
                except Exception:
                    session_id = "unknown"
            identity = {}
            if self._identity_provider is not None:
                try:
                    provided = self._identity_provider()
                    identity = dict(provided) if isinstance(provided, dict) else {}
                except Exception:
                    identity = {}
            receipt = {
                "protocol_version": RECEIPT_PROTOCOL_VERSION,
                "request_ref": public_id,
                "operation_id": public_id,
                "kind": "houdini_tool",
                "tool_name": str(tool_name),
                "state": "accepted",
                "created_at": now,
                "updated_at": now,
                "batch_size": int(batch_size),
                "wait_status": "waiting",
                "thread_still_running": False,
                "scene_consistency": "known",
                "success": None,
                "error_code": "",
                "result_available": False,
                "session_id": session_id,
                "arguments_sha256": self._arguments_sha256(arguments),
                "contract_version": self._tool_contract_version(tool_name),
                "revision": 1,
            }
            for key in ("executor_id", "houdini_version", "scene_id", "hip_path"):
                value = identity.get(key)
                if value is not None:
                    receipt[key] = str(value)
            self._receipts[public_id] = receipt
            self._receipt_ids_by_correlation[correlation_id] = public_id
            self._record_receipt_event(receipt)
            return dict(receipt)

    def _update_receipt(self, correlation_id: int, **changes) -> Optional[dict]:
        with self._receipt_lock:
            public_id = self._receipt_ids_by_correlation.get(correlation_id)
            receipt = self._receipts.get(public_id) if public_id else None
            if receipt is None:
                return None
            return self._update_receipt_locked(receipt, **changes)

    def _update_receipt_locked(self, receipt: dict, **changes) -> dict:
        if receipt["state"] in {"completed", "failed"} and changes.get("state"):
            return dict(receipt)
        receipt.update(changes)
        receipt["updated_at"] = time.time()
        receipt["revision"] += 1
        self._record_receipt_event(receipt)
        return dict(receipt)

    def _record_receipt_event(self, receipt: dict) -> None:
        self._record_event("operation_receipt", **dict(receipt))

    @staticmethod
    def _arguments_sha256(arguments: Optional[dict]) -> str:
        try:
            payload = json.dumps(arguments or {}, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            payload = repr(arguments or {})
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _tool_contract_version(tool_name: str) -> str:
        try:
            from ..utils.tool_registry import get_tool_registry
            return get_tool_registry().contract_version(tool_name)
        except Exception:
            return "unknown"

    def _attach_receipt_to_result(self, correlation_id: int, result):
        if not isinstance(result, dict):
            return result
        public_id = self._receipt_ids_by_correlation.get(correlation_id)
        receipt = self.get_operation_status(public_id) if public_id else None
        if receipt is not None:
            result = dict(result)
            result["operation_receipt"] = receipt
        return result

    def _guard_result(self, tool_name: str):
        if self._shutdown:
            self._record_event("main_thread_executor_guard", tool_name=tool_name, reason="shutdown", state="shutdown")
            return {"success": False, "error": f"Houdini 主线程执行器已关闭，拒绝执行 {tool_name}"}
        if self._blocked:
            self._record_event("main_thread_executor_guard", tool_name=tool_name, reason="blocked", state="blocked")
            return {
                "success": False,
                "error": f"Houdini 主线程执行器处于阻塞状态，拒绝执行 {tool_name}，以避免崩溃。请重启面板后再继续。",
            }
        return None

    def _record_event(self, event_type: str, **fields):
        if self._record_event_callback is None:
            return
        event = {"event_type": event_type}
        event.update(fields)
        try:
            self._record_event_callback(event)
        except Exception:
            pass

    def _drain_results(self):
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except queue.Empty:
                break

    @staticmethod
    def _capture_main_thread_stack(limit: int = 30) -> Optional[str]:
        """抓取 Houdini 主线程当前的 Python 调用栈位置，写入诊断事件。

        用于在超时/阻塞发生时定位卡住的具体工具代码位置（例如卡在哪个
        skill、哪一行 hou 调用），而不是只知道"超时了"。仅供诊断记录使用，
        不出现在返回给 LLM/用户的错误信息里。

        ★ 安全：只记录 文件名:行号:函数名，不包含源码行文本
        （`traceback.format_stack` 会内联源码行，可能把调用参数/密钥等
        敏感值原样写进诊断日志，因此改用 `extract_stack` 并丢弃 `.line`）。
        """
        try:
            main_thread = threading.main_thread()
            frame = sys._current_frames().get(main_thread.ident)
            if frame is None:
                return None
            summary = traceback.extract_stack(frame, limit=limit)
            return "\n".join(
                f'File "{entry.filename}", line {entry.lineno}, in {entry.name}'
                for entry in summary
            )
        except Exception:
            return None

    @staticmethod
    def _with_operation_id(kwargs: dict, operation_id: int) -> dict:
        request_kwargs = dict(kwargs or {})
        request_kwargs[OPERATION_ID_KEY] = operation_id
        return request_kwargs

    def _get_matching_result(self, operation_id: int, timeout: float):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            item = self._result_queue.get(timeout=remaining)
            if isinstance(item, dict) and "operation_id" in item and "result" in item:
                if item.get("operation_id") != operation_id:
                    self._record_event(
                        "main_thread_stale_result_ignored",
                        operation_id=item.get("operation_id"),
                        expected_operation_id=operation_id,
                        state="executing",
                    )
                    continue
                return item.get("result")
            return item

    @staticmethod
    def _tool_semantics(tool_name: str) -> Dict[str, bool]:
        try:
            from ..utils.tool_registry import get_tool_registry
            semantics = get_tool_registry().get_execution_semantics(tool_name)
            if semantics is not None:
                return semantics
        except Exception:
            pass
        return {
            "mutating": False,
            "undo": False,
            "cook_triggering": False,
            "cook_before_read": False,
        }

    def _set_manual_mode_for_cook_guard(self, tool_name: str, cook_triggering: bool = False):
        if not cook_triggering:
            return
        if self._explicit_update_mode == "auto":
            self._record_event(
                "update_mode_guard",
                tool_name=tool_name,
                decision="preserve_explicit_auto",
                scope="agent_run",
            )
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
