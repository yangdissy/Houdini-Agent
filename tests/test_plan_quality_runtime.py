# -*- coding: utf-8 -*-

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.plan_manager import PlanManager
from houdini_agent.utils.plan_runtime import PlanQualityGate, PlanRuntime


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


if __name__ == "__main__":
    unittest.main()