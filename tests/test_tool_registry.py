# -*- coding: utf-8 -*-
"""ToolRegistry 单元测试（不依赖 Houdini hou）。"""

import unittest

from houdini_agent.utils.tool_registry import (
    ToolRegistry,
    _infer_modes,
    _infer_tags,
    _infer_concurrency_safe,
    _infer_risk_level,
)


def _schema(name, description="desc"):
    """构造一个最小 OpenAI function-calling schema。"""
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": {}},
    }


class InferHelpersTest(unittest.TestCase):
    def test_readonly_tool_modes(self):
        modes = _infer_modes("get_network_structure")
        # 只读查询工具应在全部四种模式可用
        self.assertEqual(
            modes, {"agent", "plan_executing", "ask", "plan_planning"}
        )

    def test_mutating_tool_modes(self):
        modes = _infer_modes("create_node")
        # 写操作工具不应出现在 ask 模式
        self.assertIn("agent", modes)
        self.assertIn("plan_executing", modes)
        self.assertNotIn("ask", modes)

    def test_planning_only_tool(self):
        # create_plan 在规划阶段白名单但不在 ask 白名单
        modes = _infer_modes("create_plan")
        self.assertIn("plan_planning", modes)
        self.assertNotIn("ask", modes)

    def test_tags_readonly_and_network(self):
        tags = _infer_tags("get_node_parameters")
        self.assertIn("readonly", tags)
        self.assertIn("network", tags)

    def test_tags_system(self):
        self.assertIn("system", _infer_tags("execute_shell"))

    def test_tags_docs_and_async(self):
        tags = _infer_tags("web_search")
        self.assertIn("docs", tags)
        self.assertIn("async", tags)

    def test_concurrency_safe(self):
        self.assertTrue(_infer_concurrency_safe("web_search"))
        self.assertTrue(_infer_concurrency_safe("get_network_structure"))
        self.assertFalse(_infer_concurrency_safe("create_node"))

    def test_risk_level(self):
        self.assertEqual(_infer_risk_level("execute_shell"), "high")
        self.assertEqual(_infer_risk_level("execute_python"), "high")
        self.assertEqual(_infer_risk_level("delete_node"), "high")
        self.assertEqual(_infer_risk_level("get_network_structure"), "low")
        self.assertEqual(_infer_risk_level("create_node"), "normal")


class RegisterAndQueryTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()

    def test_register_and_has_tool(self):
        self.reg.register("foo", _schema("foo"), modes={"agent"})
        self.assertTrue(self.reg.has_tool("foo"))
        self.assertFalse(self.reg.has_tool("missing"))

    def test_get_tools_for_mode_filters_by_mode(self):
        self.reg.register("a", _schema("a"), modes={"agent"})
        self.reg.register("b", _schema("b"), modes={"ask"})
        agent_names = [s["function"]["name"] for s in self.reg.get_tools_for_mode("agent")]
        ask_names = [s["function"]["name"] for s in self.reg.get_tools_for_mode("ask")]
        self.assertEqual(agent_names, ["a"])
        self.assertEqual(ask_names, ["b"])

    def test_disabled_tool_hidden_from_mode_list(self):
        self.reg.register("a", _schema("a"), modes={"agent"})
        self.reg.set_enabled("a", False)
        self.assertEqual(self.reg.get_tools_for_mode("agent"), [])

    def test_get_tool_schemas_by_names(self):
        self.reg.register("a", _schema("a"), modes={"agent"})
        self.reg.register("b", _schema("b"), modes={"agent"})
        schemas = self.reg.get_tool_schemas(["b"])
        self.assertEqual([s["function"]["name"] for s in schemas], ["b"])

    def test_unregister(self):
        self.reg.register("a", _schema("a"), modes={"agent"})
        self.reg.unregister("a")
        self.assertFalse(self.reg.has_tool("a"))

    def test_unregister_by_source(self):
        self.reg.register("a", _schema("a"), source="plugin", plugin_name="p1")
        self.reg.register("b", _schema("b"), source="plugin", plugin_name="p2")
        self.reg.register("c", _schema("c"), source="core")
        self.reg.unregister_by_source("plugin", "p1")
        self.assertFalse(self.reg.has_tool("a"))
        self.assertTrue(self.reg.has_tool("b"))
        self.assertTrue(self.reg.has_tool("c"))


class EnableDisableTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register("a", _schema("a"), modes={"agent"})

    def test_set_enabled_toggle(self):
        self.assertTrue(self.reg.is_enabled("a"))
        self.reg.set_enabled("a", False)
        self.assertFalse(self.reg.is_enabled("a"))
        self.assertIn("a", self.reg.get_disabled_tools())
        self.reg.set_enabled("a", True)
        self.assertTrue(self.reg.is_enabled("a"))
        self.assertNotIn("a", self.reg.get_disabled_tools())

    def test_is_enabled_unknown_tool(self):
        self.assertFalse(self.reg.is_enabled("missing"))

    def test_load_disabled_from_config(self):
        self.reg.register("b", _schema("b"), modes={"agent"})
        self.reg.load_disabled_from_config(["a"])
        self.assertFalse(self.reg.is_enabled("a"))
        self.assertTrue(self.reg.is_enabled("b"))

    def test_register_respects_existing_disabled_set(self):
        # 预先标记 z 为禁用，之后注册时应保持禁用
        self.reg.load_disabled_from_config(["z"])
        self.reg.register("z", _schema("z"), modes={"agent"}, enabled=True)
        self.assertFalse(self.reg.is_enabled("z"))


class ExecuteTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()

    def test_execute_unregistered(self):
        out = self.reg.execute("nope", {})
        self.assertFalse(out["success"])
        self.assertIn("未注册", out["error"])

    def test_execute_no_handler(self):
        self.reg.register("a", _schema("a"), handler=None, modes={"agent"})
        out = self.reg.execute("a", {})
        self.assertFalse(out["success"])
        self.assertIn("无 handler", out["error"])

    def test_execute_disabled(self):
        self.reg.register("a", _schema("a"), handler=lambda args: {"success": True}, modes={"agent"})
        self.reg.set_enabled("a", False)
        out = self.reg.execute("a", {})
        self.assertFalse(out["success"])
        self.assertIn("已禁用", out["error"])

    def test_execute_success(self):
        self.reg.register(
            "echo", _schema("echo"),
            handler=lambda args: {"success": True, "result": args.get("v")},
            modes={"agent"},
        )
        out = self.reg.execute("echo", {"v": 42})
        self.assertTrue(out["success"])
        self.assertEqual(out["result"], 42)

    def test_execute_handler_raises(self):
        def boom(args):
            raise ValueError("kaboom")

        self.reg.register("boom", _schema("boom"), handler=boom, modes={"agent"})
        out = self.reg.execute("boom", {})
        self.assertFalse(out["success"])
        self.assertIn("kaboom", out["error"])


class IntentTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()

    def test_classify_intent_chinese(self):
        intents = self.reg.classify_intent("帮我创建一个 box 节点")
        self.assertIn("create", intents)

    def test_classify_intent_english(self):
        intents = self.reg.classify_intent("search the web for VEX docs")
        self.assertIn("search", intents)

    def test_classify_intent_empty(self):
        self.assertEqual(self.reg.classify_intent(""), set())

    def test_get_tools_for_intent_includes_base_groups(self):
        # 注册 query 基础工具与 create 工具
        self.reg.register("get_network_structure", _schema("get_network_structure"),
                          modes={"agent"})
        self.reg.register("create_node", _schema("create_node"), modes={"agent"})
        # 意图为空也应包含 query 基础组
        names = {s["function"]["name"] for s in self.reg.get_tools_for_intent(set(), "agent")}
        self.assertIn("get_network_structure", names)
        self.assertNotIn("create_node", names)
        # 带 create 意图后应包含 create_node
        names2 = {s["function"]["name"] for s in self.reg.get_tools_for_intent({"create"}, "agent")}
        self.assertIn("create_node", names2)


class ModeAllowanceTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register("ro", _schema("ro"), modes={"agent", "ask"})
        self.reg.register("rw", _schema("rw"), modes={"agent"})

    def test_is_tool_allowed_in_mode(self):
        self.assertTrue(self.reg.is_tool_allowed_in_mode("ro", "ask"))
        self.assertFalse(self.reg.is_tool_allowed_in_mode("rw", "ask"))

    def test_is_tool_allowed_unknown(self):
        self.assertFalse(self.reg.is_tool_allowed_in_mode("missing", "agent"))


class StreamingProfileTest(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()

    def test_readonly_network_tool_classification(self):
        # 只读 + network → dedup / batch_readonly / cache_invalidate
        self.reg.register(
            "get_node_parameters", _schema("get_node_parameters"),
            tags={"readonly", "network"}, modes={"agent"},
        )
        prof = self.reg.build_streaming_executor_profile()
        self.assertIn("get_node_parameters", prof["dedup_tools"])
        self.assertIn("get_node_parameters", prof["batch_readonly_tools"])
        self.assertIn("get_node_parameters", prof["cache_invalidate_tools"])

    def test_mutating_network_tool_classification(self):
        self.reg.register(
            "create_node", _schema("create_node"),
            tags={"network"}, modes={"agent"},
        )
        prof = self.reg.build_streaming_executor_profile()
        self.assertIn("create_node", prof["network_mutating_tools"])
        self.assertNotIn("create_node", prof["dedup_tools"])

    def test_async_tool_not_in_dedup(self):
        self.reg.register(
            "web_search", _schema("web_search"),
            tags={"readonly", "async", "docs"}, modes={"agent"},
        )
        prof = self.reg.build_streaming_executor_profile()
        self.assertIn("web_search", prof["async_tools"])
        self.assertNotIn("web_search", prof["dedup_tools"])

    def test_disabled_tool_excluded_from_profile(self):
        self.reg.register(
            "get_node_parameters", _schema("get_node_parameters"),
            tags={"readonly", "network"}, modes={"agent"},
        )
        self.reg.set_enabled("get_node_parameters", False)
        prof = self.reg.build_streaming_executor_profile()
        self.assertNotIn("get_node_parameters", prof["dedup_tools"])


class RegisterCoreToolsTest(unittest.TestCase):
    def test_register_core_tools_infers_metadata(self):
        reg = ToolRegistry()
        tools = [
            _schema("get_network_structure"),
            _schema("execute_shell"),
            _schema("create_node"),
            {"function": {}},  # 无名工具应被跳过
        ]
        reg.register_core_tools(tools)
        self.assertTrue(reg.initialized)
        self.assertTrue(reg.has_tool("get_network_structure"))
        self.assertTrue(reg.has_tool("execute_shell"))
        # ask 模式仅含只读工具
        ask_names = {s["function"]["name"] for s in reg.get_tools_for_mode("ask")}
        self.assertIn("get_network_structure", ask_names)
        self.assertNotIn("execute_shell", ask_names)
        self.assertNotIn("create_node", ask_names)


if __name__ == "__main__":
    unittest.main()
