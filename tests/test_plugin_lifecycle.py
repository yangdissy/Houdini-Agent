# -*- coding: utf-8 -*-
"""Plugin registration lifecycle characterization tests."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from houdini_agent.utils import hooks
from houdini_agent.utils.tool_registry import ToolRegistry


class PluginLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = hooks.HookManager()
        self.manager.reset()
        hooks._loaded_plugins.clear()
        hooks._plugin_config.clear()
        hooks._pending_hooks.clear()
        hooks._pending_tools.clear()
        hooks._pending_buttons.clear()
        self.registry = ToolRegistry()
        self.registry_patch = mock.patch(
            "houdini_agent.utils.tool_registry.get_tool_registry",
            return_value=self.registry,
        )
        self.registry_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        hooks._loaded_plugins.clear()
        self.manager.reset()
        self.tmp.cleanup()

    def _write(self, body):
        path = Path(self.tmp.name) / "sample.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_partial_registration_failure_rolls_back_all_adapters(self):
        path = self._write(
            "from houdini_agent.utils.hooks import EVENT_AFTER_RESPONSE\n"
            "PLUGIN_INFO = {'name': 'partial', 'version': '1'}\n"
            "def register(ctx):\n"
            "    ctx.on(EVENT_AFTER_RESPONSE, lambda **kwargs: None)\n"
            "    ctx.register_button('X', 'test', lambda: None)\n"
            "    ctx.register_tool('partial_tool', 'test', {}, lambda args: {'success': True})\n"
            "    raise RuntimeError('boom')\n"
        )

        hooks._load_single_plugin(path, "sample", [], self.manager)

        self.assertFalse(hooks._loaded_plugins["partial"]["enabled"])
        self.assertFalse(self.registry.has_tool("partial_tool"))
        self.assertEqual(self.manager.get_buttons(), [])
        self.assertEqual(self.manager._hooks[hooks.EVENT_AFTER_RESPONSE], [])

    def test_decorators_return_after_disable_and_reenable(self):
        path = self._write(
            "from houdini_agent.utils.hooks import hook, tool, ui_button\n"
            "PLUGIN_INFO = {'name': 'decorated', 'version': '1'}\n"
            "@hook('on_after_response')\n"
            "def after(**kwargs): pass\n"
            "@tool('decorated_tool', 'test', {})\n"
            "def decorated_tool(args): return {'success': True}\n"
            "@ui_button('D', 'decorated')\n"
            "def button(): pass\n"
            "def register(ctx): pass\n"
        )
        hooks._load_single_plugin(path, "sample", [], self.manager)
        self.assertTrue(self.registry.has_tool("decorated_tool"))

        self.assertTrue(hooks.disable_plugin("decorated"))
        self.assertFalse(self.registry.has_tool("decorated_tool"))
        self.assertTrue(hooks.enable_plugin("decorated"))

        self.assertTrue(self.registry.has_tool("decorated_tool"))
        self.assertEqual(len(self.manager.get_buttons()), 1)
        self.assertEqual(len(self.manager._hooks[hooks.EVENT_AFTER_RESPONSE]), 1)

    def test_cleanup_is_scoped_to_plugin_owner(self):
        left = hooks.PluginContext("left", self.manager, {}, Path(self.tmp.name) / "config.json")
        right = hooks.PluginContext("right", self.manager, {}, Path(self.tmp.name) / "config.json")
        left.register_tool("left_tool", "left", {}, lambda args: {})
        right.register_tool("right_tool", "right", {}, lambda args: {})

        left._cleanup()

        self.assertFalse(self.registry.has_tool("left_tool"))
        self.assertTrue(self.registry.has_tool("right_tool"))


if __name__ == "__main__":
    unittest.main()
