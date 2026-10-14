# -*- coding: utf-8 -*-
"""Look up VEX functions and snippet patterns from bundled documentation."""

from houdini_agent.skills.docs._doc_support import (
    compact_hit,
    extract_markdown_sections,
    read_reference,
    search_help,
)




def run(query=None, top_k=5):
    if not str(query or "").strip():
        return {"error": "'query' is required."}
    manual_hits = search_help(query, top_k=top_k, archive_names=("vex.zip",))
    snippet_hits = extract_markdown_sections(
        read_reference("vex_snippets_reference.txt"), query, top_k=top_k
    )
    return {
        "query": query,
        "manual_hits": [
            compact_hit(hit, ("usage", "arguments", "returns", "examples", "notes"))
            for hit in manual_hits
        ],
        "snippet_hits": snippet_hits,
        "evidence_count": len(manual_hits) + len(snippet_hits),
    }