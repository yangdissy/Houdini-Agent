# -*- coding: utf-8 -*-

import unittest

from houdini_agent.utils.mcp.operations import OperationRegistry


class OperationRegistryTest(unittest.TestCase):
    def test_lifecycle_distinguishes_accepted_running_and_terminal_states(self):
        registry = OperationRegistry()
        accepted = registry.create("session-a", "top_cook")
        running = registry.transition("session-a", accepted["operation_id"], "running", progress=0.25)
        completed = registry.transition(
            "session-a", accepted["operation_id"], "completed", progress=1.0,
            result={"work_items": 4},
        )

        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(running["state"], "running")
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["result"], {"work_items": 4})

    def test_session_ownership_and_invalid_transitions_fail_closed(self):
        registry = OperationRegistry()
        operation = registry.create("session-a", "top_cook")

        self.assertIsNone(registry.get("session-b", operation["operation_id"]))
        with self.assertRaises(KeyError):
            registry.transition("session-b", operation["operation_id"], "running")
        with self.assertRaises(ValueError):
            registry.transition("session-a", operation["operation_id"], "completed")

    def test_timeout_is_not_a_cancelled_state(self):
        registry = OperationRegistry()
        operation = registry.create("session-a", "top_cook")
        registry.transition("session-a", operation["operation_id"], "running")

        current = registry.get("session-a", operation["operation_id"])

        self.assertEqual(current["state"], "running")
        self.assertNotEqual(current["state"], "cancelled")

    def test_limit_evicts_terminal_but_not_running_operations(self):
        registry = OperationRegistry(max_operations=1)
        first = registry.create("session-a", "top_cook")
        with self.assertRaises(RuntimeError):
            registry.create("session-a", "top_cook")
        registry.transition("session-a", first["operation_id"], "failed", error_code="cook_error")

        second = registry.create("session-a", "top_cook")

        self.assertIsNone(registry.get("session-a", first["operation_id"]))
        self.assertEqual(second["state"], "accepted")


if __name__ == "__main__":
    unittest.main()