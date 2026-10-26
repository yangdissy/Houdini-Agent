# -*- coding: utf-8 -*-

import unittest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs

_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.plan_mixin import PlanMixin
from houdini_agent.utils.plan_manager import PlanManager
from houdini_agent.utils.plan_runtime import PlanQualityGate, PlanRuntime
from houdini_agent.utils.tool_registry import ToolRegistry


def _plan_data():
    return {
        "title": "Build terrain scatter",
        "overview": "Create a terrain base and scatter rocks.",
        "phases": [{"name": "Phase 1", "step_ids": ["step-1", "step-2"]}],
        "steps": [
            {
                "id": "step-1",
                "title": "Base terrain",
                "description": "Create terrain base nodes under /obj/geo1.",
                "tools": ["create_nodes_batch"],
                "depends_on": [],
                "expected_result": "A visible terrain base network exists.",
            },
            {
                "id": "step-2",
                "title": "Scatter rocks",
                "description": "Scatter rock instances on terrain points.",
                "tools": ["create_nodes_batch", "layout_nodes"],
                "depends_on": ["step-1"],
                "expected_result": "Rock instances are connected after the scatter node.",
            },
        ],
        "architecture": {
            "nodes": [
                {"id": "grid1", "label": "Grid", "type": "sop"},
                {"id": "scatter1", "label": "Scatter", "type": "sop"},
            ],
            "connections": [{"from": "grid1", "to": "scatter1"}],
        },
    }


