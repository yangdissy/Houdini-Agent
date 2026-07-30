# -*- coding: utf-8 -*-
"""Harness V2 foundation: runtime state and tool policy decisions.

This module is intentionally lightweight and can be enabled gradually.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .harness_policy_config import (
    HIGH_RISK_TOOLS,
    PYTHON_DANGEROUS_PATTERNS,
    SECRET_REDACTION_PATTERNS,
    SENSITIVE_ARG_KEYS,
    SENSITIVE_VALUE_PATTERNS,
    SHELL_DANGEROUS_PATTERNS,
)


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


def redact_secrets(value: Any) -> Any:
    """Redact sensitive text from tool outputs before UI/LLM reuse."""
    if isinstance(value, str):
        text = value
        for pattern, replacement in SECRET_REDACTION_PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.DOTALL)
        return text
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key).strip().lower()
            if key_text in SENSITIVE_ARG_KEYS or key_text.endswith(("_api_key", "_token", "_password", "_secret")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(child)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item) for item in value)
    return value


def sanitize_tool_result(result: Any) -> Dict[str, Any]:
    """Normalize tool result shape and redact secrets.

    The harness contract is always {success: bool, result/error: ...}. Extra
    metadata is preserved after recursive redaction.
    """
    if not isinstance(result, dict):
        return {"success": False, "error": f"Invalid tool result type: {type(result).__name__}"}

    sanitized = redact_secrets(dict(result))
    success = bool(sanitized.get("success", False))
    sanitized["success"] = success
    if success:
        sanitized.setdefault("result", "")
        if sanitized.get("error") is None:
            sanitized.pop("error", None)
    else:
        error = sanitized.get("error")
        if error is None or error == "":
            if "result" in sanitized and sanitized.get("result") not in (None, ""):
                error = sanitized.get("result")
            else:
                error = "Tool returned unsuccessful result without error details"
        sanitized["error"] = str(error)
    return sanitized


@dataclass
class ToolValidationIssue:
    """Structured argument validation issue."""

    severity: str
    code: str
    message: str
    key: str = ""


@dataclass
class ToolValidationResult:
    """Normalized tool arguments plus structured validation findings."""

    args: Dict[str, Any]
    issues: List[ToolValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def first_error(self) -> str:
        for issue in self.issues:
            if issue.severity == "error":
                return issue.message
        return ""


@dataclass
class RiskFactor:
    """One structured signal contributing to a policy decision."""

    code: str
    severity: str
    message: str
    score: float = 0.0


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
    risk_score: float = 0.0
    risk_factors: List[RiskFactor] = field(default_factory=list)
    matched_rules: List[str] = field(default_factory=list)
    required_control: str = ""


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


class ToolArgumentValidator:
    """Validate and normalize tool arguments before policy scoring."""

    _REQUIRED_ARG_KEYS = {
        "execute_python": ("code",),
        "execute_shell": ("command",),
        "get_node_parameters": ("node_path",),
        "get_parameter_schema": ("node_path",),
        "inspect_node": ("node_path",),
        "get_geometry_summary": ("node_path",),
        "temporary_auto_validate_geometry": ("node_path",),
        "list_children": ("node_path",),
        "delete_node": ("node_path",),
        "rename_node": ("node_path",),
        "set_node_parameter": ("node_path",),
        "set_parameter_expression": ("node_path", "param_name"),
        "batch_set_parameters": ("node_path",),
        "connect_nodes": ("from_path", "to_path"),
        "create_named_null": ("name",),
        "cook_node": ("node_path",),
        "disconnect_nodes": ("node_path",),
        "get_node_connections": ("node_path",),
        "suggest_connection": ("from_path", "to_path"),
        "copy_node": ("source_path",),
        "set_display_flag": ("node_path",),
        "set_node_flags": ("node_path",),
        "set_update_mode": ("mode",),
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
        "root_path",
    })

    _HOUDINI_ROOTS = frozenset({
        "/obj",
        "/out",
        "/shop",
        "/stage",
        "/tasks",
        "/ch",
        "/mat",
        "/img",
        "/cop",
    })

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

    def validate(self, tool_name: str, args: Dict[str, Any]) -> ToolValidationResult:
        safe_args = self._normalize_args(args)
        issues: List[ToolValidationIssue] = []

        for key in self._REQUIRED_ARG_KEYS.get(tool_name, ()):
            if not str(safe_args.get(key, "")).strip():
                issues.append(
                    ToolValidationIssue(
                        severity="error",
                        code="missing_required_arg",
                        message=f"Missing required {key} for tool: {tool_name}",
                        key=key,
                    )
                )

        sensitive_reason = self._check_sensitive_args(safe_args)
        if sensitive_reason:
            issues.append(ToolValidationIssue(severity="error", code="sensitive_input", message=sensitive_reason))

        path_reason = self._check_path_args(safe_args)
        if path_reason:
            issues.append(ToolValidationIssue(severity="error", code="invalid_path", message=path_reason))

        if tool_name == "execute_python":
            reason = self._match_patterns(
                str(safe_args.get("code") or ""),
                PYTHON_DANGEROUS_PATTERNS,
                "Tool input guardrail blocked dangerous Python",
            )
            if reason:
                issues.append(
                    ToolValidationIssue(severity="error", code="dangerous_python", message=reason, key="code")
                )

        if tool_name == "execute_shell":
            reason = self._match_patterns(
                str(safe_args.get("command") or ""),
                SHELL_DANGEROUS_PATTERNS,
                "Tool input guardrail blocked dangerous shell command",
                flags=re.IGNORECASE,
            )
            if reason:
                issues.append(
                    ToolValidationIssue(severity="error", code="dangerous_shell", message=reason, key="command")
                )

        return ToolValidationResult(args=safe_args, issues=issues)

    def _check_sensitive_args(self, args: Dict[str, Any]) -> str:
        for key, value in self._walk_args(args):
            key_text = str(key or "").strip().lower()
            if key_text in SENSITIVE_ARG_KEYS or key_text.endswith(("_api_key", "_token", "_password", "_secret")):
                return f"Tool input guardrail blocked sensitive argument: {key}"
            if isinstance(value, str):
                reason = self._match_patterns(
                    value,
                    SENSITIVE_VALUE_PATTERNS,
                    "Tool input guardrail blocked sensitive value",
                    flags=re.IGNORECASE,
                )
                if reason:
                    return reason
        return ""

    def _check_path_args(self, args: Dict[str, Any]) -> str:
        for key in self._NORMALIZE_KEYS:
            value = args.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            reason = self._validate_path_arg(key, value.strip())
            if reason:
                return reason
        return ""

    def _validate_path_arg(self, key: str, path: str) -> str:
        normalized = path.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if ".." in parts:
            return f"Tool input guardrail blocked path traversal in {key}"
        if "\x00" in normalized:
            return f"Tool input guardrail blocked invalid path in {key}"

        if key == "output_path":
            return ""

        if normalized.startswith("/") and not any(
            normalized == root or normalized.startswith(root + "/") for root in self._HOUDINI_ROOTS
        ):
            return f"Tool input guardrail blocked unsupported Houdini path root in {key}: {path}"

        return ""

    @staticmethod
    def _match_patterns(
        text: str,
        patterns: Iterable[Tuple[str, str]],
        prefix: str,
        flags: int = 0,
    ) -> str:
        for pattern, rule_id in patterns:
            if re.search(pattern, text or "", flags):
                return f"{prefix}: {rule_id}"
        return ""

    @classmethod
    def _walk_args(cls, value: Any, key: str = ""):
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                yield from cls._walk_args(child_value, str(child_key))
        elif isinstance(value, list):
            for child_value in value:
                yield from cls._walk_args(child_value, key)
        else:
            yield key, value

    @staticmethod
    def _normalize_path(path: str) -> str:
        # Keep Houdini path semantics while removing duplicated slashes.
        if not path:
            return path
        while "//" in path:
            path = path.replace("//", "/")
        return path


class HarnessToolPolicyEngine:
    """Centralized tool policy checks.

    The default policy is conservative and only blocks obviously invalid calls.
    """

    _DANGEROUS_TOOLS = HIGH_RISK_TOOLS

    def __init__(self, validator: Optional[ToolArgumentValidator] = None):
        self.validator = validator or ToolArgumentValidator()

    def decide(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> ToolPolicyDecision:
        validation = self.validator.validate(tool_name, args)
        safe_args = validation.args

        if not validation.ok:
            return self._decision(
                "deny",
                validation.first_error,
                risk_factors=self._validation_risk_factors(validation),
                required_control="deny",
            )

        mode = context.get("mode", "agent")
        confirm_mode = bool(context.get("confirm_mode", False))
        if mode == "ask" and tool_name in self._DANGEROUS_TOOLS:
            return self._decision(
                "deny",
                f"Ask mode blocked tool: {tool_name}",
                risk_factors=[RiskFactor("ask_mode_high_risk", "error", f"Ask mode blocked tool: {tool_name}", 1.0)],
                required_control="deny",
            )

        # confirm_mode=True means Step Confirm is enabled: high-risk tools must
        # ask the user before execution. confirm_mode=False is Direct Execute
        # (HIGH-RISK), where the user has opted out of confirmation prompts.
        if mode in {"agent", "plan"} and tool_name in self._DANGEROUS_TOOLS and confirm_mode:
            return self._decision(
                "ask",
                f"Dangerous tool requires confirmation: {tool_name}",
                risk_factors=[RiskFactor("high_risk_confirmation", "warning", f"Dangerous tool requires confirmation: {tool_name}", 0.7)],
                required_control="confirm",
            )

        if tool_name == "save_hip":
            out = str(safe_args.get("output_path") or "").strip()
            if out and not os.path.splitext(out)[1]:
                patched = dict(safe_args)
                patched["output_path"] = out + ".hip"
                return self._decision(
                    "retry",
                    "Auto-fix save_hip output_path extension to .hip",
                    patched_args=patched,
                    retry_key=f"{tool_name}:output_path_ext",
                    risk_factors=[RiskFactor("retry_patch_output_extension", "info", "Auto-fix save_hip output_path extension to .hip", 0.1)],
                    required_control="retry",
                )

        # cook_node force=true 触发硬复位（bypass 切换 + 清 cache + 强制 cook），
        # 可能长时间阻塞 Houdini 主线程。无论是否开启 confirm_mode，都要求用户确认，
        # 防止模型绕过工具描述直接硬 cook 导致界面卡死。
        if tool_name == "cook_node" and bool(safe_args.get("force")) and mode in {"agent", "plan"}:
            return self._decision(
                "ask",
                "cook_node force=true may block Houdini; requires confirmation",
                patched_args=safe_args if safe_args != args else None,
                risk_factors=[RiskFactor("cook_force_confirmation", "warning", "cook_node force=true may block Houdini", 0.8)],
                required_control="confirm",
            )

        if safe_args != args:
            return self._decision(
                action="allow",
                reason="Arguments normalized",
                patched_args=safe_args,
                risk_factors=[RiskFactor("args_normalized", "info", "Arguments normalized", 0.0)],
            )

        return self._decision("allow")

    @staticmethod
    def _validation_risk_factors(validation: ToolValidationResult) -> List[RiskFactor]:
        factors = []
        for issue in validation.issues:
            score = 1.0 if issue.severity == "error" else 0.2
            factors.append(RiskFactor(issue.code, issue.severity, issue.message, score))
        return factors

    @staticmethod
    def _decision(
        action: str,
        reason: str = "",
        patched_args: Optional[Dict[str, Any]] = None,
        retry_key: str = "",
        risk_factors: Optional[List[RiskFactor]] = None,
        required_control: str = "",
    ) -> ToolPolicyDecision:
        factors = risk_factors or []
        return ToolPolicyDecision(
            action=action,
            reason=reason,
            patched_args=patched_args,
            retry_key=retry_key,
            risk_score=round(sum(f.score for f in factors), 3),
            risk_factors=factors,
            matched_rules=[f.code for f in factors],
            required_control=required_control or (action if action in {"ask", "deny", "retry"} else ""),
        )

    def _check_input_guardrails(self, tool_name: str, args: Dict[str, Any]) -> str:
        validation = self.validator.validate(tool_name, args)
        return validation.first_error

    def _check_input_guardrails(self, tool_name: str, args: Dict[str, Any]) -> str:
        sensitive_reason = self._check_sensitive_args(args)
        if sensitive_reason:
            return sensitive_reason

        path_reason = self._check_path_args(args)
        if path_reason:
            return path_reason

        if tool_name == "execute_python":
            return self._match_patterns(
                str(args.get("code") or ""),
                PYTHON_DANGEROUS_PATTERNS,
                "Tool input guardrail blocked dangerous Python",
            )

        if tool_name == "execute_shell":
            return self._match_patterns(
                str(args.get("command") or ""),
                SHELL_DANGEROUS_PATTERNS,
                "Tool input guardrail blocked dangerous shell command",
                flags=re.IGNORECASE,
            )

        return ""

    def _check_sensitive_args(self, args: Dict[str, Any]) -> str:
        for key, value in self._walk_args(args):
            key_text = str(key or "").strip().lower()
            if key_text in SENSITIVE_ARG_KEYS or key_text.endswith(("_api_key", "_token", "_password", "_secret")):
                return f"Tool input guardrail blocked sensitive argument: {key}"
            if isinstance(value, str):
                reason = self._match_patterns(
                    value,
                    SENSITIVE_VALUE_PATTERNS,
                    "Tool input guardrail blocked sensitive value",
                    flags=re.IGNORECASE,
                )
                if reason:
                    return reason
        return ""

    def _check_path_args(self, args: Dict[str, Any]) -> str:
        for key in self._NORMALIZE_KEYS:
            value = args.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            reason = self._validate_path_arg(key, value.strip())
            if reason:
                return reason
        return ""

    def _validate_path_arg(self, key: str, path: str) -> str:
        normalized = path.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if ".." in parts:
            return f"Tool input guardrail blocked path traversal in {key}"
        if "\x00" in normalized:
            return f"Tool input guardrail blocked invalid path in {key}"

        if key == "output_path":
            return ""

        if normalized.startswith("/") and not any(
            normalized == root or normalized.startswith(root + "/") for root in self._HOUDINI_ROOTS
        ):
            return f"Tool input guardrail blocked unsupported Houdini path root in {key}: {path}"

        return ""

    @staticmethod
    def _match_patterns(
        text: str,
        patterns: Iterable[Tuple[str, str]],
        prefix: str,
        flags: int = 0,
    ) -> str:
        for pattern, rule_id in patterns:
            if re.search(pattern, text or "", flags):
                return f"{prefix}: {rule_id}"
        return ""

    @classmethod
    def _walk_args(cls, value: Any, key: str = ""):
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                yield from cls._walk_args(child_value, str(child_key))
        elif isinstance(value, list):
            for child_value in value:
                yield from cls._walk_args(child_value, key)
        else:
            yield key, value

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
