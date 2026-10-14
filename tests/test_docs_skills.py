# -*- coding: utf-8 -*-
"""Tests for structured documentation skills."""

import unittest
from pathlib import Path
from unittest import mock

from houdini_agent import skills


def _entrypoint(name):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "docs" / name / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor)


check_example_compatibility = _entrypoint("check_example_compatibility")
compare_houdini_nodes = _entrypoint("compare_houdini_nodes")
explain_houdini_error = _entrypoint("explain_houdini_error")
explain_node_parameters = _entrypoint("explain_node_parameters")
find_node_for_task = _entrypoint("find_node_for_task")
lookup_attribute_semantics = _entrypoint("lookup_attribute_semantics")
lookup_copernicus_reference = _entrypoint("lookup_copernicus_reference")
lookup_expression_reference = _entrypoint("lookup_expression_reference")
lookup_vex_reference = _entrypoint("lookup_vex_reference")


class DocsSkillsTest(unittest.TestCase):
    def test_lookup_vex_reference_requires_query(self):
        self.assertEqual(lookup_vex_reference.run()["error"], "'query' is required.")

    def test_lookup_vex_reference_combines_manual_and_snippet_evidence(self):
        manual_hit = {
            "title": "pcfind",
            "path": "vex/functions/pcfind.txt",
            "context": "vex",
            "internal": "pcfind",
            "description": "Finds points in a point cloud.",
            "sections": {"arguments": "geometry, position, radius, maxpoints"},
        }
        with mock.patch.object(lookup_vex_reference, "search_help", return_value=[manual_hit]), mock.patch.object(
            lookup_vex_reference,
            "read_reference",
            return_value="## Point cloud\nUse pcfind to find nearby points.",
        ):
            result = lookup_vex_reference.run("pcfind")

        self.assertEqual(result["evidence_count"], 2)
        self.assertEqual(result["manual_hits"][0]["internal"], "pcfind")
        self.assertEqual(result["snippet_hits"][0]["title"], "Point cloud")

    def test_lookup_vex_reference_finds_deferred_attribute_write_trap(self):
        with mock.patch.object(lookup_vex_reference, "search_help", return_value=[]):
            result = lookup_vex_reference.run("setpointattrib")

        self.assertGreater(result["evidence_count"], 0)
        self.assertTrue(
            any("可见性" in hit["title"] for hit in result["snippet_hits"])
        )

    def test_lookup_copernicus_reference_exposes_opencl_production_traps(self):
        with mock.patch.object(lookup_copernicus_reference, "search_help", return_value=[]):
            writeback = lookup_copernicus_reference.run("@WRITEBACK")
            coordinates = lookup_copernicus_reference.run("@IX @IY")
            capture = lookup_copernicus_reference.run("rop_image")

        self.assertTrue(writeback["reference_hits"])
        self.assertTrue(coordinates["reference_hits"])
        self.assertTrue(capture["reference_hits"])

    def test_explain_node_parameters_filters_for_goal(self):
        hit = {
            "title": "File Cache",
            "path": "nodes/sop/filecache.txt",
            "context": "sop",
            "internal": "filecache",
            "description": "Caches geometry to disk.",
            "sections": {
                "parameters": "File Path:\n    Output path.\n\nLoad from Disk:\n    Read cached geometry."
            },
        }
        with mock.patch.object(explain_node_parameters, "search_help", return_value=[hit]):
            result = explain_node_parameters.run("filecache", goal="load")

        evidence = result["matches"][0]["parameter_evidence"]
        self.assertIn("Load from Disk", evidence)
        self.assertNotIn("File Path", evidence)

    def test_find_node_for_task_filters_context(self):
        hits = [
            {"title": "SOP Scatter", "path": "nodes/sop/scatter.txt", "context": "sop"},
            {"title": "LOP Scatter", "path": "nodes/lop/scatter.txt", "context": "lop"},
        ]
        with mock.patch.object(find_node_for_task, "search_help", return_value=hits):
            result = find_node_for_task.run("scatter points", context="sop")

        self.assertEqual([item["title"] for item in result["candidates"]], ["SOP Scatter"])

    def test_compare_houdini_nodes_preserves_missing_candidates(self):
        first_hit = {
            "title": "Copy to Points",
            "path": "nodes/sop/copytopoints.txt",
            "context": "sop",
            "sections": {"inputs": "Geometry and target points."},
        }
        with mock.patch.object(
            compare_houdini_nodes, "search_help", side_effect=[[first_hit], []]
        ):
            result = compare_houdini_nodes.run(["copytopoints", "missing"])

        self.assertTrue(result["comparison"][0]["found"])
        self.assertFalse(result["comparison"][1]["found"])

    def test_explain_houdini_error_removes_generic_error_words(self):
        with mock.patch.object(explain_houdini_error, "search_help", return_value=[]) as search:
            result = explain_houdini_error.run("Error: Undefined function pcfind")

        search.assert_called_once_with("Undefined function pcfind", top_k=8)
        self.assertEqual(result["evidence_count"], 0)

    def test_lookup_attribute_semantics_normalizes_at_prefix(self):
        with mock.patch.object(lookup_attribute_semantics, "read_reference", return_value="## Orientation\n@orient vector4"), mock.patch.object(
            lookup_attribute_semantics, "search_help", return_value=[]
        ):
            result = lookup_attribute_semantics.run("@orient")

        self.assertEqual(result["attribute"], "orient")
        self.assertEqual(result["reference_hits"][0]["title"], "Orientation")

    def test_lookup_expression_reference_combines_sources(self):
        manual_hit = {"title": "Channel references", "path": "expressions/ch.txt"}
        with mock.patch.object(lookup_expression_reference, "read_reference", return_value="## Channels\nUse ch() for floats."), mock.patch.object(
            lookup_expression_reference, "search_help", return_value=[manual_hit]
        ):
            result = lookup_expression_reference.run("ch")

        self.assertEqual(result["evidence_count"], 2)

    def test_check_example_compatibility_reports_undocumented_calls(self):
        documented_hit = {"title": "pcfind", "path": "vex/functions/pcfind.txt"}
        with mock.patch.object(
            check_example_compatibility,
            "search_help",
            side_effect=lambda identifier, **kwargs: [documented_hit] if identifier == "pcfind" else [],
        ):
            result = check_example_compatibility.run("int pts[] = pcfind(0, \"P\", @P, 1, 10); mystery();")

        self.assertFalse(result["compatible"])
        self.assertEqual(result["undocumented_identifiers"], ["mystery"])


if __name__ == "__main__":
    unittest.main()