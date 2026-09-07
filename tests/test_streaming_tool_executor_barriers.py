# -*- coding: utf-8 -*-
"""Execution-order and barrier regressions for streaming tool calls."""

import unittest

from houdini_agent.core.streaming_tool_executor import StreamingToolExecutor


def _call(index, name, args=None):
    return ("call_%s" % index, name, args or {}, {})


class StreamingToolExecutorBarrierTest(unittest.TestCase):
    def _executor(self, calls, profile):
        def execute(name, args):
            calls.append(name)
            return {
                "success": True,
                "result": name,
                "metadata": {"source": "live", "tool": name},
            }

        def execute_batch(batch):
            calls.append("batch:" + ",".join(name for name, _args in batch))
            return [execute(name, args) for name, args in batch]

        return StreamingToolExecutor(
            execute,
            lambda args: execute("web_search", args),
            lambda args: execute("fetch_webpage", args),
            batch_tool_executor=execute_batch,
            runtime_profile_provider=lambda: profile,
        )

    def test_mutation_then_read_keeps_houdini_call_order(self):
        calls = []
        executor = self._executor(calls, {
            "dedup_tools": {"inspect_node"},
            "async_tools": set(),
            "batch_readonly_tools": {"inspect_node"},
            "network_mutating_tools": {"set_node_parameter"},
            "cache_invalidate_tools": {"inspect_node"},
            "execution_barrier_tools": {"set_node_parameter"},
        })

        executor.execute_round([
            _call(1, "set_node_parameter", {"node_path": "/obj/geo1/box1"}),
            _call(2, "inspect_node", {"node_path": "/obj/geo1/box1"}),
        ])

        self.assertEqual(calls, ["set_node_parameter", "inspect_node"])

    def test_successful_mode_barrier_invalidates_old_read_cache(self):
        calls = []
        executor = self._executor(calls, {
            "dedup_tools": {"inspect_node"},
            "async_tools": set(),
            "batch_readonly_tools": {"inspect_node"},
            "network_mutating_tools": set(),
            "cache_invalidate_tools": {"inspect_node"},
            "execution_barrier_tools": {"set_update_mode"},
        })
        args = {"node_path": "/obj/geo1/box1"}

        executor.execute_round([_call(1, "inspect_node", args)])
        result = executor.execute_round([
            _call(2, "set_update_mode", {"mode": "auto"}),
            _call(3, "inspect_node", args),
        ])

        self.assertEqual(calls, ["inspect_node", "set_update_mode", "inspect_node"])
        self.assertFalse(result["dedup_flags"][1])

    def test_cache_hit_is_copied_and_preserves_metadata(self):
        calls = []
        executor = self._executor(calls, {
            "dedup_tools": {"inspect_node"},
            "async_tools": set(),
            "batch_readonly_tools": {"inspect_node"},
            "network_mutating_tools": set(),
            "cache_invalidate_tools": {"inspect_node"},
            "execution_barrier_tools": set(),
        })
        args = {"node_path": "/obj/geo1/box1"}

        first = executor.execute_round([_call(1, "inspect_node", args)])
        second = executor.execute_round([_call(2, "inspect_node", args)])
        second["results_ordered"][0]["metadata"]["source"] = "changed"

        self.assertTrue(second["dedup_flags"][0])
        self.assertEqual(first["results_ordered"][0]["metadata"]["source"], "live")
        self.assertEqual(second["results_ordered"][0]["metadata"]["tool"], "inspect_node")


if __name__ == "__main__":
    unittest.main()