# -*- coding: utf-8 -*-
"""Internal SQLite and embedding-provenance mechanics for memory stores."""

import sqlite3
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