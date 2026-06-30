# -*- coding: utf-8 -*-
"""
三层记忆存储模块 (Memory Store)

使用 SQLite + 本地 Embedding 实现：
- Episodic Memory  (事件记忆：具体经历)
- Semantic Memory  (抽象知识：反思生成的经验规则)
- Procedural Memory (策略记忆：解决问题的套路)

向量检索使用 numpy cosine similarity（记忆条目通常 <10000 条，无需 FAISS）。
"""

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .embedding import get_embedder, LocalEmbedder
from shared.user_paths import UserPaths, normalize_username

# ============================================================
# 数据库路径
# ============================================================

_DB_DIR = Path(__file__).parent.parent.parent / "cache" / "memory"
_DB_PATH = _DB_DIR / "agent_memory.db"

# ============================================================
# 数据类
# ============================================================

@dataclass
class EpisodicRecord:
    """事件记忆记录"""
    id: str = ""
    timestamp: float = 0.0
    session_id: str = ""
    task_description: str = ""
    actions: List[dict] = field(default_factory=list)     # 工具调用序列
    result_summary: str = ""
    success: bool = True
    error_count: int = 0
    retry_count: int = 0
    reward_score: float = 0.0
    embedding: Optional[np.ndarray] = None
    importance: float = 1.0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# 用途分类常量
MEMORY_CATEGORIES = (
    "preference",     # 日常偏好（代码风格、输出语言、格式）
    "command",        # 构建命令（编译、测试、部署常用命令）
    "debug",          # 调试模式（调试思路和路径）
    "pitfall",        # 踩坑记录（特殊限制和陷阱）
    "workflow",       # 工作流模式（节点连接、操作序列）
    "knowledge",      # 技术知识（节点用法、VEX 语法）
    "user_profile",   # 用户画像（工作领域、技能水平）
    "general",        # 其他通用经验
)

# 抽象层级常量（6 层）
ABSTRACTION_LEVELS = {
    0: "core_identity",   # 核心身份：用户身份、核心偏好、语言习惯（极少极精炼）
    1: "core_preference",  # 核心偏好：代码风格、格式偏好、交互习惯
    2: "experience_rule",  # 经验规则：可复用经验、最佳实践、调试思路
    3: "workflow_pattern",  # 工作流模式：具体工作流、命令序列、节点连接
    4: "specific_case",    # 具体案例：特定任务的成功/失败记录、踩坑详情
    5: "raw_detail",       # 原始细节：对话片段、参数细节、临时记录
}


@dataclass
class SemanticRecord:
    """抽象知识记录"""
    id: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    rule: str = ""
    source_episodes: List[str] = field(default_factory=list)
    confidence: float = 0.5
    activation_count: int = 0
    embedding: Optional[np.ndarray] = None
    category: str = "general"  # preference / command / debug / pitfall / workflow / knowledge / user_profile / general
    abstraction_level: int = 2  # 0-5，默认 2（经验规则），见 ABSTRACTION_LEVELS

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now
        if self.category not in MEMORY_CATEGORIES:
            self.category = "general"


@dataclass
class ProceduralRecord:
    """策略记忆记录"""
    id: str = ""
    strategy_name: str = ""
    description: str = ""
    priority: float = 0.5
    success_rate: float = 0.5
    usage_count: int = 0
    last_used: float = 0.0
    embedding: Optional[np.ndarray] = None
    conditions: List[str] = field(default_factory=list)   # 适用条件

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.last_used == 0.0:
            self.last_used = time.time()


# ============================================================
# Memory Store 核心类
# ============================================================

