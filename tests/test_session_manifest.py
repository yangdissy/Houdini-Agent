# -*- coding: utf-8 -*-
"""Session manifest persistence tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()
sys.modules.setdefault("numpy", mock.MagicMock(name="numpy"))

from houdini_agent.ui.ai_tab import AITab


class _Tabs:
    def __init__(self, entries):
        self._entries = entries

    def count(self):
        return len(self._entries)

    def tabData(self, index):
        return self._entries[index][0]

    def tabText(self, index):
        return self._entries[index][1]


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class SessionManifestTest(unittest.TestCase):
    def _saving_tab(self, cache_dir):
        tab = object.__new__(AITab)
        tab._cache_dir = cache_dir
        tab._session_id = "5ea8f545"
        tab._ai_tab_active = True
        tab._agent_session_id = None
        tab._agent_history = None
        tab._agent_token_stats = None
        tab.session_tabs = _Tabs([("5ea8f545", "Stitch")])
        tab._tabs_backup = [("5ea8f545", "Stitch")]
        tab._sessions = {"5ea8f545": {
            "conversation_history": [{"role": "user", "content": "Stitch"}],
            "created_at": "2026-06-25T11:24:29.678295",
            "context_summary": "",
            "token_stats": {},
        }}
        tab._save_current_session_state = lambda: None
        tab._sync_tabs_backup = lambda: None
        return tab

    def test_save_all_sessions_active_falls_back_to_saved_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            tab = object.__new__(AITab)
            tab._cache_dir = cache_dir
            tab._session_id = "empty999"
            tab._agent_session_id = None
            tab._agent_history = None
            tab._agent_token_stats = None
            tab.session_tabs = _Tabs([
                ("5ea8f545", "Stitch"),
                ("empty999", "Chat 2"),
            ])
            tab._sessions = {
                "5ea8f545": {
                    "conversation_history": [{"role": "user", "content": "Stitch"}],
                    "created_at": "2026-06-25T11:24:29.678295",
                    "context_summary": "",
                    "token_stats": {},
                },
                "empty999": {
                    "conversation_history": [],
                    "created_at": "2026-06-25T11:30:00",
                    "context_summary": "",
                    "token_stats": {},
                },
            }
            tab._save_current_session_state = lambda: None
            tab._sync_tabs_backup = lambda: None

            self.assertTrue(AITab._save_all_sessions(tab))

            manifest = json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["active_session_id"], "5ea8f545")
            self.assertEqual([entry["session_id"] for entry in manifest["tabs"]], ["5ea8f545"])
            self.assertFalse((cache_dir / "session_empty999.json").exists())

    def test_save_all_sessions_writes_empty_manifest_when_all_sessions_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            tab = object.__new__(AITab)
            tab._cache_dir = cache_dir
            tab._session_id = "empty999"
            tab._agent_session_id = None
            tab._agent_history = None
            tab._agent_token_stats = None
            tab.session_tabs = _Tabs([("empty999", "Chat 1")])
            tab._sessions = {
                "empty999": {
                    "conversation_history": [],
                    "created_at": "2026-06-25T11:30:00",
                    "context_summary": "",
                    "token_stats": {},
                }
            }
            tab._save_current_session_state = lambda: None
            tab._sync_tabs_backup = lambda: None

            self.assertFalse(AITab._save_all_sessions(tab))

            manifest = json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["active_session_id"], "")
            self.assertEqual(manifest["tabs"], [])

    def test_restore_empty_manifest_does_not_scan_orphan_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "sessions_manifest.json").write_text(
                json.dumps({"version": "1.0", "active_session_id": "", "tabs": []}),
                encoding="utf-8",
            )
            (cache_dir / "session_147af525.json").write_text(
                json.dumps({
                    "version": "1.0",
                    "session_id": "147af525",
                    "conversation_history": [{"role": "user", "content": "Stitch"}],
                }),
                encoding="utf-8",
            )
            tab = object.__new__(AITab)
            tab._cache_dir = cache_dir
            tab._sessions_restored = False
            tab._sessions = {}
            tab.session_tabs = _Noop()
            tab._sync_tabs_backup = lambda: None
            tab._update_context_stats = lambda: None

            self.assertTrue(AITab._restore_all_sessions(tab))
            self.assertTrue(tab._sessions_restored)

    def test_restore_clear_marker_overrides_stale_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            (cache_dir / "sessions_cleared.json").write_text(
                json.dumps({"version": "1.0", "cleared_at": "2026-06-25T12:00:00"}),
                encoding="utf-8",
            )
            (cache_dir / "sessions_manifest.json").write_text(
                json.dumps({
                    "version": "1.0",
                    "active_session_id": "147af525",
                    "tabs": [{
                        "session_id": "147af525",
                        "tab_label": "Stitch",
                        "file": "session_147af525.json",
                    }],
                }),
                encoding="utf-8",
            )
            tab = object.__new__(AITab)
            tab._cache_dir = cache_dir
            tab._sessions_restored = False
            tab._sessions = {}
            tab.session_tabs = _Noop()
            tab._sync_tabs_backup = lambda: None
            tab._update_context_stats = lambda: None

            self.assertTrue(AITab._restore_all_sessions(tab))

            manifest = json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["active_session_id"], "")
            self.assertEqual(manifest["tabs"], [])

    def test_update_manifest_ignores_stale_session_file_for_empty_tab(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            stale_file = cache_dir / "session_147af525.json"
            stale_file.write_text(
                json.dumps({
                    "version": "1.0",
                    "session_id": "147af525",
                    "conversation_history": [{"role": "user", "content": "Stitch"}],
                }),
                encoding="utf-8",
            )
            tab = object.__new__(AITab)
            tab._cache_dir = cache_dir
            tab._session_id = "147af525"
            tab.session_tabs = _Tabs([("147af525", "Stitch")])
            tab._sessions = {
                "147af525": {
                    "conversation_history": [],
                    "created_at": "2026-06-25T11:30:00",
                    "context_summary": "",
                    "token_stats": {},
                }
            }

            AITab._update_manifest(tab)

            manifest = json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["active_session_id"], "")
            self.assertEqual(manifest["tabs"], [])
            self.assertFalse(stale_file.exists())

    def test_session_replace_failure_does_not_publish_new_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            old_manifest = {"version": "1.0", "active_session_id": "old", "tabs": []}
            (cache_dir / "sessions_manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
            tab = self._saving_tab(cache_dir)
            original = tab._replace_file

            def fail_session(source, target):
                if target.name.startswith("session_"):
                    raise PermissionError("occupied")
                return original(source, target)

            tab._replace_file = fail_session
            self.assertFalse(AITab._save_session_workspace(tab))
            self.assertEqual(
                json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8")),
                old_manifest,
            )

    def test_manifest_replace_failure_preserves_old_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            old_manifest = {"version": "1.0", "active_session_id": "old", "tabs": []}
            (cache_dir / "sessions_manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
            tab = self._saving_tab(cache_dir)
            original = tab._replace_file

            def fail_manifest(source, target):
                if target.name == "sessions_manifest.json":
                    raise PermissionError("occupied")
                return original(source, target)

            tab._replace_file = fail_manifest
            self.assertFalse(AITab._save_session_workspace(tab))
            self.assertEqual(
                json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8")),
                old_manifest,
            )

    def test_second_session_replace_failure_rolls_back_first_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            old_manifest = {
                "version": "1.0", "active_session_id": "one",
                "tabs": [
                    {"session_id": "one", "tab_label": "One", "file": "session_one.json"},
                    {"session_id": "two", "tab_label": "Two", "file": "session_two.json"},
                ],
            }
            old_one = {"session_id": "one", "conversation_history": [{"role": "user", "content": "old one"}]}
            old_two = {"session_id": "two", "conversation_history": [{"role": "user", "content": "old two"}]}
            (cache_dir / "sessions_manifest.json").write_text(json.dumps(old_manifest), encoding="utf-8")
            (cache_dir / "session_one.json").write_text(json.dumps(old_one), encoding="utf-8")
            (cache_dir / "session_two.json").write_text(json.dumps(old_two), encoding="utf-8")
            tab = self._saving_tab(cache_dir)
            tab._session_id = "one"
            tab.session_tabs = _Tabs([("one", "One"), ("two", "Two")])
            tab._tabs_backup = [("one", "One"), ("two", "Two")]
            tab._sessions = {
                "one": {"conversation_history": [{"role": "user", "content": "new one"}]},
                "two": {"conversation_history": [{"role": "user", "content": "new two"}]},
            }
            original_replace = tab._replace_file

            def fail_second(source, target):
                if target.name == "session_two.json":
                    raise PermissionError("occupied")
                return original_replace(source, target)

            tab._replace_file = fail_second
            self.assertFalse(AITab._save_session_workspace(tab))
            self.assertEqual(json.loads((cache_dir / "session_one.json").read_text(encoding="utf-8")), old_one)
            self.assertEqual(json.loads((cache_dir / "session_two.json").read_text(encoding="utf-8")), old_two)
            self.assertEqual(json.loads((cache_dir / "sessions_manifest.json").read_text(encoding="utf-8")), old_manifest)

    def test_failed_commit_does_not_delete_old_file_for_newly_empty_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            old_empty = {"session_id": "empty", "conversation_history": [{"role": "user", "content": "old"}]}
            (cache_dir / "session_empty.json").write_text(json.dumps(old_empty), encoding="utf-8")
            tab = self._saving_tab(cache_dir)
            tab._session_id = "live"
            tab.session_tabs = _Tabs([("live", "Live"), ("empty", "Empty")])
            tab._sessions = {
                "live": {"conversation_history": [{"role": "user", "content": "new"}]},
                "empty": {"conversation_history": []},
            }
            original_replace = tab._replace_file

            def fail_manifest(source, target):
                if target.name == "sessions_manifest.json":
                    raise PermissionError("occupied")
                return original_replace(source, target)

            tab._replace_file = fail_manifest
            self.assertFalse(AITab._save_session_workspace(tab))
            self.assertEqual(json.loads((cache_dir / "session_empty.json").read_text(encoding="utf-8")), old_empty)

    def test_normal_periodic_all_and_atexit_delegate_same_owner(self):
        tab = object.__new__(AITab)
        tab._conversation_history = [{"role": "user", "content": "x"}]
        tab._sessions = {"sid": {"conversation_history": tab._conversation_history}}
        tab._workspace_dir = None
        tab._save_current_session_state = lambda: None
        tab._sync_tabs_backup = lambda: None
        calls = []
        tab._save_session_workspace = lambda **kwargs: calls.append(kwargs) or True

        self.assertTrue(AITab._save_cache(tab))
        AITab._periodic_save_all(tab)
        self.assertTrue(AITab._save_all_sessions(tab))
        AITab._atexit_save(tab)

        self.assertEqual(calls, [{}, {}, {}, {"use_backup": True, "quiet": True}])

    def test_stale_tab_never_writes_and_preserves_agent_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            tab = self._saving_tab(Path(tmp))
            tab._ai_tab_active = False
            tab._agent_session_id = "5ea8f545"
            tab._agent_history = [{"role": "assistant", "content": "latest"}]

            self.assertFalse(AITab._save_session_workspace(tab))
            self.assertEqual(tab._agent_session_id, "5ea8f545")
            self.assertFalse((Path(tmp) / "sessions_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()