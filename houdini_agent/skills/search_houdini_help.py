# -*- coding: utf-8 -*-
"""Houdini built-in offline help search Skill (MVP-1).

Searches the Houdini-shipped offline help (nodes/vex/hom ZIP archives under
``$HFS/houdini/help`` or the bundled ``Doc/`` directory) as a version-accurate,
zero-maintenance documentation source.

Two modes (merged into one skill via the ``mode`` param to avoid AI mis-routing):
  - ``search``: full-text keyword search across all help pages; returns hits with
    title + zip-relative path + snippet.
  - ``page``:  retrieve the plain-text body of one help page by its path.

Read-only. Reuses ``HoudiniDocIndex._resolve_help_dir`` / ``_parse_wiki`` from
``doc_rag`` for path discovery and wiki parsing. Does not import ``hou``.
"""

import re
import zipfile

SKILL_INFO = {
    "name": "search_houdini_help",
    "category": "docs",
    "description": (
        "Search Houdini's SHIPPED offline manual (version-accurate, zero-maintenance). "
        "Use as a deep/authoritative fallback when search_local_doc (fast, curated) is "
        "insufficient or may be stale. mode='search' does full-text keyword search and "
        "returns matching pages (title + path + snippet); mode='page' returns the full "
        "plain-text body of one page given its path (from a prior search hit). Read-only."
    ),
    "risk_level": "low",
    "parameters": {
        "mode": {
            "type": "string",
            "description": "'search' for keyword search, 'page' to fetch one page's body.",
            "required": False,
            "default": "search",
        },
        "query": {
            "type": "string",
            "description": "Keyword(s) for mode='search'. Space-separated terms are AND-matched.",
            "required": False,
        },
        "path": {
            "type": "string",
            "description": "Page path for mode='page', e.g. 'nodes/sop/attribwrangle.txt' "
                           "(as returned by a search hit).",
            "required": False,
        },
        "top_k": {
            "type": "integer",
            "description": "Max hits to return in mode='search'. Defaults to 8.",
            "required": False,
            "default": 8,
        },
    },
}

# All help archives that ship with Houdini. _resolve_help_dir only requires one
# to exist; we search whichever are present.
_HELP_ZIPS = ("nodes.zip", "vex.zip", "hom.zip")

# Cap scanned pages per archive to keep a single call responsive on huge manuals.
_MAX_SCAN_PER_ZIP = 20000
# Cap total bytes decoded per page to avoid pathological large files.
_MAX_PAGE_BYTES = 512 * 1024


def _resolve():
    """Locate the help dir and return (help_dir_path, parse_wiki_fn) or (None, None)."""
    try:
        from houdini_agent.utils.doc_rag import HoudiniDocIndex
    except Exception:
        try:
            from ..utils.doc_rag import HoudiniDocIndex  # type: ignore
        except Exception:
            return None, None
    help_dir = HoudiniDocIndex._resolve_help_dir(None)
    return help_dir, HoudiniDocIndex._parse_wiki


def _iter_pages(help_dir):
    """Yield (zip_name, entry_name, raw_text) for every .txt help page present."""
    for zip_name in _HELP_ZIPS:
        zp = help_dir / zip_name
        if not zp.exists():
            continue
        try:
            with zipfile.ZipFile(zp, "r") as zf:
                scanned = 0
                for name in zf.namelist():
                    if not name.endswith(".txt"):
                        continue
                    if "/_" in name or name.startswith("_"):
                        continue
                    scanned += 1
                    if scanned > _MAX_SCAN_PER_ZIP:
                        break
                    try:
                        raw = zf.read(name)[:_MAX_PAGE_BYTES].decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                    yield zip_name, name, raw
        except Exception:
            continue


def _snippet(body, terms, width=160):
    """Return a short snippet centred on the first matched term."""
    low = body.lower()
    pos = -1
    for t in terms:
        p = low.find(t)
        if p != -1:
            pos = p
            break
    if pos == -1:
        return body[:width].strip()
    start = max(0, pos - width // 2)
    frag = body[start:start + width].strip()
    return ("…" if start > 0 else "") + frag + ("…" if start + width < len(body) else "")


def _search(help_dir, parse_wiki, query, top_k):
    terms = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
    if not terms:
        return {"error": "mode='search' requires a non-empty 'query'."}

    hits = []
    for zip_name, entry, raw in _iter_pages(help_dir):
        haystack = raw.lower()
        if not all(t in haystack for t in terms):
            continue
        doc = parse_wiki(raw)
        title = doc.get("title") or entry.rsplit("/", 1)[-1][:-4]
        # Score: title matches weigh more than body matches.
        title_low = title.lower()
        score = sum(3 for t in terms if t in title_low)
        score += sum(haystack.count(t) for t in terms)
        body = doc.get("description") or doc.get("body") or raw
        hits.append({
            "title": title,
            "path": entry,
            "context": doc.get("context", ""),
            "type": doc.get("type", ""),
            "snippet": _snippet(body, terms),
            "_score": score,
        })

    hits.sort(key=lambda h: h["_score"], reverse=True)
    top_k = max(1, min(int(top_k or 8), 50))
    hits = hits[:top_k]
    for h in hits:
        h.pop("_score", None)
    return {
        "mode": "search",
        "query": query,
        "hit_count": len(hits),
        "hits": hits,
        "help_dir": str(help_dir),
    }


def _page(help_dir, parse_wiki, path):
    if not path:
        return {"error": "mode='page' requires a 'path' (from a search hit)."}
    norm = path.replace("\\", "/").strip("/")
    for zip_name in _HELP_ZIPS:
        zp = help_dir / zip_name
        if not zp.exists():
            continue
        try:
            with zipfile.ZipFile(zp, "r") as zf:
                names = set(zf.namelist())
                if norm not in names:
                    continue
                raw = zf.read(norm)[:_MAX_PAGE_BYTES].decode("utf-8", errors="ignore")
        except Exception:
            continue
        doc = parse_wiki(raw)
        return {
            "mode": "page",
            "path": norm,
            "title": doc.get("title", ""),
            "type": doc.get("type", ""),
            "context": doc.get("context", ""),
            "description": doc.get("description", ""),
            "body": doc.get("body", ""),
            "sections": doc.get("sections", {}),
        }
    return {"error": f"Help page not found: {path}"}


def run(mode="search", query=None, path=None, top_k=8):
    """Search or fetch a Houdini offline help page. Read-only."""
    help_dir, parse_wiki = _resolve()
    if not help_dir or parse_wiki is None:
        return {
            "error": (
                "Houdini offline help not found. Expected nodes.zip/vex.zip/hom.zip under "
                "$HFS/houdini/help or the bundled Doc/ directory."
            )
        }

    mode = (mode or "search").strip().lower()
    if mode == "search":
        return _search(help_dir, parse_wiki, query, top_k)
    if mode == "page":
        return _page(help_dir, parse_wiki, path)
    return {"error": f"Unknown mode '{mode}'. Use 'search' or 'page'."}
