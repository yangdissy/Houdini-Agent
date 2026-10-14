# -*- coding: utf-8 -*-
"""Extract reusable node subgraphs from the current Houdini scene."""

from typing import Any, Dict, List, Optional

from houdini_agent.skills.learning._shared import extract_records, score_node


def _select_subgraph(
    records: List[Dict[str, Any]], root_path: str, max_nodes: int
) -> List[Dict[str, Any]]:
    by_path = {node["path"]: node for node in records}
    seen = set()
    ordered = []

    def visit(path: str) -> None:
        if path in seen or path not in by_path or len(ordered) >= max_nodes:
            return
        seen.add(path)
        node = by_path[path]
        for input_path in node.get("inputs", []):
            visit(input_path)
        if len(ordered) < max_nodes:
            ordered.append(node)

    visit(root_path)
    return ordered


def _build_memory_draft(candidate: Dict[str, Any], hip_name: str) -> str:
    nodes = candidate["nodes"]
    node_summary = " -> ".join(
        f"{node['name']}({node['type']})" for node in nodes
    )
    connections = "; ".join(candidate["connections"][:20]) or "无显式连接"
    details = []
    for node in nodes:
        notable = []
        if node.get("key_parameters"):
            notable.append("参数 " + ", ".join(node["key_parameters"][:5]))
        if node.get("script"):
            notable.append("脚本 " + node["script"][:240].replace("\n", " "))
        if node.get("comment"):
            notable.append("注释 " + node["comment"][:160].replace("\n", " "))
        if notable:
            details.append(f"- {node['name']}: {'；'.join(notable)}")
    text = (
        f"工作流记忆｜来源 HIP: {hip_name}\n"
        f"主题: {candidate['root_name']} 节点子图\n"
        f"节点链: {node_summary}\n"
        f"连接: {connections}\n"
        + ("关键配置:\n" + "\n".join(details) if details else "")
    )
    return text[:2000]


def analyze_records(
    records: List[Dict[str, Any]], hip_name: str, max_nodes: int = 20,
    candidate_count: int = 3,
) -> List[Dict[str, Any]]:
    """Rank normalized records and return reusable upstream subgraphs."""
    if not records:
        return []
    roots = sorted(records, key=lambda item: (score_node(item), item["path"]), reverse=True)
    candidates = []
    signatures = set()
    for root in roots:
        nodes = _select_subgraph(records, root["path"], max_nodes)
        signature = tuple(node["path"] for node in nodes)
        if not nodes or signature in signatures:
            continue
        signatures.add(signature)
        included = {node["path"] for node in nodes}
        connections = [
            f"{source.rsplit('/', 1)[-1]} -> {node['name']}"
            for node in nodes
            for source in node.get("inputs", [])
            if source in included
        ]
        candidate = {
            "score": sum(score_node(node) for node in nodes),
            "root_path": root["path"],
            "root_name": root["name"],
            "nodes": nodes,
            "connections": connections,
        }
        candidate["memory_draft"] = _build_memory_draft(candidate, hip_name)
        candidates.append(candidate)
        if len(candidates) >= candidate_count:
            break
    return candidates


def _upstream_nodes(root: Any) -> List[Any]:
    nodes = []
    visited = set()

    def visit(node: Any) -> None:
        if node.path() in visited:
            return
        visited.add(node.path())
        for input_node in node.inputs():
            if input_node is not None:
                visit(input_node)
        nodes.append(node)

    visit(root)
    return nodes


def run(
    node_path: Optional[str] = None, max_nodes: int = 20,
    candidate_count: int = 3,
) -> Dict[str, Any]:
    """Analyze the current HIP without modifying it."""
    import hou  # type: ignore

    max_nodes = max(2, min(int(max_nodes), 50))
    candidate_count = max(1, min(int(candidate_count), 5))
    selected = [hou.node(node_path)] if node_path else list(hou.selectedNodes())
    selected = [node for node in selected if node is not None]
    if not selected:
        return {"error": "请先选择节点，或传入 node_path。"}

    if len(selected) == 1:
        children = list(selected[0].children())
        if children:
            source_nodes = list(selected[0].allSubChildren())
            scope = selected[0].path()
        else:
            source_nodes = _upstream_nodes(selected[0])
            scope = selected[0].parent().path()
    else:
        parents = {node.parent().path() for node in selected}
        if len(parents) != 1:
            return {"error": "所选节点必须位于同一个网络。"}
        source_nodes = list(selected)
        scope = selected[0].parent().path()

    records = extract_records(source_nodes)
    hip_name = hou.hipFile.basename() or "untitled.hip"
    candidates = analyze_records(records, hip_name, max_nodes, candidate_count)
    return {
        "hip": hip_name,
        "scope": scope,
        "analyzed_nodes": len(records),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "next_step": (
            "请审核候选的 memory_draft；仅在用户明确确认保存后，"
            "调用 remember_memory 写入选中的一条记忆。"
        ),
    }