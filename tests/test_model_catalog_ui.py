# -*- coding: utf-8 -*-
"""Focused tests for model catalog UI result handling."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.header import HeaderMixin


class _Combo:
    def __init__(self, items, current=0):
        self.items = list(items)
        self.current = current
        self.blocked = False

    def currentText(self):
        return self.items[self.current] if self.items else ""

    def blockSignals(self, value):
        self.blocked = value

    def clear(self):
        self.items = []
        self.current = -1

    def addItems(self, items):
        self.items.extend(items)
        if self.current < 0 and self.items:
            self.current = 0

    def findText(self, value):
        try:
            return self.items.index(value)
        except ValueError:
            return -1

    def setCurrentIndex(self, index):
        self.current = index

    def setEditable(self, _):
        pass


class _Button:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = value

    def setVisible(self, _):
        pass


class ModelCatalogUiTest(unittest.TestCase):
    def make_tab(self):
        tab = object.__new__(HeaderMixin)
        tab.model_combo = _Combo(["old", "keep"], 1)
        tab._model_map = {"deepseek": ["old", "keep"]}
        tab._model_catalog_refreshing = True
        tab.btn_refresh_models = _Button()
        tab.btn_custom_config = _Button()
        tab._current_provider = lambda: "deepseek"
        tab._model_catalog_api_key = lambda provider: "key"
        return tab

    def test_success_preserves_valid_selection(self):
        tab = self.make_tab()
        HeaderMixin._on_model_catalog_finished(tab, "deepseek", ["new", "keep"])
        self.assertEqual(tab.model_combo.items, ["new", "keep"])
        self.assertEqual(tab.model_combo.currentText(), "keep")
        self.assertFalse(tab._model_catalog_refreshing)

    def test_empty_failure_result_does_not_clear_models(self):
        tab = self.make_tab()
        HeaderMixin._on_model_catalog_finished(tab, "deepseek", [])
        self.assertEqual(tab.model_combo.items, ["old", "keep"])

    def test_refresh_is_reentry_safe(self):
        tab = self.make_tab()
        with patch("threading.Thread") as thread:
            HeaderMixin._refresh_model_catalog_async(tab)
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
