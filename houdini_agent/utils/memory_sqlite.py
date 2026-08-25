# -*- coding: utf-8 -*-
"""Internal SQLite and embedding-provenance mechanics for memory stores."""

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


EMBEDDING_FORMAT_VERSION = 1


def embedding_metadata(embedder) -> Dict[str, str]:
    return {
        "backend": str(getattr(embedder, "_backend", "unknown")),
        "model": str(getattr(embedder, "model_name", "unknown")),
        "dimension": str(int(getattr(embedder, "dim", 0))),
        "format_version": str(EMBEDDING_FORMAT_VERSION),
    }


def open_sqlite(path, force_delete: bool = False) -> Tuple[sqlite3.Connection, bool]:
    """Open a memory DB, preferring WAL and falling back to durable DELETE mode."""
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    used_delete = force_delete
    if force_delete:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
    else:
        try:
            result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if result and str(result[0]).lower() == "wal":
                conn.execute("PRAGMA synchronous=NORMAL")
            else:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=FULL")
                used_delete = True
        except sqlite3.DatabaseError:
            conn.close()
            conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            used_delete = True
    conn.execute("PRAGMA busy_timeout=30000")
    return conn, used_delete


def ensure_metadata_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS embedding_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def read_embedding_metadata(conn: sqlite3.Connection) -> Dict[str, str]:
    ensure_metadata_table(conn)
    return dict(conn.execute("SELECT key, value FROM embedding_metadata").fetchall())


def write_embedding_metadata(conn: sqlite3.Connection, metadata: Dict[str, str]) -> None:
    ensure_metadata_table(conn)
    conn.execute("DELETE FROM embedding_metadata")
    conn.executemany(
        "INSERT INTO embedding_metadata(key, value) VALUES (?, ?)",
        sorted(metadata.items()),
    )


def metadata_diagnostic(stored: Dict[str, str], current: Dict[str, str]) -> Optional[str]:
    if not stored or any(key not in stored for key in current):
        return "legacy embedding database: provenance metadata is missing; vector scoring disabled"
    mismatches = [
        f"{key} stored={stored[key]!r} current={value!r}"
        for key, value in current.items()
        if stored.get(key) != value
    ]
    if mismatches:
        return "incompatible embedding database: " + ", ".join(mismatches) + "; vector scoring disabled"
    return None


_MEMORY_TABLES = ("episodic_memory", "semantic_memory", "procedural_memory")
_RECOVERY_FLAG_NAME = "memory_db_recovery.json"
_SQLITE_ARTIFACT_SUFFIXES = (".db", ".db-wal", ".db-shm", "-wal", "-shm")


def is_sqlite_artifact(path: Path) -> bool:
    """True for SQLite main/sidecar files that must not be copied as ordinary files."""
    name = Path(path).name.lower()
    return name.endswith(_SQLITE_ARTIFACT_SUFFIXES)


def copy_legacy_non_sqlite(src: Path, dst: Path) -> None:
    """Copy legacy cache files while skipping SQLite databases and sidecars."""
    import shutil

    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        for item in src.iterdir():
            source = src / item.name
            target = dst / item.name
            if source.is_dir():
                copy_legacy_non_sqlite(source, target)
                continue
            if target.exists() or is_sqlite_artifact(source):
                continue
            try:
                shutil.copy2(str(source), str(target))
            except Exception:
                pass
        return
    if not dst.exists() and not is_sqlite_artifact(src):
        try:
            shutil.copy2(str(src), str(dst))
        except Exception:
            pass


@dataclass(frozen=True)
class MemoryDbRecoveryResult:
    status: str
    message: str = ""
    source: Optional[Path] = None
    target: Optional[Path] = None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def inspect_memory_db(path: Path) -> Dict[str, object]:
    """Inspect an existing memory database without mutating it."""
    if not path.exists():
        return {"counts": {}, "fingerprint": ()}
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise sqlite3.DatabaseError(f"quick_check failed: {check}")
        counts = {}
        fingerprint = []
        for table in _MEMORY_TABLES:
            if _table_exists(conn, table):
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                ids = tuple(
                    row[0] for row in conn.execute(f"SELECT id FROM {table} ORDER BY id")
                )
            else:
                counts[table] = 0
                ids = ()
            fingerprint.append((table, counts[table], ids))
        return {"counts": counts, "fingerprint": tuple(fingerprint)}
    finally:
        conn.close()


def memory_db_has_user_records(snapshot: Dict[str, object]) -> bool:
    counts = snapshot.get("counts") if isinstance(snapshot, dict) else snapshot
    return any(int((counts or {}).get(table, 0) or 0) > 0 for table in _MEMORY_TABLES)


def _recovery_flag_path(user_root: Path) -> Path:
    return user_root / _RECOVERY_FLAG_NAME


def _write_recovery_flag(user_root: Path, payload: Dict[str, object]) -> None:
    flag_path = _recovery_flag_path(user_root)
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = flag_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(str(tmp_path), str(flag_path))


