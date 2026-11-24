# -*- coding: utf-8 -*-
"""Fail-closed AST checks for the read-only Houdini Python tool."""

from __future__ import annotations

import ast

from .harness_policy_config import get_security_policy

_SAFE_BUILTIN_CALLS = {"all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "print", "range", "repr", "sorted", "str", "sum", "tuple", "zip"}


def _has_allowed_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if name == prefix:
            return True
        if name.startswith(prefix) and len(name) > len(prefix):
            boundary = name[len(prefix)]
            if boundary.isupper() or boundary == "_":
                return True
    return False


def readonly_python_violation(code: str) -> str:
    tools = get_security_policy().tools
    if not tools:
        return "security policy is unavailable; inspect_python is disabled"
    allowed_calls = frozenset(tools.get("readonly_python_allowed_calls", ()))
    allowed_prefixes = tuple(tools.get("readonly_python_allowed_prefixes", ()))
    if not allowed_calls or not allowed_prefixes:
        return "read-only Python allowlist is unavailable; inspect_python is disabled"
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return f"invalid syntax at line {exc.lineno}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return f"dunder name {node.id} is not allowed"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"dunder attribute {node.attr} is not allowed"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "imports are not allowed"
        if isinstance(node, ast.ClassDef):
            return "class definitions are not allowed"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
            return "decorated functions are not allowed"
        if isinstance(node, (ast.Delete, ast.AugAssign)):
            return f"{type(node).__name__} is not allowed"
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, (ast.Attribute, ast.Subscript)) for target in targets):
                return "attribute or subscript assignment is not allowed"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _SAFE_BUILTIN_CALLS:
                continue
            if not isinstance(node.func, ast.Attribute):
                return "only explicit method calls are allowed"
            method_name = node.func.attr
            if method_name not in allowed_calls and not _has_allowed_prefix(method_name, allowed_prefixes):
                return f"call {method_name}() is not an allowed read-only query; use a dedicated read-only tool or execute_python"
    return ""