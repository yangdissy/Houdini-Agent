# -*- coding: utf-8 -*-
"""Houdini main-thread executor lifecycle tests."""

import queue
import sys
import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs


_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.houdini_main_thread_executor import HoudiniMainThreadExecutor, OPERATION_ID_KEY
from houdini_agent.core.runtime_state_mixin import RuntimeStateMixin
from houdini_agent.core.tool_execution_mixin import ToolExecutionMixin


class _ClientStub:
    def __init__(self):
        self.stop_requested = False

    def request_stop(self):
        self.stop_requested = True

    def is_stop_requested(self):
        return self.stop_requested


class _SignalStub:
    def __init__(self):
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class _AITabToolExecutionStub(RuntimeStateMixin, ToolExecutionMixin):

    def __init__(self, executor):
        self.client = _ClientStub()
        self._houdini_main_thread_executor = executor
        self._main_thread_busy = False
        self._agent_mode = True
        self._plan_mode = False
        self._plan_phase = "idle"
        self._confirm_mode = False
        self._thinking_timer = None
        self._glow_timer = None
        self.selection_watch_timer = None
        self._showToolStatus = _SignalStub()
        self._hideToolStatus = _SignalStub()

    def _stop_selection_watch(self):
        self.selection_watch_timer = None

    def _request_tool_confirmation(self, tool_name, kwargs):
        return True


class _McpRecorder:
    def __init__(self):
        self.calls = []

    def execute_tool(self, tool_name, kwargs):
        self.calls.append((tool_name, dict(kwargs)))
        return {"success": True, "tool": tool_name, "kwargs": dict(kwargs)}


