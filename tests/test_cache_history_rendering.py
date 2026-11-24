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


class _Widget:
    def __init__(self, value=None):
        self.value = value
        self.deleted = False
        self.visible = True
        self.text = ""

    def deleteLater(self):
        self.deleted = True

    def setVisible(self, visible):
        self.visible = visible

    def setText(self, text):
        self.text = text


class _Label(_Widget):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def setObjectName(self, name):
        pass

    def setStyleSheet(self, style):
        pass

    def setAlignment(self, alignment):
        pass


class _LayoutItem:
    def __init__(self, widget):
        self._widget = widget

    def widget(self):
        return self._widget


class _Layout:
    def __init__(self):
        self.widgets = [None]

    def count(self):
        return len(self.widgets)

    def takeAt(self, index):
        return _LayoutItem(self.widgets.pop(index))

    def insertWidget(self, index, widget):
        self.widgets.insert(index, widget)


class _Timeout:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _BatchTimer:
    def __init__(self, parent=None):
        self.timeout = _Timeout()
        self.started = []

    def setSingleShot(self, single_shot):
        pass

    def start(self, interval):
        self.started.append(interval)

    def stop(self):
        pass


class _Qt:
    AlignCenter = 0


class _HistoryHarness(HistoryRenderingMixin):
    def __init__(self, turn_count):
        self._conversation_history = [
            {"role": "user", "content": str(index)}
            for index in range(turn_count)
        ]
        self.chat_layout = _Layout()

    def _render_single_group(self, messages, si, ei):
        self.chat_layout.insertWidget(
            self.chat_layout.count() - 1,
            _Widget(int(messages[si]["content"])),
        )

    def values(self):
        return [
            widget.value for widget in self.chat_layout.widgets
            if widget is not None and widget.value is not None
        ]


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

    def test_thirty_turns_render_synchronously(self):
        harness = _HistoryHarness(30)

        harness._render_conversation_history()

        self.assertEqual(harness.values(), list(range(30)))
        self.assertFalse(hasattr(harness, "_batch_render_timer"))

    def test_thirty_one_turns_render_latest_thirty_then_schedule_one(self):
        harness = _HistoryHarness(31)

        with mock.patch(
                "houdini_agent.ui.history_rendering_mixin.QtCore.QTimer", _BatchTimer), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtCore.Qt", _Qt), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtWidgets.QLabel", _Label):
            harness._render_conversation_history()
            timer = harness._batch_render_timer

            self.assertEqual(harness.values(), list(range(1, 31)))
            self.assertEqual(harness._batch_cursor, 1)
            self.assertEqual(timer.started, [0])
            timer.timeout.callback()

        self.assertEqual(harness.values(), list(range(31)))
        self.assertIsNone(harness._batch_render_timer)
        self.assertIsNone(harness._batch_groups)

    def test_sixty_one_turns_render_in_batches_and_preserve_order(self):
        harness = _HistoryHarness(61)

        with mock.patch(
                "houdini_agent.ui.history_rendering_mixin.QtCore.QTimer", _BatchTimer), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtCore.Qt", _Qt), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtWidgets.QLabel", _Label):
            harness._render_conversation_history()
            timer = harness._batch_render_timer
            placeholder = harness._batch_placeholder

            self.assertEqual(harness.values(), list(range(31, 61)))
            self.assertEqual(harness._batch_cursor, 31)
            timer.timeout.callback()
            self.assertEqual(harness.values(), list(range(16, 61)))
            self.assertEqual(harness._batch_cursor, 16)
            timer.timeout.callback()
            timer.timeout.callback()

        self.assertEqual(harness.values(), list(range(61)))
        self.assertFalse(placeholder.visible)
        self.assertTrue(placeholder.deleted)
        self.assertIsNone(harness._batch_placeholder)

    def test_batch_yields_after_time_budget(self):
        harness = _HistoryHarness(61)

        with mock.patch(
                "houdini_agent.ui.history_rendering_mixin.QtCore.QTimer", _BatchTimer), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtCore.Qt", _Qt), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.QtWidgets.QLabel", _Label), \
                mock.patch(
                    "houdini_agent.ui.history_rendering_mixin.time.time",
                    side_effect=[0.0, 0.009]):
            harness._render_conversation_history()
            timer = harness._batch_render_timer
            timer.timeout.callback()

        self.assertEqual(harness.values(), [16] + list(range(31, 61)))
        self.assertEqual(harness._batch_cursor, 17)
        self.assertEqual(timer.started, [0, 0])


if __name__ == "__main__":
    unittest.main()