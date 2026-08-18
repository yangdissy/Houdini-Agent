# -*- coding: utf-8 -*-
"""Minimal runtime coverage for cache loading."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_import_smoke import _install_qt_stubs

_install_qt_stubs()

from houdini_agent.core.cache_mixin import CacheMixin


class _Tabs:
    def count(self):
        return 1

    def tabData(self, index):
        return "initial"

    def setTabData(self, index, value):
        self.session_id = value


class CacheMixinRuntimeTest(unittest.TestCase):
    def test_load_cache_silent_uses_session_cache_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "session_loaded.json"
            cache_file.write_text(json.dumps({
                "version": "1.0",
                "session_id": "loaded",
                "created_at": "2026-08-17T12:00:00",
                "conversation_history": [{"role": "user", "content": "hello"}],
                "context_summary": "summary",
                "token_stats": {"total_tokens": 7},
            }), encoding="utf-8")

            tab = object.__new__(CacheMixin)
            tab._conversation_history = []
            tab._context_summary = ""
            tab._session_id = "initial"
            tab._session_created_at = ""
            tab._token_stats = {}
            tab._sessions = {"initial": {}}
            tab.session_tabs = _Tabs()
            tab.todo_list = None
            tab._render_conversation_history = lambda: None
            tab._update_token_stats_display = lambda: None
            tab._update_context_stats = lambda: None
            renamed = []
            tab._auto_rename_tab = renamed.append

            loaded = tab._load_cache(cache_file, silent=True)

        self.assertTrue(loaded)
        self.assertEqual(tab._session_id, "loaded")
        self.assertEqual(tab._conversation_history, [{"role": "user", "content": "hello"}])
        self.assertEqual(tab._context_summary, "summary")
        self.assertEqual(tab._token_stats, {"total_tokens": 7})
        self.assertEqual(tab._sessions["loaded"]["conversation_history"], tab._conversation_history)
        self.assertEqual(renamed, ["hello"])


if __name__ == "__main__":
    unittest.main()