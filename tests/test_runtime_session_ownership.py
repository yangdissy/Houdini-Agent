# -*- coding: utf-8 -*-
"""Agent runtime session ownership tests."""

import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs


_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.core.runtime_state_mixin import RuntimeStateMixin


class _Signal:
    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        pass


class _Timer:
    def __init__(self, parent=None):
        self.timeout = _Signal()

    def start(self, interval):
        pass

    def stop(self):
        pass


class _Response:
    def __init__(self):
        self.finalized = False
        self.statuses = []

    def finalize(self):
        self.finalized = True

    def add_status(self, status):
        self.statuses.append(status)


class _Client:
    def reset_stop(self):
        pass


class _Combo:
    def currentText(self):
        return "test-model"


class _Runtime(RuntimeStateMixin):
    def __init__(self):
        history_a = [{"role": "user", "content": "from A"}]
        history_b = [{"role": "user", "content": "from B"}]
        stats_a = self._stats()
        stats_b = self._stats()
        response_a = _Response()
        response_b = _Response()
        self._sessions = {
            "A": {
                "conversation_history": history_a,
                "token_stats": stats_a,
                "current_response": response_a,
                "todo_list": object(),
            },
            "B": {
                "conversation_history": history_b,
                "token_stats": stats_b,
                "current_response": response_b,
                "todo_list": object(),
            },
        }
        self._session_id = "A"
        self._conversation_history = history_a
        self._token_stats = stats_a
        self._current_response = response_a
        self.todo_list = self._sessions["A"]["todo_list"]
        self.scroll_area = object()
        self.chat_layout = object()
        self.client = _Client()
        self.model_combo = _Combo()
        self._thinking_timer = _Timer()
        self.thinking_bar = object()
        self._memory_initialized = False
        self._pending_memory_reinforcement = None
        self._auto_save_cache = False
        self._main_thread_busy = False
        self._output_buffer = ""
        self._content_buffer = ""
        self._current_response_text = ""
        self._current_thinking_text = ""
        self._hideToolStatus = _Signal()
        self._addStatus = _Signal()
        self._selection_stop_triggered = False
        self._pending_user_switch = None
        self.title_calls = []

    @staticmethod
    def _stats():
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "cache_read": 0,
            "cache_write": 0,
            "total_tokens": 0,
            "requests": 0,
            "estimated_cost": 0.0,
        }

    def switch_to_b(self):
        state = self._sessions["B"]
        self._session_id = "B"
        self._conversation_history = state["conversation_history"]
        self._token_stats = state["token_stats"]
        self._current_response = state["current_response"]
        self.todo_list = state["todo_list"]
        self.scroll_area = object()
        self.chat_layout = object()

    def _updateThinkingTime(self):
        pass

    def _start_input_glow(self):
        pass

    def _stop_input_glow(self):
        pass

    def _stop_active_aurora(self):
        pass

    def _start_selection_watch(self):
        pass

    def _stop_selection_watch(self):
        pass

    def _update_run_buttons(self):
        pass

    def _restore_update_mode(self):
        pass

    def _fire_session_hook(self, name, session_id):
        pass

    def _finish_thinking_stream(self):
        pass

    def _strip_fake_tool_results(self, content):
        return content

    def _manage_context(self):
        pass

    def _append_session_diagnostics_records(self, rows, session_id=None):
        pass

    def _update_context_stats(self):
        pass

    def _update_token_stats_display(self):
        pass

    def _maybe_generate_title(self, session_id, history):
        self.title_calls.append((session_id, history))


class RuntimeSessionOwnershipTest(unittest.TestCase):
    @staticmethod
    def _start_on_a_then_switch_to_b(runtime):
        runtime._set_running(True)
        runtime.switch_to_b()

    def test_agent_completion_after_switch_updates_origin_session_only(self):
        runtime = _Runtime()
        history_a = runtime._sessions["A"]["conversation_history"]
        history_b = list(runtime._sessions["B"]["conversation_history"])
        stats_b = dict(runtime._sessions["B"]["token_stats"])
        response_a = runtime._sessions["A"]["current_response"]
        response_b = runtime._sessions["B"]["current_response"]

        with unittest.mock.patch(
                "houdini_agent.core.runtime_state_mixin.QtCore.QTimer", _Timer):
            self._start_on_a_then_switch_to_b(runtime)
            runtime._on_agent_done({
                "ok": True,
                "final_content": "answer for A",
                "tool_calls_history": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            })

        self.assertIs(runtime._sessions["A"]["conversation_history"], history_a)
        self.assertEqual(history_a[-1]["content"], "answer for A")
        self.assertEqual(runtime._sessions["B"]["conversation_history"], history_b)
        self.assertEqual(runtime._sessions["B"]["token_stats"], stats_b)
        self.assertEqual(runtime._sessions["A"]["token_stats"]["total_tokens"], 15)
        self.assertTrue(response_a.finalized)
        self.assertFalse(response_b.finalized)
        self.assertEqual(runtime.title_calls, [("A", history_a)])
        self.assertIsNone(runtime._agent_session_id)
        self.assertEqual(runtime._session_id, "B")

    def test_agent_error_after_switch_updates_origin_session_only(self):
        runtime = _Runtime()
        history_a = runtime._sessions["A"]["conversation_history"]
        history_b = list(runtime._sessions["B"]["conversation_history"])
        response_a = runtime._sessions["A"]["current_response"]

        with unittest.mock.patch(
                "houdini_agent.core.runtime_state_mixin.QtCore.QTimer", _Timer):
            self._start_on_a_then_switch_to_b(runtime)
            runtime._on_agent_error("boom")

        self.assertEqual(history_a[-1], {
            "role": "assistant", "content": "[Error] boom",
        })
        self.assertEqual(runtime._sessions["B"]["conversation_history"], history_b)
        self.assertEqual(response_a.statuses, ["Error: boom"])
        self.assertIsNone(runtime._agent_session_id)
        self.assertEqual(runtime._session_id, "B")

    def test_agent_stop_after_switch_updates_origin_session_only(self):
        runtime = _Runtime()
        history_a = runtime._sessions["A"]["conversation_history"]
        history_b = list(runtime._sessions["B"]["conversation_history"])
        response_a = runtime._sessions["A"]["current_response"]

        with unittest.mock.patch(
                "houdini_agent.core.runtime_state_mixin.QtCore.QTimer", _Timer):
            self._start_on_a_then_switch_to_b(runtime)
            runtime._on_agent_stopped()

        self.assertEqual(history_a[-1], {
            "role": "assistant", "content": "[Stopped by user]",
        })
        self.assertEqual(runtime._sessions["B"]["conversation_history"], history_b)
        self.assertEqual(response_a.statuses, ["Stopped"])
        self.assertIsNone(runtime._agent_session_id)
        self.assertEqual(runtime._session_id, "B")


if __name__ == "__main__":
    unittest.main()