# -*- coding: utf-8 -*-
"""Extract a reusable input/output contract from a Houdini node subgraph."""

import re
from typing import Any, Dict, List

from houdini_agent.skills.learning._shared import analyze_reference_text




_ATTRIBUTE_PATTERN = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)")
_WRITE_PATTERN = re.compile(
    r"(?:^|[;{}\n])\s*(?:[a-z]+@|@)([A-Za-z_][A-Za-z0-9_]*)\s*(?:[+\-*/]?=|\+\+|--)"
)
_READ_WRITE_PATTERN = re.compile(
    r"(?:^|[;{}\n])\s*(?:[a-z]+@|@)([A-Za-z_][A-Za-z0-9_]*)\s*(?:[+\-*/]=|\+\+|--)"
)
_ATTRIBUTE_FUNCTION_PATTERN = re.compile(
    r"\b(?:point|prim|vertex|detail)\s*\([^,]+,\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"
)
_TIME_TOKEN_PATTERN = re.compile(r"(?:@Frame|@Time|@TimeInc|\$F\d*|\$T|hou\.frame\s*\(|hou\.time\s*\()")


def infer_script_contract(script: str) -> Dict[str, Any]:
    """Infer conservative attribute and time contracts from VEX/Python-like text."""
    all_attributes = set(_ATTRIBUTE_PATTERN.findall(script or ""))
    all_attributes.update(_ATTRIBUTE_FUNCTION_PATTERN.findall(script or ""))
    written = set(_WRITE_PATTERN.findall(script or ""))
    read_written = set(_READ_WRITE_PATTERN.findall(script or ""))
    return {
        "read_attributes": sorted((all_attributes - written) | read_written),
        "written_attributes": sorted(written),
        "time_dependent": bool(_TIME_TOKEN_PATTERN.search(script or "")),
    }


def build_contract(records: List[Dict[str, Any]], root_path: str) -> Dict[str, Any]:
    included = {record["path"] for record in records}
    boundary_inputs = []
    outputs = []
    required_attributes = set()
    produced_attributes = set()
    available_attributes = set()
    time_nodes = []
    external_dependencies = []
    min_inputs = []
    for record in records:
        for input_path in record.get("inputs", []):
            if input_path not in included:
                boundary_inputs.append({"consumer": record["path"], "source": input_path})
        if not record.get("outputs") or record["path"] == root_path:
            outputs.append({"path": record["path"], "type": record["type"]})
        required = int(record.get("min_inputs", 0) or 0)
        if required:
            min_inputs.append({"path": record["path"], "required_inputs": required})
        scripts = list(record.get("scripts", []))
        for script in scripts:
            inferred = infer_script_contract(script)
            required_attributes.update(
                attribute for attribute in inferred["read_attributes"]
                if attribute not in available_attributes
            )
            required_attributes.update(
                attribute for attribute in inferred["written_attributes"]
                if attribute in set(inferred["read_attributes"])
                and attribute not in available_attributes
            )
            produced_attributes.update(inferred["written_attributes"])
            available_attributes.update(inferred["written_attributes"])
            if inferred["time_dependent"]:
                time_nodes.append(record["path"])
        for raw_value in record.get("raw_values", []):
            for finding in analyze_reference_text(raw_value):
                if finding["code"] in {
                    "environment_path", "windows_absolute_file", "unc_file", "op_uri",
                }:
                    external_dependencies.append({
                        "node": record["path"],
                        "code": finding["code"],
                        "value": finding["evidence"],
                    })
    draft = (
        "网络接口契约\n"
        f"根节点: {root_path}\n"
        f"边界输入: {len(boundary_inputs)}\n"
        f"必需输入属性: {', '.join(sorted(required_attributes)) or '未推断到'}\n"
        f"生成属性: {', '.join(sorted(produced_attributes)) or '未推断到'}\n"
        f"时间依赖节点: {', '.join(time_nodes) or '无'}\n"
        f"外部依赖数: {len(external_dependencies)}"
    )[:2000]
    return {
        "root_path": root_path,
        "node_count": len(records),
        "boundary_inputs": boundary_inputs,
        "outputs": outputs,
        "minimum_input_contracts": min_inputs,
        "required_attributes": sorted(required_attributes),
        "produced_attributes": sorted(produced_attributes),
        "time_dependent_nodes": sorted(set(time_nodes)),
        "external_dependencies": external_dependencies,
        "memory_draft": draft,
    }


def _safe_text(callable_value: Any) -> str:
    try:
        value = callable_value()
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def _upstream(root: Any, max_nodes: int) -> List[Any]:
    visited = set()
    nodes = []

    def visit(node: Any) -> None:
        if node.path() in visited or len(nodes) >= max_nodes:
            return
        visited.add(node.path())
        for input_node in node.inputs():
            if input_node is not None:
                visit(input_node)
        if len(nodes) < max_nodes:
            nodes.append(node)

    visit(root)
    return nodes


def run(node_path: str, max_nodes: int = 200) -> Dict[str, Any]:
    import hou  # type: ignore

    root = hou.node(node_path)
    if root is None:
        return {"error": f"节点不存在: {node_path}"}
    max_nodes = max(1, min(int(max_nodes), 2000))
    children = list(root.children())
    nodes = list(root.allSubChildren())[:max_nodes] if children else _upstream(root, max_nodes)
    included = {node.path() for node in nodes}
    records = []
    for node in nodes:
        inputs = [item.path() for item in node.inputs() if item is not None]
        outputs = [item.path() for item in node.outputs() if item is not None and item.path() in included]
        scripts = []
        raw_values = []
        for parm in node.parms():
            expression = _safe_text(parm.expression)
            raw_value = _safe_text(parm.unexpandedString)
            if expression:
                raw_values.append(expression)
            if raw_value:
                raw_values.append(raw_value)
                name = parm.name().lower()
                if name in {"snippet", "vex", "code", "python", "script"} or "snippet" in name:
                    scripts.append(raw_value)
        try:
            min_input_count = int(node.type().minNumInputs())
        except Exception:
            min_input_count = 0
        records.append({
            "path": node.path(),
            "type": node.type().name(),
            "inputs": inputs,
            "outputs": outputs,
            "min_inputs": min_input_count,
            "scripts": scripts,
            "raw_values": raw_values,
        })
    result = build_contract(records, root.path())
    result["scope"] = root.path() if children else root.parent().path()
    return result