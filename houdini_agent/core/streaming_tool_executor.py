# -*- coding: utf-8 -*-
"""Streaming tool executor for Harness V2.

This module extracts tool dispatch from AIClient so it can be evolved
independently (cc-haha style) while preserving current behavior.
"""

from __future__ import annotations

import concurrent.futures
import copy
import json
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


ParsedToolCall = Tuple[str, str, Dict[str, Any], Dict[str, Any]]


class StreamingToolExecutor:
    """Execute a round of tool calls with stable ordering.

    The executor keeps an in-memory dedup cache for one agent-loop run.
    """

    _LEGACY_DEDUP_TOOLS = frozenset({
        "get_network_structure",
        "get_node_parameters",
        "get_parameter_schema",
        "inspect_node",
        "get_node_connections",
        "suggest_connection",
        "preview_node_operation",
        "validate_node_network",
        "list_children",
        "find_nodes",
        "get_geometry_summary",
        "get_scene_snapshot",
        "read_selection",
        "search_node_types",
        "semantic_search_nodes",
        "check_errors",
        "search_local_doc",
        "get_houdini_node_doc",
        "list_skills",
        "perf_stop_and_report",
        "preview_layout_nodes",
    })

    _LEGACY_ASYNC_TOOL_NAMES = frozenset({"web_search", "fetch_webpage", "execute_shell"})

    _LEGACY_BATCH_READONLY = frozenset({
        "get_network_structure",
        "get_node_parameters",
        "get_parameter_schema",
        "inspect_node",
        "get_node_connections",
        "suggest_connection",
        "preview_node_operation",
        "validate_node_network",
        "list_children",
        "find_nodes",
        "get_geometry_summary",
        "get_scene_snapshot",
        "read_selection",
        "search_node_types",
        "semantic_search_nodes",
        "check_errors",
        "search_local_doc",
        "get_houdini_node_doc",
        "list_skills",
        "perf_start_profile",
        "perf_stop_and_report",
        "preview_layout_nodes",
    })

    _LEGACY_NETWORK_MUTATING_TOOLS = frozenset({
        "create_node",
        "create_nodes_batch",
        "create_named_null",
        "delete_node",
        "connect_nodes",
        "cook_node",
        "create_wrangle_node",
        "copy_node",
        "set_display_flag",
        "undo_redo",
    })

    _LEGACY_CACHE_INVALIDATE_TOOLS = frozenset({
        "get_network_structure",
        "get_geometry_summary",
        "get_scene_snapshot",
        "list_children",
        "check_errors",
    })

    def __init__(
        self,
        tool_executor: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        web_search_executor: Callable[[Dict[str, Any]], Dict[str, Any]],
        fetch_webpage_executor: Callable[[Dict[str, Any]], Dict[str, Any]],
        batch_tool_executor: Optional[Callable[[List[Tuple[str, Dict[str, Any]]]], List[Dict[str, Any]]]] = None,
        runtime_profile_provider: Optional[Callable[[], Dict[str, Set[str]]]] = None,
        max_async_workers: int = 4,
    ):
        self._tool_executor = tool_executor
        self._web_search_executor = web_search_executor
        self._fetch_webpage_executor = fetch_webpage_executor
        self._batch_tool_executor = batch_tool_executor
        self._runtime_profile_provider = runtime_profile_provider
        self._max_async_workers = max_async_workers
        self._turn_dedup_cache: Dict[str, Dict[str, Any]] = {}
        self._runtime_dedup_tools: Set[str] = set(self._LEGACY_DEDUP_TOOLS)
        self._runtime_async_tools: Set[str] = set(self._LEGACY_ASYNC_TOOL_NAMES)
        self._runtime_batch_readonly_tools: Set[str] = set(self._LEGACY_BATCH_READONLY)
        self._runtime_network_mutating_tools: Set[str] = set(self._LEGACY_NETWORK_MUTATING_TOOLS)
        self._runtime_cache_invalidate_tools: Set[str] = set(self._LEGACY_CACHE_INVALIDATE_TOOLS)
        self._runtime_execution_barrier_tools: Set[str] = set(self._LEGACY_NETWORK_MUTATING_TOOLS)

    def reset(self):
        self._turn_dedup_cache = {}

    def update_batch_executor(
        self,
        batch_tool_executor: Optional[Callable[[List[Tuple[str, Dict[str, Any]]]], List[Dict[str, Any]]]],
    ):
        self._batch_tool_executor = batch_tool_executor

    def update_runtime_profile_provider(
        self,
        runtime_profile_provider: Optional[Callable[[], Dict[str, Set[str]]]],
    ):
        self._runtime_profile_provider = runtime_profile_provider

    def _refresh_runtime_profile(self):
        if not self._runtime_profile_provider:
            return
        try:
            profile = self._runtime_profile_provider() or {}
            self._runtime_dedup_tools = set(profile.get("dedup_tools") or [])
            self._runtime_async_tools = set(profile.get("async_tools") or [])
            self._runtime_batch_readonly_tools = set(profile.get("batch_readonly_tools") or [])
            self._runtime_network_mutating_tools = set(profile.get("network_mutating_tools") or [])
            self._runtime_cache_invalidate_tools = set(profile.get("cache_invalidate_tools") or [])
            self._runtime_execution_barrier_tools = set(
                profile.get("execution_barrier_tools") or self._runtime_network_mutating_tools
            )
        except Exception:
            # Keep last-known runtime profile if registry lookup fails.
            pass

    def execute_round(self, parsed_calls: List[ParsedToolCall]) -> Dict[str, Any]:
        self._refresh_runtime_profile()
        results_ordered: List[Optional[Dict[str, Any]]] = [None] * len(parsed_calls)
        dedup_flags: List[bool] = [False] * len(parsed_calls)

        uncached_async = [
            (i, pc) for i, pc in enumerate(parsed_calls)
            if pc[1] in self._runtime_async_tools
        ]
        uncached_houdini = [
            (i, pc) for i, pc in enumerate(parsed_calls)
            if pc[1] not in self._runtime_async_tools
        ]

        self._execute_async_calls(uncached_async, results_ordered)
        self._execute_houdini_calls(uncached_houdini, results_ordered, dedup_flags)
        dedup_hit_count = sum(1 for flag in dedup_flags if flag)

        early_skip_count = self._apply_early_skip(parsed_calls, results_ordered)
        self._update_dedup_cache(parsed_calls, results_ordered, dedup_flags)

        # Ensure downstream logic always receives dict results.
        for idx, result in enumerate(results_ordered):
            if result is None:
                results_ordered[idx] = {
                    "success": False,
                    "error": "工具执行器未返回结果",
                }

        failed_count = sum(1 for r in results_ordered if not r.get("success", False))

        return {
            "results_ordered": results_ordered,
            "dedup_flags": dedup_flags,
            "early_skip_count": early_skip_count,
            "dedup_hit_count": dedup_hit_count,
            "failed_count": failed_count,
            "async_count": len(uncached_async),
            "houdini_count": len(uncached_houdini),
        }

    def _execute_async_calls(
        self,
        uncached_async: List[Tuple[int, ParsedToolCall]],
        results_ordered: List[Optional[Dict[str, Any]]],
    ):
        if len(uncached_async) > 1:
            max_workers = min(self._max_async_workers, len(uncached_async))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                for idx, result in pool.map(self._exec_async_indexed, uncached_async):
                    results_ordered[idx] = result
        elif len(uncached_async) == 1:
            idx, (_tid, tname, targs, _tc) = uncached_async[0]
            results_ordered[idx] = self._exec_async_tool(tname, targs)

    def _exec_async_indexed(self, idx_pc: Tuple[int, ParsedToolCall]) -> Tuple[int, Dict[str, Any]]:
        idx, (_tid, tname, targs, _tc) = idx_pc
        return idx, self._exec_async_tool(tname, targs)

    def _exec_async_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if tool_name == "web_search":
                return self._web_search_executor(arguments)
            if tool_name == "fetch_webpage":
                return self._fetch_webpage_executor(arguments)
            return self._tool_executor(tool_name, arguments)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_houdini_calls(
        self,
        uncached_houdini: List[Tuple[int, ParsedToolCall]],
        results_ordered: List[Optional[Dict[str, Any]]],
        dedup_flags: List[bool],
    ):
        segment: List[Tuple[int, ParsedToolCall]] = []

        def flush_readonly_segment():
            if not segment:
                return
            if len(segment) > 1 and self._batch_tool_executor:
                batch_input = [(pc[1], pc[2]) for _, pc in segment]
                try:
                    batch_results = self._batch_tool_executor(batch_input)
                    if len(batch_results) != len(segment):
                        raise ValueError("readonly batch result count mismatch")
                    for (idx, _), result in zip(segment, batch_results):
                        results_ordered[idx] = result
                except Exception:
                    for idx, (_tid, tname, targs, _tc) in segment:
                        results_ordered[idx] = self._safe_tool_executor(tname, targs)
            else:
                for idx, (_tid, tname, targs, _tc) in segment:
                    results_ordered[idx] = self._safe_tool_executor(tname, targs)
            segment[:] = []

        for idx, pc in uncached_houdini:
            tname = pc[1]
            dedup_key = self._make_dedup_key(tname, pc[2])
            if tname in self._runtime_dedup_tools and dedup_key in self._turn_dedup_cache:
                flush_readonly_segment()
                results_ordered[idx] = copy.deepcopy(self._turn_dedup_cache[dedup_key])
                dedup_flags[idx] = True
                continue
            if tname in self._runtime_batch_readonly_tools:
                segment.append((idx, pc))
                continue
            flush_readonly_segment()
            results_ordered[idx] = self._safe_tool_executor(tname, pc[2])
            if results_ordered[idx].get("success") and tname in self._runtime_execution_barrier_tools:
                self._invalidate_query_cache()
        flush_readonly_segment()

    def _invalidate_query_cache(self):
        keys_to_remove = [
            key for key in self._turn_dedup_cache
            if key.split(":", 1)[0] in self._runtime_cache_invalidate_tools
        ]
        for key in keys_to_remove:
            del self._turn_dedup_cache[key]

    def _safe_tool_executor(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._tool_executor(tool_name, arguments)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _apply_early_skip(
        self,
        parsed_calls: List[ParsedToolCall],
        results_ordered: List[Optional[Dict[str, Any]]],
    ) -> int:
        early_skip_count = 0
        if len(parsed_calls) <= 2:
            return early_skip_count

        check_errors_paths = set()
        empty_network_paths = set()

        for idx, (_tid, tname, targs, _tc) in enumerate(parsed_calls):
            result = results_ordered[idx]
            if not result:
                continue
            if tname == "check_errors" and result.get("success"):
                r_text = str(result.get("result", ""))
                if "错误" in r_text or "error" in r_text.lower():
                    path = targs.get("node_path", "")
                    if path:
                        check_errors_paths.add(path)
            if tname == "get_network_structure" and result.get("success"):
                r_text = str(result.get("result", ""))
                if "节点数量: 0" in r_text or "Nodes: 0" in r_text or not r_text.strip():
                    path = targs.get("network_path", "") or targs.get("node_path", "")
                    if path:
                        empty_network_paths.add(path)

        for idx, (_tid, tname, targs, _tc) in enumerate(parsed_calls):
            if results_ordered[idx] is not None:
                continue
            path = targs.get("node_path", "") or targs.get("network_path", "")
            if tname == "get_node_parameters" and path in check_errors_paths:
                results_ordered[idx] = {
                    "success": True,
                    "result": f"[已跳过] {path} 已有错误信息，请先修复错误。",
                }
                early_skip_count += 1
            elif tname in ("list_children", "get_node_parameters") and path in empty_network_paths:
                results_ordered[idx] = {
                    "success": True,
                    "result": f"[已跳过] {path} 网络为空，无子节点。",
                }
                early_skip_count += 1

        return early_skip_count

    def _update_dedup_cache(
        self,
        parsed_calls: List[ParsedToolCall],
        results_ordered: List[Optional[Dict[str, Any]]],
        dedup_flags: List[bool],
    ):
        has_successful_barrier = any(
            pc[1] in self._runtime_execution_barrier_tools
            and bool(results_ordered[idx_m] and results_ordered[idx_m].get("success"))
            for idx_m, pc in enumerate(parsed_calls)
            if not dedup_flags[idx_m]
        )
        if has_successful_barrier:
            self._invalidate_query_cache()

        for idx, (_tid, tname, targs, _tc) in enumerate(parsed_calls):
            result = results_ordered[idx]
            if not dedup_flags[idx] and tname in self._runtime_dedup_tools and result:
                dedup_key = self._make_dedup_key(tname, targs)
                self._turn_dedup_cache[dedup_key] = copy.deepcopy(result)

    @staticmethod
    def _make_dedup_key(tool_name: str, arguments: Dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
