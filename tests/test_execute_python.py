import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_thirdparty_stubs


_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client


class ExecutePythonTest(unittest.TestCase):
    def setUp(self) -> None:
        hou_patch = patch.object(mcp_client, "hou", object())
        hou_patch.start()
        self.addCleanup(hou_patch.stop)
        self.client = object.__new__(mcp_client.HoudiniMCP)
        self.client._stop_event = None

    def test_comprehensions_read_script_variables(self) -> None:
        for expression in (
            "[value for value in range(3) if value in parm_names]",
            "{value: value for value in range(3) if value in parm_names}",
            "tuple(value for value in range(3) if value in parm_names)",
        ):
            with self.subTest(expression=expression):
                success, result = self.client.execute_python(
                    "parm_names = [1, 2]\n"
                    "result = " + expression + "\n"
                    "assert len(result) == 2\n"
                    "assert 1 in result and 2 in result"
                )
                self.assertTrue(success, result["error"])

    def test_recursive_function_resolves_its_own_name(self) -> None:
        success, result = self.client.execute_python(
            "def walk(depth):\n"
            "    return 0 if depth == 0 else 1 + walk(depth - 1)\n"
            "result = walk(3)"
        )

        self.assertTrue(success, result["error"])
        self.assertEqual(result["return_value"], "3")

    def test_function_reads_script_imports_and_variables(self) -> None:
        success, result = self.client.execute_python(
            "import math\n"
            "distance = 9\n"
            "def evaluate():\n"
            "    return math.sqrt(distance)\n"
            "result = evaluate()"
        )

        self.assertTrue(success, result["error"])
        self.assertEqual(result["return_value"], "3.0")

    def test_expression_keeps_hou_available(self) -> None:
        success, result = self.client.execute_python("hou is not None")

        self.assertTrue(success, result["error"])
        self.assertEqual(result["return_value"], "True")

    def test_last_assignment_is_returned(self) -> None:
        success, result = self.client.execute_python("first = 1\nlast = 2")

        self.assertTrue(success, result["error"])
        self.assertEqual(result["return_value"], "2")

    def test_no_assignment_has_no_return_value(self) -> None:
        success, result = self.client.execute_python("pass")

        self.assertTrue(success, result["error"])
        self.assertIsNone(result["return_value"])

    def test_separate_calls_do_not_share_script_variables(self) -> None:
        success, result = self.client.execute_python("previous_value = 42")
        self.assertTrue(success, result["error"])

        success, result = self.client.execute_python("previous_value")

        self.assertFalse(success)
        self.assertIn("NameError", result["error"])

    def test_error_keeps_output_and_restores_streams(self) -> None:
        stdout, stderr = mcp_client.sys.stdout, mcp_client.sys.stderr

        success, result = self.client.execute_python(
            "print('before failure')\nraise ValueError('expected failure')"
        )

        self.assertFalse(success)
        self.assertEqual(result["output"], "before failure\n")
        self.assertIn("ValueError: expected failure", result["error"])
        self.assertIs(mcp_client.sys.stdout, stdout)
        self.assertIs(mcp_client.sys.stderr, stderr)