# -*- coding: utf-8 -*-
"""Manual update mode prompt injection tests."""

import sys
import unittest
from unittest import mock

from tests.test_import_smoke import (
    _install_qt_stubs,
    _install_thirdparty_stubs,
)


class _UpdateMode:
    Auto = object()
    Manual = object()
    AlwaysUpdate = Auto


class _HouStub:
    updateMode = _UpdateMode

    def __init__(self, current_mode):
        self.current_mode = current_mode
        self.set_modes = []

    def updateModeSetting(self):
        return self.current_mode

    def setUpdateMode(self, mode):
        self.set_modes.append(mode)
        self.current_mode = mode


_install_thirdparty_stubs()
_install_qt_stubs()
sys.modules["hou"] = _HouStub(_UpdateMode.Auto)

from houdini_agent.ui.action_commands_mixin import ActionCommandsMixin
from houdini_agent.ui.ai_tab import AITab
from houdini_agent.ui.i18n import tr


class ManualUpdateModeDirectiveTest(unittest.TestCase):
    def _make_start_tab(self):
        tab = object.__new__(AITab)
        tab._pre_agent_update_mode = None
        tab._conversation_history = []
        tab._auto_read_mode = "off"
        tab._agent_mode = True
        tab._plan_mode = False
        tab._confirm_mode = True
        tab._current_provider = lambda: "mock-provider"
        tab._get_current_context_limit = lambda: 64000
        tab._collect_scene_context = lambda: {"source": "test"}
        tab._current_model_supports_vision = lambda: True
        tab._update_context_stats = lambda: None
        tab._set_running = lambda running: setattr(tab, "_running_value", running)
        tab._add_ai_response = lambda: setattr(tab, "_current_response", object())
        tab._start_active_aurora = lambda: setattr(tab, "_aurora_started", True)
        tab._save_model_preference = lambda: setattr(tab, "_saved_model_preference", True)
        tab.web_check = type("Check", (), {"isChecked": lambda self: True})()
        tab.think_check = type("Check", (), {"isChecked": lambda self: True})()
        tab.model_combo = type("Combo", (), {"currentText": lambda self: "mock-model"})()

        def fake_run_agent(agent_params):
            tab._captured_agent_params = agent_params

        tab._run_agent = fake_run_agent
        return tab

    def test_directive_does_not_fallback_to_realtime_manual_without_snapshot(self):
        sys.modules["hou"] = _HouStub(_UpdateMode.Manual)
        tab = object.__new__(AITab)
        tab._pre_agent_update_mode = None

        self.assertEqual(AITab._build_manual_mode_directive(tab), "")

    def test_directive_only_mentions_persistent_setting_for_snapshot_manual(self):
        sys.modules["hou"] = _HouStub(_UpdateMode.Auto)
        tab = object.__new__(AITab)
        tab._pre_agent_update_mode = _UpdateMode.Manual

        directive = AITab._build_manual_mode_directive(tab)

        self.assertIn("这是用户的持久设置", directive)
        self.assertIn("空几何", directive)
        self.assertIn("不能单独当作拓扑或参数错误证据", directive)

    def test_confirm_directive_forbids_switching_auto(self):
        sys.modules["hou"] = _HouStub(_UpdateMode.Auto)
        tab = object.__new__(AITab)
        tab._pre_agent_update_mode = _UpdateMode.Manual

        directive = AITab._build_manual_mode_directive(tab, confirm_mode=True)

        self.assertIn("不要擅自", directive)
        self.assertIn("Auto", directive)

    def test_direct_execute_prompt_allows_temporary_auto_validation(self):
        prompt = tr('ai.direct_execute_prompt')

        self.assertIn('set_update_mode(mode="auto")', prompt)
        self.assertIn("不要用 `execute_python`", prompt)
        self.assertIn("Auto Update", prompt)

    def test_scene_read_does_not_duplicate_manual_directive_in_history(self):
        sys.modules["hou"] = _HouStub(_UpdateMode.Auto)
        tab = object.__new__(ActionCommandsMixin)
        tab._pre_agent_update_mode = _UpdateMode.Manual
        tab._auto_read_mode = "off"
        tab._conversation_history = []

        ActionCommandsMixin._auto_inject_scene_read(tab)

        self.assertEqual(tab._conversation_history, [])

    def test_start_agent_run_captures_shared_params(self):
        sys.modules["hou"] = _HouStub(_UpdateMode.Auto)
        tab = self._make_start_tab()

        AITab._start_agent_run(tab, inject_scene=False)

        self.assertIs(tab._pre_agent_update_mode, _UpdateMode.Auto)
        self.assertTrue(tab._running_value)
        self.assertTrue(tab._aurora_started)
        self.assertEqual(tab._captured_agent_params["model"], "mock-model")
        self.assertTrue(tab._captured_agent_params["use_agent"])
        self.assertFalse(tab._captured_agent_params["plan_mode"])

    def test_plan_execution_uses_shared_start_overrides(self):
        hou_stub = _HouStub(_UpdateMode.Manual)
        sys.modules["hou"] = hou_stub
        tab = self._make_start_tab()
        tab._confirm_mode = False

        AITab._start_agent_run(tab, {
            "use_agent": True,
            "plan_mode": True,
            "plan_executing": True,
            "plan_data": {"title": "Test Plan"},
        }, inject_scene=False)

        params = tab._captured_agent_params
        self.assertTrue(params["plan_mode"])
        self.assertTrue(params["plan_executing"])
        self.assertFalse(params["confirm_mode"])
        self.assertEqual(params["plan_data"]["title"], "Test Plan")
        # Plan 直接执行不再擅自切 Auto；保持用户/Cook Guard 的原模式。
        self.assertEqual(hou_stub.set_modes, [])

    def test_set_update_mode_result_updates_restore_snapshot(self):
        hou_stub = _HouStub(_UpdateMode.Manual)
        sys.modules["hou"] = hou_stub
        tab = object.__new__(AITab)
        tab._pre_agent_update_mode = _UpdateMode.Manual

        AITab._after_tool_result(tab, "set_update_mode", {"success": True, "mode": "Auto"})
        AITab._restore_update_mode(tab)

        self.assertIs(tab._pre_agent_update_mode, None)
        self.assertEqual(hou_stub.set_modes, [])

    def test_plan_confirm_hands_off_to_agent_execution(self):
        tab = object.__new__(AITab)
        captured = {}

        class _PlanViewer:
            def __init__(self):
                self.confirmed = False

            def set_confirmed(self):
                self.confirmed = True

        tab._active_plan_viewer = _PlanViewer()
        tab._session_id = "session"
        tab._plan_manager = mock.Mock()
        tab._conversation_history = []
        tab._start_agent_run = lambda overrides, **kwargs: captured.update(overrides)
        plan_data = {"title": "Build Test Network", "steps": []}
        tab._plan_manager.confirm_plan.return_value = plan_data

        AITab._on_plan_confirmed(tab, plan_data)

        self.assertEqual(tab._plan_phase, "executing")
        self.assertTrue(tab._active_plan_viewer.confirmed)
        tab._plan_manager.confirm_plan.assert_called_once_with("session")
        self.assertEqual(len(tab._conversation_history), 1)
        self.assertIn("Build Test Network", tab._conversation_history[0]["content"])
        self.assertTrue(captured["use_agent"])
        self.assertTrue(captured["plan_mode"])
        self.assertTrue(captured["plan_executing"])
        self.assertIs(captured["plan_data"], plan_data)


if __name__ == "__main__":
    unittest.main()