class PlanQuestionTest(unittest.TestCase):
    def make_tab(self, outcome=None, stopped=False):
        tab = PlanMixin()
        tab._session_id = "session"
        tab.client = mock.Mock()
        tab.client.is_stop_requested.return_value = stopped
        tab._finishAskQuestionRequest = mock.Mock()
        tab._askQuestionRequest = mock.Mock()
        if outcome is not None:
            tab._askQuestionRequest.emit.side_effect = lambda request: request["queue"].put(outcome)
        return tab

    def questions(self):
        return [{"id": "q1", "prompt": "Which source?", "options": [
            {"id": "a", "label": "Source A"},
        ], "allow_free_text": True}]

    def test_skip_is_not_authorization(self):
        tab = self.make_tab({"status": "skipped"})
        result = tab._handle_ask_question({"questions": self.questions()})
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["answers"], {})

    def test_stop_cancels_before_waiting(self):
        tab = self.make_tab(stopped=True)
        result = tab._handle_ask_question({"questions": self.questions()})
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "cancelled")
        tab._askQuestionRequest.emit.assert_not_called()

    def test_too_many_questions_do_not_render(self):
        tab = self.make_tab()
        result = tab._handle_ask_question({"questions": self.questions() * 3})
        self.assertFalse(result["success"])
        tab._askQuestionRequest.emit.assert_not_called()

    def test_answer_is_structured_and_request_is_closed(self):
        tab = self.make_tab({"status": "answered", "answers": {
            "q1": ["a", "__free_text__:extra"],
        }})
        result = tab._handle_ask_question({"questions": self.questions()})
        self.assertTrue(result["success"])
        self.assertEqual(result["answers"]["q1"], {"selected_option_ids": ["a"], "free_text": "extra"})
        self.assertFalse(tab._plan_question_request["active"].is_set())
        tab._finishAskQuestionRequest.emit.assert_called_once_with(result["question_request_id"], "answered")

    def test_timeout_and_ui_error_are_not_answers(self):
        tab = self.make_tab()
        with mock.patch("houdini_agent.core.plan_mixin.time.monotonic", side_effect=[0, 301]):
            result = tab._handle_ask_question({"questions": self.questions()})
        self.assertEqual(result["status"], "timed_out")
        self.assertFalse(result["success"])
        tab = self.make_tab({"status": "ui_error"})
        self.assertEqual(tab._handle_ask_question({"questions": self.questions()})["status"], "ui_error")

    def test_stop_during_wait(self):
        tab = self.make_tab()
        tab.client.is_stop_requested.side_effect = [False, False, True]
        result = tab._handle_ask_question({"questions": self.questions()})
        self.assertEqual(result["status"], "cancelled")

    def test_invalid_question_and_answer_contracts(self):
        from houdini_agent.utils.plan_manager import normalize_plan_answers, validate_plan_questions
        for questions in ([], self.questions() * 2, [{"id": "q", "prompt": "?", "options": []}]):
            with self.subTest(questions=questions), self.assertRaises(ValueError):
                validate_plan_questions(questions)
        for answers in ({}, {"q1": []}, {"q1": ["unknown"]}, {"q1": ["a", "a"]}):
            with self.subTest(answers=answers), self.assertRaises(ValueError):
                normalize_plan_answers(self.questions(), answers)
        questions = self.questions()
        questions[0]["options"].append({"id": "b", "label": "B"})
        with self.assertRaises(ValueError):
            normalize_plan_answers(questions, {"q1": ["a", "b"]})
        questions[0]["allow_multiple"] = True
        self.assertEqual(normalize_plan_answers(questions, {"q1": ["a", "b"]})["q1"]["selected_option_ids"], ["a", "b"])

    def test_late_card_answer_cannot_reach_new_request(self):
        tab = self.make_tab({"status": "skipped"})
        tab.chat_container = mock.Mock()
        tab.chat_layout = mock.Mock()
        tab.chat_layout.count.return_value = 1
        tab._scroll_to_bottom = mock.Mock()
        card = mock.Mock()
        with mock.patch("houdini_agent.core.plan_mixin.AskQuestionCard", return_value=card):
            original_emit = tab._askQuestionRequest.emit.side_effect
            def render_and_skip(request):
                tab._on_render_ask_question(request)
                original_emit(request)
            tab._askQuestionRequest.emit.side_effect = render_and_skip
            tab._handle_ask_question({"questions": self.questions()})
        old_queue = tab._ask_question_result_queue
        callback = card.answered.connect.call_args[0][0]
        tab._ask_question_result_queue = mock.Mock()
        callback({"q1": ["a"]})
        self.assertTrue(old_queue.empty())
        tab._ask_question_result_queue.put.assert_not_called()

    def test_card_rejects_empty_submission_and_finishes_once(self):
        from houdini_agent.ui.cursor_plan_widgets import AskQuestionCard
        card = mock.Mock()
        card._answered = False
        card._questions = self.questions()
        card._collect_answers.return_value = {"q1": []}
        AskQuestionCard._do_submit(card)
        card.answered.emit.assert_not_called()
        card._validation_error.setText.assert_called_once()
        card._widgets = {"q1": {"buttons": [mock.Mock()], "free_text": mock.Mock()}}
        AskQuestionCard.finish(card, "cancelled")
        AskQuestionCard.finish(card, "cancelled")
        card._btn_submit.setEnabled.assert_called_once_with(False)

    def test_expired_signal_does_not_render_a_new_request(self):
        tab = self.make_tab({"status": "skipped"})
        tab._handle_ask_question({"questions": self.questions()})
        old_request = tab._plan_question_request
        tab._plan_question_request = {"id": "new"}
        with mock.patch("houdini_agent.core.plan_mixin.AskQuestionCard") as card_type:
            tab._on_render_ask_question(old_request)
            card_type.assert_not_called()

    def test_session_switch_cancels_the_wait(self):
        tab = self.make_tab()
        tab._askQuestionRequest.emit.side_effect = lambda request: setattr(tab, "_session_id", "other")
        result = tab._handle_ask_question({"questions": self.questions()})
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["success"])

    def test_card_creation_or_insertion_failure_is_not_skip(self):
        for failure in ("create", "insert"):
            with self.subTest(failure=failure):
                tab = self.make_tab()
                tab.chat_container = mock.Mock()
                tab.chat_layout = mock.Mock()
                tab.chat_layout.count.return_value = 1
                if failure == "insert":
                    tab.chat_layout.insertWidget.side_effect = RuntimeError("widget unavailable")
                tab._askQuestionRequest.emit.side_effect = tab._on_render_ask_question
                with mock.patch("houdini_agent.core.plan_mixin.AskQuestionCard") as card_type:
                    if failure == "create":
                        card_type.side_effect = RuntimeError("widget unavailable")
                    result = tab._handle_ask_question({"questions": self.questions()})
                self.assertFalse(result["success"])
                self.assertEqual(result["status"], "ui_error")

    def test_duplicate_question_answer_does_not_emit_again(self):
        from houdini_agent.ui.cursor_plan_widgets import AskQuestionCard
        card = mock.Mock()
        card._answered = True
        AskQuestionCard._do_submit(card)
        AskQuestionCard._do_cancel(card)
        card.answered.emit.assert_not_called()
        card.cancelled.emit.assert_not_called()


