# -*- coding: utf-8 -*-
"""Harness V2 foundation: runtime state and tool policy decisions.

This module is intentionally lightweight and can be enabled gradually.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .harness_policy_config import (
    EXECUTION_ERROR_FAMILY_PATTERN,
    EXECUTION_FAILURE_LIMIT,
    EXECUTION_FAILURE_RECOVERY_HINT,
    EXECUTION_RECOVERY_TOOLS,
    SECRET_REDACTION_PATTERNS,
    SENSITIVE_ARG_KEYS,
    get_security_policy,
)

_AUDIT_CONTEXT: ContextVar = ContextVar("tool_audit_context", default=None)


def is_harness_v2_enabled(default: bool = True) -> bool:
    """Governance is mandatory; the legacy environment switch is ignored."""
    return True


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
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    audit_state: Dict[str, bool] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    iteration: int = 0
    retries: int = 0
    policy_retry_counts: Dict[str, int] = field(default_factory=dict)
    execution_failures: Dict[str, Tuple[str, int]] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    def add_trace(self, event: str, **payload: Any):
        item = {"ts": round(time.time(), 3), "event": event}
        item.update(payload)
        self.trace.append(item)
        if len(self.trace) > 300:
            self.trace = self.trace[-300:]


class ToolArgumentValidator:
    """Validate and normalize tool arguments before policy scoring."""

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

    def __init__(self, get_tool_meta=None, policy=None):
        self.policy = policy if policy is not None else get_security_policy()
        if get_tool_meta is None:
            from houdini_agent.utils.tool_registry import get_tool_registry
            get_tool_meta = get_tool_registry().get_meta
        self._get_tool_meta = get_tool_meta

    def _normalize_args(self, args: Dict[str, Any], path_kinds: Dict[str, str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in (args or {}).items():
            if isinstance(value, str):
                v = value.strip()
                if path_kinds.get(key) == "node" and v:
                    v = self._normalize_path(v)
                out[key] = v
            elif isinstance(value, list) and path_kinds.get(key) == "node":
                out[key] = [
                    self._normalize_path(item.strip()) if isinstance(item, str) and item.strip() else item
                    for item in value
                ]
            else:
                out[key] = value
        return out

    def validate(self, tool_name: str, args: Dict[str, Any]) -> ToolValidationResult:
        try:
            meta = self._get_tool_meta(tool_name)
        except Exception:
            meta = None
        if meta is None:
            return ToolValidationResult(args=dict(args or {}), issues=[ToolValidationIssue(
                severity="error", code="unknown_tool", message=f"Tool metadata unavailable: {tool_name}"
            )])

        path_kinds = dict(meta.path_kinds or {})
        safe_args = self._normalize_args(args, path_kinds)
        issues: List[ToolValidationIssue] = []

        for key in meta.required_args():
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

        path_reason = self._check_path_args(safe_args, path_kinds)
        if path_reason:
            issues.append(ToolValidationIssue(severity="error", code="invalid_path", message=path_reason))

        if tool_name == "execute_python":
            reason = self._check_python_code(str(safe_args.get("code") or "")) or self._match_patterns(
                str(safe_args.get("code") or ""),
                self.policy.tools["python_dangerous_patterns"],
                "Tool input guardrail blocked dangerous Python",
            )
            if reason:
                issues.append(
                    ToolValidationIssue(severity="error", code="dangerous_python", message=reason, key="code")
                )

        if tool_name == "execute_shell":
            reason = self._match_patterns(
                str(safe_args.get("command") or ""),
                self.policy.tools["shell_dangerous_patterns"],
                "Tool input guardrail blocked dangerous shell command",
                flags=re.IGNORECASE,
            )
            if reason:
                issues.append(
                    ToolValidationIssue(severity="error", code="dangerous_shell", message=reason, key="command")
                )

        return ToolValidationResult(args=safe_args, issues=issues)

    def _check_python_code(self, code: str) -> str:
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            return "Tool input guardrail blocked dangerous Python: invalid syntax"

        aliases: Dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
                    if any(item.name == module or item.name.startswith(module + '.') for module in self.policy.tools["python_blocked_modules"]):
                        return "Tool input guardrail blocked dangerous Python module: " + item.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for item in node.names:
                    aliases[item.asname or item.name] = module + '.' + item.name
                if any(module == blocked or module.startswith(blocked + '.') for blocked in self.policy.tools["python_blocked_modules"]):
                    return "Tool input guardrail blocked dangerous Python module: " + module

        def resolve(node: ast.AST) -> str:
            if isinstance(node, ast.Name):
                return aliases.get(node.id, node.id)
            if isinstance(node, ast.Attribute):
                return resolve(node.value) + '.' + node.attr
            if isinstance(node, ast.Call):
                return resolve(node.func)
            return ""

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = resolve(node.func)
            if name in self.policy.tools["python_blocked_calls"]:
                return "Tool input guardrail blocked dangerous Python call: " + name
            if name in {"open", "builtins.open", "io.open", "pathlib.Path.open"}:
                mode_index = 0 if name == "pathlib.Path.open" else 1
                mode = next((item.value for item in node.keywords if item.arg == "mode"), None)
                if mode is None and len(node.args) > mode_index:
                    mode = node.args[mode_index]
                if mode is not None and (
                    not isinstance(mode, ast.Constant) or not isinstance(mode.value, str)
                    or any(flag in mode.value for flag in "wax+")
                ):
                    return "Tool input guardrail blocked dangerous Python: file write"
        return ""

    def _check_sensitive_args(self, args: Dict[str, Any]) -> str:
        for key, value in self._walk_args(args):
            key_text = str(key or "").strip().lower()
            if key_text in self.policy.tools["sensitive_arg_keys"] or key_text.endswith(("_api_key", "_token", "_password", "_secret")):
                return f"Tool input guardrail blocked sensitive argument: {key}"
            if isinstance(value, str):
                reason = self._match_patterns(
                    value,
                    self.policy.tools["sensitive_value_patterns"],
                    "Tool input guardrail blocked sensitive value",
                    flags=re.IGNORECASE,
                )
                if reason:
                    return reason
        return ""

    def _check_path_args(self, args: Dict[str, Any], path_kinds: Dict[str, str]) -> str:
        for key, value in (args or {}).items():
            if isinstance(value, str) and value.strip():
                reason = self._validate_path_arg(key, value.strip(), path_kinds.get(key))
                if reason:
                    return reason
            elif isinstance(value, list) and path_kinds.get(key) in {"node", "file"}:
                for index, item in enumerate(value):
                    if isinstance(item, str) and item.strip():
                        reason = self._validate_path_arg(
                            f"{key}[{index}]", item.strip(), path_kinds.get(key)
                        )
                        if reason:
                            return reason
        return ""

    def _validate_path_arg(self, key: str, path: str, path_kind: Optional[str]) -> str:
        if path_kind not in {"node", "file"}:
            return ""

        normalized = path.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if ".." in parts:
            return f"Tool input guardrail blocked path traversal in {key}"
        if "\x00" in normalized:
            return f"Tool input guardrail blocked invalid path in {key}"

        # 文件系统路径（file_path/output_path）豁免 Houdini root 校验。
        if path_kind == "file":
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

    def __init__(self, validator: Optional[ToolArgumentValidator] = None, get_tool_meta=None, policy=None):
        owner = getattr(get_tool_meta, "__self__", None)
        self.policy = policy if policy is not None else getattr(owner, "policy", get_security_policy())
        self.validator = validator or ToolArgumentValidator(get_tool_meta=get_tool_meta, policy=self.policy)
        self._get_tool_meta = get_tool_meta or self.validator._get_tool_meta

    def decide(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> ToolPolicyDecision:
        if self.policy.error:
            return self._decision(
                "deny", "Security policy unavailable; execution denied",
                risk_factors=[RiskFactor("policy_unavailable", "error", "Security policy unavailable", 1.0)],
            )
        validation = self.validator.validate(tool_name, args)
        safe_args = validation.args

        username = str(context.get("username") or "").strip().casefold()
        for key, value in ToolArgumentValidator._walk_args(safe_args):
            if not isinstance(value, str):
                continue
            normalized = re.sub(r'/+', '/', value.replace('\\', '/'))
            for match in re.finditer(self.policy.tools["private_user_path_pattern"], normalized):
                owner = (match.group(1) or "").casefold()
                if not username or owner != username or "/../" in normalized:
                    return self._decision(
                        "deny", "Tool input guardrail blocked private user path",
                        required_control="deny",
                    )

        if not validation.ok:
            return self._decision(
                "deny",
                validation.first_error,
                risk_factors=self._validation_risk_factors(validation),
                required_control="deny",
            )

        try:
            meta = self._get_tool_meta(tool_name)
        except Exception:
            meta = None
        if meta is None:
            return self._decision("deny", f"Tool metadata unavailable: {tool_name}", required_control="deny")

        mode = context.get("mode", "agent")
        confirm_mode = bool(context.get("confirm_mode", False))
        confirmed = bool(context.get("confirmed", False))
        skill_params = safe_args.get("params") if isinstance(safe_args.get("params"), dict) else {}
        controlled_skill_action = skill_params.get("action") or skill_params.get("mode", "preview")
        controlled_skill_write = (
            tool_name == "run_skill"
            and safe_args.get("skill_name") in self.policy.tools["controlled_write_skills"]
            and controlled_skill_action == "preview"
        )
        if tool_name == "remember_memory":
            if int(context.get("remember_memory_calls") or 0) >= self.policy.tools["memory_calls_per_request"]:
                return self._decision(
                    "deny",
                    "remember_memory is limited to one call per request",
                    risk_factors=[RiskFactor(
                        "explicit_memory_once_per_request",
                        "error",
                        "remember_memory is limited to one call per request",
                        1.0,
                    )],
                    required_control="deny",
                )
            user_message = str(context.get("user_message") or "")
            from houdini_agent.utils.explicit_memory import ExplicitMemoryService
            intent_ok = ExplicitMemoryService.has_explicit_save_intent(user_message)
            if not intent_ok:
                return self._decision(
                    "deny",
                    "remember_memory requires an explicit save request",
                    risk_factors=[RiskFactor(
                        "explicit_memory_intent_required",
                        "error",
                        "remember_memory requires an explicit save request",
                        1.0,
                    )],
                    required_control="deny",
                )
            if mode == "ask":
                return self._decision(
                    "deny",
                    "Ask mode blocked tool: remember_memory",
                    risk_factors=[RiskFactor(
                        "ask_mode_memory_write",
                        "error",
                        "Ask mode blocked tool: remember_memory",
                        1.0,
                    )],
                    required_control="deny",
                )
        if mode == "ask" and not confirmed and (meta.risk_level == "high" or tool_name == "execute_python"):
            return self._decision(
                "deny",
                f"Ask mode blocked tool: {tool_name}",
                risk_factors=[RiskFactor("ask_mode_high_risk", "error", f"Ask mode blocked tool: {tool_name}", 1.0)],
                required_control="deny",
            )

        for rule in self.policy.tools["confirmation_rules"]:
            if tool_name not in rule["tools"] or mode not in rule["modes"]:
                continue
            if rule["action"] == "ask" and confirmed:
                continue
            if any(safe_args.get(key) != value for key, value in rule.get("arguments", {}).items()):
                continue
            if "skill_names" in rule and safe_args.get("skill_name") not in rule["skill_names"]:
                continue
            if "skill_actions" in rule and controlled_skill_action not in rule["skill_actions"]:
                continue
            return self._decision(
                rule["action"], rule["message"],
                patched_args=safe_args if safe_args != args else None,
                risk_factors=[RiskFactor(rule["id"], "warning", rule["message"], rule["score"])],
                required_control="confirm" if rule["action"] == "ask" else "deny",
            )

        # Ownership 检查必须先于通用确认返回：修改非本 session agent 创建节点时，
        # Step Confirm 升级为 ask 并携带 foreign 信号；Direct Execute 仅在后续 allow 加风险分。
        foreign_factor = self._foreign_node_factor(tool_name, safe_args, context, meta)

        # confirm_mode=True means Step Confirm is enabled: high-risk tools must
        # ask the user before execution. confirm_mode=False is Direct Execute
        # (HIGH-RISK), where the user has opted out of confirmation prompts.
        if mode in {"agent", "plan", "plan_executing"} and meta.requires_confirmation and confirm_mode and not confirmed and not controlled_skill_write:
            if tool_name == "set_update_mode":
                return self._decision(
                    "ask",
                    "persistent Update Mode change requires confirmation",
                    risk_factors=[RiskFactor(
                        "persistent_state_confirmation",
                        "warning",
                        "persistent Update Mode change requires confirmation",
                        0.4,
                    )],
                    required_control="confirm",
                )
            factors = [RiskFactor("high_risk_confirmation", "warning", f"Dangerous tool requires confirmation: {tool_name}", 0.7)]
            if foreign_factor is not None:
                factors.append(foreign_factor)
            return self._decision(
                "ask",
                foreign_factor.message if foreign_factor is not None else f"Tool requires confirmation: {tool_name}",
                risk_factors=factors,
                required_control="confirm",
            )

        if tool_name == "save_hip":
            out = str(safe_args.get("file_path") or "").strip()
            if out and not os.path.splitext(out)[1]:
                patched = dict(safe_args)
                patched["file_path"] = out + ".hip"
                return self._decision(
                    "retry",
                    "Auto-fix save_hip file_path extension to .hip",
                    patched_args=patched,
                    retry_key=f"{tool_name}:file_path_ext",
                    risk_factors=[RiskFactor("retry_patch_output_extension", "info", "Auto-fix save_hip file_path extension to .hip", 0.1)],
                    required_control="retry",
                )

        if safe_args != args:
            factors = [RiskFactor("args_normalized", "info", "Arguments normalized", 0.0)]
            if foreign_factor is not None:
                factors.append(foreign_factor)
            return self._decision(
                action="allow",
                reason="Arguments normalized",
                patched_args=safe_args,
                risk_factors=factors,
            )

        if foreign_factor is not None:
            return self._decision(
                "allow",
                reason=foreign_factor.message,
                risk_factors=[foreign_factor],
            )

        return self._decision("allow")

    def _foreign_node_factor(
        self,
        tool_name: str,
        safe_args: Dict[str, Any],
        context: Dict[str, Any],
        meta=None,
    ) -> Optional[RiskFactor]:
        """Build a risk factor when a mutation targets nodes not created by the agent.

        Policy layer does not query hou; it only compares declared node path
        arguments against the session's agent-created set from context.
        """
        # DESTRUCTIVE_TOOLS（delete_node 等）不在 SCENE_MUTATION_TOOLS 里，单独放行
        if tool_name not in self.policy.tools["scene_mutation_tools"] and tool_name != "delete_node":
            return None
        if tool_name.startswith("create_") or tool_name in {"layout_nodes", "execute_python"}:
            return None

        created = context.get("agent_created_paths")
        if not isinstance(created, (set, frozenset)) or not created:
            return None

        if meta is None:
            return None

        targets: set = set()
        for key, kind in (meta.path_kinds or {}).items():
            if kind != "node":
                continue
            value = safe_args.get(key)
            if isinstance(value, str) and value.startswith("/"):
                targets.add(value)
            elif isinstance(value, list):
                targets.update(v for v in value if isinstance(v, str) and v.startswith("/"))
        if not targets:
            return None

        foreign = sorted(t for t in targets if t not in created)
        if not foreign:
            return None
        shown = ", ".join(foreign[:3])
        extra = f" (+{len(foreign) - 3} more)" if len(foreign) > 3 else ""
        return RiskFactor(
            "foreign_node_mutation",
            "warning",
            f"{tool_name} targets node(s) not created by the agent this session: {shown}{extra}",
            0.4,
        )

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


class GovernedToolExecutor:
    """Own the fail-closed policy-to-adapter execution sequence."""

    def __init__(
        self,
        policy_engine,
        execute,
        confirm=None,
        audit=None,
        trace=None,
        retry_counts=None,
        retry_limit=2,
        execution_failures: Optional[Dict[str, Tuple[str, int]]] = None,
        audit_state: Optional[Dict[str, bool]] = None,
        get_tool_meta=None,
    ):
        self._policy_engine = policy_engine
        self._execute = execute
        self._confirm = confirm
        self._audit = audit
        self._trace = trace
        self._retry_counts = retry_counts if retry_counts is not None else {}
        self._retry_limit = retry_limit
        self._execution_failures = execution_failures if execution_failures is not None else {}
        self._audit_state = audit_state if audit_state is not None else {}
        self._get_tool_meta = get_tool_meta

    def execute(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        identity = {
            "call_id": uuid.uuid4().hex,
            "run_id": str(context.get("run_id") or ""),
            "session_id": str(context.get("session_id") or ""),
            "mode": context.get("mode", "agent"),
            "iteration": context.get("iteration", 0),
            "__terminal": False,
            "__executed": False,
        }
        token = _AUDIT_CONTEXT.set(identity)
        try:
            result = self._execute_call(tool_name, args, context)
            if not identity["__terminal"]:
                self._record_audit({
                    "event_type": "tool_call", "phase": "result", "tool": tool_name,
                    "success": bool(result.get("success")),
                    "execution_status": "executed" if identity["__executed"] else "not_started",
                    "error_code": result.get("error_code", "policy_denied" if not result.get("success") else ""),
                })
            if self._audit_state.get("degraded"):
                result["audit_status"] = "degraded"
                result["audit_warning"] = "Tool audit is incomplete; writes are blocked for this run."
                if identity["__executed"] and not self._allows_unaudited_read(tool_name):
                    result["replay_safe"] = False
                    result["audit_call_id"] = identity["call_id"]
            return result
        finally:
            _AUDIT_CONTEXT.reset(token)

    def _execute_call(self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        safe_args = dict(args or {})
        try:
            decision = self._policy_engine.decide(tool_name, safe_args, context)
        except Exception:
            self._record_decision(tool_name, "deny", "policy_error")
            return {"success": False, "error": "Tool policy evaluation failed; execution denied"}

        action = decision.action
        reason = decision.reason or ""
        exec_args = decision.patched_args if decision.patched_args is not None else safe_args
        audited = self._record_decision(tool_name, action, reason, decision)

        if (not audited or self._audit_state.get("degraded")) and action != "deny" and not self._allows_unaudited_read(tool_name):
            return {
                "success": False, "error": "Tool audit unavailable; write execution denied",
                "error_code": "audit_unavailable", "audit_status": "degraded",
            }

        if action == "deny":
            return {"success": False, "error": reason or f"Tool blocked by policy: {tool_name}"}

        previous_failure = self._execution_failures.get(tool_name)
        if previous_failure and previous_failure[1] >= EXECUTION_FAILURE_LIMIT:
            self._record_decision(tool_name, "deny", "repeated_execution_failure")
            self._record_audit({
                "event_type": "execution_failure_guard", "tool": tool_name,
                "action": "blocked", "failure_kind": previous_failure[0],
                "failure_count": previous_failure[1],
            })
            return {
                "success": False,
                "error": EXECUTION_FAILURE_RECOVERY_HINT,
                "error_code": "repeated_execution_failure",
                "recommended_next_action": "collect_evidence",
            }

        if action == "ask":
            if self._confirm is None:
                return {"success": False, "error": "Tool confirmation unavailable; execution denied", "error_code": "confirmation_unavailable"}
            confirmation_code = "confirmation_cancelled"
            try:
                confirmed = bool(self._confirm(tool_name, exec_args))
            except Exception:
                confirmation_code = "confirmation_error"
                confirmed = False
            self._record_audit({
                "event_type": "tool_confirmation", "tool": tool_name,
                "action": "confirmed" if confirmed else confirmation_code,
            })
            self._record_trace("tool_policy_ask", tool=tool_name, confirmed=confirmed)
            if not confirmed:
                return {"success": False, "error": reason or f"Tool confirmation cancelled: {tool_name}", "error_code": confirmation_code}
            confirmed_context = dict(context)
            confirmed_context["confirmed"] = True
            try:
                confirmed_decision = self._policy_engine.decide(tool_name, exec_args, confirmed_context)
            except Exception:
                self._record_decision(tool_name, "deny", "confirmed_policy_error")
                return {"success": False, "error": "Confirmed tool policy evaluation failed; execution denied"}
            self._record_decision(tool_name, confirmed_decision.action, confirmed_decision.reason or "confirmed", confirmed_decision)
            if confirmed_decision.action != "allow":
                return {
                    "success": False,
                    "error": confirmed_decision.reason or f"Confirmed tool blocked by policy: {tool_name}",
                }
            if confirmed_decision.patched_args is not None:
                exec_args = confirmed_decision.patched_args

        if action == "retry":
            if decision.patched_args is None:
                return {"success": False, "error": "Policy retry did not provide patched arguments"}
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_args)
            retry_count = self._retry_counts.get(retry_key, 0)
            if retry_count >= self._retry_limit:
                self._record_audit({
                    "event_type": "policy_retry", "tool": tool_name,
                    "action": "retry_limit", "retry_key": retry_key,
                    "retry_count": retry_count, "retry_limit": self._retry_limit,
                })
                return {"success": False, "error": f"Tool retry limit reached for {tool_name}"}
            self._retry_counts[retry_key] = retry_count + 1
            self._record_audit({
                "event_type": "policy_retry", "tool": tool_name,
                "action": "retry", "retry_key": retry_key,
                "retry_count": retry_count + 1, "retry_limit": self._retry_limit,
            })
        elif action not in {"allow", "ask"}:
            return {"success": False, "error": f"Unsupported policy action: {action}"}

        started_at = time.time()
        start_audit = {
            "event_type": "tool_call", "phase": "start", "tool": tool_name,
            "action": action, "mode": context.get("mode", "agent"),
            "args_keys": sorted(str(key) for key in exec_args.keys()),
        }
        if tool_name == "execute_python" and isinstance(exec_args.get("code"), str):
            start_audit["code_sha256"] = hashlib.sha256(
                exec_args["code"].encode("utf-8", errors="replace")
            ).hexdigest()
        self._record_audit(start_audit)
        if self._audit_state.get("degraded") and not self._allows_unaudited_read(tool_name):
            return {"success": False, "error": "Tool audit unavailable; write execution denied", "error_code": "audit_unavailable"}
        _AUDIT_CONTEXT.get()["__executed"] = True
        try:
            result = self._execute(tool_name, exec_args, action == "ask")
        except Exception:
            result = {"success": False, "error": "Tool execution adapter failed"}
        result = sanitize_tool_result(result)
        verification_status = (
            str((result.get("verification") or {}).get("status") or "")
            if isinstance(result.get("verification"), dict)
            else ""
        )
        error_code = "tool_execution_failed" if not result.get("success") else ""
        if result.get("success") and verification_status == "applied_unknown":
            error_code = "verification_inconclusive"
        if result.get("success"):
            self._execution_failures.pop(tool_name, None)
            if (
                tool_name in EXECUTION_RECOVERY_TOOLS
                and self._execution_failures
                and not result.get("thread_still_running")
                and result.get("scene_consistency") != "unknown"
                and verification_status != "applied_unknown"
            ):
                self._execution_failures.clear()
                self._record_audit({
                    "event_type": "execution_failure_guard", "tool": tool_name,
                    "action": "evidence_collected",
                })
        else:
            error_text = str(result.get("error") or "")
            exception_kinds = re.findall(EXECUTION_ERROR_FAMILY_PATTERN, error_text)
            failure_kind = exception_kinds[-1] if exception_kinds else (
                "message:" + hashlib.sha256(error_text.splitlines()[0].encode("utf-8")).hexdigest()[:16]
            )
            previous_failure = self._execution_failures.get(tool_name)
            failure_count = (
                previous_failure[1] + 1
                if previous_failure and previous_failure[0] == failure_kind else 1
            )
            self._execution_failures[tool_name] = (failure_kind, failure_count)
            if failure_count >= EXECUTION_FAILURE_LIMIT:
                result["recovery_hint"] = EXECUTION_FAILURE_RECOVERY_HINT
                result["recommended_next_action"] = "collect_evidence"
                result["error"] += "\n\n" + EXECUTION_FAILURE_RECOVERY_HINT
                self._record_audit({
                    "event_type": "execution_failure_guard", "tool": tool_name,
                    "action": "limit_reached", "failure_kind": failure_kind,
                    "failure_count": failure_count,
                })
        self._record_audit({
            "event_type": "tool_call", "phase": "result", "tool": tool_name,
            "action": action, "mode": context.get("mode", "agent"),
            "success": bool(result.get("success")),
            "verification_status": verification_status,
            "error_code": error_code,
            "thread_still_running": bool(result.get("thread_still_running", False)),
            "scene_consistency": str(result.get("scene_consistency") or ""),
            "operation_id": str(result.get("operation_id") or (result.get("operation_receipt") or {}).get("operation_id") or "")
            if isinstance(result.get("operation_receipt", {}), dict) else "",
            "duration_ms": int(max(0.0, time.time() - started_at) * 1000),
        })

        if action == "retry" and result.get("success"):
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_args)
            self._retry_counts.pop(retry_key, None)
        return result

    def _record_decision(self, tool_name: str, action: str, reason: str, decision=None) -> bool:
        self._record_trace("tool_policy", tool=tool_name, action=action, reason=reason)
        rules = list(decision.matched_rules) if decision is not None else []
        return self._record_audit({
            "event_type": "tool_policy", "tool": tool_name,
            "action": action,
            "reason_code": reason if re.fullmatch(r"[a-z][a-z0-9_]*", reason) else (rules[0] if rules else "policy_" + action),
            "matched_rules": rules,
            "risk_score": decision.risk_score if decision is not None else 0.0,
            "required_control": decision.required_control if decision is not None else action,
            "policy_id": getattr(self._policy_engine, "policy", get_security_policy()).data.get("policy_id", "unavailable"),
            "policy_version": getattr(self._policy_engine, "policy", get_security_policy()).version,
        })

    def _allows_unaudited_read(self, tool_name: str) -> bool:
        try:
            from houdini_agent.utils.tool_registry import get_tool_registry
            get_meta = self._get_tool_meta or get_tool_registry().get_meta
            meta = get_meta(tool_name)
            policy = getattr(self._policy_engine, "policy", get_security_policy())
            return bool(not policy.error and policy.tools["allow_readonly_audit_degradation"] and meta and "readonly" in meta.tags and not meta.mutating and meta.risk_level == "low")
        except Exception:
            return False

    def _record_trace(self, event: str, **fields):
        if self._trace is not None:
            try:
                self._trace(event, **fields)
            except Exception:
                pass

    def _record_audit(self, record: Dict[str, Any]) -> bool:
        identity = _AUDIT_CONTEXT.get() or {}
        if record.get("phase") == "result":
            identity["__terminal"] = True
        payload = {key: value for key, value in identity.items() if not key.startswith("__")}
        payload.update(record)
        payload.update({"schema_version": 2, "timestamp": round(time.time(), 3)})
        if self._audit is not None:
            try:
                if self._audit(payload) is not False:
                    return True
            except Exception:
                pass
        self._audit_state["degraded"] = True
        return False
