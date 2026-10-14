# -*- coding: utf-8 -*-
"""Extract task-relevant parameter documentation for a Houdini node type."""

from houdini_agent.skills.docs._doc_support import compact_hit, normalize_terms, search_help




def _matching_parameter_lines(parameters, goal):
    terms = normalize_terms(goal)
    if not terms:
        return parameters
    blocks = [block.strip() for block in parameters.split("\n\n") if block.strip()]
    return "\n\n".join(
        block for block in blocks if any(term in block.lower() for term in terms)
    )


def run(node_type=None, goal=None, top_k=3):
    if not str(node_type or "").strip():
        return {"error": "'node_type' is required."}
    hits = search_help(node_type, top_k=top_k, archive_names=("nodes.zip",), path_prefix="nodes/")
    results = []
    for hit in hits:
        item = compact_hit(hit)
        parameters = hit.get("sections", {}).get("parameters", "")
        item["parameter_evidence"] = _matching_parameter_lines(parameters, goal)
        results.append(item)
    return {"node_type": node_type, "goal": goal or "", "matches": results}