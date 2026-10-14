# -*- coding: utf-8 -*-
"""Bounded session-owned operation state for asynchronous external MCP work."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
import uuid
from typing import Any, Dict, Optional


_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
_TRANSITIONS = {
    "accepted": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
}


@dataclass
class OperationRecord:
    operation_id: str
    session_id: str
    kind: str
    state: str = "accepted"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    progress: Optional[float] = None
    stage: str = ""
    error_code: str = ""
    exit_code: Optional[int] = None
    artifacts: list = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None

    def public_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "kind": self.kind,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "progress": self.progress,
            "stage": self.stage,
            "error_code": self.error_code,
            "exit_code": self.exit_code,
            "artifacts": [dict(item) for item in self.artifacts],
            "result": dict(self.result) if isinstance(self.result, dict) else None,
        }


class OperationRegistry:
    def __init__(self, max_operations: int = 32):
        self._max_operations = max(1, int(max_operations))
        self._lock = threading.Lock()
        self._records: Dict[str, OperationRecord] = {}

    def create(self, session_id: str, kind: str) -> Dict[str, Any]:
        if not session_id or not kind:
            raise ValueError("operation session and kind are required")
        with self._lock:
            self._evict_terminal_locked()
            if len(self._records) >= self._max_operations:
                raise RuntimeError("operation registry limit reached")
            operation_id = uuid.uuid4().hex
            record = OperationRecord(operation_id=operation_id, session_id=session_id, kind=kind)
            self._records[operation_id] = record
            return record.public_dict()

    def get(self, session_id: str, operation_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(operation_id)
            if record is None or record.session_id != session_id:
                return None
            return record.public_dict()

    def transition(
        self,
        session_id: str,
        operation_id: str,
        state: str,
        progress: Optional[float] = None,
        stage: str = "",
        error_code: str = "",
        exit_code: Optional[int] = None,
        artifacts: Optional[list] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            record = self._records.get(operation_id)
            if record is None or record.session_id != session_id:
                raise KeyError("operation not found")
            if state not in _TRANSITIONS.get(record.state, frozenset()):
                raise ValueError("invalid operation state transition")
            if progress is not None and not 0.0 <= float(progress) <= 1.0:
                raise ValueError("operation progress must be between 0 and 1")
            record.state = state
            record.progress = float(progress) if progress is not None else record.progress
            record.stage = str(stage or record.stage)
            record.error_code = str(error_code or "")
            record.exit_code = int(exit_code) if exit_code is not None else None
            record.artifacts = self._public_artifacts(artifacts)
            record.result = dict(result) if isinstance(result, dict) else None
            record.updated_at = time.time()
            return record.public_dict()

    def update_progress(
        self,
        session_id: str,
        operation_id: str,
        progress: float,
        stage: str = "",
    ) -> Dict[str, Any]:
        value = float(progress)
        if not 0.0 <= value <= 1.0:
            raise ValueError("operation progress must be between 0 and 1")
        with self._lock:
            record = self._records.get(operation_id)
            if record is None or record.session_id != session_id:
                raise KeyError("operation not found")
            if record.state != "running":
                raise ValueError("operation must be running to update progress")
            if record.progress is not None and value < record.progress:
                raise ValueError("operation progress cannot decrease")
            record.progress = value
            record.stage = str(stage or record.stage)
            record.updated_at = time.time()
            return record.public_dict()

    @staticmethod
    def _public_artifacts(artifacts: Optional[list]) -> list:
        public = []
        for item in artifacts or ():
            if not isinstance(item, dict):
                raise ValueError("operation artifact must be an object")
            public.append({
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "size": int(item.get("size") or 0),
                "media_type": str(item.get("media_type") or ""),
            })
        return public

    def _evict_terminal_locked(self) -> None:
        terminal = sorted(
            (record for record in self._records.values() if record.state in _TERMINAL_STATES),
            key=lambda record: record.updated_at,
        )
        while len(self._records) >= self._max_operations and terminal:
            self._records.pop(terminal.pop(0).operation_id, None)