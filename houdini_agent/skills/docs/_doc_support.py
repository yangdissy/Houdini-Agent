# -*- coding: utf-8 -*-
"""Shared read-only helpers for documentation skills."""

import re
from pathlib import Path

from houdini_agent.utils import help_source


MAX_PAGE_BYTES = 512 * 1024
MAX_SCAN_PER_ZIP = 20000


def normalize_terms(query):
    return [term for term in re.split(r"\s+", str(query or "").strip().lower()) if term]


def search_help(query, top_k=8, archive_names=None, path_prefix=None):
    terms = normalize_terms(query)
    if not terms:
        return []
    help_dir = help_source.find_help_dir(None)
    if help_dir is None:
        return []
    allowed_archives = set(archive_names or help_source.HELP_ZIPS)
    hits = []
    for archive_name in help_source.HELP_ZIPS:
        if archive_name not in allowed_archives:
            continue
        archive_path = help_dir / archive_name
        if not archive_path.exists():
            continue
        for path, raw in help_source.iter_pages_cached(
            archive_path,
            max_scan=MAX_SCAN_PER_ZIP,
            max_bytes=MAX_PAGE_BYTES,
        ):
            if path_prefix and not path.lower().startswith(path_prefix.lower()):
                continue
            haystack = raw.lower()
            if not all(term in haystack for term in terms):
                continue
            doc = help_source.parse_wiki(raw)
            title = doc.get("title") or Path(path).stem
            score = sum(5 for term in terms if term in title.lower())
            score += sum(2 for term in terms if term in Path(path).stem.lower())
            score += sum(haystack.count(term) for term in terms)
            hits.append({
                "archive": archive_name,
                "path": path,
                "title": title,
                "type": doc.get("type", ""),
                "context": doc.get("context", ""),
                "internal": doc.get("internal", ""),
                "description": doc.get("description", ""),
                "body": doc.get("body", ""),
                "sections": doc.get("sections", {}),
                "_score": score,
            })
    hits.sort(key=lambda item: (-item["_score"], item["path"]))
    for hit in hits:
        hit.pop("_score", None)
    return hits[:max(1, min(int(top_k or 8), 20))]


def read_reference(filename):
    path = Path(__file__).resolve().parents[3] / "Doc" / filename
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def extract_markdown_sections(text, query, top_k=5):
    terms = normalize_terms(query)
    if not terms or not text:
        return []
    sections = []
    current_title = "Overview"
    current_lines = []
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.lstrip("# ").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    matches = []
    for title, body in sections:
        haystack = (title + "\n" + body).lower()
        if not all(term in haystack for term in terms):
            continue
        score = sum(4 for term in terms if term in title.lower())
        score += sum(haystack.count(term) for term in terms)
        matches.append({"title": title, "content": body, "_score": score})
    matches.sort(key=lambda item: -item["_score"])
    for match in matches:
        match.pop("_score", None)
    return matches[:max(1, min(int(top_k or 5), 20))]


def compact_hit(hit, section_names=()):
    selected_sections = {}
    sections = hit.get("sections", {})
    for name in section_names:
        if sections.get(name):
            selected_sections[name] = sections[name]
    return {
        "title": hit.get("title", ""),
        "path": hit.get("path", ""),
        "context": hit.get("context", ""),
        "internal": hit.get("internal", ""),
        "description": hit.get("description", ""),
        "sections": selected_sections,
    }