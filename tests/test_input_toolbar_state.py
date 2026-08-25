# -*- coding: utf-8 -*-
"""Input toolbar state synchronization tests."""

import unittest
from pathlib import Path

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.ai_tab import AITab


class _Style:
    def unpolish(self, _widget):
        pass

    def polish(self, _widget):
        pass


class _Widget:
    def __init__(self):
        self.text = ""
        self.tooltip = ""
        self.visible = True
        self.properties = {}
        self._style = _Style()

    def setText(self, text):
        self.text = text

    def setToolTip(self, text):
        self.tooltip = text

    def setVisible(self, visible):
        self.visible = visible

    def setProperty(self, name, value):
        self.properties[name] = value

    def style(self):
        return self._style


class InputToolbarStateTest(unittest.TestCase):
    def _tab(self):
        tab = object.__new__(AITab)
        tab._agent_mode = False
        tab._plan_mode = False
        tab._confirm_mode = True
        tab._policy_failure_count = 0
        tab._policy_timeline_records = []
        tab._mode_guard_cache = {}
        tab.chk_confirm_mode = _Widget()
        tab.mode_guard_label = _Widget()
        tab.policy_timeline_btn = _Widget()
        tab.mode_combo = _Widget()
        tab.btn_send = _Widget()
        return tab

    def test_ask_hides_irrelevant_confirmation_and_shows_read_only(self):
        tab = self._tab()

        AITab._on_mode_changed(tab, 1)

        self.assertFalse(tab.chk_confirm_mode.visible)
        self.assertEqual(tab.mode_guard_label.text, "只读")
        self.assertEqual(tab.mode_guard_label.properties["risk"], "readonly")
        self.assertEqual(tab.policy_timeline_btn.text, "安全记录 0")

    def test_agent_confirmation_states_are_explicit(self):
        tab = self._tab()
        AITab._on_mode_changed(tab, 0)

        self.assertTrue(tab.chk_confirm_mode.visible)
        self.assertEqual(tab.mode_guard_label.text, "需确认")

        AITab._on_confirm_mode_toggled(tab, False)

        self.assertFalse(tab._confirm_mode)
        self.assertEqual(tab.chk_confirm_mode.text, "免逐步确认")
        self.assertEqual(tab.mode_guard_label.text, "高风险")
        self.assertEqual(tab.mode_guard_label.properties["risk"], "high")

    def test_safety_entry_prioritizes_attention_count(self):
        tab = self._tab()
        tab._policy_timeline_records = [{"action": "allow"}] * 12
        tab._policy_failure_count = 2

        AITab._refresh_mode_guard_ui(tab)

        self.assertEqual(tab.policy_timeline_btn.text, "2 项需关注")
        self.assertTrue(tab.policy_timeline_btn.properties["failures"])
        self.assertIn("操作确认", tab.policy_timeline_btn.tooltip)

    def test_context_menu_scope_and_export_location(self):
        root = Path(__file__).resolve().parents[1]
        input_area = (root / "houdini_agent/ui/input_area.py").read_text(encoding="utf-8")
        header = (root / "houdini_agent/ui/header.py").read_text(encoding="utf-8")

        menu_body = input_area.split("def _show_attach_menu", 1)[1].split(
            "def _on_confirm_mode_toggled", 1
        )[0]
        self.assertIn("context.attach_image", menu_body)
        self.assertIn("context.read_selection", menu_body)
        self.assertIn("context.read_network", menu_body)
        self.assertIn("context.auto_read", menu_body)
        self.assertNotIn("btn_export_train", menu_body)

        overflow_body = header.split("def _show_overflow_menu", 1)[1].split(
            "def _add_dev_feature_toggle_menu", 1
        )[0]
        self.assertIn("train.menu_label", overflow_body)
        self.assertIn("export_training_action.setEnabled(False)", overflow_body)
        self.assertNotIn("btn_export_train.click", overflow_body)
        self.assertIn('update_action = menu.addAction("Update")', overflow_body)
        self.assertIn("update_action.setEnabled(False)", overflow_body)
        self.assertNotIn('menu.addAction("Update", self.btn_update.click)', overflow_body)


if __name__ == "__main__":
    unittest.main()
