# -*- coding: utf-8 -*-
"""Validated security policy snapshots and compatibility names for tool governance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "security_policy.json"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


@dataclass(frozen=True)
class SecurityPolicy:
    data: Mapping[str, Any]
    version: str
    error: str = ""

    @property
    def tools(self) -> Mapping[str, Any]:
        return self.data.get("tool_policy", {})


def load_security_policy(path: Path = POLICY_PATH) -> SecurityPolicy:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("policy_id"), str) or not data["policy_id"].strip():
            raise ValueError("Invalid security policy header")
        tools = data["tool_policy"]
        if not isinstance(tools, dict) or not isinstance(tools.get("risk_overrides"), dict):
            raise ValueError("Invalid tool policy")
        if any(value not in {"low", "normal", "high"} for value in tools["risk_overrides"].values()):
            raise ValueError("Invalid tool risk")
        for section in ("destructive_tools", "code_exec_tools", "scene_mutation_tools", "confirmation_tools", "controlled_write_skills", "sensitive_arg_keys", "python_blocked_modules", "python_blocked_calls"):
            values = tools[section]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                raise ValueError("Invalid tool policy list")
        if not isinstance(tools["mode_tools"], dict) or set(tools["mode_tools"]) != {"ask", "plan_planning"}:
            raise ValueError("Invalid tool modes")
        for names in tools["mode_tools"].values():
            if not isinstance(names, list) or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name) for name in names):
                raise ValueError("Invalid mode tool list")
        if type(tools["memory_calls_per_request"]) is not int or tools["memory_calls_per_request"] < 1:
            raise ValueError("Invalid memory call limit")
        if type(tools["allow_readonly_audit_degradation"]) is not bool:
            raise ValueError("Invalid audit degradation policy")
        re.compile(tools["private_user_path_pattern"])
        for section in ("sensitive_value_patterns", "secret_redaction_patterns", "python_dangerous_patterns", "shell_dangerous_patterns"):
            if not isinstance(tools[section], list):
                raise ValueError("Invalid tool pattern list")
            for pattern, identifier in tools[section]:
                if not isinstance(pattern, str) or not isinstance(identifier, str):
                    raise ValueError("Invalid tool pattern")
                re.compile(pattern)
        identifiers = set()
        if not isinstance(tools["confirmation_rules"], list) or not tools["confirmation_rules"]:
            raise ValueError("Missing confirmation rules")
        for rule in tools["confirmation_rules"]:
            if not isinstance(rule, dict):
                raise ValueError("Invalid confirmation rule")
            if set(rule) - {"id", "tools", "modes", "action", "score", "message", "arguments", "skill_names", "skill_actions"}:
                raise ValueError("Unknown confirmation rule field")
            if rule["id"] in identifiers or not re.fullmatch(r"[a-z][a-z0-9_]*", rule["id"]):
                raise ValueError("Invalid confirmation rule ID")
            identifiers.add(rule["id"])
            if rule["action"] not in {"ask", "deny"} or not isinstance(rule["message"], str):
                raise ValueError("Invalid confirmation rule action")
            if not isinstance(rule["score"], (int, float)) or not 0 <= rule["score"] <= 1:
                raise ValueError("Invalid confirmation rule score")
            if not isinstance(rule["tools"], list) or not rule["tools"] or any(not isinstance(name, str) for name in rule["tools"]):
                raise ValueError("Invalid confirmation rule tools")
            if not isinstance(rule["modes"], list) or not rule["modes"] or set(rule["modes"]) - {"agent", "ask", "plan", "plan_planning", "plan_executing"}:
                raise ValueError("Invalid confirmation rule modes")
            if not isinstance(rule.get("arguments", {}), dict):
                raise ValueError("Invalid confirmation rule arguments")
            for key in ("skill_names", "skill_actions"):
                if key in rule and (not isinstance(rule[key], list) or any(not isinstance(value, str) for value in rule[key])):
                    raise ValueError("Invalid confirmation skill condition")
        for section in ("injection_patterns", "memory_patterns"):
            if not isinstance(data[section], list) or not data[section]:
                raise ValueError("Missing security patterns")
            for rule, pattern in data[section]:
                if not isinstance(rule, str) or not rule or not isinstance(pattern, str):
                    raise ValueError("Invalid security pattern")
                re.compile(pattern, re.IGNORECASE)
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        return SecurityPolicy(_freeze(data), "sha256:" + hashlib.sha256(encoded).hexdigest())
    except (OSError, ValueError, KeyError, TypeError, re.error):
        return SecurityPolicy(MappingProxyType({}), "unavailable", "policy_unavailable")


@lru_cache(maxsize=1)
def get_security_policy() -> SecurityPolicy:
    return load_security_policy()


def __getattr__(name: str) -> Any:
    tools = get_security_policy().tools
    if name == "HIGH_RISK_TOOLS":
        return frozenset(tools.get("destructive_tools", ())) | frozenset(tools.get("code_exec_tools", ()))
    sections = {
        "DESTRUCTIVE_TOOLS": "destructive_tools", "CODE_EXEC_TOOLS": "code_exec_tools",
        "SCENE_MUTATION_TOOLS": "scene_mutation_tools", "CONTROLLED_WRITE_SKILLS": "controlled_write_skills",
        "SENSITIVE_ARG_KEYS": "sensitive_arg_keys", "PYTHON_BLOCKED_MODULES": "python_blocked_modules",
        "PYTHON_BLOCKED_CALLS": "python_blocked_calls", "PRIVATE_USER_PATH_PATTERN": "private_user_path_pattern",
        "SENSITIVE_VALUE_PATTERNS": "sensitive_value_patterns", "SECRET_REDACTION_PATTERNS": "secret_redaction_patterns",
        "PYTHON_DANGEROUS_PATTERNS": "python_dangerous_patterns", "SHELL_DANGEROUS_PATTERNS": "shell_dangerous_patterns",
    }
    if name not in sections:
        raise AttributeError(name)
    value = tools.get(sections[name], "" if name == "PRIVATE_USER_PATH_PATTERN" else ())
    return frozenset(value) if name.endswith(("_TOOLS", "_SKILLS", "_KEYS", "_MODULES", "_CALLS")) else value

EXECUTION_FAILURE_LIMIT = 2
EXECUTION_ERROR_FAMILY_PATTERN = r"(?m)^\s*((?:[A-Za-z_]\w*\.)?[A-Za-z_]\w*(?:Error|Exception)|OperationFailed|ObjectWasDeleted|InvalidNodeType):"
EXECUTION_RECOVERY_TOOLS = frozenset({
    "inspect_node",
    "get_parameter_schema",
    "get_network_structure",
    "inspect_python",
    "get_houdini_node_doc",
    "search_local_doc",
    "search_tool_contracts",
    "inspect_tool_contract",
})
EXECUTION_FAILURE_RECOVERY_HINT = (
    "Repeated execution failures: this tool is paused for this user turn. "
    "Do not keep rewriting code or repeating the call. Inspect the relevant node/parameters "
    "or read the relevant documentation/tool contract with a read-only tool before retrying. "
    "If no new evidence is available, report the blocker to the user."
)

# 静默工具：不在执行列表 UI 中显示
SILENT_TOOLS = frozenset({
    'add_todo',
    'update_todo',
})

# Plan 模式静默工具
PLAN_SILENT_TOOLS = frozenset({
    'create_plan',
    'update_plan_step',
    'ask_question',
})

# Plan 模式执行阶段附加工具
PLAN_EXECUTION_EXTRA_TOOLS = frozenset({
    'update_plan_step',
})