class _BatchSlotStub(ToolExecutionMixin):
    def __init__(self, executor):
        self._houdini_main_thread_executor = executor
        self._tool_result_queue = queue.Queue()
        self.mcp = _McpRecorder()
        self.cook_count = 0
        self.refresh_count = 0

    def _cook_displayed_nodes_if_manual(self):
        self.cook_count += 1

    def _refresh_selection_baseline(self):
        self.refresh_count += 1


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
    def test_success_result_includes_completed_operation_receipt(self):
        result_queue = queue.Queue()
        events = []

        def emit_tool_request(name, kwargs):
            result_queue.put({
                "operation_id": kwargs[OPERATION_ID_KEY],
                "result": {"success": True, "result": name},
            })

        executor = HoudiniMainThreadExecutor(
            emit_tool_request=emit_tool_request,
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            record_event=events.append,
            session_id_provider=lambda: "session-a",
            identity_provider=lambda: {
                "executor_id": "executor-a",
                "houdini_version": "21.0.440",
                "scene_id": "scene-a",
                "hip_path": "/projects/a.hip",
            },
        )

        result = executor.execute("get_network_structure", {"node_path": "/obj/private-value"})

        receipt = result["operation_receipt"]
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["protocol_version"], 1)
        self.assertEqual(receipt["request_ref"], receipt["operation_id"])
        self.assertEqual(receipt["session_id"], "session-a")
        self.assertEqual(receipt["executor_id"], "executor-a")
        self.assertEqual(receipt["houdini_version"], "21.0.440")
        self.assertEqual(receipt["scene_id"], "scene-a")
        self.assertEqual(len(receipt["arguments_sha256"]), 64)
        self.assertIn("contract_version", receipt)
        self.assertTrue(receipt["result_available"])
        self.assertNotIn("/obj/private-value", repr(events))
        receipt_events = [event for event in events if event.get("event_type") == "operation_receipt"]
        self.assertEqual([event["state"] for event in receipt_events], ["accepted", "running", "completed"])

    def test_timeout_receipt_is_queryable_and_late_result_completes_it(self):
        result_queue = queue.Queue()
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: None,
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
            session_id_provider=lambda: "session-a",
        )

        result = executor.execute("cook_node", {"node_path": "/obj/geo1/OUT"})
        public_id = result["operation_receipt"]["operation_id"]
        timed_out = executor.get_operation_status(public_id)
        correlation_id = executor._active_operation_id

        self.assertEqual(timed_out["state"], "running")
        self.assertEqual(timed_out["wait_status"], "timed_out")
        executor.attach_result(correlation_id, {"success": True, "result": "late"})
        completed = executor.get_operation_status(public_id)
        self.assertEqual(completed["state"], "completed")
        self.assertTrue(completed["result_available"])

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
        self.assertTrue(first["thread_still_running"])
        self.assertEqual(first["scene_consistency"], "unknown")
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

    def test_executor_records_timeout_guard_shutdown_and_stale_events(self):
        result_queue = queue.Queue()
        events = []
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: None,
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
            record_event=events.append,
        )

        timeout_result = executor.execute("cook_node", {"node_path": "/obj/geo1/OUT", "secret": "do-not-log"})
        guard_result = executor.execute("get_network_structure", {"node_path": "/obj"})
        executor.shutdown()

        self.assertFalse(timeout_result["success"])
        self.assertTrue(timeout_result["thread_still_running"])
        self.assertEqual(timeout_result["scene_consistency"], "unknown")
        self.assertFalse(guard_result["success"])
        event_types = [event.get("event_type") for event in events]
        self.assertIn("main_thread_execute_start", event_types)
        self.assertIn("main_thread_execute_timeout", event_types)
        self.assertIn("main_thread_executor_guard", event_types)
        self.assertIn("main_thread_executor_shutdown", event_types)
        event_text = repr(events)
        self.assertIn("args_keys", event_text)
        self.assertNotIn("do-not-log", event_text)
        timeout_event = next(event for event in events if event.get("event_type") == "main_thread_execute_timeout")
        self.assertTrue(timeout_event["thread_still_running"])
        self.assertEqual(timeout_event["scene_consistency"], "unknown")

    def test_executor_records_stale_result_without_payload(self):
        result_queue = queue.Queue()
        events = []

        def emit_tool_request(name, kwargs):
            result_queue.put({"operation_id": 999, "result": {"success": True, "result": "payload-secret"}})
            result_queue.put({"operation_id": kwargs[OPERATION_ID_KEY], "result": {"success": True, "result": "fresh"}})

        executor = HoudiniMainThreadExecutor(
            emit_tool_request=emit_tool_request,
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
            record_event=events.append,
        )

        result = executor.execute("get_network_structure", {"node_path": "/obj"})

        self.assertTrue(result["success"])
        stale_events = [event for event in events if event.get("event_type") == "main_thread_stale_result_ignored"]
        self.assertEqual(len(stale_events), 1)
        self.assertEqual(stale_events[0]["operation_id"], 999)
        self.assertEqual(stale_events[0]["expected_operation_id"], 1)
        self.assertNotIn("payload-secret", repr(events))

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

    def test_main_thread_execution_fails_closed_without_executor(self):
        tab = _AITabToolExecutionStub(None)

        result = tab._execute_tool_in_main_thread("cook_node", {"node_path": "/obj/geo1/OUT"})

        self.assertFalse(result["success"])
        self.assertIn("执行器不可用", result["error"])

    def test_batch_execution_fails_closed_without_executor(self):
        tab = _AITabToolExecutionStub(None)

        results = tab._execute_tools_batch_in_main_thread([
            ("get_network_structure", {"node_path": "/obj"}),
            ("list_children", {"node_path": "/obj/geo1"}),
        ])

        self.assertEqual(len(results), 2)
        for result in results:
            self.assertFalse(result["success"])
            self.assertIn("执行器不可用", result["error"])

    def test_legacy_busy_flag_does_not_block_when_executor_is_available(self):
        result_queue = queue.Queue()
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: result_queue.put({
                "operation_id": kwargs[OPERATION_ID_KEY],
                "result": {"success": True, "result": name},
            }),
            emit_batch_request=lambda batch: None,
            result_queue=result_queue,
            main_timeout=0.01,
        )
        tab = _AITabToolExecutionStub(executor)
        tab._main_thread_busy = True

        result = tab._execute_tool_impl("get_network_structure", {"node_path": "/obj"})

        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "get_network_structure")

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

    def test_cook_guard_respects_confirmed_persistent_auto(self):
        old_hou = sys.modules.get("hou")
        hou_stub = _HouStub()
        sys.modules["hou"] = hou_stub
        try:
            executor = HoudiniMainThreadExecutor(
                emit_tool_request=lambda name, kwargs: None,
                emit_batch_request=lambda batch: None,
                result_queue=queue.Queue(),
            )
            executor.set_explicit_update_mode("auto")

            result = executor.run_in_main_thread(
                tool_name="set_node_parameter",
                kwargs={"node_path": "/obj/geo1/box1"},
                execute_tool=lambda name, kwargs: {"success": True, "result": name},
                cook_before_read=lambda: None,
                snapshot_network_children=lambda: {},
                diff_network_children=lambda before, after: None,
                refresh_selection_baseline=lambda: None,
                self_tracking_tools=frozenset(),
                error_formatter=str,
            )

            self.assertTrue(result["success"])
            self.assertEqual(hou_stub.set_modes, [])
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

    def test_execute_batch_ignores_stale_result_envelope(self):
        result_queue = queue.Queue()
        emitted = []

        def emit_batch_request(batch):
            emitted.append([(name, dict(kwargs)) for name, kwargs in batch])
            operation_id = batch[0][1][OPERATION_ID_KEY]
            result_queue.put({
                "operation_id": 999,
                "result": [{"success": True, "result": "batch-stale"}],
            })
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
        self.assertIn(OPERATION_ID_KEY, emitted[0][0][1])

    def test_batch_slot_attaches_operation_envelope_and_strips_private_id(self):
        executor = HoudiniMainThreadExecutor(
            emit_tool_request=lambda name, kwargs: None,
            emit_batch_request=lambda batch: None,
            result_queue=queue.Queue(),
            batch_timeout=0.01,
        )
        tab = _BatchSlotStub(executor)
        operation_id = 42

        tab._on_execute_tool_batch_main_thread([
            ("get_network_structure", {"node_path": "/obj", OPERATION_ID_KEY: operation_id}),
            ("list_children", {"node_path": "/obj/geo1", OPERATION_ID_KEY: operation_id}),
        ])

        queued = tab._tool_result_queue.get_nowait()
        self.assertEqual(queued["operation_id"], operation_id)
        self.assertEqual(len(queued["result"]), 2)
        self.assertEqual(tab.refresh_count, 1)
        self.assertEqual(tab.cook_count, 1)
        for _, kwargs in tab.mcp.calls:
            self.assertNotIn(OPERATION_ID_KEY, kwargs)


if __name__ == "__main__":
    unittest.main()