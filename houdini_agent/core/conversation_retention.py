# -*- coding: utf-8 -*-
"""Opt-in retention cleanup for archived and legacy conversation caches."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, Optional, Set


DEFAULT_RETENTION_DAYS = 180
RETENTION_ENV = "HOUDINI_AGENT_CONVERSATION_RETENTION"
RETENTION_DAYS_ENV = "HOUDINI_AGENT_CONVERSATION_RETENTION_DAYS"
TRUE_VALUES = {"1", "true", "yes", "on"}


def is_conversation_retention_enabled() -> bool:
    return os.getenv(RETENTION_ENV, "").strip().lower() in TRUE_VALUES


def conversation_retention_days_from_env(
    default: int = DEFAULT_RETENTION_DAYS,
) -> int:
    raw = os.getenv(RETENTION_DAYS_ENV, "").strip()
    if not raw:
        return default
    try:
        days = int(raw)
    except Exception:
        return default
    return days if days > 0 else default


def cleanup_conversation_retention(
    conversations_dir: Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    current_session_id: str = "",
    now: Optional[float] = None,
) -> Dict[str, object]:
    """Delete only expired archives and legacy caches in one user directory."""
    root = Path(conversations_dir)
    summary: Dict[str, object] = {
        "deleted": 0,
        "skipped_current": 0,
        "skipped_recent": 0,
        "errors": 0,
        "blocked": "",
        "deleted_files": [],
    }
    if not root.is_dir():
        return summary
    if any(root.glob(".*.stage")):
        summary["blocked"] = "active_transaction"
        return summary

    try:
        protected = _manifest_files(root)
    except Exception:
        summary["blocked"] = "manifest_unavailable"
        return summary

    cutoff = (time.time() if now is None else now) - (
        max(1, int(retention_days)) * 86400
    )
    current_prefix = f"archive_{(current_session_id or '').strip()}_"

    for file_path in _iter_target_files(root):
        try:
            if file_path.name in protected:
                continue
            if current_prefix != "archive__" and file_path.name.startswith(current_prefix):
                summary["skipped_current"] = int(summary["skipped_current"]) + 1
                continue
            if file_path.stat().st_mtime >= cutoff:
                summary["skipped_recent"] = int(summary["skipped_recent"]) + 1
                continue
            file_path.unlink()
            summary["deleted"] = int(summary["deleted"]) + 1
            deleted_files = summary["deleted_files"]
            if isinstance(deleted_files, list) and len(deleted_files) < 20:
                deleted_files.append(str(file_path))
        except Exception:
            summary["errors"] = int(summary["errors"]) + 1
    return summary


def _manifest_files(root: Path) -> Set[str]:
    manifest_path = root / "sessions_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(str(manifest_path))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    tabs = data.get("tabs")
    if not isinstance(tabs, list):
        raise ValueError("invalid manifest tabs")
    protected = {"sessions_manifest.json"}
    for tab in tabs:
        if not isinstance(tab, dict):
            raise ValueError("invalid manifest tab")
        file_name = tab.get("file")
        if isinstance(file_name, str) and file_name:
            protected.add(Path(file_name).name)
    return protected


def _iter_target_files(root: Path) -> Iterable[Path]:
    for pattern in ("archive_*.json", "cache_*.json"):
        for file_path in root.glob(pattern):
            if file_path.name == "cache_latest.json":
                continue
            if file_path.is_file() and not file_path.is_symlink():
                yield file_path