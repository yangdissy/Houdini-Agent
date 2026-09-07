# -*- coding: utf-8 -*-
"""
ToolRegistry — 统一工具注册中心

将三套能力系统（Core Tools / Skills / Plugin Tools）统一管理：
  - 按模式获取可用工具列表 (agent / ask / plan_planning / plan_executing)
  - 统一执行入口
  - 支持工具启用/禁用（持久化到 config/plugins.json）
  - 为 UI 提供工具列表元数据
"""

import json
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

from ..core.harness_policy_config import HIGH_RISK_TOOLS, SCENE_MUTATION_TOOLS


# ─────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────

@dataclass
class ToolMeta:
    """工具元数据"""
    name: str                                    # 唯一标识
    schema: dict                                 # OpenAI function calling schema
    handler: Optional[Callable] = None           # 执行函数 (args: dict) -> dict；可为 None（由 MCP Client 分派）
    source: str = "core"                         # "core" | "skill" | "plugin" | "user"
    plugin_name: str = ""                        # 如果是插件工具，插件名
    tags: Set[str] = field(default_factory=set)  # {"readonly", "geometry", "network", "system", ...}
    modes: Set[str] = field(default_factory=set) # {"agent", "ask", "plan_planning", "plan_executing"}
    enabled: bool = True                         # 是否启用
    concurrency_safe: bool = False               # 是否允许与其他工具并发执行
    risk_level: str = "normal"                  # "low" | "normal" | "high"
    runtime: str = "houdini"                    # "houdini" | "local"
    requires_confirmation: bool = True           # Confirm Mode 下是否需要用户确认
    path_kinds: Dict[str, str] = field(default_factory=dict)  # 参数名 -> "node" | "file"
    mutating: bool = False                       # 是否修改 Houdini/网络状态
    undo: bool = False                           # 是否需要 Houdini undo group
    cook_triggering: bool = False                # 是否在执行前启用 cook guard
    cook_before_read: bool = False               # 是否在读取前定向 cook
    cache_invalidation: bool = False             # 是否使本轮网络读取缓存失效
    execution_barrier: bool = False              # 是否分隔执行段并在成功后失效读取缓存

    def execution_semantics(self) -> Dict[str, bool]:
        """Return the Houdini runtime facts owned by this registration."""
        return {
            "mutating": bool(self.mutating),
            "undo": bool(self.undo),
            "cook_triggering": bool(self.cook_triggering),
            "cook_before_read": bool(self.cook_before_read),
            "execution_barrier": bool(self.execution_barrier),
        }

    def required_args(self) -> tuple:
        parameters = self.schema.get("function", {}).get("parameters", {})
        required = parameters.get("required", []) if isinstance(parameters, dict) else []
        return tuple(str(key) for key in required if isinstance(key, str) and key)


class ToolRegistrationError(ValueError):
    """Raised when registration would ambiguously replace another owner."""


# ─────────────────────────────────────────────
# 模式推断辅助（仅用于核心工具自动注册）
# ─────────────────────────────────────────────

# Ask 模式白名单（只读 / 查询工具）
_ASK_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'get_parameter_schema', 'inspect_node', 'get_node_connections',
    'suggest_connection', 'preview_node_operation', 'validate_node_network', 'list_children', 'find_nodes',
    'get_geometry_summary', 'temporary_auto_validate_geometry', 'get_scene_snapshot',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'check_errors',
    'verify_network', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills',
    'add_todo', 'update_todo',
    'perf_start_profile', 'perf_stop_and_report',
    'search_memory', 'capture_viewport', 'preview_layout_nodes',
})

# Plan 规划阶段白名单
_PLAN_PLANNING_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'get_parameter_schema', 'inspect_node', 'get_node_connections',
    'suggest_connection', 'preview_node_operation', 'validate_node_network', 'list_children', 'find_nodes',
    'get_geometry_summary', 'temporary_auto_validate_geometry', 'get_scene_snapshot',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'check_errors',
    'verify_network', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills', 'run_skill',
    'add_todo', 'update_todo',
    'perf_start_profile', 'perf_stop_and_report',
    'search_memory', 'capture_viewport', 'preview_layout_nodes',
    'create_plan', 'ask_question',
})

# 只读标签推断
_READONLY_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'get_parameter_schema', 'inspect_node', 'get_node_connections',
    'suggest_connection', 'preview_node_operation', 'validate_node_network', 'list_children', 'find_nodes',
    'get_geometry_summary', 'temporary_auto_validate_geometry', 'get_scene_snapshot',
    'read_selection', 'search_node_types', 'semantic_search_nodes',
    'check_errors',
    'verify_network', 'web_search', 'fetch_webpage',
    'search_local_doc', 'get_houdini_node_doc', 'list_skills',
    'perf_start_profile', 'perf_stop_and_report',
    'capture_viewport', 'search_memory', 'preview_layout_nodes',
})

