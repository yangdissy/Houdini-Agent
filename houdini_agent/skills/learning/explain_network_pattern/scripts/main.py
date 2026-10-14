# -*- coding: utf-8 -*-
"""Explain the reusable design pattern in a Houdini node chain."""

from typing import Any, Dict, List

from houdini_agent.skills.learning._shared import extract_records, score_node as _score_node




def _role(node: Dict[str, Any]) -> str:
    if not node.get("inputs"):
        return "source"
    if not node.get("outputs") or node["name"].upper().startswith("OUT"):
        return "output"
    if len(node.get("inputs", [])) > 1:
        return "combine"
    if len(node.get("outputs", [])) > 1:
        return "branch"
    return "process"


def explain_records(records: List[Dict[str, Any]], hip_name: str) -> Dict[str, Any]:
    roles = {name: [] for name in ("source", "process", "combine", "branch", "output")}
    for node in records:
        roles[_role(node)].append({
            "name": node["name"], "type": node["type"], "path": node["path"],
        })
    controls = sorted(records, key=lambda node: (_score_node(node), node["path"]), reverse=True)[:5]
    insights = []
    if roles["combine"]:
        insights.append("网络通过多输入节点汇聚不同数据流，汇聚点是理解和调试的关键。")
    if roles["branch"]:
        insights.append("网络包含一对多分支，同一中间结果被多个后续步骤复用。")
    if any(node.get("script") for node in records):
        insights.append("核心行为包含 VEX/Python 等脚本，复用时必须同时保留代码和输入属性契约。")
    if any(node.get("expression_count") for node in records):
        insights.append("网络依赖参数表达式，复制节点时需要检查相对路径和通道引用。")
    if any(node.get("network_boxes") or node.get("comment") for node in records):
        insights.append("作者使用注释或 Network Box 表达了模块边界，可作为资产化边界参考。")
    if not insights:
        insights.append("该网络主要价值在节点顺序和参数组合，暂未发现显式脚本或复杂分支。")
    chain = " -> ".join(f"{node['name']}({node['type']})" for node in records)
    draft = (
        f"设计规律｜来源 HIP: {hip_name}\n"
        f"节点链: {chain}\n"
        f"可复用规律: {' '.join(insights)}\n"
        "关键控制点: " + ", ".join(node["name"] for node in controls)
    )[:2000]
    return {
        "roles": roles,
        "key_controls": controls,
        "insights": insights,
        "memory_draft": draft,
    }


def run(node_path: str, max_nodes: int = 30) -> Dict[str, Any]:
    import hou  # type: ignore

    root = hou.node(node_path)
    if root is None:
        return {"error": f"节点不存在: {node_path}"}
    max_nodes = max(2, min(int(max_nodes), 80))
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
    result = explain_records(extract_records(nodes), hou.hipFile.basename() or "untitled.hip")
    result.update({"root_path": root.path(), "analyzed_nodes": len(nodes)})
    return result