# -*- coding: utf-8 -*-
"""Harness execution boundary tests."""

import hashlib
import tempfile
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
    HarnessRuntimeState,
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
    last_target = None
    last_args = None

    def __init__(self, target, args, daemon):
        self.__class__.last_target = target
        self.__class__.last_args = args

    def start(self):
        pass


class HarnessExecutionBoundaryTest(unittest.TestCase):
    def test_web_dispatch_uses_same_governed_audit_chain(self):
        import threading
        from types import SimpleNamespace
        from houdini_agent.utils.ai_client import AIClient

        tab = self._make_tab()
        tab._showToolStatus = _SignalStub()
        tab.client = object.__new__(AIClient)
        tab.client._stop_event = threading.Event()
        tab.client._streaming_tool_executor = None
        tab.client._batch_tool_executor = None
        tab.client._tool_executor = tab._execute_tool_with_todo
        tab.client._web_searcher = SimpleNamespace(search=lambda *args: {"success": True, "results": []})
        audits = []
        tab._append_session_diagnostics_records = lambda records, **kwargs: audits.extend(records)

        result = tab.client._get_streaming_tool_executor().execute_round([
            ("web-1", "web_search", {"query": "Houdini docs"}, {}),
        ])

        self.assertTrue(result["results_ordered"][0]["success"])
        self.assertTrue(any(record.get("tool") == "web_search" and record.get("phase") == "result" for record in audits))

    def test_search_handler_explicit_load_uses_active_run_exposure(self):
        from houdini_agent.core.agent_request_assembly import ToolExposureState
        from houdini_agent.utils.tool_registry import get_tool_registry

        tab = self._make_tab()
        tab._agent_mode = True
        tab._showToolStatus = _SignalStub()
        registry = get_tool_registry()
        tab._tool_exposure = ToolExposureState(registry, registry.get_tool_schemas(["search_tool_contracts"]))

        result = AITab._execute_tool_impl(tab, "search_tool_contracts", {
            "query": "get_usd_prim_info", "load": True,
        })

        self.assertTrue(result["success"], result)
        self.assertIn("get_usd_prim_info", result["result"]["loaded_tools"])

    def test_legacy_switch_cannot_bypass_governance(self):
        tab = self._make_tab()
        tab._harness_v2_enabled = False

        result = AITab._execute_tool_with_todo(tab, "execute_python", code="pass")

        self.assertFalse(result["success"])
        self.assertIn("Ask mode", result["error"])

    def _make_tab(self):
        tab = object.__new__(AITab)
        cache_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cache_dir.cleanup)
        tab.client = _ClientStub()
        tab._cache_dir = cache_dir.name
        tab._session_id = "test-session"
        tab._agent_session_id = None
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

    def test_recreated_executor_shares_failures_only_within_user_turn(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._harness_state = HarnessRuntimeState()
        calls = []
        tab._execute_tool_impl = lambda *args, **kwargs: calls.append(args) or {
            "success": False, "error": "NameError: missing",
        }

        for _ in range(3):
            result = AITab._execute_tool_with_todo(tab, "execute_python", code="pass")

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["error_code"], "repeated_execution_failure")

        tab._execute_tool_impl = lambda *args, **kwargs: calls.append(args) or {
            "success": True, "result": "parameters inspected",
        }
        evidence = AITab._execute_tool_with_todo(
            tab, "get_parameter_schema", node_path="/obj/geo1",
        )
        recovered = AITab._execute_tool_with_todo(tab, "execute_python", code="pass")

        self.assertTrue(evidence["success"])
        self.assertTrue(recovered["success"])
        self.assertEqual(len(calls), 4)

        tab._execute_tool_impl = lambda *args, **kwargs: calls.append(args) or {
            "success": False, "error": "NameError: missing",
        }
        for _ in range(3):
            result = AITab._execute_tool_with_todo(tab, "execute_python", code="pass")
        self.assertEqual(len(calls), 6)

        tab._harness_state = HarnessRuntimeState()
        result = AITab._execute_tool_with_todo(tab, "execute_python", code="pass")

        self.assertEqual(len(calls), 7)
        self.assertNotIn("error_code", result)

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
        tab._request_tool_confirmation = lambda *args: True
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

    def test_archival_failure_preserves_successful_tool_result(self):
        tab = self._make_tab()
        tab._agent_mode = True
        diagnostics = []
        tab._append_session_diagnostics_records = lambda records, *args, **kwargs: diagnostics.extend(records)
        tab._execute_tool_impl = lambda *args, **kwargs: {"success": True, "result": "created"}

        with patch(
            "houdini_agent.core.tool_result_store.ToolResultStore.archive_if_large",
            side_effect=RuntimeError("secret-value"),
        ):
            result = AITab._execute_tool_with_todo(tab, "create_node", node_type="null")

        self.assertEqual(result, {"success": True, "result": "created"})
        self.assertEqual(diagnostics[-1]["error_code"], "archive_failed")
        self.assertNotIn("secret-value", repr(diagnostics))

    def test_archival_failure_preserves_original_tool_error(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._execute_tool_impl = lambda *args, **kwargs: {"success": False, "error": "original error"}

        with patch(
            "houdini_agent.core.tool_result_store.ToolResultStore.archive_if_large",
            side_effect=OSError("storage error"),
        ):
            result = AITab._execute_tool_with_todo(tab, "get_network_structure", network_path="/obj")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "original error")

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
        tab._request_tool_confirmation = lambda *args: True
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

    def test_confirmed_persistent_auto_reaches_cook_guard_owner(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._confirm_mode = True
        tab._request_tool_confirmation = lambda *args: True
        recorded_modes = []
        tab._houdini_main_thread_executor = type(
            "ExecutorStub",
            (),
            {"set_explicit_update_mode": lambda self, mode: recorded_modes.append(mode)},
        )()
        tab._execute_tool_impl = lambda *args, **kwargs: {
            "success": True,
            "mode": "AutoUpdate",
            "persistent_update_mode_change": True,
            "data": {"mode_kind": "auto"},
        }

        result = AITab._execute_tool_with_todo(tab, "set_update_mode", mode="auto")

        self.assertTrue(result["success"])
        self.assertEqual(tab._agent_explicit_update_mode, "auto")
        self.assertEqual(recorded_modes, ["auto"])

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

    def test_external_mcp_adapter_uses_existing_main_thread_executor(self):
        tab = self._make_tab()
        tab._username = "artist"
        tab._session_id = "session-1"
        tab.mcp = type("MCPStub", (), {
            "_TOOL_DISPATCH": {"get_network_structure": "_tool_get_network_structure"}
        })()
        tab._houdini_main_thread_executor = type("ExecutorStub", (), {
            "is_blocked": lambda self: False,
            "is_shutdown": lambda self: False,
        })()
        audits = []
        tab._append_session_diagnostics_records = lambda records, *args, **kwargs: audits.extend(records)
        main_thread_calls = []
        tab._execute_tool_in_main_thread = lambda name, args: main_thread_calls.append((name, args)) or {
            "success": True, "result": "ok",
        }

        from houdini_agent.utils.mcp.settings import MCPSettings
        settings = MCPSettings(enabled=True, allowed_tools=("health", "get_network_structure"))
        with patch("houdini_agent.utils.mcp.server.configure_external_mcp_adapter") as configure, patch(
            "houdini_agent.utils.mcp.settings.read_settings", return_value=settings
        ):
            AITab._configure_external_mcp_adapter(tab)

        adapter = configure.call_args.args[0]
        context_type = __import__(
            "houdini_agent.utils.mcp.external_adapter", fromlist=["ExternalMCPContext"]
        ).ExternalMCPContext
        result = adapter.execute(
            context_type("session-1", "client-1", "ask", "artist", "call-1"),
            "get_network_structure",
            {"network_path": "/obj"},
        )

        self.assertTrue(result["success"])
        self.assertEqual(main_thread_calls, [("get_network_structure", {"network_path": "/obj"})])
        self.assertTrue(audits)


class GovernedToolExecutorTest(unittest.TestCase):
    def test_audit_failure_blocks_write_before_adapter(self):
        calls = []

        def broken_audit(record):
            raise OSError("disk full")

        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(),
            lambda *args: calls.append(args) or {"success": True},
            audit=broken_audit,
        )

        result = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "audit_unavailable")
        self.assertEqual(calls, [])

    def test_audit_failure_allows_only_explicit_reads_with_warning(self):
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(), lambda *args: {"success": True, "result": "read"},
            audit=lambda record: False,
        )

        result = owner.execute("get_network_structure", {"network_path": "/obj"}, {"mode": "agent"})

        self.assertTrue(result["success"])
        self.assertEqual(result["audit_status"], "degraded")
        self.assertIn("audit_warning", result)

    def test_result_audit_failure_preserves_write_and_blocks_later_writes(self):
        state = HarnessRuntimeState()
        calls = []

        def audit(record):
            if record.get("phase") == "result":
                raise OSError("disk full")

        def execute(*args):
            calls.append(args)
            return {"success": True, "result": "applied", "operation_id": "op-1"}

        first = GovernedToolExecutor(
            HarnessToolPolicyEngine(), execute, audit=audit, audit_state=state.audit_state,
        ).execute("execute_python", {"code": "pass"}, {"mode": "agent"})
        second = GovernedToolExecutor(
            HarnessToolPolicyEngine(), execute, audit=lambda record: None, audit_state=state.audit_state,
        ).execute("execute_python", {"code": "pass"}, {"mode": "agent"})

        self.assertTrue(first["success"])
        self.assertEqual(first["operation_id"], "op-1")
        self.assertEqual(first["audit_status"], "degraded")
        self.assertFalse(first["replay_safe"])
        self.assertEqual(second["error_code"], "audit_unavailable")
        self.assertEqual(len(calls), 1)

    def test_confirmation_cancel_has_terminal_and_decision_metadata(self):
        audits = []
        decision = ToolPolicyDecision(
            action="ask", reason="private prompt text", matched_rules=["confirm_write"],
            risk_score=0.7, required_control="confirm",
        )
        owner = GovernedToolExecutor(
            type("AskPolicy", (), {"decide": lambda self, *args: decision})(),
            lambda *args: self.fail("cancelled tool executed"),
            confirm=lambda *args: False, audit=audits.append,
        )

        result = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent", "run_id": "run-1"})

        self.assertFalse(result["success"])
        self.assertEqual(audits[-1]["error_code"], "confirmation_cancelled")
        self.assertEqual(audits[0]["matched_rules"], ["confirm_write"])
        self.assertEqual(audits[0]["risk_score"], 0.7)
        self.assertEqual({record["run_id"] for record in audits}, {"run-1"})
        self.assertEqual(len({record["call_id"] for record in audits}), 1)
        self.assertNotIn("private prompt text", str(audits))

    def test_repeated_exception_family_blocks_changed_python_code(self):
        calls = []
        audits = []
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(),
            lambda name, args, confirmed: calls.append(args) or {
                "success": False,
                "error": "NameError: name 'value_%d' is not defined" % len(calls),
            },
            audit=audits.append,
        )

        results = [
            owner.execute("execute_python", {"code": "print(%d)" % index}, {"mode": "agent"})
            for index in range(3)
        ]

        self.assertEqual(len(calls), 2)
        self.assertEqual(results[-1]["error_code"], "repeated_execution_failure")
        self.assertEqual(results[1]["recommended_next_action"], "collect_evidence")
        self.assertTrue(any(record["event_type"] == "execution_failure_guard" for record in audits))
        self.assertNotIn("value_", str(audits))

    def test_different_errors_and_success_do_not_accumulate(self):
        responses = iter([
            {"success": False, "error": "NameError: missing"},
            {"success": False, "error": "AttributeError: missing"},
            {"success": True, "result": "fixed"},
            {"success": False, "error": "AttributeError: missing"},
            {"success": True, "result": "fixed again"},
        ])
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(), lambda *args: next(responses),
            audit=lambda record: None,
        )

        results = [
            owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})
            for _ in range(5)
        ]

        self.assertTrue(results[-1]["success"])

    def test_only_successful_current_evidence_releases_paused_tool(self):
        for evidence in (
            {"success": False, "error": "inspection failed"},
            {"success": True, "scene_consistency": "unknown"},
            {"success": True, "thread_still_running": True},
            {"success": True, "verification": {"status": "applied_unknown"}},
            {"success": True, "result": "node inspected"},
        ):
            with self.subTest(evidence=evidence):
                calls = []
                responses = iter([
                    {"success": False, "error": "NameError: first"},
                    {"success": False, "error": "NameError: second"},
                    {"success": True, "result": "archived result"},
                    evidence,
                    {"success": True, "result": "fixed"},
                ])
                owner = GovernedToolExecutor(
                    type("FixedPolicy", (), {
                        "decide": lambda self, *args: ToolPolicyDecision(action="allow")
                    })(),
                    lambda *args: calls.append(args) or next(responses),
                    audit=lambda record: None,
                )
                for _ in range(2):
                    owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})

                owner.execute("read_tool_result", {}, {"mode": "agent"})
                blocked = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})
                self.assertEqual(blocked["error_code"], "repeated_execution_failure")

                owner.execute("inspect_node", {}, {"mode": "agent"})
                result = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})

                recovered = evidence.get("result") == "node inspected"
                self.assertEqual(result["success"], recovered)
                self.assertEqual(len(calls), 5 if recovered else 4)

    def test_recovery_tool_can_collect_new_evidence_after_repeated_failures(self):
        calls = []
        responses = iter([
            {"success": False, "error": "OperationFailed: first inspection failed"},
            {"success": False, "error": "OperationFailed: second inspection failed"},
            {"success": True, "result": "different inspection succeeded"},
        ])
        owner = GovernedToolExecutor(
            type("FixedPolicy", (), {
                "decide": lambda self, *args: ToolPolicyDecision(action="allow")
            })(),
            lambda *args: calls.append(args) or next(responses),
            audit=lambda record: None,
        )

        for code in ("inspect_first()", "inspect_second()"):
            owner.execute("inspect_python", {"code": code}, {"mode": "agent"})
        result = owner.execute(
            "inspect_python", {"code": "inspect_different_target()"}, {"mode": "agent"}
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 3)

    def test_traceback_classification_uses_final_exception(self):
        state = HarnessRuntimeState()
        calls = []
        owner = GovernedToolExecutor(
            HarnessToolPolicyEngine(),
            lambda *args: calls.append(args) or {
                "success": False,
                "error": "SyntaxError: eval failed\nDuring handling:\nNameError: missing",
            },
            execution_failures=state.execution_failures,
            audit=lambda record: None,
        )

        for _ in range(3):
            result = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})

        self.assertEqual(state.execution_failures["execute_python"], ("NameError", 2))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["error_code"], "repeated_execution_failure")

    def test_plain_tool_errors_are_limited_without_logging_error_text(self):
        calls = []
        audits = []
        owner = GovernedToolExecutor(
            type("FixedPolicy", (), {
                "decide": lambda self, *args: ToolPolicyDecision(action="allow")
            })(),
            lambda *args: calls.append(args) or {
                "success": False, "error": "Cannot update /obj/private_node",
            },
            audit=audits.append,
        )

        for index in range(3):
            result = owner.execute("set_node_parameter", {"value": index}, {"mode": "agent"})

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["error_code"], "repeated_execution_failure")
        self.assertNotIn("private_node", str(audits))

    def test_execute_python_audits_code_hash_without_source(self):
        audits = []
        code = "print('audit-source-secret')"
        owner = GovernedToolExecutor(
            type("FixedPolicy", (), {
                "decide": lambda self, *args: ToolPolicyDecision(action="allow")
            })(),
            lambda *args: {"success": True, "result": "done"},
            audit=audits.append,
        )

        result = owner.execute("execute_python", {"code": code}, {"mode": "agent"})

        self.assertTrue(result["success"])
        start_record = next(record for record in audits if record.get("phase") == "start")
        self.assertEqual(start_record["code_sha256"], hashlib.sha256(code.encode("utf-8")).hexdigest())
        self.assertNotIn("audit-source-secret", str(audits))

    def test_timeout_consistency_metadata_is_audited(self):
        audits = []
        owner = GovernedToolExecutor(
            type("FixedPolicy", (), {
                "decide": lambda self, *args: ToolPolicyDecision(action="allow")
            })(),
            lambda *args: {
                "success": False,
                "error": "timed out",
                "thread_still_running": True,
                "scene_consistency": "unknown",
            },
            audit=audits.append,
        )

        result = owner.execute("execute_python", {"code": "pass"}, {"mode": "agent"})

        self.assertFalse(result["success"])
        self.assertTrue(audits[-1]["thread_still_running"])
        self.assertEqual(audits[-1]["scene_consistency"], "unknown")

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
            audit=lambda record: None,
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

    def test_governed_executor_audits_inconclusive_post_write_verification(self):
        audits = []
        owner = GovernedToolExecutor(
            type("FixedPolicy", (), {
                "decide": lambda self, *args: ToolPolicyDecision(action="allow")
            })(),
            lambda *args: {
                "success": True,
                "result": "mutation returned",
                "verification": {
                    "status": "applied_unknown",
                    "node_path": "/obj/secret",
                },
            },
            audit=audits.append,
        )

        result = owner.execute("create_node", {}, {"mode": "agent"})

        self.assertTrue(result["success"])
        self.assertEqual(audits[-1]["verification_status"], "applied_unknown")
        self.assertEqual(audits[-1]["error_code"], "verification_inconclusive")
        self.assertNotIn("/obj/secret", str(audits[-1]))


if __name__ == "__main__":
    unittest.main()
