# -*- coding: utf-8 -*-
"""Qt-free slash command parsing helpers."""

SLASH_COMMANDS_WITH_ARGS = frozenset(("remember", "forget", "search_mem"))


def parse_slash_command(text: str):
    """Parse `/command args` while preserving natural-language arguments."""
    stripped = (text or "").strip()
    if not stripped.startswith("/") or len(stripped) == 1:
        return None
    parts = stripped[1:].split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1].strip() if len(parts) == 2 else ""
    return command, args
