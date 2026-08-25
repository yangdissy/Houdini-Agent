# -*- coding: utf-8 -*-
"""
团队记忆库（Team Memory）— 只读的团队级共享记忆层。

由开发模式下手动触发的「重建团队记忆库」动作，从各成员
cache/users/<username>/memory/team_export.json 汇总去重后全量写入
cache/memory/team/team_memory.db。运行时只通过 search_memory 工具与
个人记忆库联合检索（不参与自动 system prompt 注入），对所有普通用户只读。

去重使用 embedding cosine similarity；不同 embedding 后端（sentence-transformers
vs fallback n-gram 哈希）的向量不在同一语义空间，因此只在同一后端内比较相似度，
避免跨后端误判为重复/误判为不重复。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from shared.user_paths import get_repo_root
from .embedding import LocalEmbedder, get_embedder
from .memory_sqlite import (
    embedding_metadata,
    metadata_diagnostic,
    open_sqlite,
    read_embedding_metadata,
    write_embedding_metadata,
)
from .team_memory_document import MAX_DIAGNOSTICS, parse_team_export_file

_TEAM_DB_DIR = Path(__file__).parent.parent.parent / "cache" / "memory" / "team"
_TEAM_DB_PATH = _TEAM_DB_DIR / "team_memory.db"

# 去重相似度阈值：同一 category + 同一 embedding 后端下，相似度达到此值视为重复经验。
DEDUP_SIMILARITY_THRESHOLD = 0.85


@dataclass
class TeamSemanticRecord:
    id: str = ""
    rule: str = ""
    category: str = "general"
    abstraction_level: int = 2
    confidence: float = 0.5
    embedding: Optional[np.ndarray] = None
    source_users: List[str] = field(default_factory=list)
    merged_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.merged_at == 0.0:
            self.merged_at = time.time()


@dataclass
class TeamProceduralRecord:
    id: str = ""
    strategy_name: str = ""
    description: str = ""
    priority: float = 0.5
    success_rate: float = 0.5
    embedding: Optional[np.ndarray] = None
    source_users: List[str] = field(default_factory=list)
    merged_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.merged_at == 0.0:
            self.merged_at = time.time()


class TeamMemoryStore:
    """团队共享记忆 SQLite 存储。写入仅通过 rebuild_team_memory() 全量重建。"""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        embedder: Optional[LocalEmbedder] = None,
        force_delete: bool = False,
    ):
        self.db_path = db_path or _TEAM_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedder()
        self._force_delete = force_delete
        self._conn = None
        self.embedding_diagnostic: Optional[str] = None
        self._db_lock = threading.RLock()
        self._init_db()

    def _get_conn(self):
        if self._conn is None:
            conn, _used_delete = open_sqlite(self.db_path, self._force_delete)
            self._conn = conn
        return self._conn

    def _init_db(self):
        with self._db_lock:
            conn = self._get_conn()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS team_semantic_memory (
                    id TEXT PRIMARY KEY,
                    rule TEXT,
                    category TEXT,
                    abstraction_level INTEGER,
                    confidence REAL,
                    embedding BLOB,
                    source_users TEXT,
                    merged_at REAL
                );
                CREATE TABLE IF NOT EXISTS team_procedural_memory (
                    id TEXT PRIMARY KEY,
                    strategy_name TEXT,
                    description TEXT,
                    priority REAL,
                    success_rate REAL,
                    embedding BLOB,
                    source_users TEXT,
                    merged_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_team_semantic_category ON team_semantic_memory(category);
                CREATE INDEX IF NOT EXISTS idx_team_procedural_priority ON team_procedural_memory(priority);
                """
            )
            conn.commit()
            current = embedding_metadata(self.embedder)
            stored = read_embedding_metadata(conn)
            has_vectors = any(
                conn.execute(f"SELECT 1 FROM {table} WHERE embedding IS NOT NULL AND length(embedding) > 0 LIMIT 1").fetchone()
                for table in ("team_semantic_memory", "team_procedural_memory")
            )
            if not has_vectors and not stored:
                write_embedding_metadata(conn, current)
                conn.commit()
            else:
                self.embedding_diagnostic = metadata_diagnostic(stored, current)

    def close(self):
        with self._db_lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def replace_all(
        self,
        semantic_records: List[TeamSemanticRecord],
        procedural_records: List[TeamProceduralRecord],
    ) -> None:
        """全量重建：单事务清空后写入新数据，避免中途失败留下半量数据。"""
        with self._db_lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM team_semantic_memory")
            conn.execute("DELETE FROM team_procedural_memory")
            for rec in semantic_records:
                conn.execute(
                    """INSERT OR REPLACE INTO team_semantic_memory
                       (id, rule, category, abstraction_level, confidence, embedding, source_users, merged_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        rec.id, rec.rule, rec.category, rec.abstraction_level, rec.confidence,
                        self.embedder.to_bytes(rec.embedding) if rec.embedding is not None else b"",
                        json.dumps(sorted(set(rec.source_users)), ensure_ascii=False),
                        rec.merged_at,
                    ),
                )
            for rec in procedural_records:
                conn.execute(
                    """INSERT OR REPLACE INTO team_procedural_memory
                       (id, strategy_name, description, priority, success_rate, embedding, source_users, merged_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        rec.id, rec.strategy_name, rec.description, rec.priority, rec.success_rate,
                        self.embedder.to_bytes(rec.embedding) if rec.embedding is not None else b"",
                        json.dumps(sorted(set(rec.source_users)), ensure_ascii=False),
                        rec.merged_at,
                    ),
                )
            write_embedding_metadata(conn, embedding_metadata(self.embedder))
            conn.commit()
            self.embedding_diagnostic = None

    def count_semantic(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) FROM team_semantic_memory").fetchone()
        return row[0] if row else 0

    def count_procedural(self) -> int:
        row = self._get_conn().execute("SELECT COUNT(*) FROM team_procedural_memory").fetchone()
        return row[0] if row else 0

    def search_semantic(
        self, query: str, top_k: int = 5, category: Optional[str] = None,
    ) -> List[Tuple[TeamSemanticRecord, float]]:
        if self.embedding_diagnostic:
            print(f"[TeamMemoryStore] {self.embedding_diagnostic}")
            return []
        query_vec = self.embedder.encode(query)
        with self._db_lock:
            conn = self._get_conn()
            if category:
                rows = conn.execute(
                    "SELECT id, rule, category, abstraction_level, confidence, embedding, "
                    "source_users, merged_at FROM team_semantic_memory WHERE category=?",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, rule, category, abstraction_level, confidence, embedding, "
                    "source_users, merged_at FROM team_semantic_memory"
                ).fetchall()
        scored = []
        for row in rows:
            emb_blob = row[5]
            if not emb_blob:
                continue
            emb = self.embedder.from_bytes(emb_blob)
            sim = self.embedder.cosine_similarity(query_vec, emb)
            scored.append((row, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for row, sim in scored[:top_k]:
            rec = TeamSemanticRecord(
                id=row[0], rule=row[1], category=row[2], abstraction_level=row[3],
                confidence=row[4], embedding=self.embedder.from_bytes(row[5]),
                source_users=json.loads(row[6]) if row[6] else [], merged_at=row[7],
            )
            results.append((rec, sim))
        return results

    def search_procedural(self, query: str, top_k: int = 3) -> List[Tuple[TeamProceduralRecord, float]]:
        if self.embedding_diagnostic:
            print(f"[TeamMemoryStore] {self.embedding_diagnostic}")
            return []
        query_vec = self.embedder.encode(query)
        with self._db_lock:
            rows = self._get_conn().execute(
                "SELECT id, strategy_name, description, priority, success_rate, embedding, "
                "source_users, merged_at FROM team_procedural_memory"
            ).fetchall()
        scored = []
        for row in rows:
            emb_blob = row[5]
            if not emb_blob:
                continue
            emb = self.embedder.from_bytes(emb_blob)
            sim = self.embedder.cosine_similarity(query_vec, emb)
            scored.append((row, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        results = []
        for row, sim in scored[:top_k]:
            rec = TeamProceduralRecord(
                id=row[0], strategy_name=row[1], description=row[2], priority=row[3],
                success_rate=row[4], embedding=self.embedder.from_bytes(row[5]),
                source_users=json.loads(row[6]) if row[6] else [], merged_at=row[7],
            )
            results.append((rec, sim))
        return results


# ============================================================
# 全局单例
# ============================================================

_team_store_instance: Optional[TeamMemoryStore] = None
_team_store_lock = threading.RLock()


def get_team_memory_store() -> TeamMemoryStore:
    global _team_store_instance
    with _team_store_lock:
        if _team_store_instance is None:
            _team_store_instance = TeamMemoryStore()
        return _team_store_instance


def _refresh_team_memory_singleton(db_path: Path, embedder: LocalEmbedder) -> None:
    global _team_store_instance
    if Path(db_path) != _TEAM_DB_PATH:
        return
    with _team_store_lock:
        old_store = _team_store_instance
        _team_store_instance = TeamMemoryStore(db_path=db_path, embedder=embedder)
        if old_store is not None:
            old_store.close()


def _close_live_team_singleton(db_path: Path) -> bool:
    global _team_store_instance
    if Path(db_path) != _TEAM_DB_PATH:
        return False
    with _team_store_lock:
        if _team_store_instance is None:
            return False
        _team_store_instance.close()
        _team_store_instance = None
        return True


# ============================================================
# 开发模式：全量重建（扫描所有成员导出 + 去重合并）
# ============================================================

def _iter_export_files():
    users_root = Path(get_repo_root()) / "cache" / "users"
    if not users_root.exists():
        return
    for user_dir in sorted(users_root.iterdir()):
        if not user_dir.is_dir():
            continue
        export_path = user_dir / "memory" / "team_export.json"
        if export_path.exists():
            yield user_dir.name, export_path


def _to_vector(item: dict) -> Optional[np.ndarray]:
    emb = item.get("embedding")
    if not emb:
        return None
    try:
        return np.array(emb, dtype=np.float32)
    except Exception:
        return None


def _dedup_semantic(raw_items: List[dict]) -> List[TeamSemanticRecord]:
    buckets: Dict[Tuple[str, str], List[dict]] = {}
    for item in raw_items:
        category = item.get("category")
        provenance = (
            item.get("embedding_backend", "unknown"),
            item.get("embedding_model", "unknown"),
            item.get("embedding_dimension"),
            item.get("embedding_format_version"),
        )
        buckets.setdefault((category, provenance), []).append(item)

    merged: List[TeamSemanticRecord] = []
    for (category, _provenance), items in buckets.items():
        items.sort(key=lambda x: float(x.get("confidence", 0.0)), reverse=True)
        used = [False] * len(items)
        for i, base in enumerate(items):
            if used[i]:
                continue
            used[i] = True
            base_vec = _to_vector(base)
            group_users = {base.get("_source_user")}
            best_conf = float(base.get("confidence", 0.0))
            best_item = base
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                other = items[j]
                other_vec = _to_vector(other)
                sim = 0.0
                if base_vec is not None and other_vec is not None and len(base_vec) == len(other_vec):
                    sim = LocalEmbedder.cosine_similarity(base_vec, other_vec)
                if sim >= DEDUP_SIMILARITY_THRESHOLD:
                    used[j] = True
                    group_users.add(other.get("_source_user"))
                    other_conf = float(other.get("confidence", 0.0))
                    if other_conf > best_conf:
                        best_conf = other_conf
                        best_item = other
            merged.append(
                TeamSemanticRecord(
                    rule=best_item.get("rule", ""),
                    category=category,
                    abstraction_level=int(best_item.get("abstraction_level", 2)),
                    confidence=best_conf,
                    embedding=_to_vector(best_item),
                    source_users=sorted({u for u in group_users if u}),
                )
            )
    return merged


def _dedup_procedural(raw_items: List[dict]) -> List[TeamProceduralRecord]:
    buckets: Dict[str, List[dict]] = {}
    for item in raw_items:
        provenance = (
            item.get("embedding_backend", "unknown"),
            item.get("embedding_model", "unknown"),
            item.get("embedding_dimension"),
            item.get("embedding_format_version"),
        )
        buckets.setdefault(provenance, []).append(item)

    merged: List[TeamProceduralRecord] = []
    for _provenance, items in buckets.items():
        items.sort(key=lambda x: float(x.get("success_rate", 0.0)), reverse=True)
        used = [False] * len(items)
        for i, base in enumerate(items):
            if used[i]:
                continue
            used[i] = True
            base_vec = _to_vector(base)
            group_users = {base.get("_source_user")}
            best_rate = float(base.get("success_rate", 0.0))
            best_item = base
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                other = items[j]
                # 策略名相同，或 embedding 高度相似，都视为同一策略。
                same_name = other.get("strategy_name") == base.get("strategy_name")
                other_vec = _to_vector(other)
                sim = 0.0
                if base_vec is not None and other_vec is not None and len(base_vec) == len(other_vec):
                    sim = LocalEmbedder.cosine_similarity(base_vec, other_vec)
                if same_name or sim >= DEDUP_SIMILARITY_THRESHOLD:
                    used[j] = True
                    group_users.add(other.get("_source_user"))
                    other_rate = float(other.get("success_rate", 0.0))
                    if other_rate > best_rate:
                        best_rate = other_rate
                        best_item = other
            merged.append(
                TeamProceduralRecord(
                    strategy_name=best_item.get("strategy_name", ""),
                    description=best_item.get("description", ""),
                    priority=float(best_item.get("priority", 0.5)),
                    success_rate=best_rate,
                    embedding=_to_vector(best_item),
                    source_users=sorted({u for u in group_users if u}),
                )
            )
    return merged


def rebuild_team_memory(
    embedder: Optional[LocalEmbedder] = None,
    db_path: Optional[Path] = None,
    export_files: Optional[List[Tuple[str, Path]]] = None,
) -> Dict[str, Any]:
    """开发模式手动触发：全量扫描所有 team_export.json，去重合并写入 team_memory.db。

    Args:
        embedder: 复用的 embedder 实例（测试用）
        db_path: 写入目标（测试用，默认共享盘 cache/memory/team/team_memory.db）
        export_files: 显式指定要扫描的 (username, path) 列表（测试用，默认扫描
                       cache/users/*/memory/team_export.json）
    """
    embedder = embedder or get_embedder()
    raw_semantic: List[dict] = []
    raw_procedural: List[dict] = []
    scanned_users = 0
    skipped_files = 0
    valid_documents = 0
    invalid_entries = 0
    ineligible_entries = 0
    ineligible_reasons: Dict[str, int] = {}
    diagnostics = []

    files = export_files if export_files is not None else list(_iter_export_files())
    for username, export_path in files:
        parsed = parse_team_export_file(Path(export_path), username)
        if not parsed.valid_document:
            skipped_files += 1
            diagnostics.extend(d.to_dict() for d in parsed.diagnostics[:MAX_DIAGNOSTICS - len(diagnostics)])
            continue
        scanned_users += 1
        valid_documents += 1
        invalid_entries += parsed.invalid_entries
        ineligible_entries += parsed.ineligible_entries
        for reason, count in parsed.ineligible_reasons.items():
            ineligible_reasons[reason] = ineligible_reasons.get(reason, 0) + count
        diagnostics.extend(d.to_dict() for d in parsed.diagnostics[:MAX_DIAGNOSTICS - len(diagnostics)])
        raw_semantic.extend(parsed.semantic)
        raw_procedural.extend(parsed.procedural)

    if files and valid_documents == 0:
        raise RuntimeError("No valid Team Memory export documents; existing database was preserved")

    merged_semantic = _dedup_semantic(raw_semantic)
    merged_procedural = _dedup_procedural(raw_procedural)
    for record in merged_semantic:
        record.embedding = embedder.encode(record.rule)
    for record in merged_procedural:
        record.embedding = embedder.encode(f"{record.strategy_name}: {record.description}")

    live_path = Path(db_path) if db_path is not None else _TEAM_DB_PATH
    live_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = live_path.with_name(f".{live_path.name}.{uuid.uuid4().hex}.tmp")
    store = TeamMemoryStore(db_path=temp_path, embedder=embedder, force_delete=True)
    try:
        store.replace_all(merged_semantic, merged_procedural)
        if store.embedding_diagnostic:
            raise RuntimeError(store.embedding_diagnostic)
        if store.count_semantic() != len(merged_semantic) or store.count_procedural() != len(merged_procedural):
            raise RuntimeError("Team Memory shadow database record-count validation failed")
        if store._get_conn().execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Team Memory shadow database integrity validation failed")
    finally:
        store.close()
    closed_singleton = _close_live_team_singleton(live_path)
    try:
        os.replace(str(temp_path), str(live_path))
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        if closed_singleton:
            _refresh_team_memory_singleton(live_path, embedder)
        raise
    _refresh_team_memory_singleton(live_path, embedder)

    return {
        "scanned_users": scanned_users,
        "skipped_files": skipped_files,
        "valid_documents": valid_documents,
        "invalid_entries": invalid_entries,
        "ineligible_entries": ineligible_entries,
        "ineligible_reasons": ineligible_reasons,
        "diagnostics": diagnostics,
        "semantic_raw": len(raw_semantic),
        "procedural_raw": len(raw_procedural),
        "semantic_merged": len(merged_semantic),
        "procedural_merged": len(merged_procedural),
    }
