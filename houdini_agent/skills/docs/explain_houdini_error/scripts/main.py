# -*- coding: utf-8 -*-
"""Find documentation evidence related to a Houdini error message."""

import re

from houdini_agent.skills.docs._doc_support import compact_hit, search_help




def _search_query(error_text):
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", str(error_text or ""))
    ignored = {"error", "warning", "failed", "invalid", "unable", "could", "cannot", "houdini"}
    useful = [word for word in words if word.lower() not in ignored]
    return " ".join(useful[:6]) or " ".join(words[:6])


def run(error_text=None, top_k=8):
    if not str(error_text or "").strip():
        return {"error": "'error_text' is required."}
    query = _search_query(error_text)
    hits = search_help(query, top_k=top_k) if query else []
    return {
        "error_text": error_text,
        "search_query": query,
        "evidence": [compact_hit(hit, ("errors", "notes", "tips", "examples")) for hit in hits],
        "evidence_count": len(hits),
    }