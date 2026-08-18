# -*- coding: utf-8 -*-
"""Pure-Python workspace manifest and transactional file persistence."""

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from .cache_records import SessionCacheRecord
from .session_state import SessionState


MANIFEST_NAME = 'sessions_manifest.json'
CLEAR_MARKER_NAME = 'sessions_cleared.json'


@dataclass
class WorkspaceRestorePlan:
    active_session_id: str
    sessions: List[Tuple[str, str, SessionState]]
    manifest_exists: bool
    cleared: bool = False


def active_session_id(manifest_tabs: Sequence[dict], requested_id: str) -> str:
    saved_ids = [tab.get('session_id') for tab in manifest_tabs if tab.get('session_id')]
    return requested_id if requested_id in saved_ids else (saved_ids[0] if saved_ids else '')


def build_manifest(manifest_tabs: Sequence[dict], requested_id: str) -> dict:
    return {
        'version': '1.0',
        'active_session_id': active_session_id(manifest_tabs, requested_id),
        'tabs': list(manifest_tabs),
    }


def atomic_write_json(path: Path, data: dict, indent: int = 2) -> None:
    temp_path = path.with_name(f'.{path.name}.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=indent)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp_path), str(path))
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def replace_file(source: Path, target: Path) -> None:
    os.replace(str(source), str(target))


def write_manifest(cache_dir: Path, manifest_tabs: Sequence[dict], requested_id: str,
                   indent: int = 2) -> None:
    atomic_write_json(cache_dir / MANIFEST_NAME, build_manifest(manifest_tabs, requested_id), indent)
    _update_clear_marker(cache_dir, bool(manifest_tabs))


def save_workspace(cache_dir: Path, states: Mapping[str, SessionState],
                   tabs: Sequence[Tuple[str, str]], requested_id: str,
                   replace: Callable[[Path, Path], None] = replace_file) -> bool:
    """Stage all records, publish sessions first, and roll them back on failure."""
    manifest_tabs = []
    staged_files = []
    empty_files = []
    for sid, label in tabs:
        state = states.get(sid)
        if not sid or state is None:
            continue
        target = cache_dir / f'session_{sid}.json'
        if not state.conversation_history:
            empty_files.append(target)
            continue
        staged = cache_dir / f'.{target.name}.{uuid.uuid4().hex}.stage'
        atomic_write_json(staged, state.to_cache_record().to_cache_data())
        staged_files.append((staged, target))
        manifest_tabs.append({'session_id': sid, 'tab_label': label, 'file': target.name})

    manifest_target = cache_dir / MANIFEST_NAME
    staged_manifest = cache_dir / f'.{manifest_target.name}.{uuid.uuid4().hex}.stage'
    atomic_write_json(staged_manifest, build_manifest(manifest_tabs, requested_id))

    backups = []
    try:
        for staged, target in staged_files:
            backup = cache_dir / f'.{target.name}.{uuid.uuid4().hex}.rollback'
            if target.exists():
                shutil.copy2(str(target), str(backup))
            else:
                backup = None
            backups.append((target, backup))
            replace(staged, target)
        replace(staged_manifest, manifest_target)
    except Exception:
        for target, backup in reversed(backups):
            try:
                if backup is None:
                    if target.exists():
                        target.unlink()
                else:
                    replace(backup, target)
            except OSError:
                pass
        raise
    finally:
        for staged, _ in staged_files:
            if staged.exists():
                staged.unlink()
        if staged_manifest.exists():
            staged_manifest.unlink()
        for _, backup in backups:
            if backup is not None and backup.exists():
                backup.unlink()

    for path in empty_files:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
    _update_clear_marker(cache_dir, bool(manifest_tabs))
    return bool(manifest_tabs)


def load_restore_plan(cache_dir: Path, orphan_scan: Optional[bool] = None) -> WorkspaceRestorePlan:
    """Load plain records according to the existing clear-marker/orphan policy."""
    manifest_path = cache_dir / MANIFEST_NAME
    if (cache_dir / CLEAR_MARKER_NAME).exists():
        return WorkspaceRestorePlan('', [], manifest_path.exists(), cleared=True)

    manifest_exists = manifest_path.exists()
    manifest = {}
    tabs_info = []
    if manifest_exists:
        with open(manifest_path, 'r', encoding='utf-8') as stream:
            manifest = json.load(stream)
        tabs_info = list(manifest.get('tabs', []) or [])

    should_scan = not manifest_exists if orphan_scan is None else bool(orphan_scan)
    if should_scan:
        known = {tab.get('session_id') for tab in tabs_info if tab.get('session_id')}
        for path in sorted(cache_dir.glob('session_*.json')):
            sid = path.stem.replace('session_', '', 1)
            if sid in known:
                continue
            try:
                with open(path, 'r', encoding='utf-8') as stream:
                    record = SessionCacheRecord.from_cache_data(json.load(stream))
            except Exception:
                continue
            if not record.conversation_history:
                continue
            tabs_info.append({'session_id': sid, 'tab_label': _history_label(record.conversation_history),
                              'file': path.name})
            known.add(sid)

    sessions = []
    for tab in tabs_info:
        sid = tab.get('session_id', '')
        path = cache_dir / tab.get('file', '')
        if not sid or not path.exists():
            continue
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                state = SessionState.from_cache_record(SessionCacheRecord.from_cache_data(json.load(stream)))
        except Exception:
            continue
        if state.conversation_history:
            sessions.append((sid, tab.get('tab_label', 'Chat'), state))
    requested = manifest.get('active_session_id', '')
    saved_tabs = [{'session_id': sid} for sid, _, _ in sessions]
    return WorkspaceRestorePlan(active_session_id(saved_tabs, requested), sessions, manifest_exists)


def _history_label(history: List[dict]) -> str:
    for message in history:
        content = message.get('content')
        if message.get('role') == 'user' and content:
            text = str(content)
            label = text[:18].replace('\n', ' ').strip() or 'Chat'
            return label + ('...' if len(text) > 18 else '')
    return 'Chat'


def _update_clear_marker(cache_dir: Path, has_sessions: bool) -> None:
    marker = cache_dir / CLEAR_MARKER_NAME
    if has_sessions:
        try:
            if marker.exists():
                marker.unlink()
        except OSError:
            pass
        return
    try:
        atomic_write_json(marker, {'version': '1.0', 'cleared_at': datetime.now().isoformat()})
    except OSError:
        pass