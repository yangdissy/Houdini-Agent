# -*- coding: utf-8 -*-
"""Tests for the pure analysis core of capture_network_memory."""

import unittest

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    skills.Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "learning"
    / "capture_network_memory" / "SKILL.md"
)
analyze_records = skills._load_descriptor_entrypoint(_DESCRIPTOR).analyze_records


class CaptureNetworkMemoryTest(unittest.TestCase):
    def test_prefers_connected_scripted_workflow(self):
        records = [
            {
                "path": "/obj/geo1/grid1", "name": "grid1", "type": "grid",
                "inputs": [], "outputs": ["/obj/geo1/wrangle1"],
                "key_parameters": ["sizex=10"], "expression_count": 0,
                "script": "", "comment": "", "network_boxes": [],
            },
            {
                "path": "/obj/geo1/wrangle1", "name": "wrangle1",
                "type": "attribwrangle", "inputs": ["/obj/geo1/grid1"],
                "outputs": ["/obj/geo1/OUT_EFFECT"],
                "key_parameters": ["class=point"], "expression_count": 0,
                "script": "@P.y += sin(@P.x);", "comment": "核心形变",
                "network_boxes": ["wave setup"],
            },
            {
                "path": "/obj/geo1/OUT_EFFECT", "name": "OUT_EFFECT",
                "type": "null", "inputs": ["/obj/geo1/wrangle1"],
                "outputs": [], "key_parameters": [], "expression_count": 0,
                "script": "", "comment": "", "network_boxes": [],
            },
            {
                "path": "/obj/geo1/unused", "name": "unused", "type": "null",
                "inputs": [], "outputs": [], "key_parameters": [],
                "expression_count": 0, "script": "", "comment": "",
                "network_boxes": [],
            },
        ]

        candidates = analyze_records(records, "wave.hip", max_nodes=10, candidate_count=1)

        self.assertEqual(candidates[0]["root_name"], "wrangle1")
        self.assertEqual(
            [node["name"] for node in candidates[0]["nodes"]],
            ["grid1", "wrangle1"],
        )
        self.assertIn("grid1 -> wrangle1", candidates[0]["connections"])
        self.assertIn("@P.y += sin", candidates[0]["memory_draft"])
        self.assertIn("来源 HIP: wave.hip", candidates[0]["memory_draft"])

    def test_draft_respects_explicit_memory_limit(self):
        records = [{
            "path": "/obj/geo1/wrangle1", "name": "wrangle1",
            "type": "attribwrangle", "inputs": [], "outputs": [],
            "key_parameters": ["value=" + "x" * 3000],
            "expression_count": 0, "script": "y" * 3000,
            "comment": "z" * 3000, "network_boxes": [],
        }]

        draft = analyze_records(records, "large.hip", candidate_count=1)[0]["memory_draft"]

        self.assertLessEqual(len(draft), 2000)


if __name__ == "__main__":
    unittest.main()