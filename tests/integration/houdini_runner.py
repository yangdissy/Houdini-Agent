from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Mapping, Optional, Sequence
import uuid


@dataclass(frozen=True)
class ProcessRunResult:
    status: str
    exit_code: Optional[int]
    artifact_dir: Optional[Path]
    stdout: str
    stderr: str


class IsolatedProcessRunner:
    def __init__(self, artifacts_root: Path, timeout: float = 60.0):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._artifacts_root = Path(artifacts_root).resolve()
        self._timeout = timeout

    def run(
        self,
        executable: Path,
        args: Sequence[str],
        *,
        repository_root: Path,
        extra_env: Optional[Mapping[str, str]] = None,
    ) -> ProcessRunResult:
        run_id = uuid.uuid4().hex
        self._artifacts_root.mkdir(parents=True, exist_ok=True)
        work_root = self._artifacts_root / run_id
        work_root.mkdir()
        paths = self._create_layout(work_root)
        env = self._build_environment(
            executable=Path(executable).resolve(),
            repository_root=Path(repository_root).resolve(),
            paths=paths,
            extra_env=extra_env,
        )
        manifest_path = work_root / "manifest.json"
        stdout_path = work_root / "stdout.log"
        stderr_path = work_root / "stderr.log"
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "starting",
            "started_at": time.time(),
            "executable": str(Path(executable).resolve()),
        }
        self._write_json(manifest_path, manifest)
        process = None
        timed_out = False
        try:
            popen_options = {
                "cwd": str(paths["artifacts"]),
                "env": env,
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
            process = subprocess.Popen(
                [str(executable)] + [str(item) for item in args],
                **popen_options,
            )
            manifest.update({"status": "running", "pid": process.pid})
            self._write_json(manifest_path, manifest)
            try:
                stdout, stderr = process.communicate(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_tree(process)
                stdout, stderr = process.communicate(timeout=5.0)
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")
            status = "timeout" if timed_out else (
                "passed" if process.returncode == 0 else "failed"
            )
            manifest.update({
                "status": status,
                "exit_code": process.returncode,
                "finished_at": time.time(),
            })
            self._write_json(manifest_path, manifest)
            if status == "passed":
                shutil.rmtree(work_root)
                try:
                    self._artifacts_root.rmdir()
                except OSError:
                    pass
                return ProcessRunResult(status, process.returncode, None, stdout, stderr)
            return ProcessRunResult(status, process.returncode, work_root, stdout, stderr)
        except Exception:
            if process is not None and process.poll() is None:
                self._terminate_tree(process)
            manifest.update({"status": "runner_error", "finished_at": time.time()})
            self._write_json(manifest_path, manifest)
            raise RuntimeError(f"isolated process runner failed; artifacts: {work_root}")

    @staticmethod
    def _create_layout(root: Path):
        paths = {}
        for name in (
            "prefs", "home", "appdata", "localappdata", "temp", "hip",
            "job", "packages", "artifacts",
        ):
            path = root / name
            path.mkdir()
            paths[name] = path
        return paths

    @staticmethod
    def _build_environment(executable, repository_root, paths, extra_env):
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        executable_dir = str(executable.parent)
        system32 = str(Path(system_root) / "System32")
        env = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "COMSPEC": os.environ.get("COMSPEC", str(Path(system32) / "cmd.exe")),
            "PATH": os.pathsep.join((executable_dir, system32, system_root)),
            "PYTHONPATH": str(repository_root),
            "PYTHONIOENCODING": "utf-8",
            "HOUDINI_USER_PREF_DIR": str(paths["prefs"] / "__HVER__"),
            "HOME": str(paths["home"]),
            "USERPROFILE": str(paths["home"]),
            "APPDATA": str(paths["appdata"]),
            "LOCALAPPDATA": str(paths["localappdata"]),
            "TEMP": str(paths["temp"]),
            "TMP": str(paths["temp"]),
            "HOUDINI_TEMP_DIR": str(paths["temp"]),
            "HIP": str(paths["hip"]),
            "JOB": str(paths["job"]),
            "HOUDINI_AGENT_DEV_RELOAD": "0",
            "HOUDINI_AGENT_SELECTION_WATCH": "0",
            "HOUDINI_AGENT_USE_TIKTOKEN": "0",
            "HOUDINI_AGENT_DIAGNOSTICS_RETENTION": "0",
            "HOUDINI_TEST_ROOT": str(paths["artifacts"].parent),
        }
        hfs = executable.parent.parent
        if (hfs / "bin").is_dir():
            env["HFS"] = str(hfs)
        if extra_env:
            for key, value in extra_env.items():
                if key.upper().endswith("API_KEY") or "PROXY" in key.upper():
                    raise ValueError(f"forbidden environment key: {key}")
                env[str(key)] = str(value)
        return env

    @staticmethod
    def _terminate_tree(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
        else:
            os.killpg(process.pid, 9)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)

    @staticmethod
    def _write_json(path, payload):
        path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
