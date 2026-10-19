# -*- coding: utf-8 -*-
"""Runtime contract tests for the Agent result verification Skill."""

import unittest

from houdini_agent import skills


class VerifyAgentResultSkillTest(unittest.TestCase):
    def test_runtime_discovers_instructions_only_verification_skill(self):
        skills.reload_skills()

        found = {item["name"] for item in skills.list_skills(category="workflow")}
        instructions = skills.get_skill_instructions("verify_agent_result")
        result = skills.run_skill("verify_agent_result", {
            "review_type": "geometry",
            "target_path": "/obj/geo1/OUT",
            "visual_goal": "No visible holes or intersections",
            "width": 1280,
            "height": 720,
        })

        self.assertIn("verify_agent_result", found)
        self.assertFalse(instructions["executable"])
        self.assertTrue(result["instructions_only"])
        self.assertIn("visual_review", result["instructions"])
        self.assertIn("Task completion is the trigger", result["instructions"])
        self.assertIn("at most once per user task", result["instructions"])
        self.assertIn("temporary_auto_validate_geometry", result["instructions"])
        self.assertIn("current mode is Auto and freshness is established, do not call it", result["instructions"])
        self.assertIn("Do not use persistent `set_update_mode`", result["instructions"])
        self.assertIn("stale viewport", result["instructions"])
        self.assertIn("Fail closed", result["instructions"])
        self.assertIn("technical_facts", result["instructions"])


if __name__ == "__main__":
    unittest.main()