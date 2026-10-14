# -*- coding: utf-8 -*-
"""Pure tests for network-learning skills."""

import unittest
from pathlib import Path

from houdini_agent import skills


def _entrypoint(name):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "learning" / name / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor)


compare_records = _entrypoint("compare_network_patterns").compare_records
explain_records = _entrypoint("explain_network_pattern").explain_records
find_repeated_patterns = _entrypoint("find_repeated_subgraphs").find_repeated_patterns


def _node(path, node_type, inputs=None, outputs=None, script="", comment=""):
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "type": node_type,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "key_parameters": [],
        "expression_count": 0,
        "script": script,
        "comment": comment,
        "network_boxes": [],
    }


class ExplainNetworkPatternTest(unittest.TestCase):
    def test_identifies_combine_script_and_output_roles(self):
        records = [
            _node("/a", "grid", outputs=["/merge"]),
            _node("/b", "sphere", outputs=["/merge"]),
            _node("/merge", "merge", ["/a", "/b"], ["/OUT"], script="@Cd=1;"),
            _node("/OUT", "null", ["/merge"]),
        ]

        result = explain_records(records, "example.hip")

        self.assertEqual(len(result["roles"]["source"]), 2)
        self.assertEqual(result["roles"]["combine"][0]["name"], "merge")
        self.assertEqual(result["roles"]["output"][0]["name"], "OUT")
        self.assertTrue(any("脚本" in insight for insight in result["insights"]))
        self.assertLessEqual(len(result["memory_draft"]), 2000)


class CompareNetworkPatternsTest(unittest.TestCase):
    def test_preserves_duplicate_common_node_types(self):
        first = [_node("/a1", "blast"), _node("/a2", "blast"), _node("/a3", "null")]
        second = [_node("/b1", "blast"), _node("/b2", "blast"), _node("/b3", "filecache")]

        result = compare_records(first, second)

        self.assertEqual(result["common_node_types"], ["blast", "blast"])
        self.assertEqual(result["only_first_types"], ["null"])
        self.assertEqual(result["only_second_types"], ["filecache"])


class FindRepeatedSubgraphsTest(unittest.TestCase):
    def test_matches_same_type_chain_with_different_names(self):
        records = [
            _node("/a1", "grid", outputs=["/a2"]),
            _node("/a2", "mountain", ["/a1"], ["/a3"]),
            _node("/a3", "normal", ["/a2"]),
            _node("/b1", "grid", outputs=["/b2"]),
            _node("/b2", "mountain", ["/b1"], ["/b3"]),
            _node("/b3", "normal", ["/b2"]),
        ]

        patterns = find_repeated_patterns(records, chain_length=3)

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["signature"], ["grid", "mountain", "normal"])
        self.assertEqual(patterns[0]["occurrences"], 2)


if __name__ == "__main__":
    unittest.main()