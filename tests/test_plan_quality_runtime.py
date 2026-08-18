# -*- coding: utf-8 -*-

import unittest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

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


class PlanQualityGateTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()