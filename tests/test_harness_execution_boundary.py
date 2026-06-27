# -*- coding: utf-8 -*-
"""Harness execution boundary tests."""

import unittest

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.harness_engine import HarnessToolPolicyEngine
from houdini_agent.ui.ai_tab import AITab


class _SignalStub:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class _ClientStub:
    def is_stop_requested(self):
        return False


class HarnessExecutionBoundaryTest(unittest.TestCase):
    def _make_tab(self):
        tab = object.__new__(AITab)
        tab.client = _ClientStub()
        tab._harness_v2_enabled = True
        tab._tool_policy_engine = HarnessToolPolicyEngine()
        tab._harness_state = None
        tab._plan_mode = False
        tab._agent_mode = False
        tab._plan_phase = "idle"
        tab._confirm_mode = False
        tab._policy_retry_limit = 2
        tab._append_policy_timeline = lambda *args, **kwargs: None
        tab._append_session_diagnostics_records = lambda *args, **kwargs: None
        tab._addStatus = _SignalStub()
        tab._execute_tool_impl = lambda *args, **kwargs: {"success": True, "result": "should not run"}
        return tab

    def test_model_supplied_policy_checked_flag_cannot_bypass_harness(self):
        tab = self._make_tab()

        result = AITab._execute_tool_with_todo(
            tab,
            "execute_python",
            code="print(1)",
            _harness_policy_checked=True,
        )

        self.assertFalse(result["success"])
        self.assertIn("Ask mode", result["error"])

    def test_model_supplied_skip_confirm_flag_is_discarded(self):
        tab = self._make_tab()
        tab._agent_mode = True
        tab._confirm_mode = True
        confirmations = []

        def request_confirmation(tool_name, args):
            confirmations.append((tool_name, args))
            return False

        tab._request_tool_confirmation = request_confirmation

        result = AITab._execute_tool_with_todo(
            tab,
            "execute_shell",
            command="dir",
            _harness_skip_confirm=True,
        )

        self.assertFalse(result["success"])
        self.assertEqual(confirmations[0][0], "execute_shell")


if __name__ == "__main__":
    unittest.main()
