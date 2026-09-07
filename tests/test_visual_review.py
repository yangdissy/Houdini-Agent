# -*- coding: utf-8 -*-

import unittest
import sys
import tempfile
from pathlib import Path
from unittest import mock

for name in ("requests", "trafilatura"):
    if name not in sys.modules:
        sys.modules[name] = mock.MagicMock(name=name)

from houdini_agent.utils.ai_client import HOUDINI_TOOLS
from houdini_agent.utils.mcp import client as mcp_client
from houdini_agent.utils.mcp.client import HoudiniMCP, compare_capture_fingerprints
from houdini_agent.utils.tool_registry import ToolRegistry


class VisualReviewContractTest(unittest.TestCase):
    def test_fingerprints_are_comparable_only_for_matching_camera_views(self):
        before = {
            "frame": 12.5,
            "viewport": "persp1",
            "camera_mode": "camera",
            "camera_path": "/obj/cam1",
            "resolution": [800, 450],
            "target_path": "/obj/geo1",
        }

        self.assertEqual(compare_capture_fingerprints(before, dict(before)), {
            "status": "comparable",
            "reason": "matching_camera_view",
        })

        free_view = dict(before, camera_mode="free", camera_path="")
        self.assertEqual(
            compare_capture_fingerprints(free_view, dict(free_view))["status"],
            "incomparable",
        )
        unknown = dict(before, viewport="")
        self.assertEqual(
            compare_capture_fingerprints(unknown, dict(unknown))["status"],
            "incomparable",
        )
        changed = dict(before, frame=13.0)
        self.assertEqual(
            compare_capture_fingerprints(before, changed)["status"],
            "incomparable",
        )

    def test_capture_primitive_returns_bytes_and_preserves_subframe(self):
        client = object.__new__(HoudiniMCP)
        viewport = mock.Mock()
        viewport.name.return_value = "persp1"
        viewport.camera.return_value = None
        viewer = mock.Mock()
        viewer.curViewport.return_value = viewport
        settings = viewer.flipbookSettings.return_value.stash.return_value

        def write_capture(current_viewport, flipbook_settings):
            Path(flipbook_settings.output.call_args.args[0]).write_bytes(b"jpeg-data")

        viewer.flipbook.side_effect = write_capture
        desktop = mock.Mock()
        desktop.paneTabOfType.return_value = viewer
        hou = mock.Mock()
        hou.ui.curDesktop.return_value = desktop
        hou.frame.return_value = 12.5

        with mock.patch.object(mcp_client, "hou", hou):
            capture = client._capture_viewport({"width": 800, "height": 450})
            result = client._tool_capture_viewport({"width": 800, "height": 450})

        self.assertTrue(capture["success"])
        self.assertEqual(capture["image_bytes"], b"jpeg-data")
        self.assertEqual(capture["media_type"], "image/jpeg")
        self.assertEqual(capture["fingerprint"]["frame"], 12.5)
        self.assertEqual(capture["fingerprint"]["viewport"], "persp1")
        self.assertEqual(capture["fingerprint"]["resolution"], [800, 450])
        self.assertTrue(result["success"])
        self.assertEqual(result["_viewport_image"], "anBlZy1kYXRh")

    def test_capture_cleans_its_temp_files_when_flipbook_fails(self):
        client = object.__new__(HoudiniMCP)
        viewer = mock.Mock()
        settings = viewer.flipbookSettings.return_value.stash.return_value

        def fail_after_writing(viewport, flipbook_settings):
            Path(flipbook_settings.output.call_args.args[0]).write_bytes(b"partial")
            raise RuntimeError("capture failed")

        viewer.flipbook.side_effect = fail_after_writing
        desktop = mock.Mock()
        desktop.paneTabOfType.return_value = viewer
        hou = mock.Mock()
        hou.ui.curDesktop.return_value = desktop
        hou.frame.return_value = 12.5

        with tempfile.TemporaryDirectory() as temp_root:
            old_capture = Path(temp_root) / "houdini_viewport_old.jpg"
            old_capture.write_bytes(b"old")
            with mock.patch.object(mcp_client, "hou", hou), mock.patch(
                "tempfile.gettempdir", return_value=temp_root
            ):
                result = client._tool_capture_viewport({})

            self.assertFalse(result["success"])
            self.assertEqual(list(Path(temp_root).iterdir()), [old_capture])

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
            "target_path": "/obj/geo1",
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