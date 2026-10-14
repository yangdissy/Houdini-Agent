# -*- coding: utf-8 -*-
"""Pure tests for memory progression skills."""

import unittest
from pathlib import Path

from houdini_agent import skills


def _entrypoint(name):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "learning" / name / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor)


build_report = _entrypoint("build_hip_learning_report").build_report
compare_snapshots = _entrypoint("compare_before_after_network").compare_snapshots
generalize_memory = _entrypoint("generalize_network_memory").generalize_memory
rank_memories = _entrypoint("recall_workflow_for_task").rank_memories
suggest_cleanup = _entrypoint("suggest_memory_cleanup").suggest_cleanup
validate_claims = _entrypoint("validate_memory_against_scene").validate_claims


class GeneralizeNetworkMemoryTest(unittest.TestCase):
    def test_removes_concrete_names_and_preserves_contract(self):
        result = generalize_memory(
            "来源 demo.hip，/obj/geo1/wrangle17 生成 mask。",
            {"required_attributes": ["Cd"], "boundary_inputs": [{"source": "a"}]},
        )

        self.assertNotIn("demo.hip", result["memory_draft"])
        self.assertNotIn("/obj/geo1", result["memory_draft"])
        self.assertIn("输入应提供属性: Cd", result["memory_draft"])
        self.assertLessEqual(len(result["memory_draft"]), 2000)


class ValidateMemoryAgainstSceneTest(unittest.TestCase):
    def test_reports_confirmed_contradicted_and_unknown(self):
        result = validate_claims(
            "节点 /obj/geo1/OUT (null)，参数 group，输出 @Cd 和 @missing。",
            {
                "paths": ["/obj/geo1/OUT"], "types": ["null"],
                "parameters": ["group"], "attributes": ["Cd"],
                "geometry_checked": False,
            },
        )

        statuses = {(item["kind"], item["value"]): item["status"] for item in result["claims"]}
        self.assertEqual(statuses[("node_path", "/obj/geo1/OUT")], "confirmed")
        self.assertEqual(statuses[("node_type", "null")], "confirmed")
        self.assertEqual(statuses[("attribute", "missing")], "unknown")


class RecallWorkflowForTaskTest(unittest.TestCase):
    def test_ranks_task_and_scene_match_first(self):
        ranked = rank_memories(
            "制作 vellum 布料撕裂",
            [
                {"id": "a", "rule": "使用 vellumconstraints 配置布料撕裂", "score": 0.8},
                {"id": "b", "rule": "使用 boolean 制作硬表面切割", "score": 0.9},
            ],
            ["vellumconstraints"],
        )

        self.assertEqual(ranked[0]["id"], "a")
        self.assertIn("vellumconstraints", ranked[0]["matching_node_types"])


class CompareBeforeAfterNetworkTest(unittest.TestCase):
    def test_reports_added_and_resolved_errors(self):
        before = {"scene": {"path": "/obj", "children": [
            {"path": "/obj/old", "type": "null", "has_errors": True, "has_warnings": False},
        ]}}
        after = {"scene": {"path": "/obj", "children": [
            {"path": "/obj/old", "type": "null", "has_errors": False, "has_warnings": False},
            {"path": "/obj/new", "type": "box", "has_errors": False, "has_warnings": False},
        ]}}

        result = compare_snapshots(before, after)

        self.assertEqual(result["added_nodes"], ["/obj/new"])
        self.assertEqual(len(result["resolved_issues"]), 1)
        self.assertEqual(result["introduced_issues"], [])


class BuildHipLearningReportTest(unittest.TestCase):
    def test_aggregates_existing_analysis(self):
        result = build_report("demo.hip", {
            "capture_network_memory": {"candidates": [{"root_path": "/OUT", "score": 8, "memory_draft": "draft"}]},
            "find_repeated_subgraphs": {"patterns": [{"signature": ["grid", "normal"]}]},
            "find_fragile_references": {"finding_count": 2, "affected_nodes": 1},
            "extract_network_contract": {"required_attributes": ["N"], "memory_draft": "contract"},
        })

        self.assertIn("demo.hip", result["report"])
        self.assertEqual(result["memory_candidates"], ["draft", "contract"])
        self.assertEqual(len(result["assetization_candidates"]), 1)


class SuggestMemoryCleanupTest(unittest.TestCase):
    def test_suggests_duplicate_generalization_and_low_value_review(self):
        suggestions = suggest_cleanup([
            {"id": "a", "rule": "/obj/geo1/wrangle17 使用 mask", "confidence": 0.3, "activation_count": 0},
            {"id": "b", "rule": "/obj/geo1/wrangle18 使用 mask", "confidence": 0.9, "activation_count": 2},
        ], duplicate_threshold=0.75)
        actions = {item["action"] for item in suggestions}

        self.assertIn("generalize", actions)
        self.assertIn("review_low_value", actions)
        self.assertIn("merge_duplicates", actions)


if __name__ == "__main__":
    unittest.main()