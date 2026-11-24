# -*- coding: utf-8 -*-
"""Translation dictionary completeness tests."""

import unittest

from tests.test_import_smoke import _install_qt_stubs


_install_qt_stubs()

from houdini_agent.ui.i18n import _EN, _ZH


class I18nTest(unittest.TestCase):
    def test_language_dictionaries_have_identical_keys(self):
        self.assertEqual(set(_ZH), set(_EN))

    def test_user_menu_keys_have_nonempty_translations(self):
        prefixes = (
            "header.menu.", "cache.menu.", "optimize.menu.", "diagnostics.menu.",
        )
        keys = [key for key in _ZH if key.startswith(prefixes)]
        self.assertTrue(keys)
        for key in keys:
            self.assertTrue(_ZH[key].strip(), key)
            self.assertTrue(_EN[key].strip(), key)


if __name__ == "__main__":
    unittest.main()