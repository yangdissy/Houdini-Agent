# -*- coding: utf-8 -*-
"""Harness V2 foundation: runtime state and tool policy decisions.

This module is intentionally lightweight and can be enabled gradually.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .harness_policy_config import HIGH_RISK_TOOLS


def _parse_bool(value: str, default: bool = False) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def is_harness_v2_enabled(default: bool = True) -> bool:
    """Read Harness V2 switch from environment variable.

    HOUDINI_AGENT_HARNESS_V2=true|false  (default: enabled)
    """
    return _parse_bool(os.getenv("HOUDINI_AGENT_HARNESS_V2", ""), default=default)


def build_tool_retry_key(tool_name: str, args: Optional[Dict[str, Any]]) -> str:
    """Build a stable retry key from tool name and argument fingerprint."""
    payload_obj = args or {}
    try:
        payload = json.dumps(
            payload_obj,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        payload = repr(payload_obj)
    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{tool_name}:{digest}"


@dataclass
class ToolPolicyDecision:
    """Policy output for a single tool call.

    action:
      - allow: run tool
      - deny: reject tool
            - ask: request user confirmation first
      - retry: run tool with patched arguments
    """

    action: str = "allow"
    reason: str = ""
    patched_args: Optional[Dict[str, Any]] = None
    retry_key: str = ""


@dataclass
class HarnessRuntimeState:
    """Small state container for runtime tracing."""

    session_id: str = ""
    started_at: float = field(default_factory=time.time)
    iteration: int = 0
    retries: int = 0
    policy_retry_counts: Dict[str, int] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def add_trace(self, event: str, **payload: Any):
        item = {"ts": round(time.time(), 3), "event": event}
        item.update(payload)
        self.trace.append(item)
        if len(self.trace) > 300:
            self.trace = self.trace[-300:]


class HarnessToolPolicyEngine:
    """Centralized tool policy checks.

    The default policy is conservative and only blocks obviously invalid calls.
    """

    _DANGEROUS_TOOLS = HIGH_RISK_TOOLS

    _REQUIRED_ARG_KEYS = {
        "get_node_parameters": ("node_path",),
        "list_children": ("node_path",),
        "delete_node": ("node_path",),
        "rename_node": ("node_path",),
        "set_node_parameter": ("node_path",),
        "batch_set_parameters": ("node_path",),
        "connect_nodes": ("from_path", "to_path"),
        "disconnect_nodes": ("node_path",),
        "copy_node": ("source_path",),
        "set_display_flag": ("node_path",),
        "set_node_flags": ("node_path",),
        "get_node_inputs": ("node_type",),
        "check_errors": ("node_path",),
        "read_selection": ("node_path",),
    }

    _NORMALIZE_KEYS = frozenset({
        "node_path",
        "source_path",
        "target_path",
        "network_path",
        "parent_path",
        "output_path",
        "from_path",
        "to_path",
        "path",
    })

    def decide(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> ToolPolicyDecision:
        safe_args = self._normalize_args(args)

        mode = context.get("mode", "agent")
        confirm_mode = bool(context.get("confirm_mode", False))
        if mode == "ask" and tool_name in self._DANGEROUS_TOOLS:
            return ToolPolicyDecision(
                action="deny",
                reason=f"Ask mode blocked tool: {tool_name}",
            )

        # confirm_mode=True means Step Confirm is enabled: high-risk tools must
        # ask the user before execution. confirm_mode=False is Direct Execute
        # (HIGH-RISK), where the user has opted out of confirmation prompts.
        if mode in {"agent", "plan"} and tool_name in self._DANGEROUS_TOOLS and confirm_mode:
            return ToolPolicyDecision(
                action="ask",
                reason=f"Dangerous tool requires confirmation: {tool_name}",
            )

        required_keys = self._REQUIRED_ARG_KEYS.get(tool_name, ())
        for key in required_keys:
            if not str(safe_args.get(key, "")).strip():
                return ToolPolicyDecision(
                    action="deny",
                    reason=f"Missing required {key} for tool: {tool_name}",
                )

        if tool_name == "save_hip":
            out = str(safe_args.get("output_path") or "").strip()
            if out and not os.path.splitext(out)[1]:
                patched = dict(safe_args)
                patched["output_path"] = out + ".hip"
                return ToolPolicyDecision(
                    action="retry",
                    reason="Auto-fix save_hip output_path extension to .hip",
                    patched_args=patched,
                    retry_key=f"{tool_name}:output_path_ext",
                )

        if safe_args != args:
            return ToolPolicyDecision(
                action="allow",
                reason="Arguments normalized",
                patched_args=safe_args,
            )

        return ToolPolicyDecision(action="allow")

    def _normalize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in (args or {}).items():
            if isinstance(value, str):
                v = value.strip()
                if key in self._NORMALIZE_KEYS and v:
                    v = self._normalize_path(v)
                out[key] = v
            else:
                out[key] = value
        return out

    @staticmethod
    def _normalize_path(path: str) -> str:
        # Keep Houdini path semantics while removing duplicated slashes.
        if not path:
            return path
        while "//" in path:
            path = path.replace("//", "/")
        return path
