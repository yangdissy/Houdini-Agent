# -*- coding: utf-8 -*-
"""Cache history rendering adapter tests."""

import sys
import unittest
from unittest import mock

from tests.test_import_smoke import (
    _install_hou_stub,
    _install_qt_stubs,
    _install_thirdparty_stubs,
)

_install_hou_stub()
_install_thirdparty_stubs()
_install_qt_stubs()
sys.modules.setdefault("numpy", mock.MagicMock(name="numpy"))

from houdini_agent.ui.history_rendering_mixin import HistoryRenderingMixin


class _Response:
    def __init__(self):
        self.shell_widgets = []
        self.system_shell_widgets = []

    def add_shell_widget(self, widget):
        self.shell_widgets.append(widget)

    def add_sys_shell_widget(self, widget):
        self.system_shell_widgets.append(widget)


class CacheHistoryRenderingTest(unittest.TestCase):
    def test_restore_shell_widgets_recreates_python_and_system_shells(self):
        response = _Response()
        msg = {
            'python_shells': [{
                'code': 'print(1)',
                'output': '输出:\n1\n执行时间: 0.25s',
                'error': '',
                'success': True,
            }],
            'system_shells': [{
                'command': 'echo hi',
                'output': '--- stdout ---\nhi\n退出码: 7, 耗时: 0.50s',
                'error': 'warn',
                'success': False,
                'cwd': 'C:/work/project',
            }],
        }

        with mock.patch('houdini_agent.ui.history_rendering_mixin.PythonShellWidget') as py_widget, \
                mock.patch('houdini_agent.ui.history_rendering_mixin.SystemShellWidget') as sys_widget:
            py_widget.side_effect = lambda **kwargs: ('python', kwargs)
            sys_widget.side_effect = lambda **kwargs: ('system', kwargs)

            HistoryRenderingMixin._restore_shell_widgets(object.__new__(HistoryRenderingMixin), response, msg)

        self.assertEqual(len(response.shell_widgets), 1)
        self.assertEqual(response.shell_widgets[0][1]['code'], 'print(1)')
        self.assertEqual(response.shell_widgets[0][1]['output'], '1')
        self.assertEqual(response.shell_widgets[0][1]['exec_time'], 0.25)
        self.assertTrue(response.shell_widgets[0][1]['success'])

        self.assertEqual(len(response.system_shell_widgets), 1)
        self.assertEqual(response.system_shell_widgets[0][1]['command'], 'echo hi')
        self.assertEqual(response.system_shell_widgets[0][1]['output'], 'hi')
        self.assertEqual(response.system_shell_widgets[0][1]['error'], 'warn')
        self.assertEqual(response.system_shell_widgets[0][1]['exit_code'], 7)
        self.assertEqual(response.system_shell_widgets[0][1]['exec_time'], 0.50)
        self.assertFalse(response.system_shell_widgets[0][1]['success'])
        self.assertEqual(response.system_shell_widgets[0][1]['cwd'], 'C:/work/project')


if __name__ == "__main__":
    unittest.main()