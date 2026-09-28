# -*- coding: utf-8 -*-
"""Governed execution boundary for calls arriving from external MCP clients."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable, Dict, Optional

from houdini_agent.core.harness_engine import GovernedToolExecutor, ToolPolicyDecision

from .settings import MCPSettings


_RISK_ORDER = {"low": 0, "normal": 1, "high": 2}


@dataclass(frozen=True)
class ExternalMCPContext:
    session_id: str
    client_id: str
    mode: str
    username: str
    correlation_id: str

    def is_valid(self) -> bool:
        return all((self.session_id, self.client_id, self.username, self.correlation_id)) and self.mode in {
            "ask", "agent", "plan_planning", "plan_executing"
        }


class ExternalMCPExecutionAdapter:
    """Authorize and govern one external MCP tool call before dispatch."""

    def __init__(
        self,
        settings: MCPSettings,
        registry,
        policy_engine,
        execute: Callable[[str, Dict[str, Any]], Dict[str, Any]],
        confirm: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
        audit: Optional[Callable[[Dict[str, Any]], None]] = None,
        session_id: str = "",
        client_id: str = "external-mcp",
        username: str = "",
        manifest=None,
        dispatcher=None,
        executor=None,
        hou_module=None,
        agent_version: str = "unknown",
        sdk_version: Optional[str] = None,
    ):
        self._settings = settings
        self._registry = registry
        self._policy_engine = policy_engine
        self._execute = execute
        self._confirm = confirm
        self._audit = audit
        self._session_id = session_id
        self._client_id = client_id
        self._username = username
        self._stopped = threading.Event()
        self._retry_counts: Dict[str, int] = {}
        self._call_counts: Dict[str, int] = {}
        self._call_count_lock = threading.Lock()
        self._concurrency = threading.BoundedSemaphore(settings.max_concurrent_calls)
        self._long_running = threading.BoundedSemaphore(settings.max_long_running_calls)
        self._long_running_tools = {
            item.get("name") for item in (manifest or [])
            if item.get("long_running") and item.get("name")
        }
        self.manifest = tuple(dict(item) for item in (manifest or []))
        self._dispatcher = dispatcher
        self._executor = executor
        self._hou_module = hou_module
        self._agent_version = agent_version
        self._sdk_version = sdk_version

    def shutdown(self) -> None:
        """Permanently reject calls after the owning server lifecycle stops."""
        self._stopped.set()

    def is_shutdown(self) -> bool:
        return self._stopped.is_set()

    def capabilities(self) -> dict:
        from .capabilities import build_runtime_capabilities
        return build_runtime_capabilities(
            manifest=list(self.manifest),
            dispatcher=self._dispatcher,
            executor=self._executor,
            hou_module=self._hou_module,
            agent_version=self._agent_version,
            sdk_version=self._sdk_version,
            session_id=self._session_id,
        )

    def session_info(self) -> dict:
        capabilities = self.capabilities()
        return {
            "session_id": capabilities["session_id"],
            "username": self._username,
            "client_id": self._client_id,
            "executor_state": capabilities["executor_state"],
            "status": capabilities["status"],
        }

    def new_context(self, mode: str = "ask") -> ExternalMCPContext:
        import uuid
        return ExternalMCPContext(
            session_id=self._session_id,
            client_id=self._client_id,
            mode=mode,
            username=self._username,
            correlation_id=uuid.uuid4().hex,
        )

    def execute(
        self,
        context: ExternalMCPContext,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        denial = self._authorize(context, tool_name, args)
        if denial is not None:
            self._record(context, {
                "event_type": "tool_policy", "tool": tool_name,
                "action": "deny", "reason_code": denial,
            })
            return {"success": False, "error": denial}

        with self._call_count_lock:
            call_count = self._call_counts.get(context.session_id, 0)
            if call_count >= self._settings.max_calls_per_session:
                denial = "External MCP session call limit reached"
            else:
                self._call_counts[context.session_id] = call_count + 1
                denial = None
        if denial is not None:
            self._record(context, {
                "event_type": "tool_policy", "tool": tool_name,
                "action": "deny", "reason_code": "session_call_limit",
            })
            return {"success": False, "error": denial}

        if not self._concurrency.acquire(blocking=False):
            self._record(context, {
                "event_type": "tool_policy", "tool": tool_name,
                "action": "deny", "reason_code": "concurrency_limit",
            })
            return {"success": False, "error": "External MCP concurrency limit reached"}

        long_running_acquired = False
        if tool_name in self._long_running_tools:
            long_running_acquired = self._long_running.acquire(blocking=False)
            if not long_running_acquired:
                self._concurrency.release()
                self._record(context, {
                    "event_type": "tool_policy", "tool": tool_name,
                    "action": "deny", "reason_code": "long_running_limit",
                })
                return {"success": False, "error": "External MCP long-running call limit reached"}

        try:
            policy_engine = self._policy_engine
            authorization = self._registry.authorize_dispatch(tool_name, context.mode, "houdini")
            meta = authorization.get("meta")
            if meta is not None and meta.mutating:
                class ExternalMutationPolicy:
                    def __init__(inner_self, base_policy):
                        inner_self._base_policy = base_policy

                    def decide(inner_self, name, safe_args, policy_context):
                        decision = inner_self._base_policy.decide(name, safe_args, policy_context)
                        if decision.action == "allow":
                            return ToolPolicyDecision(
                                action="ask",
                                reason="External MCP scene mutation requires Houdini panel confirmation",
                            )
                        return decision

                policy_engine = ExternalMutationPolicy(policy_engine)
            owner = GovernedToolExecutor(
                policy_engine,
                lambda name, safe_args, confirmed: self._execute(name, safe_args),
                confirm=self._confirm,
                audit=lambda record: self._record(context, record),
                retry_counts=self._retry_counts,
            )
            return owner.execute(tool_name, dict(args or {}), {
                "mode": context.mode,
                "confirm_mode": True,
                "external_mcp": True,
            })
        finally:
            if long_running_acquired:
                self._long_running.release()
            self._concurrency.release()

    def _authorize(
        self,
        context: ExternalMCPContext,
        tool_name: str,
        context_args: Dict[str, Any],
    ) -> Optional[str]:
        if not context.is_valid():
            return "External MCP context is incomplete or untrusted"
        if self._stopped.is_set():
            return "adapter_stopped"
        if self._executor is not None:
            try:
                if self._executor.is_shutdown():
                    return "executor_shutdown"
                if self._executor.is_blocked():
                    return "executor_blocked"
            except Exception:
                return "executor_state_unavailable"
        if tool_name in self._settings.denied_tools:
            return f"External MCP tool is explicitly denied: {tool_name}"
        if tool_name not in self._settings.allowed_tools:
            return f"External MCP tool is not allowlisted: {tool_name}"
        try:
            authorization = self._registry.authorize_dispatch(tool_name, context.mode, "houdini")
        except Exception:
            return "Tool Registry unavailable; execution denied"
        if not authorization.get("allowed"):
            return authorization.get("error", "Tool Registry denied external MCP dispatch")
        meta = authorization.get("meta")
        if meta is None:
            return f"Tool metadata unavailable: {tool_name}"
        if _RISK_ORDER.get(meta.risk_level, 99) > _RISK_ORDER[self._settings.max_risk_level]:
            return f"External MCP risk limit blocked tool: {tool_name}"
        if meta.mutating:
            if tool_name == "create_node" and not str(context_args.get("parent_path") or "").strip():
                return "External MCP create_node requires explicit parent_path"
            if tool_name == "rename_node":
                new_name = str(context_args.get("new_name") or "").strip()
                if not new_name or any(char in new_name for char in "/\\") or new_name in {".", ".."}:
                    return "External MCP rename_node requires a valid leaf node name"
            if tool_name == "layout_nodes":
                node_paths = context_args.get("node_paths")
                if not str(context_args.get("network_path") or "").strip():
                    return "External MCP layout_nodes requires explicit network_path"
                if not isinstance(node_paths, list) or not 1 <= len(node_paths) <= 50:
                    return "External MCP layout_nodes requires 1 to 50 explicit node_paths"
            if tool_name == "set_node_flags" and any(
                key in context_args for key in ("display", "render", "select", "current")
            ):
                return "External MCP set_node_flags only allows bypass, template, and lock"
            node_paths = [
                str(args_value).replace("\\", "/").rstrip("/")
                for key, args_value in context_args.items()
                if meta.path_kinds.get(key) == "node" and args_value
            ]
            if tool_name == "layout_nodes":
                node_paths.extend(
                    str(path).replace("\\", "/").rstrip("/")
                    for path in context_args.get("node_paths", [])
                    if path
                )
            if node_paths:
                roots = self._settings.write_node_roots
                if not roots:
                    return "External MCP write node roots are not configured"
                if any(not any(path == root or path.startswith(root + "/") for root in roots) for path in node_paths):
                    return "External MCP node path is outside configured write roots"
        return None

    def _record(self, context: ExternalMCPContext, record: Dict[str, Any]) -> None:
        if self._audit is None:
            return
        safe_record = dict(record)
        safe_record.update({
            "session_id": context.session_id,
            "client_id": context.client_id,
            "username": context.username,
            "correlation_id": context.correlation_id,
            "external_mcp": True,
        })
        try:
            self._audit(safe_record)
        except Exception:
            pass