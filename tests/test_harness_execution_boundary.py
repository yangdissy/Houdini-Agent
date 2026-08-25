# -*- coding: utf-8 -*-
"""Harness execution boundary tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.harness_engine import (
    GovernedToolExecutor,
    HarnessToolPolicyEngine,
    ToolPolicyDecision,
)
from houdini_agent.core.send_orchestrator_mixin import SendOrchestratorMixin
from houdini_agent.ui.ai_tab import AITab


class _SignalStub:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class _ClientStub:
    def is_stop_requested(self):
        return False


class _ControlStub:
    def __init__(self, value):
        self._value = value

    def currentText(self):
        return self._value

    def isChecked(self):
        return bool(self._value)


class _ThreadStub:
    last_args = None

    def __init__(self, target, args, daemon):
        self.__class__.last_args = args

    def start(self):
        pass


class _ThreadStub:
    last_target = None
    last_args = None

    def __init__(self, target, args, daemon):
        self.__class__.last_target = target
        self.__class__.last_args = args

    def start(self):
        pass


class HarnessExecutionBoundaryTest(unittest.TestCase):
    def _make_tab(self):
        tab = object.__new__(AITab)
        tab.client = _ClientStub()
        tab._harness_v2_enabled = True
        tab._tool_policy_engine = HarnessToolPolicyEngine()
        tab._harness_state = None
        tab._plan_mode = False
        tab._agent_mode = False
        tab._plan_phase = "idle"
        tab._confirm_mode = False
        tab._policy_retry_limit = 2
        tab._append_policy_timeline = lambda *args, **kwargs: None
        tab._append_session_diagnostics_records = lambda *args, **kwargs: None
        tab._addStatus = _SignalStub()
        tab._execute_tool_impl = lambda *args, **kwargs: {"success": True, "result": "should not run"}
        tab._pre_agent_update_mode = None
        return tab

    @staticmethod
    def _empty_geometry_result(node_path="/obj/geo1/OUT"):
        return {
            "success": True,
            "result": "empty geometry",
            "node_path": node_path,
            "manual_mode": True,
            "is_empty_geometry": True,
            "recommended_next_action": "temporary_auto_validate",
        }

    def test_model_supplied_policy_checked_flag_cannot_bypass_harness(self):
        tab = self._make_tab()

        result = AITab._execute_tool_with_todo(
            tab,
            "execute_python",
            code="print(1)",
            _harness_policy_checked=True,
        )

        self.assertFalse(result["success"])
        self.assertIn("Ask mode", result["error"])

    def test_model_supplied_skip_confirm_flag_is_discarded(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._confirm_mode = True
        confirmations = []

        def request_confirmation(tool_name, args):
            confirmations.append((tool_name, args))
            return False

        tab._request_tool_confirmation = request_confirmation

        result = AITab._execute_tool_with_todo(
            tab,
            "execute_shell",
            command="dir",
            _harness_skip_confirm=True,
        )

        self.assertFalse(result["success"])
        self.assertEqual(confirmations[0][0], "execute_shell")

    def test_start_agent_run_captures_user_message_in_thread_params(self):
        tab = self._make_tab()
        tab._current_user_message = "上一轮消息"
        tab._capture_pre_agent_update_mode = lambda: None
        tab._update_context_stats = lambda: None
        tab._set_running = lambda value: None
        tab._add_ai_response = lambda: None
        tab._current_response = object()
        tab._start_active_aurora = lambda: None
        tab._current_provider = lambda: "test"
        tab.model_combo = _ControlStub("model")
        tab.web_check = _ControlStub(False)
        tab.think_check = _ControlStub(False)
        tab._get_current_context_limit = lambda: 1000
        tab._collect_scene_context = lambda: {}
        tab._current_model_supports_vision = lambda: False
        tab._plan_mode = False
        tab._save_model_preference = lambda: None

        with patch("houdini_agent.core.send_orchestrator_mixin.threading.Thread", _ThreadStub):
            SendOrchestratorMixin._start_agent_run(
                tab, inject_scene=False, user_message="记住上面这次的回答"
            )

        params = _ThreadStub.last_args[0]
        self.assertEqual(params["user_message"], "记住上面这次的回答")
        self.assertEqual(tab._current_user_message, "记住上面这次的回答")

    def test_empty_geometry_after_cook_blocks_validation_signal(self):
        tab = self._make_tab()
        tab._agent_mode = True
        diagnostics = []
        tab._append_session_diagnostics_records = lambda records, *args, **kwargs: diagnostics.extend(records)
        results = [
            self._empty_geometry_result(),
            {"success": True, "result": "cooked"},
            self._empty_geometry_result(),
        ]
        tab._execute_tool_impl = lambda *args, **kwargs: results.pop(0)

        first = AITab._execute_tool_with_todo(tab, "get_geometry_summary", node_path="/obj/geo1/OUT")
        cook = AITab._execute_tool_with_todo(tab, "cook_node", node_path="/obj/geo1/OUT")
        second = AITab._execute_tool_with_todo(tab, "get_geometry_summary", node_path="/obj/geo1/OUT")

        self.assertNotIn("recovery_hint", first)
        self.assertTrue(cook["success"])
        self.assertIn("recovery_hint", second)
        self.assertIn("temporary_auto_validate", second["recovery_hint"])
        self.assertTrue(second["validation_blocked"])
        self.assertEqual(second["validation_block_reason"], "manual_empty_geometry_after_cook")
        self.assertEqual(second["recommended_next_action"], "temporary_auto_validate")
        self.assertTrue(any(record.get("event_type") == "geometry_validation_loop_guard" for record in diagnostics))


    def test_set_update_mode_policy_path_updates_restore_snapshot(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._confirm_mode = True
        tab._pre_agent_update_mode = "Manual"
        tab._execute_tool_impl = lambda *args, **kwargs: {
            "success": True,
            "mode": "Auto",
            "persistent_update_mode_change": True,
        }

        result = AITab._execute_tool_with_todo(tab, "set_update_mode", mode="auto")

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "Auto")
        self.assertNotEqual(tab._pre_agent_update_mode, "Manual")

    def test_batch_items_each_pass_through_harness(self):
        tab = self._make_tab()
        tab._houdini_main_thread_executor = object()
        calls = []
        tab._execute_tool_impl = lambda name, args, **kwargs: calls.append((name, args)) or {
            "success": True, "result": name,
        }

        results = AITab._execute_tools_batch_in_main_thread(tab, [
            ("get_network_structure", {"network_path": "/obj"}),
            ("execute_python", {"code": "print(1)"}),
        ])

        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertEqual([name for name, _ in calls], ["get_network_structure"])


class GovernedToolExecutorTest(unittest.TestCase):
    def test_allow_sanitizes_result_and_audits_metadata_only(self):
        audits = []
        calls = []
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(),
            lambda name, args, confirmed: calls.append(args) or {
                "success": True, "result": "api_key=sk-testsecret1234567890",
            },
            audit=audits.append,
        )

        result = owner.execute("get_network_structure", {"network_path": "/obj"}, {"mode": "agent"})

        self.assertTrue(result["success"])
        self.assertIn("[REDACTED]", result["result"])
        self.assertEqual(calls, [{"network_path": "/obj"}])
        self.assertEqual([r.get("phase") for r in audits if r["event_type"] == "tool_call"], ["start", "result"])
        self.assertNotIn("/obj", str(audits))

    def test_policy_and_confirmation_errors_fail_closed(self):
        class BrokenPolicy:
            def decide(self, *args):
                raise RuntimeError("secret policy detail")

        calls = []
        broken = GovernedToolExecutor(BrokenPolicy(), lambda *args: calls.append(args))
        result = broken.execute("anything", {}, {"mode": "agent"})
        self.assertFalse(result["success"])
        self.assertEqual(calls, [])
        self.assertNotIn("secret", result["error"])

        asking = GovernedToolExecutor(
            type("AskPolicy", (), {"decide": lambda self, *args: ToolPolicyDecision(action="ask")})(),
            lambda *args: calls.append(args),
            confirm=lambda *args: (_ for _ in ()).throw(RuntimeError("dialog failed")),
        )
        result = asking.execute("anything", {}, {"mode": "agent"})
        self.assertFalse(result["success"])
        self.assertEqual(calls, [])

    def test_retry_uses_only_patched_args_and_exhausts_closed(self):
        decision = ToolPolicyDecision(
            action="retry", patched_args={"file_path": "safe.hip"}, retry_key="save",
        )
        policy = type("RetryPolicy", (), {"decide": lambda self, *args: decision})()
        calls = []
        retry_counts = {}
        owner = GovernedToolExecutor(
            policy,
            lambda name, args, confirmed: calls.append(args) or {"success": False, "error": "again"},
            retry_counts=retry_counts,
            retry_limit=1,
        )

        first = owner.execute("save_hip", {"file_path": "unsafe"}, {"mode": "agent"})
        second = owner.execute("save_hip", {"file_path": "unsafe"}, {"mode": "agent"})

        self.assertFalse(first["success"])
        self.assertFalse(second["success"])
        self.assertEqual(calls, [{"file_path": "safe.hip"}])

    def test_adapter_exception_becomes_safe_audited_result(self):
        audits = []
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(),
            lambda *args: (_ for _ in ()).throw(RuntimeError("password=topsecret")),
            audit=audits.append,
        )

        result = owner.execute("get_network_structure", {"network_path": "/obj"}, {"mode": "agent"})

        self.assertFalse(result["success"])
        self.assertNotIn("topsecret", str(result))
        self.assertEqual(audits[-1]["error_code"], "tool_execution_failed")
        self.assertNotIn("topsecret", str(audits))


if __name__ == "__main__":
    unittest.main()
