"""
Per-user path helpers for Houdini Agent.
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from typing import Iterable, Optional, Set


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{2,32}$")


def _normalize_allowlist_entries(entries: Iterable[object]) -> Set[str]:
    allowed = set()
    for entry in entries:
        if not isinstance(entry, str):
            continue
        try:
            allowed.add(normalize_username(entry))
        except Exception:
            continue
    return allowed


def normalize_username(username: str) -> str:
    """Normalize and validate username.

    Rules:
    - 2-32 chars
    - letters, numbers, underscore, Chinese characters
    - lowercased
    """
    if not username:
        raise ValueError("username is required")
    cleaned = username.strip().lower()
    if not _USERNAME_RE.match(cleaned):
        raise ValueError("invalid username")
    return cleaned


def get_repo_root(start_dir: Optional[str] = None) -> str:
    """Get repo root by locating README.md."""
    try:
        current = start_dir or os.path.dirname(os.path.abspath(__file__))
        while True:
            if os.path.exists(os.path.join(current, "README.md")):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
    except Exception:
        pass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_access_path() -> Path:
    return Path(get_repo_root()) / "cache" / ".access"


def load_user_allowlist(access_path: Optional[Path] = None) -> Set[str]:
    path = Path(access_path) if access_path is not None else get_user_access_path()
    if not path.exists():
        return set()

    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:
        return set()

    try:
        data = json.loads(raw_text)
    except Exception:
        entries = []
        for line in raw_text.splitlines():
            value = line.split("#", 1)[0].strip()
            if value:
                entries.append(value)
        return _normalize_allowlist_entries(entries)

    if isinstance(data, list):
        return _normalize_allowlist_entries(data)
    if isinstance(data, dict):
        users = data.get("users") or data.get("allow") or data.get("allowed")
        if isinstance(users, list):
            return _normalize_allowlist_entries(users)
    return set()


def is_user_allowed(username: str, access_path: Optional[Path] = None) -> bool:
    try:
        uname = normalize_username(username)
    except Exception:
        return False
    return uname in load_user_allowlist(access_path)


class UserPaths:
    """Compute per-user cache/config paths."""

    def __init__(self, username: str):
        self.username = normalize_username(username)
        self.repo_root = Path(get_repo_root())
        self.user_root = self.repo_root / "cache" / "users" / self.username

    def ensure_dirs(self) -> None:
        for p in (
            self.user_root,
            self.conversations_dir(),
            self.plans_dir(),
            self.memory_dir(),
            self.embeddings_dir(),
            self.workspace_dir(),
        ):
            p.mkdir(parents=True, exist_ok=True)

    def conversations_dir(self) -> Path:
        return self.user_root / "conversations"

    def plans_dir(self) -> Path:
        return self.user_root / "plans"

    def memory_dir(self) -> Path:
        return self.user_root / "memory"

    def embeddings_dir(self) -> Path:
        return self.memory_dir() / "embeddings"

    def memory_db(self) -> Path:
        return self.memory_dir() / "agent_memory.db"

    def legacy_local_memory_db(self) -> Path:
        """Return the former local DB path, used only as a recovery source."""
        local_base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("TMPDIR") or os.path.expanduser("~"))
        return local_base / "HoudiniAgent" / "memory" / self.username / "agent_memory.db"

    def growth_profile_path(self) -> Path:
        return self.memory_dir() / "growth_profile.json"

    def workspace_dir(self) -> Path:
        return self.user_root / "workspace"

    def workspace_file(self) -> Path:
        return self.workspace_dir() / "workspace.json"

    def user_config_path(self) -> Path:
        return self.user_root / "config.ini"

    def user_rules_path(self) -> Path:
        return self.user_root / "user_rules.json"

    def migration_flag_path(self) -> Path:
        return self.user_root / "migration_done.json"

    # Shared resources
    def shared_doc_index_dir(self) -> Path:
        return self.repo_root / "cache" / "doc_index"

    def legacy_cache_dir(self) -> Path:
        return self.repo_root / "cache"
