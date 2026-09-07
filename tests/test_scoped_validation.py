# -*- coding: utf-8 -*-
"""Manual Scoped Validation transaction tests."""

import unittest

from houdini_agent.utils.scoped_validation import (
    ScopedValidationOperationResult,
    ScopedValidationTransaction,
)


class ScopedValidationTransactionTest(unittest.TestCase):
    def test_success_switches_runs_and_restores(self):
        state = {"mode": "manual"}
        writes = []

        def set_mode(mode):
            writes.append(mode)
            state["mode"] = mode

        transaction = ScopedValidationTransaction(
            lambda: state["mode"], set_mode, lambda: "auto"
        )
        result = transaction.run("/obj/geo1/OUT", lambda: ScopedValidationOperationResult(
            success=True, payload={"points": 4}, health="healthy",
            cook_succeeded=True, read_succeeded=True,
        ))

        self.assertTrue(result["success"])
        self.assertEqual(result["health"], "healthy")
        self.assertEqual(result["freshness"]["status"], "fresh")
        self.assertEqual(writes, ["auto", "manual"])

    def test_operation_and_restore_errors_are_both_preserved(self):
        state = {"mode": "manual"}

        def set_mode(mode):
            if mode == "manual" and state["mode"] == "auto":
                raise RuntimeError("restore broke")
            state["mode"] = mode

        transaction = ScopedValidationTransaction(
            lambda: state["mode"], set_mode, lambda: "auto"
        )
        result = transaction.run("/obj/geo1/OUT", lambda: (_ for _ in ()).throw(RuntimeError("cook broke")))

        self.assertFalse(result["success"])
        self.assertIn("cook broke", result["operation_error"])
        self.assertIn("restore broke", result["restore_error"])
        self.assertEqual(result["health"], "unknown")
        self.assertEqual(result["freshness"]["status"], "unknown")

    def test_blocked_operation_is_not_successful(self):
        state = {"mode": "manual"}
        transaction = ScopedValidationTransaction(
            lambda: state["mode"], lambda mode: state.update(mode=mode), lambda: "auto"
        )
        result = transaction.run("/obj/geo1/VDB", lambda: ScopedValidationOperationResult(
            success=False, validation_blocked=True, block_reason="unsafe VDB cook",
            error="unsafe VDB cook",
        ))

        self.assertFalse(result["success"])
        self.assertTrue(result["validation_blocked"])
        self.assertEqual(result["block_reason"], "unsafe VDB cook")
        self.assertEqual(result["health"], "unknown")

    def test_existing_auto_mode_is_still_set_and_restored(self):
        state = {"mode": "auto"}
        writes = []

        def set_mode(mode):
            writes.append(mode)
            state["mode"] = mode

        transaction = ScopedValidationTransaction(
            lambda: state["mode"], set_mode, lambda: "auto"
        )
        result = transaction.run("/obj/geo1/OUT", lambda: ScopedValidationOperationResult(
            success=True, health="healthy", cook_succeeded=True, read_succeeded=True,
        ))

        self.assertTrue(result["success"])
        self.assertEqual(writes, ["auto", "auto"])
        self.assertTrue(result["restore_attempted"])
        self.assertTrue(result["restore_succeeded"])


if __name__ == "__main__":
    unittest.main()