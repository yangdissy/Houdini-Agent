# -*- coding: utf-8 -*-
"""Tests for Houdini node tidy-layout pure algorithm."""

import unittest
import importlib.util
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOU_CORE_PATH = _REPO_ROOT / "houdini_agent" / "utils" / "mcp" / "hou_core.py"
_spec = importlib.util.spec_from_file_location("hou_core_for_layout_test", str(_HOU_CORE_PATH))
_hou_core = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_hou_core)
_compute_tidy_layout = _hou_core._compute_tidy_layout
plan_node_layout = _hou_core.plan_node_layout


class TidyLayoutTests(unittest.TestCase):
    def test_layout_plan_normalizes_compatible_methods(self):
        node_ids = ["source", "output"]
        edges = [("source", "output", 0)]
        original = {"source": (10.0, 10.0), "output": (10.0, 8.0)}

        tidy = plan_node_layout(node_ids, edges, original, method="tidy")
        columns = plan_node_layout(node_ids, edges, original, method="columns")

        self.assertEqual(tidy["method"], "tidy")
        self.assertEqual(columns["method"], "tidy")
        self.assertEqual(columns["positions"], tidy["positions"])

    def test_layout_plan_preserves_pins_and_avoids_fixed_obstacles(self):
        plan = plan_node_layout(
            ["source", "output"],
            [("source", "output", 0)],
            {"source": (0.0, 2.0), "output": (0.0, 0.0)},
            method="tidy",
            pinned_node_ids={"output"},
            obstacles=[{"id": "existing", "x": 0.0, "y": 2.0, "width": 4.0, "height": 1.5}],
        )

        self.assertEqual(plan["positions"]["output"], (0.0, 0.0))
        self.assertGreaterEqual(abs(plan["positions"]["source"][0]), 4.0)

    def test_layout_plan_reports_before_and_after_quality_metrics(self):
        plan = plan_node_layout(
            ["left", "right", "left_out", "right_out"],
            [("left", "right_out", 0), ("right", "left_out", 0)],
            {
                "left": (-3.0, 2.0), "right": (3.0, 2.0),
                "left_out": (-3.0, 0.0), "right_out": (3.0, 0.0),
            },
            method="tidy",
        )

        self.assertEqual(plan["metrics_before"]["crossing_count"], 1)
        self.assertLessEqual(
            plan["metrics_after"]["crossing_count"],
            plan["metrics_before"]["crossing_count"],
        )
        self.assertGreater(plan["metrics_after"]["total_movement"], 0.0)
        self.assertIn("overlap_count", plan["metrics_after"])
        self.assertIn("total_wire_length", plan["metrics_after"])

    def test_chain_stays_vertical(self):
        positions = _compute_tidy_layout(
            ["box", "scatter", "attrib", "copy"],
            [("box", "scatter", 0), ("scatter", "attrib", 0), ("attrib", "copy", 1)],
        )

        self.assertAlmostEqual(positions["box"][0], positions["scatter"][0], places=6)
        self.assertAlmostEqual(positions["scatter"][0], positions["attrib"][0], places=6)
        self.assertGreater(positions["box"][1], positions["scatter"][1])
        self.assertGreater(positions["scatter"][1], positions["attrib"][1])
        self.assertGreater(positions["attrib"][1], positions["copy"][1])

    def test_two_input_join_splits_parents(self):
        positions = _compute_tidy_layout(
            ["shape", "points", "copy"],
            [("shape", "copy", 0), ("points", "copy", 1)],
        )

        self.assertLess(positions["shape"][0], positions["copy"][0])
        self.assertGreater(positions["points"][0], positions["copy"][0])
        self.assertGreater(positions["shape"][1], positions["copy"][1])
        self.assertGreater(positions["points"][1], positions["copy"][1])

    def test_isolated_nodes_are_placed_aside(self):
        positions = _compute_tidy_layout(
            ["a", "b", "lonely"],
            [("a", "b", 0)],
        )

        self.assertGreater(positions["lonely"][0], positions["a"][0])
        self.assertGreater(positions["lonely"][0], positions["b"][0])

    def test_cycles_do_not_crash(self):
        positions = _compute_tidy_layout(
            ["a", "b", "c"],
            [("a", "b", 0), ("b", "c", 0), ("c", "a", 0)],
        )

        self.assertEqual(set(positions), {"a", "b", "c"})
        for x_value, y_value in positions.values():
            self.assertIsInstance(x_value, float)
            self.assertIsInstance(y_value, float)

    def test_original_center_is_preserved_for_created_batch(self):
        positions = _compute_tidy_layout(
            ["shape", "points", "copy"],
            [("shape", "copy", 0), ("points", "copy", 1)],
            original_positions={"shape": (10.0, 5.0), "points": (10.0, 5.0), "copy": (10.0, 5.0)},
        )

        center_x = sum(pos[0] for pos in positions.values()) / len(positions)
        center_y = sum(pos[1] for pos in positions.values()) / len(positions)
        self.assertAlmostEqual(center_x, 10.0, places=6)
        self.assertAlmostEqual(center_y, 5.0, places=6)

    def test_anchor_position_overrides_original_center(self):
        positions = _compute_tidy_layout(
            ["shape", "points", "copy"],
            [("shape", "copy", 0), ("points", "copy", 1)],
            original_positions={"shape": (-100.0, -20.0), "points": (-100.0, -20.0), "copy": (-100.0, -20.0)},
            anchor_position=(25.0, 12.0),
        )

        center_x = sum(pos[0] for pos in positions.values()) / len(positions)
        center_y = sum(pos[1] for pos in positions.values()) / len(positions)
        self.assertAlmostEqual(center_x, 25.0, places=6)
        self.assertAlmostEqual(center_y, 12.0, places=6)


if __name__ == "__main__":
    unittest.main()