# -*- coding: utf-8 -*-
"""一次性合并脚本：权威库 ∪ 残留库 -> 新库。

策略：逐表做行级并集。canonical 键 = 全行内容元组（排除 id 列）。
- 内容完全相同的行视为同一条，只保留一份（id 取任一）。
- 内容不同的行都保留，重新分配连续 id，避免 id 冲突。
这比按 id 合并更安全：id 是两库各自独立分配的主键，同 id 不代表同一条记忆。

用法:
    python _merge_mem_dbs.py <authoritative.db> <leftover_dir> <out.db>

<leftover_dir> 需包含 agent_memory.db.leftover-backup / -wal / -shm。
"""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

TABLES = ("episodic_memory", "semantic_memory", "procedural_memory")


def snapshot(db_path: Path, out_path: Path) -> None:
    """把源库（含 wal，若同目录存在）备份成一个独立完整快照。"""
    src = sqlite3.connect(str(db_path), timeout=30)
    src.execute("PRAGMA busy_timeout=30000")
    dst = sqlite3.connect(str(out_path), timeout=30)
    src.backup(dst)
    dst.close()
    src.close()


def table_columns(conn: sqlite3.Connection, table: str):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # (cid, name, type, notnull, dflt, pk)
    return [r[1] for r in rows], [r[5] for r in rows]


def main() -> int:
    auth_db = Path(sys.argv[1])
    leftover_dir = Path(sys.argv[2])
    out_db = Path(sys.argv[3])

    work = Path(tempfile.mkdtemp(prefix="hamem_merge_"))

    # 1) 残留库 db+wal -> 独立快照
    leftover_main = leftover_dir / "agent_memory.db"
    shutil.copy(leftover_dir / "agent_memory.db.leftover-backup", leftover_main)
    for suffix in ("-wal", "-shm"):
        src = leftover_dir / f"agent_memory.db{suffix}"
        if src.exists():
            shutil.copy(src, leftover_dir / f"agent_memory.db{suffix}.copy")
            shutil.move(str(leftover_dir / f"agent_memory.db{suffix}.copy"),
                        str(leftover_main.parent / f"agent_memory.db{suffix}"))
    leftover_snap = work / "leftover_snap.db"
    snapshot(leftover_main, leftover_snap)

    # 2) 权威库（实时，含自身 wal）-> 独立快照
    auth_snap = work / "auth_snap.db"
    snapshot(auth_db, auth_snap)

    # 3) 以残留快照为基底，向其中补插权威快照里内容不同的行
    shutil.copy(leftover_snap, out_db)
    out = sqlite3.connect(str(out_db), timeout=30)
    auth = sqlite3.connect(str(auth_snap), timeout=30)

    report = {}
    for table in TABLES:
        out_cols, _ = table_columns(out, table)
        auth_cols, _ = table_columns(auth, table)
        if not out_cols or not auth_cols:
            report[table] = "skipped(missing in one db)"
            continue
        if out_cols != auth_cols:
            report[table] = f"SCHEMA_MISMATCH out={out_cols} auth={auth_cols}"
            continue

        non_id = [c for c in out_cols if c != "id"]
        col_list = ", ".join(f'"{c}"' for c in non_id)

        existing = set()
        for row in out.execute(f"SELECT {col_list} FROM {table}"):
            existing.add(row)

        inserted = 0
        skipped = 0
        for row in auth.execute(f"SELECT {col_list} FROM {table}"):
            if row in existing:
                skipped += 1
                continue
            placeholders = ", ".join("?" for _ in non_id)
            out.execute(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", row)
            existing.add(row)
            inserted += 1

        total = out.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        report[table] = f"inserted={inserted} dup_skipped={skipped} total={total}"

    out.commit()
    check = out.execute("PRAGMA quick_check").fetchone()[0]
    out.close()
    auth.close()

    print(f"workdir: {work}")
    for t, r in report.items():
        print(f"  {t}: {r}")
    print(f"quick_check: {check}")
    print(f"OUT_DB={out_db}")
    return 0 if str(check).lower() == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
