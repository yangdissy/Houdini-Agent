# -*- coding: utf-8 -*-
"""Look up Copernicus and OpenCL guidance from bundled documentation."""

from houdini_agent.skills.docs._doc_support import (
    compact_hit,
    extract_markdown_sections,
    read_reference,
    search_help,
)




def run(query=None, top_k=5):
    if not str(query or "").strip():
        return {"error": "'query' is required."}
    manual_hits = search_help(query, top_k=top_k, path_prefix="copernicus/")
    reference_hits = extract_markdown_sections(
        read_reference("copernicus_opencl_reference.txt"), query, top_k=top_k
    )
    return {
        "query": query,
        "manual_hits": [
            compact_hit(hit, ("overview", "parameters", "tips", "examples", "notes"))
            for hit in manual_hits
        ],
        "reference_hits": reference_hits,
        "evidence_count": len(manual_hits) + len(reference_hits),
    }
