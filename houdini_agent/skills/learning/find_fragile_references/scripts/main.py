# -*- coding: utf-8 -*-
"""Find path and expression references that make a Houdini network fragile."""

from typing import Any, Dict, List

from houdini_agent.skills.learning._shared import analyze_reference_text




def _safe_text(callable_value: Any) -> str:
    try:
        value = callable_value()
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def run(network_path: str, recursive: bool = True, max_nodes: int = 2000) -> Dict[str, Any]:
    import hou  # type: ignore

    network = hou.node(network_path)
    if network is None:
        return {"error": f"网络不存在: {network_path}"}
    max_nodes = max(1, min(int(max_nodes), 10000))
    all_nodes = list(network.allSubChildren() if recursive else network.children())
    results = []
    severity_counts: Dict[str, int] = {}
    for node in all_nodes[:max_nodes]:
        node_findings = []
        for parm in node.parms():
            parm_name = parm.name()
            expression = _safe_text(parm.expression)
            raw_value = _safe_text(parm.unexpandedString)
            for source, text in (("expression", expression), ("parameter", raw_value)):
                for finding in analyze_reference_text(text, source):
                    finding["parameter"] = parm_name
                    node_findings.append(finding)
                    severity = finding["severity"]
                    severity_counts[severity] = severity_counts.get(severity, 0) + 1
        if node_findings:
            results.append({
                "node": node.name(),
                "node_type": node.type().name(),
                "path": node.path(),
                "findings": node_findings,
            })
    return {
        "network_path": network.path(),
        "recursive": bool(recursive),
        "scanned_nodes": min(len(all_nodes), max_nodes),
        "scan_truncated": len(all_nodes) > max_nodes,
        "affected_nodes": len(results),
        "finding_count": sum(len(item["findings"]) for item in results),
        "severity_counts": severity_counts,
        "nodes": results,
    }