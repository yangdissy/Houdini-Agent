from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


def main():
    mode = sys.argv[1]
    if mode == "hang":
        time.sleep(60)
        return 0
    output = {
        "home": os.environ.get("HOME"),
        "prefs": os.environ.get("HOUDINI_USER_PREF_DIR"),
        "hip": os.environ.get("HIP"),
        "cwd": os.getcwd(),
    }
    Path("environment.json").write_text(json.dumps(output), encoding="utf-8")
    return 7 if mode == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
