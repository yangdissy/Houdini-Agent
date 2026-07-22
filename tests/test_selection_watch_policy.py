# -*- coding: utf-8 -*-
"""Selection watch policy tests."""

import os
import sys
import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs


_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.runtime_state_mixin import RuntimeStateMixin


class _NodeStub:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _HouUiStub:
    def __init__(self):
        self.callbacks = []

    def addEventLoopCallback(self, callback):
        self.callbacks.append(callback)

    def removeEventLoopCallback(self, callback):
        self.callbacks.remove(callback)


class _HouStub:
    def __init__(self, selected_paths):
        self.ui = _HouUiStub()
        self.selected_paths = list(selected_paths)

    def selectedNodes(self):
        return [_NodeStub(path) for path in self.selected_paths]


class _ClientStub:
    def __init__(self):
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True


class _RuntimeStub(RuntimeStateMixin):
    def __init__(self):
        self.client = _ClientStub()
        self._is_running = True


class SelectionWatchPolicyTest(unittest.TestCase):
    def setUp(self):
        self._old_env = os.environ.get("HOUDINI_AGENT_SELECTION_WATCH")
        self._old_hou = sys.modules.get("hou")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("HOUDINI_AGENT_SELECTION_WATCH", None)
        else:
            os.environ["HOUDINI_AGENT_SELECTION_WATCH"] = self._old_env
        if self._old_hou is None:
            sys.modules.pop("hou", None)
        else:
            sys.modules["hou"] = self._old_hou

    def test_selection_watch_is_disabled_by_default(self):
        os.environ.pop("HOUDINI_AGENT_SELECTION_WATCH", None)
        hou_stub = _HouStub(["/obj/geo1/start"])
        sys.modules["hou"] = hou_stub
        runtime = _RuntimeStub()

        runtime._start_selection_watch()
        hou_stub.selected_paths = ["/obj/geo1/changed"]
        runtime._on_selection_poll()

        self.assertFalse(runtime.client.stop_requested)
        self.assertIsNone(runtime._selection_watch_cb)
        self.assertEqual(hou_stub.ui.callbacks, [])

    def test_selection_change_stops_agent_when_enabled(self):
        os.environ["HOUDINI_AGENT_SELECTION_WATCH"] = "true"
        hou_stub = _HouStub(["/obj/geo1/start"])
        sys.modules["hou"] = hou_stub
        runtime = _RuntimeStub()

        runtime._start_selection_watch()
        runtime._selection_settle_until = 0.0
        hou_stub.selected_paths = ["/obj/geo1/changed"]
        runtime._on_selection_poll()

        self.assertTrue(runtime.client.stop_requested)
        self.assertTrue(runtime._selection_stop_triggered)
        self.assertEqual(len(hou_stub.ui.callbacks), 1)

    def test_selection_watch_env_false_disables_auto_stop(self):
        os.environ["HOUDINI_AGENT_SELECTION_WATCH"] = "false"
        hou_stub = _HouStub(["/obj/geo1/start"])
        sys.modules["hou"] = hou_stub
        runtime = _RuntimeStub()

        runtime._start_selection_watch()
        hou_stub.selected_paths = ["/obj/geo1/changed"]
        runtime._on_selection_poll()

        self.assertFalse(runtime.client.stop_requested)
        self.assertIsNone(runtime._selection_watch_cb)
        self.assertEqual(hou_stub.ui.callbacks, [])


if __name__ == "__main__":
    unittest.main()