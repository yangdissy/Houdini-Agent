# -*- coding: utf-8 -*-
"""Houdini main-thread executor lifecycle tests."""

import queue
import sys
import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs


_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.houdini_main_thread_executor import HoudiniMainThreadExecutor
from houdini_agent.core.runtime_state_mixin import RuntimeStateMixin
from houdini_agent.core.tool_execution_mixin import ToolExecutionMixin


class _ClientStub:
    def __init__(self):
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True


class _AITabToolExecutionStub(RuntimeStateMixin, ToolExecutionMixin):
    def __init__(self, executor):
        self.client = _ClientStub()
        self._houdini_main_thread_executor = executor
        self._main_thread_busy = False
        self._thinking_timer = None
        self._glow_timer = None
        self.selection_watch_timer = None

    def _stop_selection_watch(self):
        self.selection_watch_timer = None


class _UpdateMode:
    Auto = object()
    Manual = object()


class _UndoStub:
    def __init__(self):
        self.events = []

    def beginGroup(self, name):
        self.events.append(("begin", name))

    def endGroup(self):
        self.events.append(("end", None))


class _HouStub:
    updateMode = _UpdateMode

    def __init__(self):
        self.current_mode = _UpdateMode.Auto
        self.set_modes = []
        self.undos = _UndoStub()

    def updateModeSetting(self):
        return self.current_mode

    def setUpdateMode(self, mode):
        self.set_modes.append(mode)
        self.current_mode = mode


class HoudiniMainThreadExecutorTest(unittest.TestCase):
    def test_timeout_blocks_later_execution(self):
        result_queue = queue.Queue()
        emitted = []
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: emitted.append((name, kwargs)),
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
        )

        first = executor.execute("cook_node", {"node_path": "/obj/geo1/OUT"})
        second = executor.execute("get_network_structure", {"node_path": "/obj"})

        self.assertFalse(first["success"])
        self.assertTrue(executor.is_blocked())
        self.assertFalse(second["success"])
        self.assertIn("阻塞", second["error"])
        self.assertEqual(len(emitted), 1)

    def test_shutdown_rejects_new_execution(self):
        result_queue = queue.Queue()
        emitted = []
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: emitted.append((name, kwargs)),
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
        )

        executor.shutdown()
        result = executor.execute("cook_node", {"node_path": "/obj/geo1/OUT"})

        self.assertFalse(result["success"])
        self.assertIn("已关闭", result["error"])
        self.assertEqual(emitted, [])

    def test_cleanup_shutdown_rejects_later_main_thread_execution(self):
        result_queue = queue.Queue()
        emitted = []
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: emitted.append((name, kwargs)),
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
        )
        tab = _AITabToolExecutionStub(executor)

        tab.cleanup()
        result = tab._execute_tool_in_main_thread("cook_node", {"node_path": "/obj/geo1/OUT"})

        self.assertTrue(tab.client.stop_requested)
        self.assertFalse(result["success"])
        self.assertIn("已关闭", result["error"])
        self.assertEqual(emitted, [])

    def test_main_thread_wrapper_applies_cook_guard_undo_and_refresh(self):
        old_hou = sys.modules.get("hou")
        hou_stub = _HouStub()
        sys.modules["hou"] = hou_stub
        try:
            result_queue = queue.Queue()
            executor = HoudiniMainThreadExecutor(
                emit_tool_request=lambda name, kwargs: None,
                emit_batch_request=lambda batch: None,
                result_queue=result_queue,
                main_timeout=0.01,
            )
            calls = []

            result = executor.run_in_main_thread(
                tool_name="set_node_parameter",
                kwargs={"node_path": "/obj/geo1/box1"},
                execute_tool=lambda name, kwargs: {"success": True, "result": name},
                cook_before_read=lambda: calls.append("cook"),
                snapshot_network_children=lambda: {"before": True},
                diff_network_children=lambda before, after: {"created": [{"path": "/obj/geo1/box1"}]},
                refresh_selection_baseline=lambda: calls.append("refresh"),
                self_tracking_tools=frozenset(),
                error_formatter=str,
            )

            self.assertTrue(result["success"])
            self.assertEqual(hou_stub.set_modes, [_UpdateMode.Manual])
            self.assertEqual(hou_stub.undos.events, [("begin", "AI Agent: set_node_parameter"), ("end", None)])
            self.assertEqual(result["_node_changes"], {"created": [{"path": "/obj/geo1/box1"}]})
            self.assertEqual(calls, ["refresh"])
        finally:
            if old_hou is None:
                sys.modules.pop("hou", None)
            else:
                sys.modules["hou"] = old_hou

    def test_execute_ignores_stale_result_envelope(self):
        result_queue = queue.Queue()
        emitted = []

        def emit_tool_request(name, kwargs):
            emitted.append((name, dict(kwargs)))
            if len(emitted) == 1:
                result_queue.put({"operation_id": 999, "result": {"success": True, "result": "stale"}})
                result_queue.put({"operation_id": kwargs["_ha_operation_id"], "result": {"success": True, "result": "fresh"}})

        executor = HoudiniMainThreadExecutor(
            emit_tool_request=emit_tool_request,
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
        )

        result = executor.execute("get_network_structure", {"node_path": "/obj"})

        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "fresh")
        self.assertIn("_ha_operation_id", emitted[0][1])

    def test_batch_execution_uses_operation_envelope(self):
        result_queue = queue.Queue()
        emitted = []

        def emit_batch_request(batch):
            emitted.append([(name, dict(kwargs)) for name, kwargs in batch])
            operation_id = batch[0][1]["_ha_operation_id"]
            result_queue.put({
                "operation_id": operation_id,
                "result": [{"success": True, "result": "batch-fresh"}],
            })

        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: None,
            emit_batch_request=emit_batch_request,
            result_queue=result_queue,
            batch_timeout=0.01,
        )

        results = executor.execute_batch([("get_network_structure", {"node_path": "/obj"})])

        self.assertEqual(results, [{"success": True, "result": "batch-fresh"}])
        self.assertIn("_ha_operation_id", emitted[0][0][1])


if __name__ == "__main__":
    unittest.main()