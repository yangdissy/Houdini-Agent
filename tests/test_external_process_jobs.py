# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from houdini_agent.utils.mcp.external_jobs import (
    ExternalJobSpec,
    ExternalProcessJobAdapter,
)
from houdini_agent.utils.mcp.operations import OperationRegistry


WORKER = Path(__file__).parent / "fixtures" / "external_job_worker.py"


class ExternalProcessJobAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audit = []
        self.registry = OperationRegistry(max_operations=16)
        self.adapter = ExternalProcessJobAdapter(
            self.registry,
            self.temp_dir.name,
            audit=self.audit.append,
        )
        self.adapter.register(ExternalJobSpec(
            kind="test_worker",
            executable=sys.executable,
            build_args=lambda payload, request_path: [str(WORKER), request_path],
            timeout=2.0,
            artifacts={"result": ("result.json", "application/json")},
            required_artifacts=("result",),
        ))

    def tearDown(self):
        self.adapter.shutdown()
        self.temp_dir.cleanup()

    def wait_terminal(self, operation_id, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = self.adapter.get("session-a", operation_id)
            if current["state"] in {"completed", "failed", "cancelled"}:
                return current
            time.sleep(0.02)
        self.fail("operation did not reach a terminal state")

    def test_success_reports_progress_exit_code_and_validated_artifact(self):
        operation = self.adapter.start("session-a", "test_worker", {"mode": "success"})

        current = self.wait_terminal(operation["operation_id"])

        self.assertEqual(current["state"], "completed")
        self.assertEqual(current["progress"], 1.0)
        self.assertEqual(current["exit_code"], 0)
        self.assertEqual(current["artifacts"][0]["path"], "result.json")
        self.assertEqual(current["result"], {"ok": True})

    def test_audit_failure_prevents_process_start(self):
        self.adapter._audit = lambda record: False
        with mock.patch("houdini_agent.utils.mcp.external_jobs.subprocess.Popen") as process:
            with self.assertRaises(OSError):
                self.adapter.start("session-a", "test_worker", {"mode": "success"})
        process.assert_not_called()

    def test_post_start_audit_failure_preserves_job_and_blocks_new_starts(self):
        def audit(record):
            return record["event_type"] == "job_policy"

        self.adapter._audit = audit
        operation = self.adapter.start("session-a", "test_worker", {"mode": "success"})
        current = self.wait_terminal(operation["operation_id"])

        self.assertEqual(current["state"], "completed")
        self.assertEqual(current["audit_status"], "degraded")
        self.assertFalse(current["replay_safe"])
        with self.assertRaises(OSError):
            self.adapter.start("session-a", "test_worker", {"mode": "success"})

    def test_nonzero_exit_is_failed_not_cancelled(self):
        operation = self.adapter.start("session-a", "test_worker", {"mode": "failure"})

        current = self.wait_terminal(operation["operation_id"])

        self.assertEqual(current["state"], "failed")
        self.assertEqual(current["error_code"], "process_exit")
        self.assertEqual(current["exit_code"], 7)

    def test_cancel_is_session_owned_and_idempotent(self):
        operation = self.adapter.start("session-a", "test_worker", {"mode": "hang"})
        operation_id = operation["operation_id"]

        with self.assertRaises(KeyError):
            self.adapter.cancel("session-b", operation_id)
        first = self.adapter.cancel("session-a", operation_id)
        second = self.adapter.cancel("session-a", operation_id)
        current = self.wait_terminal(operation_id)

        self.assertIn(first["state"], {"running", "cancelled"})
        self.assertIn(second["state"], {"running", "cancelled"})
        self.assertEqual(current["state"], "cancelled")

    def test_timeout_is_failed(self):
        spec = ExternalJobSpec(
            kind="short_timeout",
            executable=sys.executable,
            build_args=lambda payload, request_path: [str(WORKER), request_path],
            timeout=0.1,
        )
        self.adapter.register(spec)
        operation = self.adapter.start("session-a", "short_timeout", {"mode": "hang"})

        current = self.wait_terminal(operation["operation_id"])

        self.assertEqual(current["state"], "failed")
        self.assertEqual(current["error_code"], "timeout")

    def test_missing_or_escaping_artifact_fails_closed(self):
        for mode, code in (("missing", "artifact_missing"), ("escape", "invalid_event")):
            with self.subTest(mode=mode):
                operation = self.adapter.start("session-a", "test_worker", {"mode": mode})
                current = self.wait_terminal(operation["operation_id"])
                self.assertEqual(current["state"], "failed")
                self.assertEqual(current["error_code"], code)

    def test_unknown_event_fails_closed(self):
        operation = self.adapter.start(
            "session-a", "test_worker", {"mode": "invalid_event"}
        )

        current = self.wait_terminal(operation["operation_id"])

        self.assertEqual(current["state"], "failed")
        self.assertEqual(current["error_code"], "invalid_event")

    def test_unknown_kind_and_invalid_payload_are_denied(self):
        with self.assertRaises(KeyError):
            self.adapter.start("session-a", "not_registered", {})
        with self.assertRaises(ValueError):
            self.adapter.start("session-a", "test_worker", {"secret": object()})

    def test_get_does_not_cross_session_boundary(self):
        operation = self.adapter.start("session-a", "test_worker", {"mode": "success"})

        self.assertIsNone(self.adapter.get("session-b", operation["operation_id"]))

    def test_duplicate_registration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter.register(ExternalJobSpec(
                kind="test_worker",
                executable=sys.executable,
                build_args=lambda payload, request_path: [str(WORKER), request_path],
            ))

    def test_shutdown_cancels_running_job_and_rejects_new_work(self):
        operation = self.adapter.start(
            "session-a", "test_worker", {"mode": "hang"}
        )

        self.adapter.shutdown()
        current = self.registry.get("session-a", operation["operation_id"])

        self.assertEqual(current["state"], "cancelled")
        with self.assertRaises(RuntimeError):
            self.adapter.start("session-a", "test_worker", {"mode": "success"})

    def test_audit_omits_payload_and_absolute_paths(self):
        operation = self.adapter.start("session-a", "test_worker", {"mode": "success"})
        self.wait_terminal(operation["operation_id"])

        serialized = repr(self.audit)
        self.assertNotIn(self.temp_dir.name, serialized)
        self.assertNotIn("payload", serialized)
        self.assertTrue(any(item["event_type"] == "job_exit" for item in self.audit))


if __name__ == "__main__":
    unittest.main()