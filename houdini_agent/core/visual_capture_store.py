# -*- coding: utf-8 -*-
"""Atomic, session-scoped persistence for visual capture pairs."""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .workspace_persistence import atomic_write_json


class CaptureStore:
    def __init__(self, session_root: Path, session_id: str):
        self.session_root = Path(session_root)
        self.session_id = session_id

    def create_baseline(
        self,
        image_bytes: bytes,
        media_type: str,
        fingerprint: Dict[str, Any],
    ) -> Dict[str, Any]:
        self.session_root.mkdir(parents=True, exist_ok=True)
        pair_id = uuid.uuid4().hex
        capture_id = uuid.uuid4().hex
        image_name = f"{capture_id}-before.jpg"
        image_path = self.session_root / image_name
        temp_path = self.session_root / f".{image_name}.tmp"
        manifest_name = f"{pair_id}.json"
        manifest_path = self.session_root / manifest_name
        manifest = {
            "schema_version": 1,
            "pair_id": pair_id,
            "session_id": self.session_id,
            "status": "baseline_only",
            "before": {
                "capture_id": capture_id,
                "role": "before",
                "relative_path": image_name,
                "created_at": datetime.now().isoformat(),
                "media_type": media_type,
                "resolution": fingerprint.get("resolution", []),
                "target_path": fingerprint.get("target_path", ""),
                "fingerprint": dict(fingerprint),
            },
            "after": None,
        }
        try:
            with open(temp_path, "wb") as stream:
                stream.write(image_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temp_path), str(image_path))
            atomic_write_json(manifest_path, manifest)
        except Exception:
            for path in (temp_path, image_path):
                try:
                    path.unlink()
                except OSError:
                    pass
            raise
        result = dict(manifest)
        result["manifest_path"] = manifest_name
        return result