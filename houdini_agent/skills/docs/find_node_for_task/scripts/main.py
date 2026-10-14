# -*- coding: utf-8 -*-
"""Find Houdini node candidates from documented task descriptions."""

from houdini_agent.skills.docs._doc_support import compact_hit, search_help




def run(task=None, context=None, top_k=8):
    if not str(task or "").strip():
        return {"error": "'task' is required."}
    hits = search_help(task, top_k=20, archive_names=("nodes.zip",), path_prefix="nodes/")
    context_value = str(context or "").strip().lower()
    if context_value:
        hits = [
            hit for hit in hits
            if hit.get("context", "").lower() == context_value
            or ("nodes/" + context_value + "/") in hit.get("path", "").lower()
        ]
    limit = max(1, min(int(top_k or 8), 20))
    return {
        "task": task,
        "context": context_value,
        "candidates": [compact_hit(hit) for hit in hits[:limit]],
    }