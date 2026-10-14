# -*- coding: utf-8 -*-
"""Compare two Houdini node chains and extract their stable pattern."""

from collections import Counter
from typing import Any, Dict, List

from houdini_agent.skills.learning._shared import extract_records




def compare_records(first: List[Dict[str, Any]], second: List[Dict[str, Any]]) -> Dict[str, Any]:
    first_types = Counter(node["type"] for node in first)
    second_types = Counter(node["type"] for node in second)
    common = first_types & second_types
    only_first = first_types - second_types
    only_second = second_types - first_types
    common_types = sorted(common.elements())
    draft = (
        "通用网络规律｜两个实现对比\n"
        f"共同节点类型: {', '.join(common_types) or '无'}\n"
        f"实现 A 特有: {', '.join(sorted(only_first.elements())) or '无'}\n"
        f"实现 B 特有: {', '.join(sorted(only_second.elements())) or '无'}\n"
        "复用建议: 优先把共同节点类型及其顺序作为稳定骨架；特有步骤作为可选分支，"
        "并分别保留脚本和输入属性契约。"
    )[:2000]
    return {
        "common_node_types": common_types,
        "only_first_types": sorted(only_first.elements()),
        "only_second_types": sorted(only_second.elements()),
        "first_node_count": len(first),
        "second_node_count": len(second),
        "first_script_nodes": [node["name"] for node in first if node.get("script")],
        "second_script_nodes": [node["name"] for node in second if node.get("script")],
        "memory_draft": draft,
    }


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


def run(first_node_path: str, second_node_path: str, max_nodes: int = 50) -> Dict[str, Any]:
    import hou  # type: ignore

    first_root = hou.node(first_node_path)
    second_root = hou.node(second_node_path)
    if first_root is None or second_root is None:
        missing = first_node_path if first_root is None else second_node_path
        return {"error": f"节点不存在: {missing}"}
    max_nodes = max(2, min(int(max_nodes), 100))
    first = extract_records(_upstream(first_root, max_nodes))
    second = extract_records(_upstream(second_root, max_nodes))
    result = compare_records(first, second)
    result.update({"first_root": first_root.path(), "second_root": second_root.path()})
    return result