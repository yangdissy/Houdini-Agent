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


class TidyLayoutTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()