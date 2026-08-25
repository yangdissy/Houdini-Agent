# -*- coding: utf-8 -*-
"""Rules editor path display tests."""

import unittest

from shared.user_paths import UserPaths
from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()


class RulesEditorPathTest(unittest.TestCase):
    def test_ui_rule_displays_its_storage_path(self):
        from houdini_agent.ui.cursor_rules_editor_dialog import _rule_source_text

        expected = str(UserPaths("yangdi").user_rules_path())

        self.assertEqual(_rule_source_text({"source": "ui"}, "yangdi"), expected)

    def test_file_rule_displays_its_file_path(self):
        from houdini_agent.ui.cursor_rules_editor_dialog import _rule_source_text

        self.assertEqual(
            _rule_source_text({"source": "file", "file_path": r"U:\rules\main.md"}, "yangdi"),
            r"U:\rules\main.md",
        )


if __name__ == "__main__":
    unittest.main()