# -*- coding: utf-8 -*-
"""Read-only TOP/PDG inspection contract tests."""

import unittest
from unittest.mock import patch

from tests.test_import_smoke import _install_hou_stub, _install_thirdparty_stubs


_install_hou_stub()
_install_thirdparty_stubs()

import houdini_agent.utils.mcp.client as mcp_client
from houdini_agent.utils.pdg_inspection import get_top_errors, inspect_top_network, list_work_items


class _State:
    def __init__(self, name):
        self.name = name


class _Attrib:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class _OutputFile:
    def __init__(self, path, tag="file/geo"):
        self.path = path
        self.tag = tag


class _WorkItem:
    def __init__(self, index, state):
        self.index = index
        self.name = f"item_{index}"
        self.state = _State(state)
        self.attribs = [_Attrib("frame", index + 1)]
        self.outputFiles = [_OutputFile(f"/tmp/{index}.bgeo.sc")]
        self.errorMessage = "render failed" if state == "CookFailed" else ""
        self.command = "hython render.py" if state == "CookFailed" else ""
        self.logFile = f"/tmp/{index}.log" if state == "CookFailed" else ""


class _PDGNode:
    def __init__(self):
        self.name = "ropgeometry1"
        self.workItems = [
            _WorkItem(0, "CookedSuccess"),
            _WorkItem(1, "CookFailed"),
            _WorkItem(2, "Waiting"),
        ]


class _Context:
    def __init__(self, pdg_node):
        self.graph = type("Graph", (), {"nodes": [pdg_node]})()


class _TopNode:
    def __init__(self):
        self.pdg_node = _PDGNode()
        self.context = _Context(self.pdg_node)

    def path(self):
        return "/obj/topnet1/ropgeometry1"

    def getPDGNode(self):
        return self.pdg_node

    def getPDGGraphContext(self):
        return self.context

    def schedulerNode(self):
        return type("Scheduler", (), {"path": lambda self: "/obj/topnet1/localscheduler"})()


class PDGInspectionTest(unittest.TestCase):
    def setUp(self):
        self.node = _TopNode()

    def test_network_summary_counts_states_and_scheduler(self):
        result = inspect_top_network(self.node, pdg_module=object())

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["node_path"], "/obj/topnet1/ropgeometry1")
        self.assertEqual(data["scheduler_path"], "/obj/topnet1/localscheduler")
        self.assertEqual(data["pdg_node_count"], 1)
        self.assertEqual(data["work_item_count"], 3)
        self.assertEqual(data["state_counts"]["CookFailed"], 1)

    def test_work_items_are_paginated_and_bounded(self):
        result = list_work_items(
            self.node, start=1, count=1, max_attributes=5,
            max_output_files=5, pdg_module=object(),
        )

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["items"][0]["index"], 1)
        self.assertEqual(data["items"][0]["state"], "CookFailed")
        self.assertEqual(data["items"][0]["attributes"][0], {"name": "frame", "value": 2})
        self.assertEqual(data["items"][0]["output_files"][0]["path"], "/tmp/1.bgeo.sc")
        self.assertTrue(data["truncated"])
        self.assertEqual(data["next_start"], 2)

    def test_missing_pdg_and_missing_node_are_structured(self):
        with patch("houdini_agent.utils.pdg_inspection._load_pdg", return_value=None):
            unavailable = inspect_top_network(self.node)
        self.assertFalse(unavailable["success"])
        self.assertEqual(unavailable["error_code"], "pdg_unavailable")

        missing = list_work_items(None, pdg_module=object())
        self.assertFalse(missing["success"])
        self.assertEqual(missing["error_code"], "top_node_unavailable")

    def test_errors_include_metadata_but_not_log_contents(self):
        result = get_top_errors(self.node, pdg_module=object())

        self.assertTrue(result["success"])
        error = result["data"]["errors"][0]
        self.assertEqual(error["index"], 1)
        self.assertEqual(error["error"], "render failed")
        self.assertEqual(error["command"], "hython render.py")
        self.assertEqual(error["log_path"], "/tmp/1.log")
        self.assertNotIn("log_contents", error)


class PDGToolHandlerTest(unittest.TestCase):
    def setUp(self):
        self.old_hou = mcp_client.hou
        self.node = _TopNode()
        mcp_client.hou = type("Hou", (), {"node": lambda owner, path: self.node})()
        self.client = object.__new__(mcp_client.HoudiniMCP)

    def tearDown(self):
        mcp_client.hou = self.old_hou

    def test_handlers_read_status_without_lifecycle_calls(self):
        with patch("houdini_agent.utils.pdg_inspection._load_pdg", return_value=object()):
            status = self.client._tool_get_top_network_status({
                "node_path": "/obj/topnet1/ropgeometry1"
            })
            items = self.client._tool_list_top_work_items({
                "node_path": "/obj/topnet1/ropgeometry1", "count": 1
            })
            errors = self.client._tool_get_top_errors({
                "node_path": "/obj/topnet1/ropgeometry1"
            })

        self.assertTrue(status["success"])
        self.assertEqual(status["data"]["work_item_count"], 3)
        self.assertTrue(items["success"])
        self.assertEqual(items["data"]["count"], 1)
        self.assertTrue(errors["success"])
        self.assertEqual(errors["data"]["total_failed_count"], 1)


if __name__ == "__main__":
    unittest.main()