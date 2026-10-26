# -*- coding: utf-8 -*-
"""Governed lifecycle for allowlisted external process jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .operations import OperationRegistry


_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class ExternalJobSpec:
    kind: str
    executable: str
    build_args: Callable[[Mapping[str, Any], str], Sequence[str]]
    timeout: float = 300.0
    artifacts: Mapping[str, Tuple[str, str]] = field(default_factory=dict)
    required_artifacts: Tuple[str, ...] = ()
    max_event_bytes: int = 64 * 1024
    max_log_bytes: int = 1024 * 1024
    max_artifact_bytes: int = 1024 * 1024 * 1024

    def validate(self) -> None:
        if not self.kind or not self.executable or not callable(self.build_args):
            raise ValueError("external job kind, executable and build_args are required")
        if self.timeout <= 0:
            raise ValueError("external job timeout must be positive")
        if any(name not in self.artifacts for name in self.required_artifacts):
            raise ValueError("required artifact is not declared")
        for name, value in self.artifacts.items():
            if not name or not isinstance(value, tuple) or len(value) != 2:
                raise ValueError("invalid external job artifact declaration")
            _validate_relative_path(value[0])


@dataclass
class _ActiveJob:
    session_id: str
    operation_id: str
    spec: ExternalJobSpec
    work_dir: Path
    process: subprocess.Popen
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)


class ExternalProcessJobAdapter:
    def __init__(
        self,
        registry: OperationRegistry,
        jobs_root: str,
        audit: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self._registry = registry
        self._jobs_root = Path(jobs_root).resolve()
        self._jobs_root.mkdir(parents=True, exist_ok=True)
        self._audit = audit
        self._audit_degraded = False
        self._specs: Dict[str, ExternalJobSpec] = {}
        self._active: Dict[str, _ActiveJob] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def register(self, spec: ExternalJobSpec) -> None:
        spec.validate()
        with self._lock:
            if self._stopped.is_set():
                raise RuntimeError("external job adapter is stopped")
            if spec.kind in self._specs:
                raise ValueError("external job kind is already registered")
            self._specs[spec.kind] = spec

    def start(
        self,
        session_id: str,
        kind: str,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if self._stopped.is_set():
            raise RuntimeError("external job adapter is stopped")
        with self._lock:
            spec = self._specs.get(kind)
        if spec is None:
            self._record("job_policy_denied", session_id, "", kind, "unknown_kind")
            raise KeyError("external job kind is not registered")
        if self._audit_degraded or not self._record("job_policy", session_id, "", kind, "allow"):
            raise OSError("External job audit unavailable; process start denied")
        safe_payload = _json_payload(payload)
        operation = self._registry.create(session_id, kind)
        operation_id = operation["operation_id"]
        work_dir = (self._jobs_root / operation_id).resolve()
        work_dir.mkdir(parents=False, exist_ok=False)
        request_path = work_dir / "request.json"
        _atomic_json(request_path, safe_payload)
        args = [str(item) for item in spec.build_args(safe_payload, str(request_path))]
        if not args:
            raise ValueError("external job produced no arguments")
        popen_args = [spec.executable] + args
        popen_options: Dict[str, Any] = {
            "cwd": str(work_dir),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "shell": False,
        }
        if os.name == "nt":
            popen_options["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            popen_options["start_new_session"] = True
        try:
            process = subprocess.Popen(popen_args, **popen_options)
        except Exception:
            self._registry.transition(
                session_id, operation_id, "failed", error_code="process_start"
            )
            self._record("job_exit", session_id, operation_id, kind, "process_start")
            raise
        job = _ActiveJob(session_id, operation_id, spec, work_dir, process)
        with self._lock:
            self._active[operation_id] = job
        self._registry.transition(session_id, operation_id, "running", progress=0.0)
        self._record("job_start", session_id, operation_id, kind, "allow")
        threading.Thread(
            target=self._monitor,
            args=(job,),
            name="external-job-" + operation_id[:8],
            daemon=True,
        ).start()
        return self.get(session_id, operation_id)

    def get(self, session_id: str, operation_id: str) -> Optional[Dict[str, Any]]:
        operation = self._registry.get(session_id, operation_id)
        if operation is not None and self._audit_degraded:
            operation = dict(operation, audit_status="degraded", replay_safe=False,
                             audit_warning="Job audit is incomplete; new process starts are blocked.")
        return operation

    def cancel(self, session_id: str, operation_id: str) -> Dict[str, Any]:
        current = self._registry.get(session_id, operation_id)
        if current is None:
            raise KeyError("operation not found")
        if current["state"] in _TERMINAL_STATES:
            return current
        with self._lock:
            job = self._active.get(operation_id)
        if job is None or job.session_id != session_id:
            raise KeyError("active operation not found")
        job.cancel_requested.set()
        self._terminate(job.process)
        self._record("job_cancel", session_id, operation_id, job.spec.kind, "allow")
        return self._registry.get(session_id, operation_id)

    def shutdown(self) -> None:
        if self._stopped.is_set():
            return
        self._stopped.set()
        with self._lock:
            jobs = list(self._active.values())
        for job in jobs:
            job.cancel_requested.set()
            self._terminate(job.process)
        for job in jobs:
            job.done.wait(timeout=5.0)

    def _monitor(self, job: _ActiveJob) -> None:
        stdout_lines = []
        stderr_lines = []
        output_lock = threading.Lock()
        error_code = ""
        artifact_events: Dict[str, str] = {}
        result_holder: Dict[str, Optional[Dict[str, Any]]] = {"value": None}

        def read_stdout() -> None:
            nonlocal error_code
            assert job.process.stdout is not None
            for line in job.process.stdout:
                with output_lock:
                    stdout_lines.append(line)
                if error_code or job.cancel_requested.is_set():
                    continue
                try:
                    self._consume_event(job, line, artifact_events, result_holder)
                except ValueError:
                    error_code = "invalid_event"
                    self._terminate(job.process)

        def read_stderr() -> None:
            assert job.process.stderr is not None
            for line in job.process.stderr:
                with output_lock:
                    stderr_lines.append(line)

        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        try:
            try:
                job.process.wait(timeout=job.spec.timeout)
            except subprocess.TimeoutExpired:
                error_code = "timeout"
                self._terminate(job.process)
                job.process.wait(timeout=5.0)
            stdout_thread.join(timeout=5.0)
            stderr_thread.join(timeout=5.0)
            with output_lock:
                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)
            _write_bounded(job.work_dir / "stdout.log", stdout, job.spec.max_log_bytes)
            _write_bounded(job.work_dir / "stderr.log", stderr, job.spec.max_log_bytes)
            result = result_holder["value"]
            exit_code = job.process.returncode
            if job.cancel_requested.is_set():
                state = "cancelled"
                error_code = ""
            elif error_code:
                state = "failed"
            elif exit_code != 0:
                state = "failed"
                error_code = "process_exit"
            else:
                try:
                    artifacts = self._validate_artifacts(job, artifact_events)
                except FileNotFoundError:
                    state = "failed"
                    error_code = "artifact_missing"
                    artifacts = []
                except ValueError:
                    state = "failed"
                    error_code = "artifact_invalid"
                    artifacts = []
                else:
                    state = "completed"
            if state != "completed":
                artifacts = []
                result = None
            self._registry.transition(
                job.session_id,
                job.operation_id,
                state,
                progress=1.0 if state == "completed" else None,
                error_code=error_code,
                exit_code=exit_code,
                artifacts=artifacts,
                result=result,
            )
            self._record(
                "job_exit", job.session_id, job.operation_id, job.spec.kind,
                error_code or state, exit_code=exit_code,
                artifacts=artifacts,
            )
        except Exception:
            current = self._registry.get(job.session_id, job.operation_id)
            if current and current["state"] not in _TERMINAL_STATES:
                self._terminate(job.process)
                self._registry.transition(
                    job.session_id,
                    job.operation_id,
                    "failed",
                    error_code="monitor_error",
                    exit_code=job.process.poll(),
                )
            self._record(
                "job_exit", job.session_id, job.operation_id, job.spec.kind,
                "monitor_error", exit_code=job.process.poll(),
            )
        finally:
            for stream in (job.process.stdout, job.process.stderr):
                if stream is not None:
                    stream.close()
            with self._lock:
                self._active.pop(job.operation_id, None)
            job.done.set()

    def _consume_event(
        self,
        job: _ActiveJob,
        line: str,
        artifacts: Dict[str, str],
        result_holder: Dict[str, Optional[Dict[str, Any]]],
    ) -> None:
        if not line.strip():
            return
        if len(line.encode("utf-8")) > job.spec.max_event_bytes:
            raise ValueError("external job event is too large")
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            raise ValueError("external job event is not valid JSON")
        event_type = event.get("type") if isinstance(event, dict) else None
        if event_type == "progress":
            self._registry.update_progress(
                job.session_id,
                job.operation_id,
                float(event["progress"]),
                stage=str(event.get("stage") or "")[:128],
            )
        elif event_type == "artifact":
            name = str(event.get("name") or "")
            relative = str(event.get("path") or "")
            if name not in job.spec.artifacts:
                raise ValueError("external job artifact is not declared")
            _validate_relative_path(relative)
            if relative != job.spec.artifacts[name][0]:
                raise ValueError("external job artifact path does not match spec")
            artifacts[name] = relative
        elif event_type == "result":
            summary = event.get("summary")
            result_holder["value"] = (
                dict(summary) if isinstance(summary, dict) else None
            )
        else:
            raise ValueError("external job event type is not allowed")

    def _validate_artifacts(
        self, job: _ActiveJob, events: Mapping[str, str]
    ) -> list:
        published = []
        for name in job.spec.required_artifacts:
            if name not in events:
                raise FileNotFoundError("required external job artifact was not announced")
        for name, relative in events.items():
            path = (job.work_dir / relative).resolve()
            if path.parent != job.work_dir or path.is_symlink():
                raise ValueError("external job artifact escapes its job directory")
            if not path.is_file():
                raise FileNotFoundError("external job artifact is missing")
            size = path.stat().st_size
            if size > job.spec.max_artifact_bytes:
                raise ValueError("external job artifact is too large")
            _declared_path, media_type = job.spec.artifacts[name]
            published.append({
                "name": name,
                "path": relative,
                "size": size,
                "media_type": media_type,
            })
        return published

    def _record(
        self,
        event_type: str,
        session_id: str,
        operation_id: str,
        kind: str,
        decision: str,
        exit_code: Optional[int] = None,
        artifacts: Optional[list] = None,
    ) -> bool:
        if self._audit is None:
            self._audit_degraded = True
            return False
        record = {
            "event_type": event_type,
            "session_id": session_id,
            "operation_id": operation_id,
            "kind": kind,
            "decision": decision,
        }
        if exit_code is not None:
            record["exit_code"] = exit_code
        if artifacts:
            record["artifacts"] = [
                {key: item[key] for key in ("name", "path", "size", "media_type")}
                for item in artifacts
            ]
        try:
            if self._audit(record) is not False:
                return True
        except Exception:
            pass
        self._audit_degraded = True
        return False

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                    shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _json_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("external job payload must be an object")
    try:
        encoded = json.dumps(dict(payload), ensure_ascii=True, separators=(",", ":"))
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        raise ValueError("external job payload must contain JSON values only")
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise ValueError("external job payload is too large")
    return decoded


def _validate_relative_path(value: str) -> None:
    path = Path(str(value or ""))
    if not value or path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError("external job artifact path must be a leaf relative path")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    partial = path.with_suffix(path.suffix + ".part")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(partial), str(path))


def _write_bounded(path: Path, text: str, limit: int) -> None:
    data = (text or "").encode("utf-8", errors="replace")[:max(0, int(limit))]
    partial = path.with_suffix(path.suffix + ".part")
    with partial.open("wb") as stream:
        stream.write(data)
    os.replace(str(partial), str(path))