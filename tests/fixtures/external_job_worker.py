# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def emit(event):
    print(json.dumps(event, separators=(",", ":")), flush=True)


def main():
    request_path = sys.argv[1]
    work_dir = os.path.dirname(os.path.abspath(request_path))
    with open(request_path, encoding="utf-8") as stream:
        request = json.load(stream)
    mode = request.get("mode", "success")

    if mode == "failure":
        print("worker failed", file=sys.stderr, flush=True)
        return 7
    if mode == "hang":
        while True:
            time.sleep(0.1)
    if mode == "child":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        while True:
            time.sleep(0.1)

    emit({"type": "progress", "progress": 0.25, "stage": "preparing"})
    if mode == "invalid_event":
        emit({"type": "unknown"})
        return 0
    if mode == "escape":
        emit({"type": "artifact", "name": "result", "path": "../result.json"})
        return 0
    if mode == "missing":
        emit({"type": "artifact", "name": "result", "path": "result.json"})
        return 0

    result_path = os.path.join(work_dir, "result.json")
    with open(result_path + ".part", "w", encoding="utf-8") as stream:
        json.dump({"ok": True}, stream)
    os.replace(result_path + ".part", result_path)
    emit({"type": "artifact", "name": "result", "path": "result.json"})
    emit({"type": "progress", "progress": 1.0, "stage": "finished"})
    emit({"type": "result", "summary": {"ok": True}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())