class MemoryStore:
    """三层记忆 SQLite 存储 + Embedding 向量检索"""

    def __init__(self, db_path: Optional[Path] = None, embedder: Optional[LocalEmbedder] = None):
        self.db_path = db_path or _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedder()
        self._conn: Optional[sqlite3.Connection] = None
        self._force_delete = False  # 网络盘 fallback: 跳过 WAL，直接用 DELETE 模式
        # 单连接多线程共享时，必须由上层显式串行化访问。
        self._db_lock = threading.RLock()
        self._init_db()

    # ==========================================================
    # 数据库初始化
    # ==========================================================

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            if self._force_delete:
                # 已知网络盘，直接跳过 WAL 尝试
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA synchronous=FULL")
                print("[Memory] 使用 DELETE 模式（网络盘兼容）")
            else:
                try:
                    result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
                    if result and result[0] == "wal":
                        conn.execute("PRAGMA synchronous=NORMAL")
                    else:
                        # WAL 未生效（如网络盘），回退 DELETE 模式
                        conn.execute("PRAGMA journal_mode=DELETE")
                        conn.execute("PRAGMA synchronous=FULL")
                        print("[Memory] WAL 不可用，使用 DELETE 模式（网络盘兼容）")
                except sqlite3.DatabaseError:
                    # WAL 锁协议失败（SMB/NFS），关闭损坏连接并重建
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = sqlite3.connect(
                        str(self.db_path),
                        check_same_thread=False,
                        timeout=30.0,
                    )
                    conn.execute("PRAGMA journal_mode=DELETE")
                    conn.execute("PRAGMA synchronous=FULL")
                    print("[Memory] WAL 不可用，使用 DELETE 模式（网络盘兼容）")
            conn.execute("PRAGMA busy_timeout=30000")
            self._conn = conn
        return self._conn

    def _execute(self, sql: str, params: tuple = ()):
        with self._db_lock:
            return self._get_conn().execute(sql, params)

    def _fetchone(self, sql: str, params: tuple = ()):
        with self._db_lock:
            return self._get_conn().execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple = ()):
        with self._db_lock:
            return self._get_conn().execute(sql, params).fetchall()

    def _commit(self):
        with self._db_lock:
            self._get_conn().commit()

    def _rank_by_embedding(
        self,
        table: str,
        query: str,
        where_sql: str,
        where_params: tuple,
        top_k: int,
        weight_col: str,
        weight_fn,
        sim_threshold: float = 0.0,
    ) -> List[Tuple[str, float, float]]:
        """检索路径瘦身：只拉 (id, embedding, weight_col) 算相似度，返回 top-k 的 id。

        weight_fn(sim, weight) -> combined_score
        Returns: [(id, sim, combined), ...] 按 combined 降序
        """
        query_vec = self.embedder.encode(query)
        sql = f"SELECT id, embedding, {weight_col} FROM {table} WHERE {where_sql}"
        rows = self._fetchall(sql, where_params)
        if not rows:
            return []
        scored: List[Tuple[str, float, float]] = []
        for rec_id, emb_blob, weight in rows:
            if not emb_blob:
                continue
            emb = self.embedder.from_bytes(emb_blob)
            sim = self.embedder.cosine_similarity(query_vec, emb)
            if sim < sim_threshold:
                continue
            scored.append((rec_id, sim, weight_fn(sim, weight)))
        scored.sort(key=lambda x: x[2], reverse=True)
        return scored[:top_k]

    def _init_db(self):
        with self._db_lock:
            try:
                self._init_db_with_conn()
            except sqlite3.DatabaseError as e:
                if "locking protocol" in str(e).lower() or "unable to open" in str(e).lower():
                    # WAL 模式在网络盘上写入失败，重置连接并强制 DELETE 模式重试
                    print(f"[Memory] 检测到网络盘锁协议问题，切换 DELETE 模式重试: {e}")
                    try:
                        if self._conn:
                            self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
                    self._force_delete = True
                    self._init_db_with_conn()
                else:
                    raise

    def _init_db_with_conn(self):
        with self._db_lock:
            conn = self._get_conn()
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodic_memory (
                id TEXT PRIMARY KEY,
                timestamp REAL,
                session_id TEXT,
                task_description TEXT,
                actions TEXT,
                result_summary TEXT,
                success INTEGER,
                error_count INTEGER,
                retry_count INTEGER,
                reward_score REAL,
                embedding BLOB,
                importance REAL,
                tags TEXT
            );

            CREATE TABLE IF NOT EXISTS semantic_memory (
                id TEXT PRIMARY KEY,
                created_at REAL,
                updated_at REAL,
                rule TEXT,
                source_episodes TEXT,
                confidence REAL,
                activation_count INTEGER,
                embedding BLOB,
                category TEXT
            );

            CREATE TABLE IF NOT EXISTS procedural_memory (
                id TEXT PRIMARY KEY,
                strategy_name TEXT,
                description TEXT,
                priority REAL,
                success_rate REAL,
                usage_count INTEGER,
                last_used REAL,
                embedding BLOB,
                conditions TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memory(session_id);
            CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic_memory(timestamp);
            CREATE INDEX IF NOT EXISTS idx_episodic_importance ON episodic_memory(importance);
            CREATE INDEX IF NOT EXISTS idx_semantic_category ON semantic_memory(category);
            CREATE INDEX IF NOT EXISTS idx_semantic_confidence ON semantic_memory(confidence);
            CREATE INDEX IF NOT EXISTS idx_procedural_priority ON procedural_memory(priority);
        """)
            conn.commit()
            # ── DB migration: 添加 abstraction_level 列（兼容旧数据库） ──
            self._migrate_add_abstraction_level(conn)

    @staticmethod
    def _migrate_add_abstraction_level(conn: sqlite3.Connection):
        """为 semantic_memory 表添加 abstraction_level 列（兼容旧 DB）"""
        try:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(semantic_memory)").fetchall()]
            if "abstraction_level" not in cols:
                conn.execute("ALTER TABLE semantic_memory ADD COLUMN abstraction_level INTEGER DEFAULT 2")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_abstraction ON semantic_memory(abstraction_level)")
                conn.commit()
                print("[MemoryStore] Migration: 已添加 abstraction_level 列")
        except Exception as e:
            print(f"[MemoryStore] Migration 失败 (非致命): {e}")

    def close(self):
        with self._db_lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    # ==========================================================
    # Episodic Memory CRUD
    # ==========================================================

    def add_episodic(self, record: EpisodicRecord) -> str:
        """写入一条事件记忆"""
        # 自动计算 embedding
        if record.embedding is None:
            text = f"{record.task_description} {record.result_summary}"
            record.embedding = self.embedder.encode(text)

        self._execute(
            """INSERT OR REPLACE INTO episodic_memory
               (id, timestamp, session_id, task_description, actions,
                result_summary, success, error_count, retry_count,
                reward_score, embedding, importance, tags)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.timestamp,
                record.session_id,
                record.task_description,
                json.dumps(record.actions, ensure_ascii=False),
                record.result_summary,
                1 if record.success else 0,
                record.error_count,
                record.retry_count,
                record.reward_score,
                self.embedder.to_bytes(record.embedding),
                record.importance,
                json.dumps(record.tags, ensure_ascii=False),
            ),
        )
        self._commit()
        return record.id

    def get_episodic(self, record_id: str) -> Optional[EpisodicRecord]:
        """根据 ID 获取事件记忆"""
        row = self._fetchone("SELECT * FROM episodic_memory WHERE id=?", (record_id,))
        if not row:
            return None
        return self._row_to_episodic(row)

    def get_recent_episodic(self, limit: int = 20) -> List[EpisodicRecord]:
        """获取最近的事件记忆"""
        rows = self._fetchall(
            "SELECT * FROM episodic_memory ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_episodic(r) for r in rows]

    def search_episodic(self, query: str, top_k: int = 5, min_importance: float = 0.1) -> List[Tuple[EpisodicRecord, float]]:
        """向量检索事件记忆

        Returns:
            [(record, similarity_score), ...] 按相似度降序
        """
        ranked = self._rank_by_embedding(
            table="episodic_memory",
            query=query,
            where_sql="importance >= ?",
            where_params=(min_importance,),
            top_k=top_k,
            weight_col="importance",
            weight_fn=lambda sim, imp: sim * (0.5 + 0.5 * min(imp, 2.0)),
        )
        if not ranked:
            return []
        # 按 id 回查完整记录，避免在检索路径反序列化 actions/tags JSON。
        id_to_score = {rid: combined for rid, _sim, combined in ranked}
        placeholders = ",".join("?" * len(id_to_score))
        rows = self._fetchall(
            f"SELECT * FROM episodic_memory WHERE id IN ({placeholders})",
            tuple(id_to_score.keys()),
        )
        results = []
        for row in rows:
            rec = self._row_to_episodic(row)
            results.append((rec, id_to_score[rec.id]))
        # 回查顺序不保证，按 combined 重排
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def update_episodic_importance(self, record_id: str, new_importance: float):
        """更新事件记忆的重要度"""
        self._execute(
            "UPDATE episodic_memory SET importance=? WHERE id=?",
            (new_importance, record_id)
        )
        self._commit()

    def update_episodic_reward(self, record_id: str, reward_score: float, importance: float):
        """更新事件记忆的 reward 和 importance"""
        self._execute(
            "UPDATE episodic_memory SET reward_score=?, importance=? WHERE id=?",
            (reward_score, importance, record_id)
        )
        self._commit()

    def update_episodic_tags(self, record_id: str, tags: List[str]):
        """更新事件记忆的 tags"""
        self._execute(
            "UPDATE episodic_memory SET tags=? WHERE id=?",
            (json.dumps(tags, ensure_ascii=False), record_id)
        )
        self._commit()

    def count_episodic(self) -> int:
        """统计事件记忆总数"""
        row = self._fetchone("SELECT COUNT(*) FROM episodic_memory")
        return row[0] if row else 0

    def get_episodic_by_session(self, session_id: str) -> List[EpisodicRecord]:
        """获取某个 session 的所有事件记忆"""
        rows = self._fetchall(
            "SELECT * FROM episodic_memory WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,)
        )
        return [self._row_to_episodic(r) for r in rows]

    def delete_episodic(self, record_id: str) -> bool:
        """删除一条事件记忆"""
        cur = self._execute("DELETE FROM episodic_memory WHERE id=?", (record_id,))
        self._commit()
        return cur.rowcount > 0

    # ==========================================================
    # Semantic Memory CRUD
    # ==========================================================

    def _scale_similarity_threshold(self, threshold: float) -> float:
        """根据 embedding 后端缩放相似度阈值。"""
        if self.embedder.is_semantic:
            return threshold
        # fallback embedding (n-gram hash) 相似度值域显著偏低。
        return threshold * 0.2

    def add_semantic(self, record: SemanticRecord) -> str:
        """写入一条抽象知识"""
        if record.embedding is None:
            record.embedding = self.embedder.encode(record.rule)

        self._execute(
            """INSERT OR REPLACE INTO semantic_memory
               (id, created_at, updated_at, rule, source_episodes,
                confidence, activation_count, embedding, category, abstraction_level)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.created_at,
                record.updated_at,
                record.rule,
                json.dumps(record.source_episodes, ensure_ascii=False),
                record.confidence,
                record.activation_count,
                self.embedder.to_bytes(record.embedding),
                record.category,
                record.abstraction_level,
            ),
        )
        self._commit()
        return record.id

    def get_semantic(self, record_id: str) -> Optional[SemanticRecord]:
        """根据 ID 获取抽象知识"""
        row = self._fetchone("SELECT * FROM semantic_memory WHERE id=?", (record_id,))
        if not row:
            return None
        return self._row_to_semantic(row)

    def search_semantic(self, query: str, top_k: int = 5, min_confidence: float = 0.2) -> List[Tuple[SemanticRecord, float]]:
        """向量检索抽象知识"""
        ranked = self._rank_by_embedding(
            table="semantic_memory",
            query=query,
            where_sql="confidence >= ?",
            where_params=(min_confidence,),
            top_k=top_k,
            weight_col="confidence",
            weight_fn=lambda sim, conf: sim * (0.5 + 0.5 * conf),
        )
        if not ranked:
            return []
        id_to_score = {rid: combined for rid, _sim, combined in ranked}
        placeholders = ",".join("?" * len(id_to_score))
        rows = self._fetchall(
            f"SELECT * FROM semantic_memory WHERE id IN ({placeholders})",
            tuple(id_to_score.keys()),
        )
        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            results.append((rec, id_to_score[rec.id]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_all_semantic(self, category: Optional[str] = None) -> List[SemanticRecord]:
        """获取所有抽象知识（可按分类过滤）"""
        if category:
            rows = self._fetchall(
                "SELECT * FROM semantic_memory WHERE category=? ORDER BY confidence DESC",
                (category,)
            )
        else:
            rows = self._fetchall("SELECT * FROM semantic_memory ORDER BY confidence DESC")
        return [self._row_to_semantic(r) for r in rows]

    def increment_semantic_activation(self, record_id: str):
        """增加抽象知识的激活次数"""
        self._execute(
            "UPDATE semantic_memory SET activation_count = activation_count + 1, updated_at=? WHERE id=?",
            (time.time(), record_id)
        )
        self._commit()

    def update_semantic_confidence(self, record_id: str, confidence: float):
        """更新抽象知识的置信度"""
        self._execute(
            "UPDATE semantic_memory SET confidence=?, updated_at=? WHERE id=?",
            (confidence, time.time(), record_id)
        )
        self._commit()

    def find_duplicate_semantic(self, rule_text: str, threshold: float = 0.85) -> Optional[SemanticRecord]:
        """查找是否已存在高度相似的规则（去重用）

        注意：去重必须用纯相似度 sim，不能用 search_semantic 返回的 combined
        （combined = sim * (0.5 + 0.5*confidence) 会被低置信度压低，导致漏判重复）。
        """
        query_vec = self.embedder.encode(rule_text)
        rows = self._fetchall("SELECT id, embedding FROM semantic_memory")
        if not rows:
            return None

        effective_threshold = self._scale_similarity_threshold(threshold)
        best_id: Optional[str] = None
        best_sim: float = -1.0
        for rec_id, emb_blob in rows:
            if not emb_blob:
                continue
            emb = self.embedder.from_bytes(emb_blob)
            sim = self.embedder.cosine_similarity(query_vec, emb)
            if sim > best_sim:
                best_sim = sim
                best_id = rec_id

        if best_id is not None and best_sim >= effective_threshold:
            return self.get_semantic(best_id)
        return None

    def delete_semantic(self, record_id: str):
        """删除指定语义记忆"""
        self._execute("DELETE FROM semantic_memory WHERE id=?", (record_id,))
        self._commit()

    def count_semantic(self) -> int:
        row = self._fetchone("SELECT COUNT(*) FROM semantic_memory")
        return row[0] if row else 0

    # ==========================================================
    # 分层记忆检索（6 层抽象层级）
    # ==========================================================

    def get_core_memories(self, max_count: int = 5) -> List[SemanticRecord]:
        """获取 level=0 核心记忆，按 confidence 降序，最多 max_count 条"""
        rows = self._fetchall(
            "SELECT * FROM semantic_memory WHERE abstraction_level = 0 ORDER BY confidence DESC LIMIT ?",
            (max_count,)
        )
        return [self._row_to_semantic(r) for r in rows]

    def search_by_level(
        self, query: str, level: int, top_k: int = 3,
        min_confidence: float = 0.2, threshold: float = 0.25,
    ) -> List[Tuple[SemanticRecord, float]]:
        """按指定层级搜索记忆 chunk

        Args:
            query: 搜索查询
            level: 抽象层级 (0-5)
            top_k: 返回条数上限
            min_confidence: 最低置信度过滤
            threshold: 最低相似度阈值（会根据 embedding 后端自动缩放）

        Returns:
            [(record, similarity_score), ...] 按综合分降序
        """
        # fallback embedding (n-gram hash) 的相似度值域偏低，需要动态缩放阈值。
        effective_threshold = self._scale_similarity_threshold(threshold)
        ranked = self._rank_by_embedding(
            table="semantic_memory",
            query=query,
            where_sql="abstraction_level = ? AND confidence >= ?",
            where_params=(level, min_confidence),
            top_k=top_k,
            weight_col="confidence",
            weight_fn=lambda sim, conf: sim * (0.5 + 0.5 * conf),
            sim_threshold=effective_threshold,
        )
        if not ranked:
            return []
        id_to_score = {rid: combined for rid, _sim, combined in ranked}
        placeholders = ",".join("?" * len(id_to_score))
        rows = self._fetchall(
            f"SELECT * FROM semantic_memory WHERE id IN ({placeholders})",
            tuple(id_to_score.keys()),
        )
        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            results.append((rec, id_to_score[rec.id]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def search_all_levels(
        self, query: str, category: Optional[str] = None,
        top_k: int = 5, min_confidence: float = 0.1,
    ) -> List[Tuple[SemanticRecord, float]]:
        """跨层级搜索（供 search_memory 工具使用），可按 category 过滤

        Args:
            query: 搜索查询
            category: 用途分类过滤（可选）
            top_k: 返回条数上限
            min_confidence: 最低置信度过滤

        Returns:
            [(record, similarity_score), ...] 按综合分降序
        """
        if category:
            where_sql, where_params = "category = ? AND confidence >= ?", (category, min_confidence)
        else:
            where_sql, where_params = "confidence >= ?", (min_confidence,)
        ranked = self._rank_by_embedding(
            table="semantic_memory",
            query=query,
            where_sql=where_sql,
            where_params=where_params,
            top_k=top_k,
            weight_col="confidence",
            weight_fn=lambda sim, conf: sim * (0.5 + 0.5 * conf),
        )
        if not ranked:
            return []
        id_to_score = {rid: combined for rid, _sim, combined in ranked}
        placeholders = ",".join("?" * len(id_to_score))
        rows = self._fetchall(
            f"SELECT * FROM semantic_memory WHERE id IN ({placeholders})",
            tuple(id_to_score.keys()),
        )
        results = []
        for row in rows:
            rec = self._row_to_semantic(row)
            results.append((rec, id_to_score[rec.id]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    # ==========================================================
    # Procedural Memory CRUD
    # ==========================================================

    def add_procedural(self, record: ProceduralRecord) -> str:
        """写入一条策略记忆"""
        if record.embedding is None:
            text = f"{record.strategy_name}: {record.description}"
            record.embedding = self.embedder.encode(text)

        self._execute(
            """INSERT OR REPLACE INTO procedural_memory
               (id, strategy_name, description, priority, success_rate,
                usage_count, last_used, embedding, conditions)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                record.id,
                record.strategy_name,
                record.description,
                record.priority,
                record.success_rate,
                record.usage_count,
                record.last_used,
                self.embedder.to_bytes(record.embedding),
                json.dumps(record.conditions, ensure_ascii=False),
            ),
        )
        self._commit()
        return record.id

    def get_procedural(self, record_id: str) -> Optional[ProceduralRecord]:
        row = self._fetchone("SELECT * FROM procedural_memory WHERE id=?", (record_id,))
        if not row:
            return None
        return self._row_to_procedural(row)

    def search_procedural(self, query: str, top_k: int = 3) -> List[Tuple[ProceduralRecord, float]]:
        """向量检索策略记忆"""
        ranked = self._rank_by_embedding(
            table="procedural_memory",
            query=query,
            where_sql="1=1",
            where_params=(),
            top_k=top_k,
            weight_col="priority",
            weight_fn=lambda sim, prio: sim * (0.3 + 0.7 * prio),
        )
        if not ranked:
            return []
        id_to_score = {rid: combined for rid, _sim, combined in ranked}
        placeholders = ",".join("?" * len(id_to_score))
        rows = self._fetchall(
            f"SELECT * FROM procedural_memory WHERE id IN ({placeholders})",
            tuple(id_to_score.keys()),
        )
        results = []
        for row in rows:
            rec = self._row_to_procedural(row)
            results.append((rec, id_to_score[rec.id]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def get_all_procedural(self) -> List[ProceduralRecord]:
        rows = self._fetchall("SELECT * FROM procedural_memory ORDER BY priority DESC")
        return [self._row_to_procedural(r) for r in rows]

    def update_procedural_usage(self, record_id: str, success: bool):
        """更新策略使用统计（原子化，避免读改写丢更新）

        success_rate 用滑动平均：alpha = min(0.3, 1/usage_count)，
        在 SQL 里用 CASE 递增 usage_count 后再算 alpha。
        """
        now = time.time()
        success_val = 1.0 if success else 0.0
        with self._db_lock:
            conn = self._get_conn()
            # 单条 SQL 完成递增 + 滑动平均，避免 read-modify-write 的并发丢更新。
            conn.execute(
                """
                UPDATE procedural_memory
                SET usage_count = usage_count + 1,
                    last_used = ?,
                    success_rate = (
                        CASE
                            WHEN usage_count + 1 <= 3
                                THEN (1.0 - 1.0 / (usage_count + 1)) * success_rate
                                     + (1.0 / (usage_count + 1)) * ?
                            ELSE 0.7 * success_rate + 0.3 * ?
                        END
                    )
                WHERE id = ?
                """,
                (now, success_val, success_val, record_id),
            )
            conn.commit()

    def update_procedural_priority(self, record_id: str, priority_delta: float):
        """调整策略优先级"""
        self._execute(
            "UPDATE procedural_memory SET priority = MIN(1.0, MAX(0.0, priority + ?)) WHERE id=?",
            (priority_delta, record_id)
        )
        self._commit()

    def count_procedural(self) -> int:
        row = self._fetchone("SELECT COUNT(*) FROM procedural_memory")
        return row[0] if row else 0

    def delete_procedural(self, record_id: str) -> bool:
        """删除一条策略记忆"""
        cur = self._execute("DELETE FROM procedural_memory WHERE id=?", (record_id,))
        self._commit()
        return cur.rowcount > 0

    def get_procedural_by_name(self, name: str) -> Optional[ProceduralRecord]:
        """按策略名查找"""
        row = self._fetchone("SELECT * FROM procedural_memory WHERE strategy_name=?", (name,))
        if not row:
            return None
        return self._row_to_procedural(row)

    # ==========================================================
    # 全局重要度衰减
    # ==========================================================

    def decay_importance(self, lambda_decay: float = 0.01):
        """对所有 episodic 记忆执行时间衰减

        importance *= exp(-lambda * days_since_creation)
        """
        with self._db_lock:
            conn = self._get_conn()
            now = time.time()
            # 早退：只处理 importance 仍高于下限+epsilon 的记录，
            # 已经接近 0.01 下限的不再扫描/更新。
            rows = conn.execute(
                "SELECT id, timestamp, importance FROM episodic_memory WHERE importance > 0.011"
            ).fetchall()
            for row_id, ts, imp in rows:
                days = (now - ts) / 86400.0
                new_imp = imp * math.exp(-lambda_decay * days)
                new_imp = max(new_imp, 0.01)  # 不完全归零
                if abs(new_imp - imp) > 0.001:
                    conn.execute(
                        "UPDATE episodic_memory SET importance=? WHERE id=?",
                        (new_imp, row_id)
                    )
            conn.commit()

    def decay_semantic_confidence(self, lambda_decay: float = 0.003) -> int:
        """对 semantic 记忆执行时间衰减。

        规则：越久未激活、激活次数越少的规则衰减越快；L0/L1 核心记忆保留较高下限。
        Returns:
            更新条目数
        """
        updated = 0
        with self._db_lock:
            conn = self._get_conn()
            now = time.time()
            # 早退：跳过已经接近最低下限(0.05)的记录，避免无意义扫描。
            rows = conn.execute(
                "SELECT id, updated_at, confidence, activation_count, abstraction_level "
                "FROM semantic_memory WHERE confidence > 0.051"
            ).fetchall()

            for rec_id, updated_at, confidence, activation_count, abstraction_level in rows:
                days = max(0.0, (now - (updated_at or now)) / 86400.0)
                act_factor = 1.0 + math.log1p(max(0, activation_count))
                decay_multiplier = math.exp(-lambda_decay * days / act_factor)
                new_conf = confidence * decay_multiplier

                # 核心记忆保底，避免用户偏好被过度淡化。
                if abstraction_level <= 1:
                    min_floor = 0.45
                elif abstraction_level == 2:
                    min_floor = 0.10
                else:
                    min_floor = 0.05

                new_conf = max(min_floor, min(1.0, new_conf))
                if abs(new_conf - confidence) > 0.001:
                    conn.execute(
                        "UPDATE semantic_memory SET confidence=?, updated_at=? WHERE id=?",
                        (new_conf, now, rec_id),
                    )
                    updated += 1

            conn.commit()
        return updated

    def decay_procedural_priority(self, lambda_decay: float = 0.002) -> int:
        """对 procedural 策略优先级执行时间衰减。

        规则：长期未使用且成功率低的策略会逐渐降级；高成功率策略保底更高。
        Returns:
            更新条目数
        """
        updated = 0
        with self._db_lock:
            conn = self._get_conn()
            now = time.time()
            # 早退：跳过已经接近最低下限(0.15)的记录。
            rows = conn.execute(
                "SELECT id, last_used, priority, success_rate, usage_count "
                "FROM procedural_memory WHERE priority > 0.151"
            ).fetchall()

            for rec_id, last_used, priority, success_rate, usage_count in rows:
                days = max(0.0, (now - (last_used or now)) / 86400.0)
                usage_factor = 1.0 + math.log1p(max(0, usage_count))
                decay_multiplier = math.exp(-lambda_decay * days / usage_factor)
                decayed = priority * decay_multiplier

                # 高成功率策略更稳定，低成功率策略允许更低优先级。
                quality_floor = 0.15 + 0.25 * max(0.0, min(1.0, success_rate))
                new_priority = max(quality_floor, min(1.0, decayed))

                if abs(new_priority - priority) > 0.001:
                    conn.execute(
                        "UPDATE procedural_memory SET priority=? WHERE id=?",
                        (new_priority, rec_id),
                    )
                    updated += 1

            conn.commit()
        return updated

    def prune_semantic_memories(
        self,
        max_count: int = 1200,
        stale_days: float = 45.0,
        min_confidence: float = 0.22,
        min_activation: int = 1,
    ) -> int:
        """清理低质量 semantic 记忆，优先删除长期未激活且低置信度条目。"""
        now = time.time()
        stale_cutoff = now - stale_days * 86400.0
        deleted = 0

        with self._db_lock:
            conn = self._get_conn()

            # 1) 删除明显低价值且陈旧的数据（不动 L0/L1）。
            cur = conn.execute(
                """
                DELETE FROM semantic_memory
                WHERE abstraction_level >= 2
                  AND confidence < ?
                  AND activation_count <= ?
                  AND updated_at < ?
                """,
                (min_confidence, min_activation, stale_cutoff),
            )
            deleted += cur.rowcount if cur.rowcount > 0 else 0

            # 2) 超过容量上限时，再按质量排序删除尾部。
            row = conn.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()
            total = row[0] if row else 0
            overflow = max(0, total - max_count)
            if overflow > 0:
                ids = conn.execute(
                    """
                    SELECT id FROM semantic_memory
                    WHERE abstraction_level >= 2
                    ORDER BY confidence ASC, activation_count ASC, updated_at ASC
                    LIMIT ?
                    """,
                    (overflow,),
                ).fetchall()
                if ids:
                    conn.executemany(
                        "DELETE FROM semantic_memory WHERE id=?",
                        ids,
                    )
                    deleted += len(ids)

            conn.commit()

        return deleted

    def prune_procedural_memories(
        self,
        max_count: int = 300,
        stale_days: float = 60.0,
        min_priority: float = 0.25,
        min_success_rate: float = 0.30,
    ) -> int:
        """清理低价值 procedural 策略。"""
        now = time.time()
        stale_cutoff = now - stale_days * 86400.0
        deleted = 0

        with self._db_lock:
            conn = self._get_conn()

            cur = conn.execute(
                """
                DELETE FROM procedural_memory
                WHERE usage_count = 0
                  AND priority < ?
                  AND success_rate < ?
                  AND last_used < ?
                """,
                (min_priority, min_success_rate, stale_cutoff),
            )
            deleted += cur.rowcount if cur.rowcount > 0 else 0

            row = conn.execute("SELECT COUNT(*) FROM procedural_memory").fetchone()
            total = row[0] if row else 0
            overflow = max(0, total - max_count)
            if overflow > 0:
                ids = conn.execute(
                    """
                    SELECT id FROM procedural_memory
                    ORDER BY priority ASC, success_rate ASC, usage_count ASC, last_used ASC
                    LIMIT ?
                    """,
                    (overflow,),
                ).fetchall()
                if ids:
                    conn.executemany(
                        "DELETE FROM procedural_memory WHERE id=?",
                        ids,
                    )
                    deleted += len(ids)

            conn.commit()

        return deleted

    def maintain_long_term_memory(self) -> Dict[str, int]:
        """执行长期记忆维护：衰减 + 淘汰。"""
        semantic_decayed = self.decay_semantic_confidence()
        procedural_decayed = self.decay_procedural_priority()
        semantic_pruned = self.prune_semantic_memories()
        procedural_pruned = self.prune_procedural_memories()
        return {
            "semantic_decayed": semantic_decayed,
            "procedural_decayed": procedural_decayed,
            "semantic_pruned": semantic_pruned,
            "procedural_pruned": procedural_pruned,
        }

    # ==========================================================
    # 统计信息
    # ==========================================================

    def get_stats(self) -> Dict:
        """获取记忆库统计信息"""
        return {
            "episodic_count": self.count_episodic(),
            "semantic_count": self.count_semantic(),
            "procedural_count": self.count_procedural(),
            "backend": self.embedder._backend,
            "embedding_dim": self.embedder.dim,
        }

    # ==========================================================
    # 内部工具方法
    # ==========================================================

    def _row_to_episodic(self, row) -> EpisodicRecord:
        return EpisodicRecord(
            id=row[0],
            timestamp=row[1],
            session_id=row[2],
            task_description=row[3],
            actions=json.loads(row[4]) if row[4] else [],
            result_summary=row[5],
            success=bool(row[6]),
            error_count=row[7],
            retry_count=row[8],
            reward_score=row[9],
            embedding=self.embedder.from_bytes(row[10]) if row[10] else None,
            importance=row[11],
            tags=json.loads(row[12]) if row[12] else [],
        )

    def _row_to_semantic(self, row) -> SemanticRecord:
        return SemanticRecord(
            id=row[0],
            created_at=row[1],
            updated_at=row[2],
            rule=row[3],
            source_episodes=json.loads(row[4]) if row[4] else [],
            confidence=row[5],
            activation_count=row[6],
            embedding=self.embedder.from_bytes(row[7]) if row[7] else None,
            category=row[8],
            abstraction_level=row[9] if len(row) > 9 and row[9] is not None else 2,
        )

    def _row_to_procedural(self, row) -> ProceduralRecord:
        return ProceduralRecord(
            id=row[0],
            strategy_name=row[1],
            description=row[2],
            priority=row[3],
            success_rate=row[4],
            usage_count=row[5],
            last_used=row[6],
            embedding=self.embedder.from_bytes(row[7]) if row[7] else None,
            conditions=json.loads(row[8]) if row[8] else [],
        )

    # ==========================================================
    # 初始化默认策略
    # ==========================================================

    def seed_default_strategies(self):
        """写入默认策略（首次运行时调用）"""
        if self.count_procedural() > 0:
            return  # 已有策略，跳过

        defaults = [
            ProceduralRecord(
                strategy_name="decompose_complex_task",
                description="复杂问题应该分解为多个子步骤，逐步执行",
                priority=0.7,
                conditions=["task_complexity > high", "tool_calls > 5"],
            ),
            ProceduralRecord(
                strategy_name="clarify_ambiguous_task",
                description="不确定的任务应该先提问澄清，避免盲目执行",
                priority=0.6,
                conditions=["task_clarity < low", "missing_parameters"],
            ),
            ProceduralRecord(
                strategy_name="multi_path_reasoning",
                description="高风险任务应该多路径推理，对比不同方案后选择最优",
                priority=0.5,
                conditions=["risk_level > high", "irreversible_action"],
            ),
            ProceduralRecord(
                strategy_name="verify_before_modify",
                description="修改节点或文件前，先查询现有结构确认状态",
                priority=0.65,
                conditions=["action_type == modify", "target_unknown"],
            ),
            ProceduralRecord(
                strategy_name="error_recovery",
                description="遇到错误后，分析错误信息，尝试替代方案而非重复相同操作",
                priority=0.7,
                conditions=["error_occurred", "retry_count > 1"],
            ),
        ]

        for s in defaults:
            self.add_procedural(s)

        print(f"[MemoryStore] 已写入 {len(defaults)} 条默认策略")


# ============================================================
# 全局单例
# ============================================================

_store_instances: Dict[str, MemoryStore] = {}
_store_instances_lock = threading.RLock()

def get_memory_store(username: Optional[str] = None) -> MemoryStore:
    """获取 MemoryStore 实例（按用户隔离）。"""
    global _store_instances
    if not username:
        key = "default"
        with _store_instances_lock:
            if key not in _store_instances:
                _store_instances[key] = MemoryStore()
                _store_instances[key].seed_default_strategies()
            return _store_instances[key]

    uname = normalize_username(username)
    with _store_instances_lock:
        if uname not in _store_instances:
            user_paths = UserPaths(uname)
            user_paths.ensure_dirs()
            _store_instances[uname] = MemoryStore(db_path=user_paths.memory_db())
            _store_instances[uname].seed_default_strategies()
        return _store_instances[uname]
