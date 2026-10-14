# -*- coding: utf-8 -*-
"""Shared pure helpers for network-learning Skills."""

import re
from typing import Any, Dict, List


_SCRIPT_PARM_NAMES = frozenset({
    "snippet", "vex", "code", "python", "script", "expression",
})
_OUTPUT_TYPES = frozenset({
    "output", "rop_geometry", "rop_alembic", "filecache", "usd_rop",
})
_LOW_SIGNAL_TYPES = frozenset({"null", "merge", "switch", "dot"})
_REFERENCE_RULES = (
    ("absolute_node_path", "high", re.compile(r"(?<![\w$])/(?:obj|stage|out|mat|shop|ch|img|tasks)/[^\s\"']+"),
     "绝对节点路径在节点移动、封装或改名后容易失效。", "改用输入连接、相对引用或显式暴露的参数接口。"),
    ("relative_node_reference", "medium", re.compile(r"(?:\.\./)+[A-Za-z0-9_./:-]+"),
     "相对节点引用依赖当前网络层级。", "封装前统一检查层级，并优先通过输入或资产参数传递。"),
    ("op_uri", "high", re.compile(r"\bop:(?:/|\.\.?/)[^\s\"']+"),
     "op: URI 直接绑定其他节点。", "把依赖声明为输入或资产参数，并验证目标节点存在。"),
    ("cross_node_function", "medium", re.compile(r"\b(?:ch|chs|chf|chi|chv|chramp|detail|point|prim|vertex)\s*\(\s*[\"'][^\"']*[/.][^\"']*[\"']"),
     "表达式或 VEX 从其他节点读取值。", "记录被引用节点和属性契约，重命名或封装后重新验证。"),
    ("environment_path", "medium", re.compile(r"\$(?:HIP|JOB|HOME|TEMP|HOUDINI_PATH|HSITE)\b"),
     "文件依赖由环境变量决定，不同机器可能解析到不同位置。", "记录所需环境变量，并在发布前验证展开后的文件存在。"),
    ("windows_absolute_file", "high", re.compile(r"\b[A-Za-z]:[\\/][^\n\r\"']+"),
     "盘符绝对路径通常无法跨机器复用。", "改用项目变量或受管理的相对路径。"),
    ("unc_file", "high", re.compile(r"\\\\[^\\\s]+\\[^\n\r\"']+"),
     "UNC 文件路径依赖网络共享和权限。", "记录共享依赖、权限要求和离线降级方案。"),
)


def score_node(node: Dict[str, Any]) -> int:
    score = 1
    score += min(len(node.get("inputs", [])), 3)
    score += min(len(node.get("outputs", [])), 2)
    score += min(len(node.get("key_parameters", [])), 3)
    score += min(int(node.get("expression_count", 0)), 2) * 2
    if node.get("script"):
        score += 4
    if node.get("comment"):
        score += 2
    if node.get("network_boxes"):
        score += 1
    node_type = str(node.get("type", "")).split("::", 1)[0].lower()
    if node_type in _OUTPUT_TYPES or str(node.get("name", "")).upper().startswith("OUT"):
        score += 2
    if node_type in _LOW_SIGNAL_TYPES and not node.get("comment"):
        score -= 2
    if not node.get("inputs") and not node.get("outputs"):
        score -= 3
    return score


def _safe_text(value: Any, limit: int = 500) -> str:
    try:
        return str(value)[:limit]
    except Exception:
        return ""


def _extract_record(node: Any, allowed_paths: set) -> Dict[str, Any]:
    inputs = [item.path() for item in node.inputs() if item and item.path() in allowed_paths]
    outputs = [item.path() for item in node.outputs() if item and item.path() in allowed_paths]
    key_parameters = []
    expression_count = 0
    script = ""
    for parm in node.parms():
        try:
            if parm.isAtDefault():
                continue
            name = parm.name()
            expression = ""
            try:
                expression = parm.expression()
            except Exception:
                pass
            if expression:
                expression_count += 1
                key_parameters.append(f"{name}={expression[:120]}")
                continue
            value = _safe_text(
                parm.unexpandedString() if hasattr(parm, "unexpandedString") else parm.eval()
            )
            if name.lower() in _SCRIPT_PARM_NAMES or "snippet" in name.lower():
                script = value
            elif len(key_parameters) < 8:
                key_parameters.append(f"{name}={value[:120]}")
        except Exception:
            continue
    boxes = []
    try:
        for box in node.parent().networkBoxes():
            if node in box.items():
                boxes.append(_safe_text(box.comment() or box.name(), 120))
    except Exception:
        pass
    return {
        "path": node.path(), "name": node.name(), "type": node.type().name(),
        "inputs": inputs, "outputs": outputs, "key_parameters": key_parameters,
        "expression_count": expression_count, "script": script,
        "comment": _safe_text(node.comment(), 500), "network_boxes": boxes,
    }


def extract_records(nodes: List[Any]) -> List[Dict[str, Any]]:
    allowed_paths = {node.path() for node in nodes}
    return [_extract_record(node, allowed_paths) for node in nodes]


def analyze_reference_text(
        text: str, source: str = "parameter") -> List[Dict[str, str]]:
    findings = []
    seen = set()
    for code, severity, pattern, reason, suggestion in _REFERENCE_RULES:
        for match in pattern.finditer(text or ""):
            evidence = match.group(0)[:240]
            key = (code, evidence)
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "code": code, "severity": severity, "source": source,
                "evidence": evidence, "reason": reason, "suggestion": suggestion,
            })
    return findings