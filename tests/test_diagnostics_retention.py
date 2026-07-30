# -*- coding: utf-8 -*-
"""Diagnostics retention cleanup tests."""

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.core.diagnostics_retention import (
    cleanup_diagnostics_retention,
    is_retention_cleanup_enabled,
    retention_days_from_env,
)


class DiagnosticsRetentionTest(unittest.TestCase):
    def setUp(self):
        self._old_enabled = os.environ.get("HOUDINI_AGENT_DIAGNOSTICS_RETENTION")
        self._old_days = os.environ.get("HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS")

    def tearDown(self):
        if self._old_enabled is None:
            os.environ.pop("HOUDINI_AGENT_DIAGNOSTICS_RETENTION", None)
        else:
            os.environ["HOUDINI_AGENT_DIAGNOSTICS_RETENTION"] = self._old_enabled
        if self._old_days is None:
            os.environ.pop("HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS", None)
        else:
            os.environ["HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS"] = self._old_days

    def test_cleanup_deletes_only_expired_diagnostics_and_trace_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            diagnostics = root / "diagnostics"
            trace = root / "harness_trace"
            diagnostics.mkdir()
            trace.mkdir()
            now = time.time()
            old_time = now - 40 * 86400
            recent_time = now - 5 * 86400

            old_diag_export = self._touch(diagnostics / "diagnostics_old_20260601_120000.json", old_time)
            old_diag_session = self._touch(diagnostics / "session_olddiag.jsonl", old_time)
            old_trace = self._touch(trace / "session_oldtrace.jsonl", old_time)
            recent_diag = self._touch(diagnostics / "diagnostics_recent_20260720_120000.json", recent_time)
            current_diag = self._touch(diagnostics / "session_current.jsonl", old_time)
            current_trace = self._touch(trace / "session_current.jsonl", old_time)
            nonmatching = self._touch(diagnostics / "notes.txt", old_time)
            conversation = self._touch(root / "session_oldchat.json", old_time)
            manifest = self._touch(root / "sessions_manifest.json", old_time)

            summary = cleanup_diagnostics_retention(root, retention_days=30, current_session_id="current", now=now)

            self.assertEqual(summary["deleted"], 3)
            self.assertFalse(old_diag_export.exists())
            self.assertFalse(old_diag_session.exists())
            self.assertFalse(old_trace.exists())
            self.assertTrue(recent_diag.exists())
            self.assertTrue(current_diag.exists())
            self.assertTrue(current_trace.exists())
            self.assertTrue(nonmatching.exists())
            self.assertTrue(conversation.exists())
            self.assertTrue(manifest.exists())
            self.assertEqual(summary["skipped_current"], 2)
            self.assertEqual(summary["errors"], 0)

    def test_cleanup_handles_missing_directories(self):
        with TemporaryDirectory() as tmp:
            summary = cleanup_diagnostics_retention(Path(tmp), retention_days=30, current_session_id="abc")

            self.assertEqual(summary["deleted"], 0)
            self.assertEqual(summary["errors"], 0)

    def test_retention_environment_parsing(self):
        os.environ.pop("HOUDINI_AGENT_DIAGNOSTICS_RETENTION", None)
        os.environ.pop("HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS", None)
        self.assertTrue(is_retention_cleanup_enabled())
        self.assertEqual(retention_days_from_env(), 30)

        os.environ["HOUDINI_AGENT_DIAGNOSTICS_RETENTION"] = "false"
        os.environ["HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS"] = "14"
        self.assertFalse(is_retention_cleanup_enabled())
        self.assertEqual(retention_days_from_env(), 14)

        os.environ["HOUDINI_AGENT_DIAGNOSTICS_RETENTION_DAYS"] = "bad"
        self.assertEqual(retention_days_from_env(), 30)

    @staticmethod
    def _touch(path: Path, mtime: float) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path


if __name__ == "__main__":
    unittest.main()
