# -*- coding: utf-8 -*-
"""Find repeated linear node patterns that may deserve assetization."""

from collections import defaultdict
from typing import Any, Dict, List, Tuple




def find_repeated_patterns(
    records: List[Dict[str, Any]], chain_length: int = 3
) -> List[Dict[str, Any]]:
    by_path = {node["path"]: node for node in records}
    patterns: Dict[Tuple[str, ...], List[List[str]]] = defaultdict(list)
    for endpoint in records:
        chain = []
        current = endpoint
        seen = set()
        while current and current["path"] not in seen and len(chain) < chain_length:
            seen.add(current["path"])
            chain.append(current)
            inputs = [path for path in current.get("inputs", []) if path in by_path]
            current = by_path[inputs[0]] if len(inputs) == 1 else None
        if len(chain) != chain_length:
            continue
        chain.reverse()
        signature = tuple(node["type"] for node in chain)
        paths = [node["path"] for node in chain]
        if paths not in patterns[signature]:
            patterns[signature].append(paths)
    repeated = [
        {
            "signature": list(signature),
            "occurrences": len(instances),
            "instances": instances,
            "recommendation": "考虑封装为 HDA/子网，并先审核输入、输出和暴露参数契约。",
        }
        for signature, instances in patterns.items()
        if len(instances) >= 2
    ]
    return sorted(repeated, key=lambda item: (-item["occurrences"], item["signature"]))


def run(network_path: str, chain_length: int = 3, max_nodes: int = 1000) -> Dict[str, Any]:
    import hou  # type: ignore
    from houdini_agent.skills.learning._shared import extract_records

    network = hou.node(network_path)
    if network is None:
        return {"error": f"网络不存在: {network_path}"}
    chain_length = max(2, min(int(chain_length), 6))
    max_nodes = max(2, min(int(max_nodes), 5000))
    all_nodes = list(network.allSubChildren())
    nodes = all_nodes[:max_nodes]
    patterns = find_repeated_patterns(extract_records(nodes), chain_length)
    return {
        "network_path": network.path(),
        "scanned_nodes": len(nodes),
        "scan_truncated": len(all_nodes) > max_nodes,
        "pattern_count": len(patterns),
        "patterns": patterns[:20],
    }