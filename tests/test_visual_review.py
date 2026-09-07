# -*- coding: utf-8 -*-

import unittest
import sys
from unittest import mock

for name in ("requests", "trafilatura"):
    if name not in sys.modules:
        sys.modules[name] = mock.MagicMock(name=name)

from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.mcp.client import HoudiniMCP
from houdini_agent.utils.tool_registry import ToolRegistry


class VisualReviewContractTest(unittest.TestCase):
    def test_schema_dispatch_and_registry_metadata_are_aligned(self):
        schemas = {
            schema["function"]["name"]: schema
            for schema in HOUDINI_TOOLS
        }
        self.assertIn("visual_review", schemas)
        self.assertEqual(
            HoudiniMCP._TOOL_DISPATCH["visual_review"],
            "_tool_visual_review",
        )

        registry = ToolRegistry()
        registry.register_core_tools(HOUDINI_TOOLS)
        meta = registry.get_meta("visual_review")
        self.assertEqual(meta.risk_level, "low")
        self.assertIn("readonly", meta.tags)
        self.assertIn("ask", meta.modes)
        self.assertFalse(meta.requires_confirmation)
        self.assertEqual(meta.path_kinds["target_path"], "node")

    def test_handler_reuses_capture_and_adds_review_contract(self):
        client = object.__new__(HoudiniMCP)
        capture = {
            "success": True,
            "result": "captured",
            "_viewport_image": "encoded",
            "_image_media_type": "image/jpeg",
        }
        client._tool_capture_viewport = mock.Mock(return_value=capture)

        result = client._tool_visual_review({
            "review_type": "composition",
            "target_path": "/obj/geo1",
            "visual_goal": "clean product shot",
            "width": 800,
            "height": 450,
        })

        client._tool_capture_viewport.assert_called_once_with({
            "width": 800,
            "height": 450,
        })
        self.assertTrue(result["success"])
        self.assertEqual(result["review_type"], "composition")
        self.assertEqual(result["target_path"], "/obj/geo1")
        self.assertEqual(result["technical_status"], "not_evaluated")
        self.assertEqual(result["visual_status"], "pending_model_review")
        self.assertIn("clean product shot", result["_image_prompt"])
        self.assertEqual(result["_viewport_image"], "encoded")

    def test_handler_rejects_unknown_review_type_without_capture(self):
        client = object.__new__(HoudiniMCP)
        client._tool_capture_viewport = mock.Mock()

        result = client._tool_visual_review({"review_type": "beauty"})

        self.assertFalse(result["success"])
        self.assertIn("review_type", result["error"])
        client._tool_capture_viewport.assert_not_called()

    def test_handler_preserves_capture_failure_without_claiming_review(self):
        client = object.__new__(HoudiniMCP)
        client._tool_capture_viewport = mock.Mock(return_value={
            "success": False,
            "error": "找不到 Scene Viewer 面板",
        })

        result = client._tool_visual_review({"review_type": "general"})

        self.assertEqual(result, {
            "success": False,
            "error": "找不到 Scene Viewer 面板",
        })
        self.assertNotIn("visual_status", result)


if __name__ == "__main__":
    unittest.main()