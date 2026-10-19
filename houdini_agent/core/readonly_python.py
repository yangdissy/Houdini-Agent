# -*- coding: utf-8 -*-
"""Fail-closed AST checks for the read-only Houdini Python tool."""

from __future__ import annotations

import ast


_MUTATING_CALLS = {
    "addEventCallback", "addSpareParmTuple", "appendToFolder", "changeNodeType",
    "collapseIntoSubnet", "copyItems", "createDigitalAsset", "createNode",
    "deleteItems", "destroy", "destroyUserData", "installFile", "layoutChildren",
    "move", "moveToGoodPosition", "pressButton", "removeEventCallback",
    "removeSpareParmTuple", "save", "saveAsBackup", "set", "setColor",
    "setComment", "setCurrent", "setDisplayFlag", "setExpression", "setInput",
    "setName", "setNextInput", "setParms", "setParmTemplateGroup", "setPosition",
    "setRenderFlag", "setSelected", "setUpdateMode", "setUserData", "uninstallFile",
}
_SAFE_BUILTIN_CALLS = {"all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "print", "range", "repr", "sorted", "str", "sum", "tuple", "zip"}


def readonly_python_violation(code: str) -> str:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return f"invalid syntax at line {exc.lineno}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "imports are not allowed"
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
            if node.func.attr in _MUTATING_CALLS:
                return f"mutating call {node.func.attr}() is not allowed"
    return ""