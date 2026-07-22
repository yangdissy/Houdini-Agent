# -*- coding: utf-8 -*-
"""Development feature toggle tests."""

import os
import unittest

from houdini_agent.utils.dev_feature_toggles import (
    DEV_FEATURE_TOGGLES,
    is_dev_reload_enabled,
    is_toggle_enabled,
    parse_env_bool,
    set_toggle_enabled,
)


class DevFeatureTogglesTest(unittest.TestCase):
    def setUp(self):
        self._old_env = {toggle.env_name: os.environ.get(toggle.env_name) for toggle in DEV_FEATURE_TOGGLES}
        self._old_dev_reload = os.environ.get("HOUDINI_AGENT_DEV_RELOAD")

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if self._old_dev_reload is None:
            os.environ.pop("HOUDINI_AGENT_DEV_RELOAD", None)
        else:
            os.environ["HOUDINI_AGENT_DEV_RELOAD"] = self._old_dev_reload

    def test_parse_env_bool_accepts_common_values(self):
        self.assertTrue(parse_env_bool("1"))
        self.assertTrue(parse_env_bool("true"))
        self.assertFalse(parse_env_bool("0", default=True))
        self.assertFalse(parse_env_bool("off", default=True))
        self.assertTrue(parse_env_bool("", default=True))

    def test_dev_reload_gate_uses_environment(self):
        os.environ["HOUDINI_AGENT_DEV_RELOAD"] = "1"
        self.assertTrue(is_dev_reload_enabled())
        os.environ["HOUDINI_AGENT_DEV_RELOAD"] = "false"
        self.assertFalse(is_dev_reload_enabled())

    def test_set_toggle_enabled_changes_environment_value(self):
        toggle = next(t for t in DEV_FEATURE_TOGGLES if t.env_name == "HOUDINI_AGENT_SELECTION_WATCH")

        set_toggle_enabled(toggle, False)
        self.assertFalse(is_toggle_enabled(toggle))
        self.assertEqual(os.environ[toggle.env_name], "0")

        set_toggle_enabled(toggle, True)
        self.assertTrue(is_toggle_enabled(toggle))
        self.assertEqual(os.environ[toggle.env_name], "1")


if __name__ == "__main__":
    unittest.main()