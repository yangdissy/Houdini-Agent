# -*- coding: utf-8 -*-
"""Diagnostics export payload tests."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
        tab.model_combo = type("ModelCombo", (), {"currentText": lambda self: "gpt-5.6"})()
        tab._harness_state = type(
            "HarnessState",
            (),
            {
                "trace": [{"event": i} for i in range(350)],
                "policy_retry_counts": {"tool:key": 1},
            },
        )()

        with TemporaryDirectory() as tmp:
            tab._cache_dir = Path(tmp)
            audit_path = AITab._get_session_diagnostics_jsonl_path(tab, "abc123")
            audit_path.write_text(
                '{"event_type":"tool_call","recorded_at":"2026-07-20T10:00:00"}\n'
                '{"event_type":"geometry_validation_loop_guard","recorded_at":"2026-07-20T10:01:00"}\n'
                '{"event_type":"job_start","recorded_at":"2026-07-20T10:02:00",'
                '"operation_id":"op-1","kind":"render","decision":"allow",'
                '"payload":"secret","absolute_path":"C:/secret/result.json"}\n'
                '{"event_type":"job_exit","recorded_at":"2026-07-20T10:03:00",'
                '"operation_id":"op-1","kind":"render","decision":"completed",'
                '"exit_code":0,"artifacts":[{"name":"result","path":"result.json",'
                '"size":12,"media_type":"application/json"}]}\n',
                encoding="utf-8",
            )

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
            self.assertTrue(payload["session"]["session_audit_exists"])
            self.assertEqual(payload["session"]["session_audit_records"], 4)
            self.assertEqual(payload["session"]["session_audit_last_recorded_at"], "2026-07-20T10:03:00")
            self.assertIn("session_audit_stale", payload["session"])
            self.assertTrue(payload["external_jobs"]["module_available"])
            self.assertFalse(payload["external_jobs"]["runtime_configured"])
            self.assertEqual(payload["external_jobs"]["event_counts"]["job_start"], 1)
            self.assertEqual(payload["external_jobs"]["event_counts"]["job_exit"], 1)
            self.assertEqual(payload["external_jobs"]["events"][-1]["exit_code"], 0)
            self.assertNotIn("secret", rendered)
            self.assertNotIn("C:/secret", rendered)

    def test_operations_use_latest_receipt_and_project_running_as_abandoned(self):
        tab = object.__new__(AITab)
        tab._session_id = "receipt-session"
        tab._username = "tester"
        tab._agent_mode = True
        tab._plan_mode = False
        tab._plan_phase = "idle"
        tab._confirm_mode = False
        tab._conversation_history = []
        tab._policy_timeline_records = []
        tab._harness_trace_records = []
        tab._call_records = []
        tab._token_stats = {}
        tab._harness_state = type("HarnessState", (), {"trace": [], "policy_retry_counts": {}})()
        tab._current_provider = lambda: "test"
        tab.model_combo = type("ModelCombo", (), {"currentText": lambda self: "model"})()

        with TemporaryDirectory() as tmp:
            tab._cache_dir = Path(tmp)
            audit_path = AITab._get_session_diagnostics_jsonl_path(tab, tab._session_id)
            audit_path.write_text(
                '{"event_type":"operation_receipt","operation_id":"done","state":"running",'
                '"tool_name":"cook_node","recorded_at":"2026-10-14T10:00:00"}\n'
                '{"event_type":"operation_receipt","operation_id":"done","state":"completed",'
                '"success":true,"result":"secret-result","path":"C:/secret",'
                '"recorded_at":"2026-10-14T10:01:00"}\n'
                '{"event_type":"operation_receipt","operation_id":"lost","state":"running",'
                '"recorded_at":"2026-10-14T10:02:00"}\n'
                'not-json\n'
                '[1,2,3]\n'
                '{"event_type":"operation_receipt","operation_id":"partial"',
                encoding="utf-8",
            )

            payload = AITab._build_diagnostics_payload(tab)

        operations = {item["operation_id"]: item for item in payload["operations"]["items"]}
        self.assertEqual(payload["operations"]["total_count"], 2)
        self.assertEqual(operations["done"]["state"], "completed")
        self.assertEqual(operations["lost"]["state"], "abandoned")
        self.assertEqual(operations["lost"]["wait_status"], "process_interrupted")
        rendered = str(payload["operations"])
        self.assertNotIn("secret-result", rendered)
        self.assertNotIn("C:/secret", rendered)

    def test_summary_tool_usage_policy_actions_and_python_ratio(self):
        tab = object.__new__(AITab)
        tab._session_id = "usage-session"
        tab._username = "tester"
        tab._agent_mode = True
        tab._plan_mode = False
        tab._plan_phase = "idle"
        tab._confirm_mode = False
        tab._conversation_history = []
        tab._harness_trace_records = []
        tab._call_records = []
        tab._token_stats = {}
        tab._harness_state = type("HarnessState", (), {"trace": [], "policy_retry_counts": {}})()
        tab._current_provider = lambda: "test"
        tab.model_combo = type("ModelCombo", (), {"currentText": lambda self: "model"})()
        tab._policy_timeline_records = [
            {"tool": "delete_node", "action": "allow", "reason": ""},
            {"tool": "execute_python", "action": "allow", "reason": ""},
            {"tool": "cook_node", "action": "ask", "reason": "confirm"},
        ]

        with TemporaryDirectory() as tmp:
            tab._cache_dir = Path(tmp)
            audit_path = AITab._get_session_diagnostics_jsonl_path(tab, tab._session_id)
            audit_path.write_text(
                '{"event_type":"operation_receipt","operation_id":"a","state":"completed",'
                '"success":true,"tool_name":"create_nodes_batch","recorded_at":"2026-10-14T10:00:00"}\n'
                '{"event_type":"operation_receipt","operation_id":"b","state":"completed",'
                '"success":true,"tool_name":"execute_python","recorded_at":"2026-10-14T10:01:00"}\n'
                '{"event_type":"operation_receipt","operation_id":"c","state":"completed",'
                '"success":true,"tool_name":"execute_python","recorded_at":"2026-10-14T10:02:00"}\n'
                '{"event_type":"operation_receipt","operation_id":"d","state":"completed",'
                '"success":true,"tool_name":"get_network_structure","recorded_at":"2026-10-14T10:03:00"}\n',
                encoding="utf-8",
            )

            payload = AITab._build_diagnostics_payload(tab)

        summary = payload["summary"]
        self.assertEqual(summary["tool_usage_counts"]["execute_python"], 2)
        self.assertEqual(summary["tool_usage_counts"]["create_nodes_batch"], 1)
        self.assertEqual(summary["policy_action_counts"], {"allow": 2, "ask": 1})
        # 修改类调用 3 次（execute_python x2 + create_nodes_batch x1），python 占 2/3
        self.assertEqual(summary["execute_python_ratio"], round(2 / 3, 4))


if __name__ == "__main__":
    unittest.main()