# -*- coding: utf-8 -*-
"""Pure tests for fragile-reference and network-contract skills."""

import unittest
from pathlib import Path

from houdini_agent import skills


def _entrypoint(name):
    descriptor = skills._parse_skill_markdown(
        Path(__file__).resolve().parents[1]
        / "houdini_agent" / "skills" / "learning" / name / "SKILL.md"
    )
    return skills._load_descriptor_entrypoint(descriptor)


_contract = _entrypoint("extract_network_contract")
build_contract = _contract.build_contract
infer_script_contract = _contract.infer_script_contract
analyze_reference_text = _entrypoint("find_fragile_references").analyze_reference_text


class FindFragileReferencesTest(unittest.TestCase):
    def test_classifies_paths_expressions_and_environment_dependencies(self):
        text = (
            'chs("../../CTRL/cache") '
            'point("/obj/source/OUT", 0, "P", 0); '
            'op:/obj/geo1/OUT $HIP/cache/test.$F4.bgeo.sc '
            'C:\\show\\cache\\result.bgeo.sc'
        )

        findings = analyze_reference_text(text, "expression")
        codes = {item["code"] for item in findings}

        self.assertIn("relative_node_reference", codes)
        self.assertIn("absolute_node_path", codes)
        self.assertIn("op_uri", codes)
        self.assertIn("cross_node_function", codes)
        self.assertIn("environment_path", codes)
        self.assertIn("windows_absolute_file", codes)
        self.assertTrue(all(item["source"] == "expression" for item in findings))

    def test_deduplicates_same_evidence_per_rule(self):
        findings = analyze_reference_text("$HIP/cache $HIP/cache")

        self.assertEqual(
            len([item for item in findings if item["code"] == "environment_path"]),
            1,
        )


class ExtractNetworkContractTest(unittest.TestCase):
    def test_infers_read_write_and_time_contract(self):
        result = infer_script_contract(
            "v@v = @N * f@speed; @Cd *= point(1, 'mask', @ptnum); i@frame = @Frame;"
        )

        self.assertEqual(result["written_attributes"], ["Cd", "frame", "v"])
        self.assertEqual(result["read_attributes"], ["Cd", "Frame", "N", "mask", "ptnum", "speed"])
        self.assertTrue(result["time_dependent"])

    def test_builds_boundary_and_removes_locally_produced_requirements(self):
        records = [
            {
                "path": "/geo/wrangle1", "type": "attribwrangle",
                "inputs": ["/external/SOURCE"], "outputs": ["/geo/wrangle2"],
                "min_inputs": 1, "scripts": ["f@mask = @Cd.r;"], "raw_values": [],
            },
            {
                "path": "/geo/wrangle2", "type": "attribwrangle",
                "inputs": ["/geo/wrangle1"], "outputs": [],
                "min_inputs": 1, "scripts": ["@P += @N * f@mask;"],
                "raw_values": ["$JOB/cache/result.bgeo.sc"],
            },
        ]

        contract = build_contract(records, "/geo/wrangle2")

        self.assertEqual(contract["required_attributes"], ["Cd", "N", "P"])
        self.assertEqual(contract["produced_attributes"], ["P", "mask"])
        self.assertEqual(contract["boundary_inputs"][0]["source"], "/external/SOURCE")
        self.assertEqual(contract["external_dependencies"][0]["code"], "environment_path")
        self.assertLessEqual(len(contract["memory_draft"]), 2000)


if __name__ == "__main__":
    unittest.main()