def restore_legacy_local_memory_db(user_paths) -> MemoryDbRecoveryResult:
    """Restore a leftover local DB into the authoritative user directory if needed."""
    target = Path(user_paths.memory_db())
    source = Path(user_paths.legacy_local_memory_db())
    flag_path = _recovery_flag_path(user_paths.user_root)
    if flag_path.exists():
        return MemoryDbRecoveryResult("skipped", "recovery already recorded", source, target)
    if not source.exists():
        return MemoryDbRecoveryResult("skipped", "no leftover local database", source, target)

    try:
        source_snapshot = inspect_memory_db(source)
    except Exception as exc:
        return MemoryDbRecoveryResult("failed", f"leftover local database is unreadable: {exc}", source, target)
    if not memory_db_has_user_records(source_snapshot):
        return MemoryDbRecoveryResult("skipped", "leftover local database has no user records", source, target)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            target_snapshot = inspect_memory_db(target)
        except Exception as exc:
            return MemoryDbRecoveryResult("conflict", f"authoritative database is unreadable: {exc}", source, target)
        if memory_db_has_user_records(target_snapshot) and target_snapshot.get("fingerprint") != source_snapshot.get("fingerprint"):
            return MemoryDbRecoveryResult(
                "conflict",
                "authoritative and leftover databases both contain records; automatic merge is disabled",
                source,
                target,
            )
        if memory_db_has_user_records(target_snapshot):
            _write_recovery_flag(user_paths.user_root, {
                "status": "equivalent",
                "timestamp": datetime.now().isoformat(),
                "source": str(source),
                "target": str(target),
            })
            return MemoryDbRecoveryResult("skipped", "authoritative database already has equivalent records", source, target)

    tmp_target = target.with_name(target.name + ".restore-tmp")
    if tmp_target.exists():
        tmp_target.unlink()
    src_conn = sqlite3.connect(str(source), timeout=30.0)
    dst_conn = sqlite3.connect(str(tmp_target), timeout=30.0)
    try:
        src_conn.backup(dst_conn)
        check = dst_conn.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise sqlite3.DatabaseError(f"restored database failed quick_check: {check}")
    except Exception as exc:
        try:
            dst_conn.close()
        except Exception:
            pass
        try:
            src_conn.close()
        except Exception:
            pass
        if tmp_target.exists():
            tmp_target.unlink()
        return MemoryDbRecoveryResult("failed", f"failed to restore leftover database: {exc}", source, target)
    dst_conn.close()
    src_conn.close()
    os.replace(str(tmp_target), str(target))
    _write_recovery_flag(user_paths.user_root, {
        "status": "restored",
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
    })
    return MemoryDbRecoveryResult("restored", "restored leftover local database to the user directory", source, target)


def overwrite_authoritative_with_leftover(user_paths) -> MemoryDbRecoveryResult:
    """User-confirmed: overwrite the authoritative DB with the leftover local DB.

    Backs up the current authoritative DB to agent_memory.db.pre-overwrite-backup
    before replacing, so the operation is reversible. Marks recovery as resolved so
    the conflict dialog does not reappear.
    """
    source = Path(user_paths.legacy_local_memory_db())
    target = Path(user_paths.memory_db())
    if not source.exists():
        return MemoryDbRecoveryResult("skipped", "no leftover local database", source, target)
    try:
        source_snapshot = inspect_memory_db(source)
    except Exception as exc:
        return MemoryDbRecoveryResult("failed", f"leftover local database is unreadable: {exc}", source, target)
    if not memory_db_has_user_records(source_snapshot):
        return MemoryDbRecoveryResult("skipped", "leftover local database has no user records", source, target)

    # 在临时目录把残留 db+wal 合并成完整快照，避免直接拷贝时丢失 WAL 里的最新写入
    tmp_target = target.with_name(target.name + ".overwrite-tmp")
    if tmp_target.exists():
        tmp_target.unlink()
    src_conn = sqlite3.connect(str(source), timeout=30.0)
    dst_conn = sqlite3.connect(str(tmp_target), timeout=30.0)
    try:
        src_conn.backup(dst_conn)
        check = dst_conn.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise sqlite3.DatabaseError(f"overwritten database failed quick_check: {check}")
    except Exception as exc:
        for conn in (dst_conn, src_conn):
            try:
                conn.close()
            except Exception:
                pass
        if tmp_target.exists():
            tmp_target.unlink()
        return MemoryDbRecoveryResult("failed", f"failed to overwrite with leftover database: {exc}", source, target)
    dst_conn.close()
    src_conn.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        backup = target.with_name(target.name + ".pre-overwrite-backup")
        if backup.exists():
            backup.unlink()
        os.replace(str(target), str(backup))
        for suffix in ("-wal", "-shm"):
            side = target.with_name(target.name + suffix)
            if side.exists():
                try:
                    side.unlink()
                except Exception:
                    pass

    os.replace(str(tmp_target), str(target))
    # 覆盖成功后清理本地残留库（历史 bug 产物）
    try:
        if source.exists():
            source.unlink()
        for suffix in ("-wal", "-shm"):
            side = source.with_name(source.name + suffix)
            if side.exists():
                side.unlink()
    except Exception:
        pass
    _write_recovery_flag(user_paths.user_root, {
        "status": "overwritten",
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
    })
    return MemoryDbRecoveryResult("restored", "用本地残留库覆盖了权威库", source, target)


def dismiss_memory_db_conflict(user_paths) -> MemoryDbRecoveryResult:
    """保留权威库：删除残留的本地库（历史 bug 产物），并写标记不再提示。"""
    source = Path(user_paths.legacy_local_memory_db())
    target = Path(user_paths.memory_db())
    try:
        if source.exists():
            source.unlink()
        for suffix in ("-wal", "-shm"):
            side = source.with_name(source.name + suffix)
            if side.exists():
                side.unlink()
    except Exception as exc:
        return MemoryDbRecoveryResult("failed", f"删除本地残留库失败: {exc}", source, target)
    _write_recovery_flag(user_paths.user_root, {
        "status": "kept_authoritative",
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
    })
    return MemoryDbRecoveryResult("skipped", "已保留权威库并删除本地残留库", source, target)