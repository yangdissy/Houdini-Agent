# -*- coding: utf-8 -*-
"""一次性校验脚本：对比合并后的残留库与旧权威库。"""
import sqlite3
import sys

MERGED = r"C:\Users\yangdi\AppData\Local\Temp\hamem_restore_2b097f94\merged.db"
AUTHORITATIVE = r"U:\CG_VFX\sfxLib\sfx_third_party\houdini\extensions\Houdini-Agent\cache\users\yangdi\memory\agent_memory.db"

TABLES = ("episodic_memory", "semantic_memory", "procedural_memory")


def inspect(label: str, path: str) -> bool:
    uri = "file:" + path.replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    counts = {}
    for t in TABLES:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[t] = "missing"
    check = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.close()
    ok = str(check).lower() == "ok"
    print(f"{label}: counts={counts} quick_check={check}")
    return ok


if __name__ == "__main__":
    ok1 = inspect("merged(leftover+wal)", MERGED)
    ok2 = inspect("authoritative(old) ", AUTHORITATIVE)
    sys.exit(0 if (ok1 and ok2) else 1)
