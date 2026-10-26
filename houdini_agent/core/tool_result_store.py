# -*- coding: utf-8 -*-
"""Session-scoped storage for large, sanitized tool results."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict


class ToolResultStore:
    def __init__(self, root: Path, session_id: str, threshold: int = 16_000):
        self._root = Path(root) / "tool_results" / self._validate_session_id(session_id)
        self._threshold = max(1, int(threshold))

    def archive_if_large(self, tool_name: str, result: dict) -> dict:
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        size = len(payload.encode("utf-8"))
        if size <= self._threshold:
            return result

        result_ref = "res_" + uuid.uuid4().hex
        sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        document = {
            "schema_version": 1,
            "result_ref": result_ref,
            "tool_name": str(tool_name),
            "sha256": sha256,
            "size": size,
            "result": result,
        }
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(result_ref)
        temporary = target.with_suffix(".json.partial")
        temporary.write_text(json.dumps(document, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(str(temporary), str(target))
        return {
            "success": bool(result.get("success")),
            "result": "Large tool result archived; use read_tool_result with result_ref.",
            "result_ref": result_ref,
            "stored": True,
            "size": size,
            "sha256": sha256,
            "content_type": "application/json",
            **({"operation_receipt": result["operation_receipt"]} if "operation_receipt" in result else {}),
            **{key: result[key] for key in (
                "audit_status", "audit_warning", "audit_call_id", "replay_safe", "operation_id", "request_ref",
                "scene_consistency", "thread_still_running", "verification", "error_code",
            ) if key in result},
        }

    def read(self, result_ref: str, pointer: str = "", offset: int = 0, limit: int = 6000) -> Dict[str, Any]:
        document = json.loads(self._path(result_ref).read_text(encoding="utf-8"))
        value = self._resolve_pointer(document.get("result"), pointer)
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        bounded_offset = max(0, int(offset))
        bounded_limit = min(16_000, max(1, int(limit)))
        end = min(len(text), bounded_offset + bounded_limit)
        return {
            "success": True,
            "result_ref": result_ref,
            "pointer": pointer,
            "offset": bounded_offset,
            "next_offset": end if end < len(text) else None,
            "total_chars": len(text),
            "content": text[bounded_offset:end],
            "sha256": document.get("sha256"),
        }

    def describe(self, result_ref: str) -> Dict[str, Any]:
        document = json.loads(self._path(result_ref).read_text(encoding="utf-8"))
        payload = json.dumps(document["result"], ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str)
        sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if document.get("result_ref") != result_ref or document.get("sha256") != sha256:
            raise ValueError("Tool result reference integrity check failed.")
        result = document["result"]
        return {"tool_name": document["tool_name"], "sha256": sha256,
                "success": bool(result.get("success")) if isinstance(result, dict) else False}

    def _path(self, result_ref: str) -> Path:
        if not isinstance(result_ref, str) or not result_ref.startswith("res_"):
            raise ValueError("invalid result_ref")
        token = result_ref[4:]
        if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
            raise ValueError("invalid result_ref")
        return self._root / (result_ref + ".json")

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        value = str(session_id or "").strip()
        if not value or len(value) > 64 or any(not (char.isalnum() or char in "_-") for char in value):
            raise ValueError("invalid session_id")
        return value

    @staticmethod
    def _resolve_pointer(value: Any, pointer: str) -> Any:
        if pointer in (None, ""):
            return value
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("pointer must be an RFC 6901 JSON Pointer")
        current = value
        for raw_part in pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(part)
        return current