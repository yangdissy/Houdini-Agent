# -*- coding: utf-8 -*-
"""Helpers for rendering Houdini node references as clickable rich-text links."""

import html
import re
from typing import Mapping


# Match Houdini node paths: /obj/..., /out/..., /ch/..., /shop/..., /stage/..., /mat/..., /tasks/...
_NODE_PATH_RE = re.compile(
    r'(?<!["\w/])'
    r'(/(?:obj|out|ch|shop|stage|mat|tasks)(?:/[\w.]+)+)'
    r'(?!["\w/])'
)

_PROTECTED_HTML_RE = re.compile(
    r'(<a\b[^>]*>.*?</a>|<code\b[^>]*>.*?</code>|<img\b[^>]*>|<[^>]+>)',
    re.IGNORECASE | re.DOTALL,
)

_NODE_LINK_STYLE = "color:#10b981;text-decoration:none;font-family:Consolas,Monaco,monospace;"


def _single_path_by_name(session_node_map: Mapping[str, object] = None) -> dict:
    if not session_node_map:
        return {}

    result = {}
    for name, path_values in session_node_map.items():
        if not name:
            continue
        try:
            paths = {str(path) for path in path_values if path}
        except TypeError:
            paths = {str(path_values)} if path_values else set()
        if len(paths) == 1:
            result[str(name)] = next(iter(paths))
    return result


def _linkify_chunk(text: str, name_to_path: dict) -> str:
    for name in sorted(name_to_path, key=len, reverse=True):
        escaped_name = html.escape(name)
        if not escaped_name:
            continue
        pattern = re.compile(r'(?<![/\w])' + re.escape(escaped_name) + r'(?![\w/])')
        full_path = name_to_path[name]
        text = pattern.sub(
            f'<a href="houdini://{full_path}" style="{_NODE_LINK_STYLE}">{escaped_name}</a>',
            text,
        )

    return _NODE_PATH_RE.sub(
        lambda m: f'<a href="houdini://{m.group(1)}" style="{_NODE_LINK_STYLE}">{m.group(1)}</a>',
        text,
    )


def _linkify_node_paths(text: str, session_node_map: Mapping[str, object] = None) -> str:
    """Convert Houdini node references in already-escaped rich text into links.

    Full paths keep displaying as full paths. Unambiguous short names from
    session_node_map display unchanged, but link to their full Houdini path.
    """
    name_to_path = _single_path_by_name(session_node_map)
    if not text:
        return text

    parts = _PROTECTED_HTML_RE.split(text)
    for index, part in enumerate(parts):
        if part.startswith('<'):
            continue
        parts[index] = _linkify_chunk(part, name_to_path)
    return ''.join(parts)


def _linkify_node_paths_plain(text: str, session_node_map: Mapping[str, object] = None) -> str:
    """Escape plain text, then convert Houdini node references to rich-text links."""
    return _linkify_node_paths(html.escape(text), session_node_map).replace('\n', '<br>')