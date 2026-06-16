# -*- coding: utf-8 -*-
"""Diagnostics export payload tests."""

import unittest

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.ai_tab import AITab


class DiagnosticsPayloadTest(unittest.TestCase):
    def test_payload_omits_conversation_content_and_bounds_records(self):
        tab = object.__new__(AITab)
        tab._session_id = "abc123"
        tab._username = "tester"
        tab._agent_mode = True
        tab._plan_mode = False
        tab._plan_phase = "idle"
        tab._confirm_mode = True
        tab._auto_read_mode = "sel"
        tab._conversation_history = [
            {"role": "user", "content": "secret user message"},
            {"role": "assistant", "content": "secret assistant reply"},
        ]
        tab._is_running = False
        tab._harness_v2_enabled = True
        tab._policy_retry_limit = 2
        tab._pending_user_switch = None
        tab._token_stats = {"total_tokens": 12}
        tab._policy_failure_count = 1
        tab._policy_timeline_records = [{"tool": str(i)} for i in range(250)]
        tab._harness_trace_records = [{"round": i} for i in range(600)]
        tab._call_records = [{"call": i} for i in range(150)]
        tab._current_provider = lambda: "of3d"
        tab.model_combo = type("ModelCombo", (), {"currentText": lambda self: "gpt-5.5"})()
        tab._harness_state = type(
            "HarnessState",
            (),
            {
                "trace": [{"event": i} for i in range(350)],
                "policy_retry_counts": {"tool:key": 1},
            },
        )()

        payload = AITab._build_diagnostics_payload(tab)
        rendered = str(payload)

        self.assertEqual(payload["session"]["conversation_messages"], 2)
        self.assertNotIn("secret user message", rendered)
        self.assertNotIn("secret assistant reply", rendered)
        self.assertEqual(len(payload["policy"]["timeline"]), 200)
        self.assertEqual(len(payload["harness"]["runtime_trace"]), 300)
        self.assertEqual(len(payload["harness"]["executor_trace"]), 500)
        self.assertEqual(len(payload["calls"]), 100)
        self.assertIn("session_audit_jsonl", payload["session"])
        self.assertIn("session_audit_exists", payload["session"])
        self.assertTrue(str(payload["session"]["session_audit_jsonl"]).endswith("session_abc123.jsonl"))
        self.assertIsInstance(payload["session"]["session_audit_exists"], bool)


if __name__ == "__main__":
    unittest.main()