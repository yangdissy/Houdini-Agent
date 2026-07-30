# -*- coding: utf-8 -*-
"""Retention cleanup for diagnostics and harness trace files."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


DEFAULT_RETENTION_DAYS = 30
RETENTION_ENV = "HOUDINI_AGENT_DIAGNOSTICS_RETENTION"
RETENTION_DAYS_ENV = "HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS"
FALSE_VALUES = {"0", "false", "no", "off"}
TARGETS: Tuple[Tuple[str, str], ...] = (
    ("diagnostics", "diagnostics_*.json"),
    ("diagnostics", "session_*.jsonl"),
    ("harness_trace", "session_*.jsonl"),
)


def is_retention_cleanup_enabled() -> bool:
    return os.getenv(RETENTION_ENV, "").strip().lower() not in FALSE_VALUES


def retention_days_from_env(default: int = DEFAULT_RETENTION_DAYS) -> int:
    raw = os.getenv(RETENTION_DAYS_ENV, "").strip()
    if not raw:
        return default
    try:
        days = int(raw)
    except Exception:
        return default
    return days if days > 0 else default


def cleanup_diagnostics_retention(
    conversations_dir: Path,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    current_session_id: str = "",
    now: Optional[float] = None,
) -> Dict[str, object]:
    """Delete old diagnostics and harness trace files under one user's conversations dir."""
    root = Path(conversations_dir)
    cutoff = (time.time() if now is None else now) - (max(1, int(retention_days)) * 86400)
    current_names = _current_session_names(current_session_id)
    summary: Dict[str, object] = {
        "deleted": 0,
        "skipped_current": 0,
        "skipped_recent": 0,
        "errors": 0,
        "deleted_files": [],
    }

    for file_path in _iter_target_files(root):
        try:
            if file_path.name in current_names:
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


def _iter_target_files(root: Path) -> Iterable[Path]:
    for subdir_name, pattern in TARGETS:
        target_dir = root / subdir_name
        if not target_dir.is_dir():
            continue
        for file_path in target_dir.glob(pattern):
            if file_path.is_file():
                yield file_path


def _current_session_names(current_session_id: str) -> List[str]:
    sid = (current_session_id or "").strip()
    if not sid:
        return []
    return [f"session_{sid}.jsonl"]