class PlanQualityGateTest(unittest.TestCase):
    def test_architecture_is_optional_in_tool_contract(self):
        from houdini_agent.utils.plan_manager import PLAN_TOOL_CREATE
        self.assertNotIn("architecture", PLAN_TOOL_CREATE["function"]["parameters"]["required"])
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            raw = _plan_data()
            raw.pop("architecture")
            raw["steps"][1]["depends_on"] = []
            plan = manager.create_plan("session", raw)
            self.assertEqual(plan["architecture"], {})

    def test_create_handler_returns_located_diagnostics_and_preserves_old_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            old_plan = manager.create_plan("session", _plan_data())
            tab = PlanMixin()
            tab._session_id = "session"
            tab._plan_manager = manager
            tab._restore_plan_projection = mock.Mock()
            tab._showGenerating = mock.Mock()
            bad = _plan_data()
            bad["steps"][1]["depends_on"] = ["missing"]
            result = tab._handle_create_plan(bad)
            self.assertFalse(result["success"])
            self.assertEqual(result["error_kind"], "plan_quality")
            self.assertTrue(any(item["step_id"] == "step-2" and item["code"] == "unknown_dependency"
                                for item in result["diagnostics"]))
            self.assertEqual(manager.load_plan("session")["plan_id"], old_plan["plan_id"])
            tab._showGenerating.emit.assert_not_called()
            result = tab._handle_create_plan(_plan_data())
            self.assertEqual(result["status"], "awaiting_confirmation")
            self.assertIn("plan_id", result)
            self.assertIn("quality", result)

    def test_manager_persists_quality_diagnostics_for_warnings(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            raw = _plan_data()
            raw["steps"][1]["expected_result"] = "ok"

            plan = manager.create_plan("session", raw)

            self.assertIn("quality", plan)
            codes = [d["code"] for d in plan["quality"]["diagnostics"]]
            self.assertIn("weak_expected_result", codes)
            self.assertLess(plan["quality"]["score"], 1.0)
            self.assertIsNotNone(manager.load_plan("session"))

    def test_manager_rejects_missing_dependency(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            raw = _plan_data()
            raw["steps"][1]["depends_on"] = ["step-missing"]

            with self.assertRaisesRegex(ValueError, "quality gate"):
                manager.create_plan("session", raw)

            self.assertIsNone(manager.load_plan("session"))

    def test_rejected_new_plan_preserves_existing_active_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            bad = _plan_data()
            bad["title"] = "Broken Plan"
            bad["steps"][1]["depends_on"] = ["step-missing"]

            with self.assertRaises(ValueError):
                manager.create_plan("session", bad)

            self.assertEqual(manager.load_plan("session")["title"], "Build terrain scatter")

    def test_quality_gate_detects_dependency_cycle(self):
        normalized_plan = {
            "steps": [
                {"id": "step-1", "depends_on": ["step-2"], "status": "pending", "tools": [], "expected_result": "valid expected result"},
                {"id": "step-2", "depends_on": ["step-1"], "status": "pending", "tools": [], "expected_result": "valid expected result"},
            ],
            "phases": [],
            "architecture": {},
        }

        _, diagnostics = PlanQualityGate().evaluate(normalized_plan)

        self.assertIn("dependency_cycle", [d.code for d in diagnostics])


class PlanEvidenceTest(unittest.TestCase):
    def make_tab(self, manager):
        tab = PlanMixin()
        tab._session_id = "session"
        tab._agent_session_id = None
        tab._plan_manager = manager
        tab._updatePlanStep = mock.Mock()
        tab._restore_plan_projection = mock.Mock()
        tab._houdini_main_thread_executor = mock.Mock()
        tab._houdini_main_thread_executor.get_operation_status.return_value = None
        tab._read_operation_receipts = mock.Mock(return_value=[])
        return tab

    def test_status_is_required_and_blocked_needs_reason(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            tab = self.make_tab(manager)
            for kwargs in ({"step_id": "step-1"}, {"step_id": "step-1", "status": "blocked"}):
                self.assertFalse(tab._handle_update_plan_step(kwargs)["success"])
            result = tab._handle_update_plan_step({"step_id": "step-1", "status": "blocked", "result_summary": "Missing input"})
            self.assertTrue(result["success"])
            self.assertEqual(manager.load_plan("session")["status"], "blocked")
            with self.assertRaises(ValueError):
                manager.update_step("session", "step-1", "running")

    def test_foreign_or_missing_receipt_does_not_publish_update(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            tab = self.make_tab(manager)
            for receipt in (None, {"session_id": "other", "operation_id": "ref"}):
                tab._houdini_main_thread_executor.get_operation_status.return_value = receipt
                result = tab._handle_update_plan_step({"step_id": "step-1", "status": "running",
                                                       "evidence_refs": [{"kind": "operation_receipt", "ref": "ref"}]})
                self.assertFalse(result["success"])
                self.assertEqual(manager.load_plan("session")["steps"][0]["status"], "pending")
            tab._updatePlanStep.emit.assert_not_called()

    def test_receipt_is_reference_evidence_not_acceptance(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            manager.update_step("session", "step-1", "running")
            tab = self.make_tab(manager)
            tab._houdini_main_thread_executor.get_operation_status.return_value = {
                "session_id": "session", "operation_id": "ref", "tool_name": "create_nodes_batch",
                "state": "completed", "success": True, "thread_still_running": False, "scene_consistency": "known",
            }
            result = tab._handle_update_plan_step({"step_id": "step-1", "status": "done",
                                                   "evidence_refs": [{"kind": "operation_receipt", "ref": "ref"}]})
            self.assertTrue(result["success"])
            verification = manager.load_plan("session")["steps"][0]["verification"]
            self.assertEqual(verification["reference_check"], "verified")
            self.assertEqual(verification["acceptance"], "unverified")

    def test_unverified_legacy_completion_and_save_failure(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            manager.update_step("session", "step-1", "running")
            tab = self.make_tab(manager)
            with mock.patch.object(manager, "_save", side_effect=OSError("disk failed")):
                self.assertFalse(tab._handle_update_plan_step({"step_id": "step-1", "status": "done"})["success"])
            tab._updatePlanStep.emit.assert_not_called()
            self.assertEqual(manager.load_plan("session")["steps"][0]["status"], "running")
            result = tab._handle_update_plan_step({"step_id": "step-1", "status": "done"})
            self.assertTrue(result["success"])
            self.assertEqual(result["verification"], {"reference_check": "not_provided", "acceptance": "unverified"})
            self.assertIn("Acceptance unverified", manager.get_plan_for_context("session"))

    def test_result_reference_integrity_and_session_isolation(self):
        from houdini_agent.core.tool_result_store import ToolResultStore
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manager = PlanManager(root)
            manager.create_plan("session", _plan_data())
            tab = self.make_tab(manager)
            tab._cache_dir = root
            store = ToolResultStore(root, "session", threshold=1)
            archived = store.archive_if_large("inspect_node", {"success": True, "result": "observed"})
            references = [{"kind": "result", "ref": archived["result_ref"]}]
            evidence = tab._resolve_plan_evidence("session", references)
            self.assertEqual(evidence[0]["tool_name"], "inspect_node")
            self.assertEqual(evidence[0]["sha256"], archived["sha256"])
            with self.assertRaises(FileNotFoundError):
                tab._resolve_plan_evidence("other", references)
            document = json.loads(store._path(archived["result_ref"]).read_text(encoding="utf-8"))
            document["result"]["success"] = False
            store._path(archived["result_ref"]).write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                tab._resolve_plan_evidence("session", references)

    def test_running_failed_and_audited_receipts_are_not_acceptance(self):
        with TemporaryDirectory() as temp_dir:
            tab = self.make_tab(PlanManager(Path(temp_dir)))
            for state in ("running", "failed"):
                tab._read_operation_receipts.return_value = [{
                    "session_id": "session", "request_ref": "ref", "state": state, "success": False,
                }]
                evidence = tab._resolve_plan_evidence("session", [{"kind": "operation_receipt", "ref": "ref"}])
                self.assertEqual(evidence[0]["state"], state)
                self.assertNotIn("acceptance", evidence[0])

    def test_invalid_reference_shapes_do_not_update(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            tab = self.make_tab(manager)
            for references in (None, {}, [{}], [{"kind": "unknown", "ref": "a"}],
                               [{"kind": "result", "ref": "../other"}],
                               [{"kind": "result", "ref": "a", "success": True}]):
                with self.subTest(references=references):
                    result = tab._handle_update_plan_step({"step_id": "step-1", "status": "running", "evidence_refs": references})
                    self.assertFalse(result["success"])
            tab._updatePlanStep.emit.assert_not_called()
            self.assertEqual(manager.load_plan("session")["steps"][0]["status"], "pending")

    def test_cards_never_show_failed_plan_as_complete(self):
        from houdini_agent.ui.cursor_plan_widgets import PlanViewer, StreamingPlanCard, _plan_step_title
        for widget_class in (PlanViewer, StreamingPlanCard):
            widget = mock.Mock()
            widget._plan = {"status": "executing", "steps": [{"id": "s1", "status": "running"}]}
            widget._step_labels = {}
            widget_class.update_step_status(widget, "s1", "error", "Missing input")
            self.assertEqual(widget._plan["status"], "blocked")
            self.assertIn("blocked", widget_class._STATUS_ICONS)
            widget._badge_text_cache = None
            widget_class._refresh_ui(widget)
            widget._status_badge.setText.assert_called_with("BLOCKED")
        self.assertNotEqual(_plan_step_title({"title": "Task", "status": "done"}), "Task")

    def test_step_dag_preserves_independent_roots(self):
        from houdini_agent.ui.cursor_plan_widgets import PlanViewer
        dag = PlanViewer._build_step_dag([
            {"id": "s1", "title": "Inspect first", "depends_on": []},
            {"id": "s2", "title": "Inspect second", "depends_on": []},
        ])
        self.assertEqual(len(dag["nodes"]), 2)
        self.assertEqual(dag["connections"], [])


class PlanRuntimeTest(unittest.TestCase):
    def test_runtime_returns_ready_frontier_and_blocks_unmet_dependencies(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            plan = manager.load_plan("session")
            runtime = PlanRuntime()

            self.assertEqual([s["id"] for s in runtime.next_ready_steps(plan)], ["step-1"])
            allowed, reason = runtime.can_transition(plan, "step-2", "running")
            self.assertFalse(allowed)
            self.assertIn("unmet dependencies", reason)

            manager.update_step("session", "step-1", "running")
            plan = manager.update_step("session", "step-1", "done", "Base terrain exists")

            self.assertEqual([s["id"] for s in runtime.next_ready_steps(plan)], ["step-2"])

    def test_error_and_blocked_steps_never_complete_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            manager.create_plan("session", _plan_data())
            manager.update_step("session", "step-1", "running")
            plan = manager.update_step("session", "step-1", "error", "cook failed")

            self.assertEqual(plan["status"], "blocked")
            self.assertEqual([s["id"] for s in PlanRuntime().blocked_steps(plan)], ["step-2"])
            self.assertEqual(PlanRuntime().next_ready_steps(plan), [])


class PlanLifecycleTest(unittest.TestCase):
    def test_confirm_and_reject_persist_without_deleting_files(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("confirmed", _plan_data())
                manager.confirm_plan("confirmed")
                manager.create_plan("rejected", _plan_data())
                manager.reject_plan("rejected")

            self.assertEqual(manager.load_plan("confirmed")["status"], "confirmed")
            self.assertEqual(manager.load_plan("rejected")["status"], "rejected")
            self.assertTrue(manager._plan_path("rejected").exists())

    def test_save_failure_propagates_and_does_not_publish_transition(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("session", _plan_data())
            with mock.patch("houdini_agent.utils.plan_manager.os.replace", side_effect=PermissionError("occupied")):
                with self.assertRaises(PermissionError):
                    manager.confirm_plan("session")
            self.assertEqual(manager.load_plan("session")["status"], "draft")

    def test_archive_failure_preserves_old_active_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("session", _plan_data())
                replacement = _plan_data()
                replacement["title"] = "Replacement"
                with mock.patch.object(Path, "rename", side_effect=PermissionError("occupied")):
                    with self.assertRaises(PermissionError):
                        manager.create_plan("session", replacement)
            self.assertEqual(manager.load_plan("session")["title"], "Build terrain scatter")

    def test_new_plan_publish_failure_restores_old_active_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("session", _plan_data())
                replacement = _plan_data()
                replacement["title"] = "Replacement"
                original_replace = os.replace

                def fail_active_publish(source, target):
                    if Path(target) == manager._plan_path("session"):
                        raise PermissionError("occupied")
                    return original_replace(source, target)

                with mock.patch("houdini_agent.utils.plan_manager.os.replace", side_effect=fail_active_publish):
                    with self.assertRaises(PermissionError):
                        manager.create_plan("session", replacement)
            self.assertEqual(manager.load_plan("session")["title"], "Build terrain scatter")

    def test_old_plan_json_without_quality_or_new_fields_remains_readable(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            old_plan = {"title": "Legacy", "status": "draft", "steps": []}
            manager._plan_path("legacy").write_text(json.dumps(old_plan), encoding="utf-8")

            self.assertEqual(manager.load_plan("legacy"), old_plan)

    def test_quality_gate_uses_enabled_mode_and_runtime_registry_view(self):
        registry = ToolRegistry()
        schema = lambda name: {"type": "function", "function": {"name": name}}
        registry.register("good", schema("good"), modes={"plan_executing"}, runtime="houdini")
        registry.register("disabled", schema("disabled"), modes={"plan_executing"}, enabled=False)
        registry.register("wrong_mode", schema("wrong_mode"), modes={"ask"})

        self.assertEqual(registry.get_executable_tool_names("plan_executing", {"houdini"}), {"good"})
        _, diagnostics = PlanQualityGate(
            registry.get_executable_tool_names("plan_executing", {"houdini"})
        ).evaluate({
            "steps": [{
                "id": "step-1", "status": "pending", "depends_on": [],
                "tools": ["disabled", "wrong_mode"],
                "expected_result": "A verifiable expected result exists.",
            }],
        })
        self.assertIn("unavailable_tool", [d.code for d in diagnostics])

    def test_resume_does_not_auto_complete_running_step(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("session", _plan_data())
            manager.update_step("session", "step-1", "running")
            tab = type("PlanAdapter", (PlanMixin,), {})()
            tab._plan_manager = manager
            tab._session_id = "session"
            tab._plan_resume_count = 0
            tab._last_resume_done_count = -1

            message = tab._check_plan_resume()

            self.assertIn("计划尚未完成", message)
            self.assertEqual(manager.load_plan("session")["steps"][0]["status"], "running")

    def test_projection_is_derived_per_session_and_after_restart(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                manager.create_plan("a", _plan_data())
                manager.create_plan("b", _plan_data())
                manager.confirm_plan("b")

            tab = type("PlanAdapter", (PlanMixin,), {})()
            tab._plan_manager = manager
            tab._session_id = "a"
            self.assertEqual(tab._restore_plan_projection()["status"], "draft")
            self.assertEqual(tab._plan_phase, "awaiting_confirmation")
            tab._session_id = "b"
            tab._restore_plan_projection()
            self.assertEqual(tab._plan_phase, "executing")

            restarted = type("PlanAdapter", (PlanMixin,), {})()
            restarted._plan_manager = PlanManager(Path(temp_dir))
            restarted._session_id = "a"
            restarted._restore_plan_projection()
            self.assertEqual(restarted._plan_phase, "awaiting_confirmation")

    def test_restore_projection_is_idempotent_for_active_plan(self):
        with TemporaryDirectory() as temp_dir:
            manager = PlanManager(Path(temp_dir))
            with mock.patch.object(manager, "_quality_gate", return_value=PlanQualityGate()):
                plan = manager.create_plan("session", _plan_data())
                other_plan = manager.create_plan("other", _plan_data())

            render_signal = mock.Mock()
            tab = type("PlanAdapter", (PlanMixin,), {})()
            tab._plan_manager = manager
            tab._session_id = "session"
            tab._active_plan_viewer = mock.Mock()
            tab._projected_plan_key = ("session", plan["plan_id"])
            tab._renderPlanViewer = render_signal

            restored = tab._restore_plan_projection()

            self.assertEqual(restored["plan_id"], plan["plan_id"])
            self.assertEqual(tab._plan_phase, "awaiting_confirmation")
            render_signal.emit.assert_not_called()
            self.assertIsNotNone(tab._active_plan_viewer)

            tab._session_id = "other"
            tab._restore_plan_projection()

            render_signal.emit.assert_called_once_with(other_plan)


if __name__ == "__main__":
    unittest.main()