# -*- coding: utf-8 -*-

import json
import tempfile
import unittest
from pathlib import Path

from houdini_agent.core.visual_capture_store import CaptureStore


class CaptureStoreTest(unittest.TestCase):
    def test_create_baseline_publishes_image_then_sanitized_manifest(self):
        fingerprint = {
            "frame": 12.5,
            "viewport": "persp1",
            "camera_mode": "camera",
            "camera_path": "/obj/cam1",
            "resolution": [800, 450],
            "target_path": "/obj/geo1",
        }
        with tempfile.TemporaryDirectory() as root:
            store = CaptureStore(Path(root), "session-01")

            manifest = store.create_baseline(b"jpeg-data", "image/jpeg", fingerprint)

            manifest_path = Path(root) / manifest["manifest_path"]
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
            image_path = Path(root) / saved["before"]["relative_path"]
            self.assertEqual(image_path.read_bytes(), b"jpeg-data")
            self.assertEqual(saved["schema_version"], 1)
            self.assertEqual(saved["session_id"], "session-01")
            self.assertEqual(saved["status"], "baseline_only")
            self.assertNotIn("image_bytes", saved)
            self.assertNotIn("visual_goal", saved)
            self.assertFalse(Path(saved["before"]["relative_path"]).is_absolute())


if __name__ == "__main__":
    unittest.main()