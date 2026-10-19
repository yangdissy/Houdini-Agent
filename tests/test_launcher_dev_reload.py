# -*- coding: utf-8 -*-
"""Development launcher reload tests."""

import importlib
import os
import sys
import types
import unittest
from unittest import mock

import houdini_agent_launcher


class LauncherDevReloadTest(unittest.TestCase):
    def test_dev_launch_clears_all_package_modules_and_disables_nested_reload(self):
        saved_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "houdini_agent" or name.startswith("houdini_agent.")
        }
        stale_module = types.ModuleType("houdini_agent.core.send_orchestrator_mixin")
        sys.modules[stale_module.__name__] = stale_module
        observed_reload_values = []

        fake_main = types.ModuleType("houdini_agent.main")

        def show_tool():
            observed_reload_values.append(os.environ.get("HOUDINI_AGENT_DEV_RELOAD"))
            return "window"

        fake_main.show_tool = show_tool

        def fake_register(package_name, package_dir):
            package = types.ModuleType(package_name)
            package.__path__ = [package_dir]
            package.__package__ = package_name
            sys.modules[package_name] = package
            return package

        real_module_from_spec = importlib.util.module_from_spec

        def fake_module_from_spec(spec):
            if spec.name == "houdini_agent.main":
                return fake_main
            return real_module_from_spec(spec)

        old_reload = os.environ.get("HOUDINI_AGENT_DEV_RELOAD")
        os.environ["HOUDINI_AGENT_DEV_RELOAD"] = "1"
        stale_module_was_cleared = False
        try:
            with mock.patch.object(
                houdini_agent_launcher, "_is_dev_reload_enabled", return_value=True
            ), mock.patch.object(
                importlib.util, "module_from_spec", side_effect=fake_module_from_spec
            ), mock.patch.object(
                houdini_agent_launcher.importlib.util, "spec_from_file_location"
            ) as spec_from_file:
                package_spec = mock.Mock()
                package_spec.loader.exec_module.side_effect = lambda module: None
                main_spec = mock.Mock(name="main_spec")
                main_spec.name = "houdini_agent.main"
                main_spec.loader.exec_module.side_effect = lambda module: None
                spec_from_file.side_effect = [package_spec, package_spec, package_spec, main_spec]

                with mock.patch.dict(
                    houdini_agent_launcher.__dict__, {"_register_pkg": fake_register}, clear=False
                ):
                    result = houdini_agent_launcher.launch_houdini_agent()
                    stale_module_was_cleared = (
                        sys.modules.get(stale_module.__name__) is not stale_module
                    )
        finally:
            if old_reload is None:
                os.environ.pop("HOUDINI_AGENT_DEV_RELOAD", None)
            else:
                os.environ["HOUDINI_AGENT_DEV_RELOAD"] = old_reload
            for name in list(sys.modules):
                if name == "houdini_agent" or name.startswith("houdini_agent."):
                    sys.modules.pop(name, None)
            sys.modules.update(saved_modules)

        self.assertEqual("window", result)
        self.assertTrue(stale_module_was_cleared)
        self.assertEqual(["0"], observed_reload_values)


if __name__ == "__main__":
    unittest.main()