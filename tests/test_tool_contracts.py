# -*- coding: utf-8 -*-
"""Tool schema and policy contract tests."""

import unittest
import sys
from unittest import mock

from houdini_agent.core.harness_policy_config import CONFIRM_TOOLS, HIGH_RISK_TOOLS

for name in ("requests", "trafilatura"):
    if name not in sys.modules:
        sys.modules[name] = mock.MagicMock(name=name)

from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.tool_registry import ToolRegistry


class CoreToolContractTest(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register_core_tools(HOUDINI_TOOLS)

    def test_tool_schema_names_match_registry_names(self):
        for meta in self.registry._tools.values():
            with self.subTest(tool=meta.name):
                self.assertEqual(meta.schema.get("type"), "function")
                self.assertEqual(meta.schema.get("function", {}).get("name"), meta.name)

    def test_all_core_tools_have_descriptions(self):
        for meta in self.registry._tools.values():
            with self.subTest(tool=meta.name):
                description = meta.schema.get("function", {}).get("description", "")
                self.assertTrue(description.strip())

    def test_ask_mode_contains_only_readonly_core_tools(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        for name in ask_names:
            with self.subTest(tool=name):
                tags = self.registry._tools[name].tags
                self.assertTrue("readonly" in tags or "task" in tags)

    def test_high_risk_core_tools_require_confirmation(self):
        core_names = set(self.registry._tools)
        for name in HIGH_RISK_TOOLS & core_names:
            with self.subTest(tool=name):
                self.assertIn(name, CONFIRM_TOOLS)
                self.assertEqual(self.registry._tools[name].risk_level, "high")

    def test_mutating_confirm_tools_do_not_leak_into_ask_mode(self):
        ask_names = {
            schema["function"]["name"]
            for schema in self.registry.get_tools_for_mode("ask")
        }
        self.assertFalse(CONFIRM_TOOLS & ask_names)


if __name__ == "__main__":
    unittest.main()