_HIGH_RISK_TOOLS = HIGH_RISK_TOOLS
_CORE_CONFIRM_TOOLS = frozenset(SCENE_MUTATION_TOOLS | HIGH_RISK_TOOLS | {"set_update_mode"})

_LOCAL_RUNTIME_TOOLS = frozenset({
    "execute_shell", "search_local_doc", "list_skills", "search_memory", "remember_memory",
})

_CONCURRENCY_SAFE_TOOLS = frozenset({
    'web_search',
    'fetch_webpage',
    'search_local_doc',
    'list_skills',
    'search_memory',
})

_ASYNC_PREFERRED_TOOLS = frozenset({
    'web_search',
    'fetch_webpage',
    'execute_shell',
})

_MUTATING_TOOLS = frozenset({
    'create_node', 'create_nodes_batch', 'create_named_null', 'delete_node',
    'rename_node', 'set_node_parameter', 'set_parameter_expression',
    'batch_set_parameters', 'connect_nodes', 'disconnect_nodes', 'copy_node',
    'create_wrangle_node', 'set_display_flag', 'set_node_flags', 'layout_nodes',
    'create_network_box', 'add_nodes_to_box', 'execute_python', 'save_hip',
    'run_skill', 'undo_redo',
})

_EXECUTION_BARRIER_TOOLS = frozenset(
    set(_MUTATING_TOOLS) | {"set_update_mode", "temporary_auto_validate_geometry"}
)

_NODE_PATH_KEYS = frozenset({
    "node_path", "source_path", "target_path", "network_path", "parent_path",
    "from_path", "to_path", "input_path", "path", "root_path",
})

_FILE_PATH_KEYS = frozenset({"file_path", "output_path"})


def _infer_path_kinds(schema: dict) -> Dict[str, str]:
    parameters = schema.get("function", {}).get("parameters", {})
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    if not isinstance(properties, dict):
        return {}
    return {
        key: "node" if key in _NODE_PATH_KEYS else "file"
        for key in properties
        if key in _NODE_PATH_KEYS or key in _FILE_PATH_KEYS
    }

_COOK_TRIGGERING_TOOLS = frozenset({
    'connect_nodes', 'set_display_flag', 'set_node_parameter',
    'batch_set_parameters', 'execute_python', 'run_skill',
})

_COOK_BEFORE_READ_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'list_children',
    'check_errors', 'verify_network', 'capture_viewport',
})

_DEFAULT_HISTORY_QUERY_TOOLS = frozenset({
    'get_network_structure', 'get_node_parameters', 'get_parameter_schema', 'inspect_node',
    'get_node_connections', 'suggest_connection', 'preview_node_operation', 'validate_node_network',
    'list_children', 'find_nodes', 'get_geometry_summary', 'get_scene_snapshot',
    'read_selection', 'search_node_types',
    'semantic_search_nodes', 'check_errors', 'verify_network',
    'search_local_doc', 'get_houdini_node_doc',
    'execute_python', 'execute_shell', 'web_search', 'fetch_webpage',
    'run_skill', 'list_skills',
    'capture_viewport',
})

_DEFAULT_COMPRESSION_OPERATION_TOOLS = frozenset({
    'create_node', 'create_nodes_batch', 'create_named_null', 'connect_nodes', 'cook_node',
    'set_node_parameter', 'create_wrangle_node',
})

_DEFAULT_THINKING_SIMPLE_SUCCESS_TOOLS = frozenset({
    'create_node', 'get_node_parameters', 'get_parameter_schema', 'inspect_node', 'get_node_connections',
    'suggest_connection', 'preview_node_operation', 'validate_node_network',
    'list_children', 'find_nodes', 'get_geometry_summary', 'get_scene_snapshot',
    'read_selection', 'check_errors', 'verify_network',
})

_DEFAULT_THINKING_DEEP_TOOLS = frozenset({
    'connect_nodes', 'cook_node', 'create_named_null', 'delete_node', 'disconnect_nodes', 'rename_node', 'preview_layout_nodes',
    'set_node_parameter', 'batch_set_parameters', 'create_nodes_batch',
    'create_wrangle_node', 'copy_node', 'set_display_flag', 'set_node_flags',
    'execute_python', 'execute_shell', 'save_hip', 'run_skill',
})

_DEFAULT_LOOP_GUIDANCE_QUERY_TOOLS = frozenset({
    'get_parameter_schema', 'search_node_types', 'search_local_doc',
    'list_node_parameters', 'get_node_info', 'search_parameters',
})


