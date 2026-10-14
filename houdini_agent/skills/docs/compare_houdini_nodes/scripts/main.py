# -*- coding: utf-8 -*-
"""Compare Houdini node types using their shipped documentation."""

from houdini_agent.skills.docs._doc_support import compact_hit, search_help




def run(node_types=None):
    names = [str(name).strip() for name in (node_types or []) if str(name).strip()]
    if len(names) < 2:
        return {"error": "'node_types' requires at least two node type names."}
    comparison = []
    for name in names:
        hits = search_help(name, top_k=1, archive_names=("nodes.zip",), path_prefix="nodes/")
        if not hits:
            comparison.append({"node_type": name, "found": False})
            continue
        item = compact_hit(hits[0], ("inputs", "parameters", "examples", "tips", "notes"))
        item.update({"node_type": name, "found": True})
        comparison.append(item)
    return {"node_types": names, "comparison": comparison}