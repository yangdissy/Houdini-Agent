# -*- coding: utf-8 -*-
"""Skill metadata and import contract tests."""

import importlib
import unittest


NEW_SKILL_MODULES = (
    "houdini_agent.skills.inspect_scene_context",
    "houdini_agent.skills.analyze_groups",
    "houdini_agent.skills.inspect_material_assignments",
    "houdini_agent.skills.inspect_lop_stage",
    "houdini_agent.skills.validate_network_contract",
    "houdini_agent.skills.cache_node_report",
)


class SkillMetadataTest(unittest.TestCase):
    def test_new_skills_import_without_hou(self):
        for module_name in NEW_SKILL_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                self.assertTrue(callable(module.run))

    def test_new_skills_have_valid_metadata(self):
        for module_name in NEW_SKILL_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                info = module.SKILL_INFO
                self.assertTrue(info["name"].strip())
                self.assertTrue(info["description"].strip())
                self.assertIsInstance(info.get("parameters", {}), dict)
                for param_name, param_def in info.get("parameters", {}).items():
                    self.assertTrue(param_name.strip())
                    self.assertIn("type", param_def)
                    self.assertIn("description", param_def)


if __name__ == "__main__":
    unittest.main()