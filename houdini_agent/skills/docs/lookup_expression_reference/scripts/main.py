# -*- coding: utf-8 -*-
"""Look up channel expressions, local variables, and snippet references."""

from houdini_agent.skills.docs._doc_support import (
    compact_hit,
    extract_markdown_sections,
    read_reference,
    search_help,
)




def run(query=None, top_k=5):
    if not str(query or "").strip():
        return {"error": "'query' is required."}
    reference_hits = extract_markdown_sections(
        read_reference("vex_snippets_reference.txt"), query, top_k=top_k
    )
    manual_hits = search_help(query, top_k=top_k)
    return {
        "query": query,
        "reference_hits": reference_hits,
        "manual_hits": [compact_hit(hit, ("usage", "examples", "notes")) for hit in manual_hits],
        "evidence_count": len(reference_hits) + len(manual_hits),
    }