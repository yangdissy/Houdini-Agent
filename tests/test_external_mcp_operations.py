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

    def test_running_progress_updates_are_monotonic(self):
        registry = OperationRegistry()
        operation = registry.create("session-a", "external_job")
        registry.transition(
            "session-a", operation["operation_id"], "running", progress=0.25
        )

        current = registry.update_progress(
            "session-a", operation["operation_id"], 0.5, stage="rendering"
        )

        self.assertEqual(current["progress"], 0.5)
        self.assertEqual(current["stage"], "rendering")
        with self.assertRaises(ValueError):
            registry.update_progress(
                "session-a", operation["operation_id"], 0.4, stage="regressed"
            )

    def test_terminal_state_publishes_exit_code_and_artifacts(self):
        registry = OperationRegistry()
        operation = registry.create("session-a", "external_job")
        registry.transition("session-a", operation["operation_id"], "running")

        completed = registry.transition(
            "session-a",
            operation["operation_id"],
            "completed",
            progress=1.0,
            exit_code=0,
            artifacts=[{
                "name": "result",
                "path": "result.json",
                "size": 12,
                "media_type": "application/json",
            }],
        )

        self.assertEqual(completed["exit_code"], 0)
        self.assertEqual(completed["artifacts"][0]["path"], "result.json")
        self.assertNotIn("absolute_path", completed["artifacts"][0])

    def test_progress_update_requires_running_session_owned_operation(self):
        registry = OperationRegistry()
        operation = registry.create("session-a", "external_job")

        with self.assertRaises(KeyError):
            registry.update_progress("session-b", operation["operation_id"], 0.1)
        with self.assertRaises(ValueError):
            registry.update_progress("session-a", operation["operation_id"], 0.1)

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