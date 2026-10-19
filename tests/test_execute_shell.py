# -*- coding: utf-8 -*-
"""execute_shell runtime behavior tests."""

import sys
import tempfile
import time
import unittest

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs

_install_hou_stub()
_install_thirdparty_stubs()

from houdini_agent.utils.mcp.client import HoudiniMCP


@unittest.skipUnless(sys.platform == "win32", "Windows shell encoding behavior")
class ExecuteShellTest(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(HoudiniMCP)
        self.client._tool_page_cache = {}
        self.client._stop_event = None

    def test_cmd_unicode_output_uses_windows_code_page(self):
        result = self.client._tool_execute_shell({"command": "echo 中文测试", "timeout": 5})

        self.assertTrue(result["success"])
        self.assertIn("中文测试", result["result"])

    def test_nonzero_exit_code_is_failure(self):
        result = self.client._tool_execute_shell({"command": "cmd /c exit 7", "timeout": 5})

        self.assertFalse(result["success"])
        self.assertIn("退出码: 7", result["result"])

    def test_large_stdout_does_not_deadlock(self):
        result = self.client._tool_execute_shell({
            "command": f'{sys.executable} -c "import sys;sys.stdout.write(chr(120)*1000000)"',
            "timeout": 5,
        })

        self.assertTrue(result["success"])
        self.assertIn("x" * 1000, result["result"])

    def test_large_stderr_does_not_deadlock(self):
        result = self.client._tool_execute_shell({
            "command": f'{sys.executable} -c "import sys;sys.stderr.write(chr(121)*1000000)"',
            "timeout": 5,
        })

        self.assertTrue(result["success"])
        self.assertIn("[stderr]", result["result"])
        self.assertIn("y" * 1000, result["result"])

    def test_large_stdout_and_stderr_do_not_deadlock(self):
        result = self.client._tool_execute_shell({
            "command": (
                f'{sys.executable} -c "import sys;'
                'sys.stdout.write(chr(120)*500000);sys.stderr.write(chr(121)*500000)"'
            ),
            "timeout": 5,
        })

        self.assertTrue(result["success"])
        self.assertIn("x" * 1000, result["result"])
        self.assertIn("y" * 1000, result["result"])

    def test_timeout_still_terminates_process(self):
        started = time.time()
        result = self.client._tool_execute_shell({
            "command": f'{sys.executable} -c "import time;time.sleep(10)"',
            "timeout": 1,
        })

        self.assertFalse(result["success"])
        self.assertIn("命令超时", result["error"])
        self.assertLess(time.time() - started, 8)

    def test_pagination_cache_is_isolated_by_cwd(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            command = f'{sys.executable} -c "import os;print(os.getcwd()+chr(120)*20000)"'
            first_page = self.client._tool_execute_shell({"command": command, "cwd": first, "page": 1})
            second_page = self.client._tool_execute_shell({"command": command, "cwd": second, "page": 1})

            first_continuation = self.client._tool_execute_shell({"command": command, "cwd": first, "page": 2})
            second_continuation = self.client._tool_execute_shell({"command": command, "cwd": second, "page": 2})

        self.assertTrue(first_page["success"])
        self.assertTrue(second_page["success"])
        self.assertNotEqual(first_continuation["result"], second_continuation["result"])


if __name__ == "__main__":
    unittest.main()