def build_default_tool_execution_profile() -> Dict[str, Set[str]]:
    """Return fallback runtime classifications used before registry metadata is ready."""
    return {
        "async_tools": set(_ASYNC_PREFERRED_TOOLS),
        "batch_readonly_tools": set(_READONLY_TOOLS - _ASYNC_PREFERRED_TOOLS),
        "history_query_tools": set(_DEFAULT_HISTORY_QUERY_TOOLS),
        "compression_query_tools": set(_DEFAULT_HISTORY_QUERY_TOOLS),
        "compression_operation_tools": set(_DEFAULT_COMPRESSION_OPERATION_TOOLS),
        "thinking_simple_success_tools": set(_DEFAULT_THINKING_SIMPLE_SUCCESS_TOOLS),
        "thinking_deep_tools": set(_DEFAULT_THINKING_DEEP_TOOLS),
        "loop_guidance_query_tools": set(_DEFAULT_LOOP_GUIDANCE_QUERY_TOOLS),
        "execution_barrier_tools": set(_EXECUTION_BARRIER_TOOLS),
    }


def _infer_modes(name: str) -> Set[str]:
    """根据工具名自动推断适用模式"""
    modes = {"agent", "plan_executing"}  # 所有工具默认可在 Agent 和 Plan 执行阶段使用
    if name in _ASK_TOOLS:
        modes.add("ask")
    if name in _PLAN_PLANNING_TOOLS:
        modes.add("plan_planning")
    return modes


def _infer_tags(name: str) -> Set[str]:
    """根据工具名自动推断标签"""
    tags: Set[str] = set()
    if name in _READONLY_TOOLS:
        tags.add("readonly")
    # 几何/网络相关
    geo_kw = ('node', 'network', 'connect', 'create', 'delete', 'display',
              'parameter', 'children', 'selection', 'wrangle', 'copy', 'batch',
              'geometry', 'scene',
              'inputs', 'flag', 'layout', 'box')
    for kw in geo_kw:
        if kw in name.lower():
            tags.add("network")
            break
    # 系统/Shell
    if name in ('execute_python', 'execute_shell', 'save_hip', 'undo_redo'):
        tags.add("system")
    # 搜索/文档
    if name in ('web_search', 'fetch_webpage', 'search_local_doc', 'get_houdini_node_doc'):
        tags.add("docs")
    # 异步优先（不依赖 Houdini 主线程）
    if name in _ASYNC_PREFERRED_TOOLS:
        tags.add("async")
    # Skill
    if name.startswith("skill_") or name in ('run_skill', 'list_skills'):
        tags.add("skill")
    # 任务管理
    if name in ('add_todo', 'update_todo'):
        tags.add("task")
    return tags


def _infer_concurrency_safe(name: str) -> bool:
    """Infer if a tool can be safely run concurrently."""
    return name in _READONLY_TOOLS or name in _CONCURRENCY_SAFE_TOOLS


def _infer_risk_level(name: str) -> str:
    """Infer risk level for policy and UI display."""
    if name in _HIGH_RISK_TOOLS:
        return "high"
    if name in _READONLY_TOOLS:
        return "low"
    return "normal"


# ─────────────────────────────────────────────
# ToolRegistry 单例
# ─────────────────────────────────────────────

