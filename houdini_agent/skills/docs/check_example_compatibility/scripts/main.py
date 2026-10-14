# -*- coding: utf-8 -*-
"""Check identifiers in a Houdini example against bundled documentation."""

import re

from houdini_agent.skills.docs._doc_support import search_help




_VEX_KEYWORDS = {
    "break", "continue", "else", "export", "float", "for", "foreach", "if", "int",
    "matrix", "matrix3", "return", "string", "struct", "vector", "vector2", "vector4", "void", "while",
}


def _identifiers(example, language):
    if language == "vex":
        calls = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", example)
        return sorted({name for name in calls if name not in _VEX_KEYWORDS})
    return sorted(set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", example)))[:20]


def run(example=None, language="vex"):
    if not str(example or "").strip():
        return {"error": "'example' is required."}
    language_value = str(language or "vex").strip().lower()
    if language_value not in {"vex", "houdini"}:
        return {"error": "'language' must be 'vex' or 'houdini'."}
    checks = []
    archives = ("vex.zip",) if language_value == "vex" else ("nodes.zip", "hom.zip")
    for identifier in _identifiers(example, language_value):
        hits = search_help(identifier, top_k=1, archive_names=archives)
        checks.append({
            "identifier": identifier,
            "documented": bool(hits),
            "source_path": hits[0].get("path", "") if hits else "",
            "title": hits[0].get("title", "") if hits else "",
        })
    undocumented = [item["identifier"] for item in checks if not item["documented"]]
    return {
        "language": language_value,
        "checks": checks,
        "undocumented_identifiers": undocumented,
        "compatible": bool(checks) and not undocumented,
        "note": "Documentation presence is not runtime or semantic validation.",
    }