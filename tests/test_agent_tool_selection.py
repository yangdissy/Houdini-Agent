# -*- coding: utf-8 -*-
"""Agent-mode tool selection tests."""

import unittest

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.ai_tab import AITab
from houdini_agent.utils.ai_client import HOUDINI_TOOLS


def _tool_names(tools):
    return {t.get("function", {}).get("name", "") for t in tools}


class AgentToolSelectionTest(unittest.TestCase):
    def test_agent_mode_create_request_uses_intent_minimal_tools(self):
        tab = object.__new__(AITab)

        tools = AITab._select_agent_tools_for_message(
            tab,
            "帮我创建一个 box 节点并检查结果",
            use_web=False,
        )
        names = _tool_names(tools)

        self.assertLess(len(tools), len(HOUDINI_TOOLS))
        self.assertIn("create_node", names)
        self.assertIn("get_network_structure", names)
        self.assertIn("add_todo", names)
        self.assertNotIn("execute_shell", names)
        self.assertNotIn("save_hip", names)
        self.assertNotIn("web_search", names)
        self.assertNotIn("fetch_webpage", names)

    def test_agent_mode_code_request_adds_code_tools_without_full_exposure(self):
        tab = object.__new__(AITab)

        tools = AITab._select_agent_tools_for_message(
            tab,
            "运行一段 python 脚本检查当前场景",
            use_web=True,
        )
        names = _tool_names(tools)

        self.assertLess(len(tools), len(HOUDINI_TOOLS))
        self.assertIn("execute_python", names)
        self.assertIn("get_network_structure", names)
        self.assertNotIn("save_hip", names)

    def test_explicit_remember_request_exposes_write_tool(self):
        tab = object.__new__(AITab)

        tools = AITab._select_agent_tools_for_message(
            tab,
            "请记住始终使用中文回答",
            use_web=False,
        )
        names = _tool_names(tools)

        self.assertIn("remember_memory", names)
        self.assertIn("search_memory", names)

    def test_recall_request_does_not_expose_write_tool(self):
        tab = object.__new__(AITab)

        tools = AITab._select_agent_tools_for_message(
            tab,
            "你还记得我的偏好吗",
            use_web=False,
        )
        names = _tool_names(tools)

        self.assertIn("search_memory", names)
        self.assertNotIn("remember_memory", names)


if __name__ == "__main__":
    unittest.main()
