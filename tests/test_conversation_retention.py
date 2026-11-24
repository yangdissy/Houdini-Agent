# -*- coding: utf-8 -*-
"""Conversation retention data-safety tests."""

import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.core.conversation_retention import (
    cleanup_conversation_retention,
    conversation_retention_days_from_env,
    is_conversation_retention_enabled,
)


class ConversationRetentionTest(unittest.TestCase):
    def setUp(self):
        self._old_enabled = os.environ.get("HOUDINI_AGENT_CONVERSATION_RETENTION")
        self._old_days = os.environ.get("HOUDINI_AGENT_CONVERSATION_RETENTION_DAYS")

    def tearDown(self):
        self._restore_env("HOUDINI_AGENT_CONVERSATION_RETENTION", self._old_enabled)
        self._restore_env("HOUDINI_AGENT_CONVERSATION_RETENTION_DAYS", self._old_days)

    def test_cleanup_deletes_only_expired_archives_and_legacy_caches(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_manifest(root, ["session_live.json"])
            now = time.time()
            old = now - 200 * 86400
            recent = now - 10 * 86400

            archive = self._touch(root / "archive_old_20260101.json", old)
            legacy = self._touch(root / "cache_old.json", old)
            recent_archive = self._touch(root / "archive_recent_20261101.json", recent)
            current_archive = self._touch(root / "archive_live_20260101.json", old)
            latest = self._touch(root / "cache_latest.json", old)
            session = self._touch(root / "session_orphan.json", old)
            rollback = self._touch(root / ".session_live.json.rollback", old)
            clear_marker = self._touch(root / "sessions_cleared.json", old)

            summary = cleanup_conversation_retention(
                root, retention_days=180, current_session_id="live", now=now,
            )

            self.assertEqual(summary["deleted"], 2)
            self.assertFalse(archive.exists())
            self.assertFalse(legacy.exists())
            for path in (
                    recent_archive, current_archive, latest, session, rollback, clear_marker):
                self.assertTrue(path.exists())
            self.assertEqual(summary["skipped_current"], 1)
            self.assertEqual(summary["errors"], 0)

    def test_cleanup_fails_closed_without_valid_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self._touch(root / "archive_old_20260101.json", 1)

            missing = cleanup_conversation_retention(root, now=time.time())
            self.assertEqual(missing["blocked"], "manifest_unavailable")
            self.assertTrue(archive.exists())

            (root / "sessions_manifest.json").write_text("{broken", encoding="utf-8")
            invalid = cleanup_conversation_retention(root, now=time.time())
            self.assertEqual(invalid["blocked"], "manifest_unavailable")
            self.assertTrue(archive.exists())

    def test_cleanup_fails_closed_during_save_transaction(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_manifest(root, [])
            archive = self._touch(root / "archive_old_20260101.json", 1)
            self._touch(root / ".session_live.json.stage", 1)

            summary = cleanup_conversation_retention(root, now=time.time())

            self.assertEqual(summary["blocked"], "active_transaction")
            self.assertTrue(archive.exists())

    def test_environment_is_opt_in(self):
        os.environ.pop("HOUDINI_AGENT_CONVERSATION_RETENTION", None)
        os.environ.pop("HOUDINI_AGENT_CONVERSATION_RETENTION_DAYS", None)
        self.assertFalse(is_conversation_retention_enabled())
        self.assertEqual(conversation_retention_days_from_env(), 180)

        os.environ["HOUDINI_AGENT_CONVERSATION_RETENTION"] = "true"
        os.environ["HOUDINI_AGENT_CONVERSATION_RETENTION_DAYS"] = "90"
        self.assertTrue(is_conversation_retention_enabled())
        self.assertEqual(conversation_retention_days_from_env(), 90)

    @staticmethod
    def _write_manifest(root, files):
        (root / "sessions_manifest.json").write_text(json.dumps({
            "version": "1.0",
            "active_session_id": "live",
            "tabs": [{"session_id": "live", "file": name} for name in files],
        }), encoding="utf-8")

    @staticmethod
    def _touch(path, mtime):
        path.write_text("{}\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    @staticmethod
    def _restore_env(name, value):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()