class ToolRegistry:
    """统一工具注册中心

    每个工具注册时需要：
      - name: 唯一标识
      - schema: OpenAI function calling schema
      - handler: 执行函数 (args: dict) -> dict，可为 None
      - source: "core" | "skill" | "plugin" | "user"
      - tags: set[str]  例如 {"readonly", "geometry", "network"}
      - modes: set[str]  例如 {"agent", "ask", "plan_planning", "plan_executing"}
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._tools: Dict[str, ToolMeta] = {}       # name -> ToolMeta
        self._disabled_tools: Set[str] = set()       # 持久化禁用列表
        self._initialized = False

    # ---------- 注册 / 注销 ----------

    def register(self, name: str, schema: dict,
                 handler: Optional[Callable] = None,
                 source: str = "core",
                 plugin_name: str = "",
                 tags: Optional[Set[str]] = None,
                 modes: Optional[Set[str]] = None,
                 enabled: bool = True,
                 concurrency_safe: bool = False,
                 risk_level: str = "normal",
                 runtime: str = "houdini",
                 requires_confirmation: bool = True,
                 path_kinds: Optional[Dict[str, str]] = None,
                 mutating: bool = False,
                 undo: bool = False,
                 cook_triggering: bool = False,
                 cook_before_read: bool = False,
                 cache_invalidation: bool = False,
                 execution_barrier: bool = False):
        """注册工具"""
        if runtime not in {"houdini", "local"}:
            raise ToolRegistrationError(f"Unsupported tool runtime: {runtime}")
        resolved_path_kinds = dict(path_kinds or {})
        if any(kind not in {"node", "file"} for kind in resolved_path_kinds.values()):
            raise ToolRegistrationError("Tool path kinds must be 'node' or 'file'")
        schema_name = schema.get("function", {}).get("name") if isinstance(schema, dict) else None
        if not name or schema_name != name:
            raise ToolRegistrationError("Tool schema name must match registration name")
        with self._lock:
            current = self._tools.get(name)
            owner = (source, plugin_name)
            if current and (current.source, current.plugin_name) != owner:
                raise ToolRegistrationError(
                    f"Tool '{name}' is already owned by "
                    f"{current.plugin_name or current.source}; refusing owner {plugin_name or source}"
                )
            meta = ToolMeta(
                name=name,
                schema=schema,
                handler=handler,
                source=source,
                plugin_name=plugin_name,
                tags=tags or set(),
                modes=modes or set(),
                enabled=enabled and (name not in self._disabled_tools),
                concurrency_safe=concurrency_safe,
                risk_level=risk_level,
                runtime=runtime,
                requires_confirmation=requires_confirmation,
                path_kinds=resolved_path_kinds,
                mutating=mutating or ("network" in (tags or set()) and "readonly" not in (tags or set())),
                undo=undo or ("network" in (tags or set()) and "readonly" not in (tags or set())),
                cook_triggering=cook_triggering,
                cook_before_read=cook_before_read,
                cache_invalidation=cache_invalidation or ("network" in (tags or set()) and "readonly" in (tags or set())),
                execution_barrier=execution_barrier or name in _EXECUTION_BARRIER_TOOLS,
            )
            self._tools[name] = meta

    def unregister(self, name: str):
        """注销工具"""
        with self._lock:
            self._tools.pop(name, None)

    def unregister_by_source(self, source: str, plugin_name: str = ""):
        """按来源注销（可指定插件名）"""
        with self._lock:
            to_remove = [
                n for n, m in self._tools.items()
                if m.source == source and (not plugin_name or m.plugin_name == plugin_name)
            ]
            for n in to_remove:
                del self._tools[n]

    # ---------- 查询 ----------

    def get_tools_for_mode(self, mode: str, runtime: Optional[str] = None) -> List[dict]:
        """按模式获取工具 schema 列表（仅返回启用的工具）"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if mode in meta.modes:
                    if runtime is not None and meta.runtime != runtime:
                        continue
                    result.append(meta.schema)
            return result

    def get_executable_tool_names(self, mode: str, runtimes: Optional[Set[str]] = None) -> Set[str]:
        """Return the enabled tools reachable in ``mode`` and the current runtime."""
        allowed_runtimes = set(runtimes or {"houdini", "local"})
        with self._lock:
            return {
                meta.name for meta in self._tools.values()
                if meta.enabled and mode in meta.modes and meta.runtime in allowed_runtimes
            }

    def get_tool_schemas(self, names: Optional[List[str]] = None) -> List[dict]:
        """获取指定工具的 schema 列表（如 names 为 None 则返回全部启用的）"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if names is None or meta.name in names:
                    result.append(meta.schema)
            return result

    def has_tool(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools

    def get_handler(self, name: str) -> Optional[Callable]:
        """获取工具的执行函数"""
        meta = self._tools.get(name)
        return meta.handler if meta else None

    def get_handler_for_execution(self, name: str, mode: str,
                                  runtime: str) -> Optional[Callable]:
        """Return a handler only when every execution constraint is satisfied."""
        with self._lock:
            meta = self._tools.get(name)
            if not meta or not meta.enabled or mode not in meta.modes:
                return None
            if meta.runtime != runtime:
                return None
            return meta.handler

    def authorize_dispatch(self, name: str, mode: str, runtime: str) -> Dict[str, Any]:
        """Authorize a dispatch against registration, enabled, mode and runtime facts."""
        with self._lock:
            meta = self._tools.get(name)
            if meta is None:
                return {"allowed": False, "error": f"工具未注册: {name}"}
            if not meta.enabled:
                return {"allowed": False, "error": f"工具已禁用: {name}"}
            if mode not in meta.modes:
                return {"allowed": False, "error": f"工具 {name} 不允许在 {mode} 模式执行"}
            if meta.runtime != runtime:
                return {"allowed": False, "error": f"工具 {name} runtime 不匹配"}
            return {"allowed": True, "meta": meta}

    def get_meta(self, name: str) -> Optional[ToolMeta]:
        """获取工具的完整元数据（含 risk_level / tags / modes 等）"""
        return self._tools.get(name)

    def get_tool_names_for_mode(self, mode: str, runtime: Optional[str] = None) -> Set[str]:
        """Return enabled tool names for a mode without exposing schema internals."""
        with self._lock:
            return {
                meta.name for meta in self._tools.values()
                if meta.enabled and mode in meta.modes
                and (runtime is None or meta.runtime == runtime)
            }

    def get_execution_semantics(self, name: str) -> Optional[Dict[str, bool]]:
        """Return registered Houdini execution semantics, or None for unknown tools."""
        with self._lock:
            meta = self._tools.get(name)
            return meta.execution_semantics() if meta is not None else None

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有工具元数据（供 UI 显示）"""
        with self._lock:
            result = []
            for meta in self._tools.values():
                result.append({
                    "name": meta.name,
                    "source": meta.source,
                    "plugin_name": meta.plugin_name,
                    "tags": sorted(meta.tags),
                    "modes": sorted(meta.modes),
                    "enabled": meta.enabled,
                    "concurrency_safe": meta.concurrency_safe,
                    "risk_level": meta.risk_level,
                    "runtime": meta.runtime,
                    "mutating": meta.mutating,
                    "undo": meta.undo,
                    "cook_triggering": meta.cook_triggering,
                    "cook_before_read": meta.cook_before_read,
                    "cache_invalidation": meta.cache_invalidation,
                    "execution_barrier": meta.execution_barrier,
                    "description": meta.schema.get("function", {}).get("description", "")[:120],
                })
            return sorted(result, key=lambda x: (x["source"], x["name"]))

    def build_streaming_executor_profile(self) -> Dict[str, Set[str]]:
        """Build runtime classification for StreamingToolExecutor.

        Returns enabled tool-name sets used by executor dispatch and cache policy.
        """
        with self._lock:
            dedup_tools: Set[str] = set()
            async_tools: Set[str] = set()
            batch_readonly_tools: Set[str] = set()
            network_mutating_tools: Set[str] = set()
            cache_invalidate_tools: Set[str] = set()
            history_query_tools: Set[str] = set()
            compression_query_tools: Set[str] = set()
            compression_operation_tools: Set[str] = set()
            thinking_simple_success_tools: Set[str] = set()
            thinking_deep_tools: Set[str] = set()
            loop_guidance_query_tools: Set[str] = set()
            execution_barrier_tools: Set[str] = set()

            for meta in self._tools.values():
                if not meta.enabled:
                    continue

                tags = meta.tags or set()
                readonly = "readonly" in tags
                is_async = "async" in tags
                is_network = "network" in tags

                if readonly or is_async or "system" in tags or "skill" in tags or "task" in tags:
                    history_query_tools.add(meta.name)
                    compression_query_tools.add(meta.name)

                if is_async:
                    async_tools.add(meta.name)

                # 只读工具默认可去重；异步工具不参与当前轮去重缓存。
                if readonly and not is_async:
                    dedup_tools.add(meta.name)
                    batch_readonly_tools.add(meta.name)
                    if meta.cache_invalidation:
                        cache_invalidate_tools.add(meta.name)

                # 网络写操作会导致结构缓存失效。
                if meta.mutating:
                    network_mutating_tools.add(meta.name)
                if meta.execution_barrier:
                    execution_barrier_tools.add(meta.name)

                if meta.name in {
                    "create_node", "create_nodes_batch", "create_named_null",
                    "connect_nodes", "cook_node", "set_node_parameter",
                    "create_wrangle_node",
                }:
                    compression_operation_tools.add(meta.name)

                if meta.name in {
                    "create_node", "get_node_parameters", "get_parameter_schema",
                    "inspect_node", "get_node_connections", "suggest_connection",
                    "preview_node_operation", "validate_node_network", "list_children",
                    "find_nodes", "get_geometry_summary", "get_scene_snapshot",
                    "read_selection", "check_errors", "verify_network",
                }:
                    thinking_simple_success_tools.add(meta.name)

                if meta.name in {
                    "connect_nodes", "cook_node", "create_named_null", "delete_node",
                    "disconnect_nodes", "rename_node", "preview_layout_nodes",
                    "set_node_parameter", "batch_set_parameters", "create_nodes_batch",
                    "create_wrangle_node", "copy_node", "set_display_flag", "set_node_flags",
                    "execute_python", "execute_shell", "save_hip", "run_skill",
                }:
                    thinking_deep_tools.add(meta.name)

                if meta.name in {
                    "get_parameter_schema", "search_node_types", "search_local_doc",
                    "list_node_parameters", "get_node_info", "search_parameters",
                }:
                    loop_guidance_query_tools.add(meta.name)

            # 兼容旧行为：部分只读工具并非 network 标签，但应参与失效清理。
            if "check_errors" in dedup_tools:
                cache_invalidate_tools.add("check_errors")

            return {
                "dedup_tools": dedup_tools,
                "async_tools": async_tools,
                "batch_readonly_tools": batch_readonly_tools,
                "network_mutating_tools": network_mutating_tools,
                "cache_invalidate_tools": cache_invalidate_tools,
                "history_query_tools": history_query_tools,
                "compression_query_tools": compression_query_tools,
                "compression_operation_tools": compression_operation_tools,
                "thinking_simple_success_tools": thinking_simple_success_tools,
                "thinking_deep_tools": thinking_deep_tools,
                "loop_guidance_query_tools": loop_guidance_query_tools,
                "execution_barrier_tools": execution_barrier_tools,
            }

    # ---------- 执行 ----------

    def execute(self, name: str, args: dict, mode: Optional[str] = None,
                runtime: Optional[str] = None) -> dict:
        """统一执行入口

        如果工具有 handler，直接调用。否则返回错误。
        注意：核心 Houdini 工具的 handler 为 None，由 MCP Client 分派。
        """
        meta = self._tools.get(name)
        if not meta:
            return {"success": False, "error": f"工具未注册: {name}"}
        if not meta.enabled:
            return {"success": False, "error": f"工具已禁用: {name}"}
        if mode is not None and mode not in meta.modes:
            return {"success": False, "error": f"工具 {name} 不允许在 {mode} 模式执行"}
        if runtime is not None and meta.runtime != runtime:
            return {"success": False, "error": f"工具 {name} runtime 不匹配"}
        if not meta.handler:
            return {"success": False, "error": f"工具 {name} 无 handler（由 MCP Client 分派）"}
        try:
            return meta.handler(args)
        except Exception as e:
            return {"success": False, "error": f"工具 {name} 执行失败: {e}\n{traceback.format_exc()[:500]}"}

    # ---------- 启用 / 禁用 ----------

    def set_enabled(self, name: str, enabled: bool):
        """设置工具启用/禁用状态"""
        with self._lock:
            meta = self._tools.get(name)
            if meta:
                meta.enabled = enabled
            if enabled:
                self._disabled_tools.discard(name)
            else:
                self._disabled_tools.add(name)

    def is_enabled(self, name: str) -> bool:
        """查询工具是否启用"""
        meta = self._tools.get(name)
        return meta.enabled if meta else False

    def load_disabled_from_config(self, disabled_list: List[str]):
        """从配置文件加载禁用列表"""
        with self._lock:
            self._disabled_tools = set(disabled_list)
            for name, meta in self._tools.items():
                meta.enabled = name not in self._disabled_tools

    def get_disabled_tools(self) -> List[str]:
        """获取当前禁用列表"""
        return sorted(self._disabled_tools)

    def save_disabled_to_config(self):
        """将禁用列表保存到 plugins.json"""
        try:
            from .hooks import _plugin_config, _save_plugin_config
            _plugin_config["disabled_tools"] = sorted(self._disabled_tools)
            _save_plugin_config()
        except Exception as e:
            print(f"[ToolRegistry] 保存禁用列表失败: {e}")

    # ---------- 核心工具批量注册 ----------

    def register_core_tools(self, houdini_tools: List[dict]):
        """将 HOUDINI_TOOLS 列表批量注册为核心工具

        handler 为 None — 核心工具由 MCP Client 通过 _TOOL_DISPATCH 分派。
        """
        registered_names = []
        try:
            for tool_def in houdini_tools:
                name = tool_def.get("function", {}).get("name", "")
                if not name:
                    continue
                self.register(
                    name=name,
                    schema=tool_def,
                    handler=None,
                    source="core",
                    tags=_infer_tags(name),
                    modes=_infer_modes(name),
                    concurrency_safe=_infer_concurrency_safe(name),
                    risk_level=_infer_risk_level(name),
                    runtime="local" if name in _LOCAL_RUNTIME_TOOLS else "houdini",
                    requires_confirmation=name in _CORE_CONFIRM_TOOLS,
                    path_kinds=_infer_path_kinds(tool_def),
                    mutating=name in _MUTATING_TOOLS,
                    undo=name in _MUTATING_TOOLS,
                    cook_triggering=name in _COOK_TRIGGERING_TOOLS,
                    cook_before_read=name in _COOK_BEFORE_READ_TOOLS,
                    cache_invalidation=name in _READONLY_TOOLS and "network" in _infer_tags(name),
                )
                registered_names.append(name)
        except Exception:
            with self._lock:
                for name in registered_names:
                    meta = self._tools.get(name)
                    if meta is not None and meta.source == "core":
                        self._tools.pop(name, None)
            raise
        self._initialized = True

    # ---------- 意图感知工具过滤 ----------

    # 工具按功能分组
    _INTENT_TOOL_GROUPS: Dict[str, Set[str]] = {
        'base': {
            'get_network_structure', 'read_selection', 'verify_network',
            'search_memory',
        },
        'query': {
            'get_network_structure', 'get_parameter_schema', 'inspect_node', 'get_node_connections',
            'suggest_connection', 'preview_node_operation', 'validate_node_network', 'find_nodes',
            'get_geometry_summary', 'temporary_auto_validate_geometry', 'get_scene_snapshot',
            'verify_network', 'read_selection',
            'search_memory',
            'capture_viewport',
        },
        'create': {
            'create_node', 'create_nodes_batch', 'create_wrangle_node',
            'connect_nodes', 'copy_node', 'create_named_null',
            'verify_network',
        },
        'connection': {
            'get_node_connections', 'suggest_connection',
            'preview_node_operation', 'connect_nodes', 'disconnect_nodes',
        },
        'parameter': {
            'get_parameter_schema', 'inspect_node',
            'set_node_parameter', 'set_parameter_expression', 'batch_set_parameters',
        },
        'flags': {
            'inspect_node', 'preview_node_operation', 'set_node_flags', 'set_update_mode',
            'validate_node_network',
        },
        'validate': {
            'inspect_node', 'get_node_connections', 'validate_node_network',
            'verify_network', 'get_geometry_summary', 'temporary_auto_validate_geometry',
        },
        'cook': {
            'inspect_node', 'cook_node', 'verify_network', 'validate_node_network',
        },
        'null': {
            'create_named_null', 'get_node_connections', 'suggest_connection',
            'preview_node_operation', 'validate_node_network',
        },
        'modify': {
            'set_node_parameter', 'set_parameter_expression', 'batch_set_parameters',
            'set_node_flags', 'set_update_mode',
        },
        'operation': {
            'get_network_structure', 'inspect_node', 'get_parameter_schema',
            'get_node_connections', 'suggest_connection',
            'preview_node_operation', 'validate_node_network',
            'set_node_parameter', 'batch_set_parameters', 'set_node_flags',
            'connect_nodes', 'disconnect_nodes', 'delete_node', 'rename_node',
            'layout_nodes', 'verify_network',
        },
        'delete': {
            'delete_node', 'rename_node',
            'preview_node_operation', 'get_node_connections', 'get_network_structure',
        },
        'code': {
            'execute_python', 'execute_shell',
        },
        'search': {
            'web_search', 'fetch_webpage', 'search_local_doc',
            'search_node_types', 'semantic_search_nodes',
            'find_nodes', 'inspect_node', 'get_node_connections', 'suggest_connection',
            'preview_node_operation', 'validate_node_network', 'get_scene_snapshot', 'get_houdini_node_doc',
            'search_memory',
        },
        'memory_write': {
            'remember_memory',
            'search_memory',
        },
        'layout': {
            'layout_nodes', 'create_network_box',
        },
        'task': {
            'add_todo', 'update_todo',
        },
        'perf': {
            'perf_start_profile', 'perf_stop_and_report',
        },
        'file': {
            'save_hip', 'undo_redo',
        },
        'plan': {
            'create_plan', 'update_plan_step', 'ask_question',
        },
        'skill': set(),  # 动态填充
    }

    # 意图关键词（中英文）
    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        'query': ['what', 'show', 'list', 'check', 'look', 'display', 'view', 'see',
                  '查看', '检查', '分析', '看看', '显示', '状态', '有什么', '哪些'],
        'create': ['create', 'build', 'make', 'add', 'generate', 'construct',
                   '创建', '搭建', '添加', '生成', '建', '做', '造'],
        'connection': ['connect', 'disconnect', 'wire', 'input', 'output', 'link',
                       '连接', '接线', '断开', '输入', '输出', '端口', '插到'],
        'parameter': ['parameter', 'parm', 'param', 'value', 'menu', 'tuple',
                      '参数', '取值', '菜单', '数值'],
        'flags': ['flag', 'display flag', 'render flag', 'bypass', 'template', 'lock',
                  '显示标志', '渲染标志', '旁路', '模板', '锁定', '选中'],
        'validate': ['validate', 'verify', 'diagnose', 'error', 'warning', 'issue', 'problem',
                     '验证', '校验', '诊断', '错误', '警告', '问题'],
        'cook': ['cook', 'recook', 'cache', 'bake',
                 '烹饪', '缓存', '重新计算'],
        'null': ['null', 'out null', 'output null', 'named null', 'OUT_', 'IN_', 'CTRL_', 'CACHE_',
                 '空节点', '输出空节点', '命名null'],
        'modify': ['change', 'set', 'modify', 'update', 'adjust', 'tweak',
                   '修改', '设置', '调整', '改', '变'],
        'delete': ['delete', 'remove', 'destroy', 'rename',
                   '删除', '删掉', '移除', '销毁', '清除', '重命名', '改名'],
        'operation': ['apply', 'implement', 'optimize', 'fix', 'repair', 'cleanup', 'clean up',
                      '应用', '落实', '优化', '修复', '执行优化', '清理', '简化'],
        'code': ['python', 'script', 'code', 'vex', 'wrangle',
                  '脚本', '代码'],
        'search': ['search', 'find', 'where', 'document', 'doc', 'web', 'online',
                   'memory', 'recall',
                   '搜索', '查找', '文档', '网上', '在线',
                   '记忆', '回忆', '偏好', '历史'],
        'memory_write': ['记住', '记下来', '保存为长期记忆', 'remember this', 'save this'],
        'layout': ['layout', 'organize', 'arrange', 'position', 'move',
                   '排列', '布局', '整理', '位置'],
        'perf': ['performance', 'profile', 'benchmark', 'speed', 'slow',
                 '性能', '速度', '慢', '优化'],
        'file': ['save', 'undo', 'redo', '保存', '撤销', '重做'],
    }

    _DEFAULT_INTENT_GROUPS = frozenset({'base', 'task'})

    # Agent 模式应始终具备最小写操作能力；Ask 模式仍保持只读。
    _AGENT_ALWAYS_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'create_wrangle_node',
        'set_node_parameter', 'batch_set_parameters', 'set_node_flags',
        'connect_nodes', 'disconnect_nodes', 'delete_node', 'rename_node',
        'layout_nodes', 'copy_node', 'create_named_null',
        'set_update_mode',
    })

    _TOOL_DEPENDENCIES: Dict[str, Set[str]] = {
        'connect_nodes': {'get_node_connections', 'suggest_connection', 'preview_node_operation'},
        'disconnect_nodes': {'get_node_connections', 'preview_node_operation'},
        'set_node_parameter': {'inspect_node', 'get_parameter_schema'},
        'batch_set_parameters': {'inspect_node', 'get_parameter_schema'},
        'set_node_flags': {'inspect_node', 'preview_node_operation', 'validate_node_network'},
        'create_node': {'get_network_structure', 'search_node_types'},
        'create_nodes_batch': {'get_network_structure', 'search_node_types', 'verify_network'},
        'create_wrangle_node': {'get_network_structure', 'get_houdini_node_doc'},
        'create_named_null': {'get_node_connections', 'suggest_connection', 'preview_node_operation', 'validate_node_network'},
        'layout_nodes': {'get_network_structure'},
        'create_network_box': set(),
        'cook_node': {'inspect_node', 'verify_network'},
        'copy_node': {'inspect_node', 'get_network_structure'},
        'save_hip': {'get_scene_snapshot'},
    }

    def classify_intent(self, user_message: str) -> Set[str]:
        """根据用户消息关键词推断意图类别

        Returns:
            命中的意图集合，如 {'query', 'create'}
        """
        if not user_message:
            return set()
        msg_lower = user_message.lower()
        matched = set()
        for intent, keywords in self._INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in msg_lower:
                    matched.add(intent)
                    break  # 一个关键词命中即可
        return matched

    def _expand_tool_dependencies(self, tool_names: Set[str]) -> Set[str]:
        """Add helper tools that make selected write tools safer to call."""
        expanded = set(tool_names)
        pending = list(tool_names)
        while pending:
            name = pending.pop()
            for dep in self._TOOL_DEPENDENCIES.get(name, set()):
                if dep not in expanded:
                    expanded.add(dep)
                    pending.append(dep)
        return expanded

    def select_tools_for_request(self, user_message: str, mode: str = 'agent') -> List[dict]:
        """Classify a user request and return the smallest useful tool schema set."""
        return self.get_tools_for_intent(self.classify_intent(user_message or ""), mode=mode)

    def get_tools_for_intent(self, intents: Set[str], mode: str = 'agent') -> List[dict]:
        """根据意图集获取相关工具 schema

        始终包含 'base' 和 'task' 组，额外包含匹配意图的工具组。
        只返回该 mode 下允许且启用的工具。
        """
        # 始终包含基础工具组
        active_groups = set(self._DEFAULT_INTENT_GROUPS) | intents

        # 收集目标工具名集合
        target_names: Set[str] = set()
        for group in active_groups:
            target_names |= self._INTENT_TOOL_GROUPS.get(group, set())
        if mode == 'agent':
            target_names |= self._AGENT_ALWAYS_TOOLS
        target_names = self._expand_tool_dependencies(target_names)

        # Skill 元工具始终可用：skill 通过 run_skill/list_skills 暴露（非独立工具），
        # 不属于任何意图组，必须显式纳入，否则会被意图过滤剔除。
        target_names |= {'run_skill', 'list_skills'}

        # 过滤：必须在指定 mode 中且启用
        with self._lock:
            result = []
            for meta in self._tools.values():
                if not meta.enabled:
                    continue
                if mode not in meta.modes:
                    continue
                if meta.name in target_names:
                    result.append(meta.schema)
            return result

    def is_tool_allowed_in_mode(self, tool_name: str, mode: str) -> bool:
        """检查工具是否被允许在指定模式下使用"""
        meta = self._tools.get(tool_name)
        if not meta:
            return False
        return meta.enabled and mode in meta.modes

    @property
    def initialized(self) -> bool:
        return self._initialized


# ─────────────────────────────────────────────
# 全局单例
# ─────────────────────────────────────────────

_instance: Optional[ToolRegistry] = None
_instance_lock = threading.Lock()


def get_tool_registry() -> ToolRegistry:
    """获取 ToolRegistry 全局单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ToolRegistry()
    return _instance
