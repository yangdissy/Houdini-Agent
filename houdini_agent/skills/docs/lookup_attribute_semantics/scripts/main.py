# -*- coding: utf-8 -*-
"""Look up Houdini geometry attribute semantics."""

from houdini_agent.skills.docs._doc_support import extract_markdown_sections, read_reference, search_help




def run(attribute=None, top_k=5):
    name = str(attribute or "").strip().lstrip("@").strip()
    if not name:
        return {"error": "'attribute' is required."}
    reference_hits = extract_markdown_sections(
        read_reference("vex_attributes_reference.txt"), "@" + name, top_k=top_k
    )
    manual_hits = search_help(name, top_k=top_k, archive_names=("vex.zip", "nodes.zip"))
    return {
        "attribute": name,
        "reference_hits": reference_hits,
        "manual_hits": [
            {
                "title": hit.get("title", ""),
                "path": hit.get("path", ""),
                "context": hit.get("context", ""),
                "description": hit.get("description", ""),
            }
            for hit in manual_hits
        ],
        "evidence_count": len(reference_hits) + len(manual_hits),
    }