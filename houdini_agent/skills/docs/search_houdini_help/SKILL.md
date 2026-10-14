---
{"name":"search_houdini_help","category":"docs","description":"Search Houdini's SHIPPED offline manual (version-accurate, zero-maintenance). Use as a deep/authoritative fallback when search_local_doc (fast, curated) is insufficient or may be stale. mode='search' does full-text keyword search and returns matching pages (title + path + snippet); mode='page' returns the full plain-text body of one page given its path (from a prior search hit). Read-only.","risk_level":"low","parameters":{"mode":{"type":"string","description":"'search' for keyword search, 'page' to fetch one page's body.","required":false,"default":"search"},"query":{"type":"string","description":"Keyword(s) for mode='search'. Space-separated terms are AND-matched.","required":false},"path":{"type":"string","description":"Page path for mode='page', e.g. 'nodes/sop/attribwrangle.txt' (as returned by a search hit).","required":false},"top_k":{"type":"integer","description":"Max hits to return in mode='search'. Defaults to 8.","required":false,"default":8}},"entrypoint":"scripts/main.py:run"}
---
# Search Houdini Help

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
