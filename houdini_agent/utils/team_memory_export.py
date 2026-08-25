# -*- coding: utf-8 -*-
"""
团队记忆导出 — 把个人长期记忆里符合团队共享条件的记录导出到共享盘。

触发时机：浅睡眠 / 深度睡眠维护周期结束后（见 send_orchestrator_mixin.py），
非致命、后台执行，不阻塞主流程。

隐私边界：
- 只导出技术类 category（command/debug/pitfall/workflow/knowledge/general），
  排除 preference（个人偏好）与 user_profile（用户画像/身份信息）。
- 只导出中间抽象层级 L2-L4（经验规则/工作流模式/具体案例），
  排除 L0/L1（核心身份/核心偏好）与 L5（原始细节，可能含对话片段）。
- 只导出 Semantic / Procedural（抽象后的知识/策略），不导出 Episodic 原始事件记录。
- 达不到质量阈值（低置信度、低成功率、未充分验证）的记录不导出。

用户可在设置里随时关闭导出（见 team_memory_settings.py），默认开启。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from shared.user_paths import UserPaths, normalize_username
from .memory_store import MemoryStore
from .memory_sqlite import EMBEDDING_FORMAT_VERSION
from .team_memory_document import (
    ELIGIBLE_ABSTRACTION_LEVELS,
    ELIGIBLE_SEMANTIC_CATEGORIES,
    MIN_PROCEDURAL_SUCCESS_RATE,
    MIN_PROCEDURAL_USAGE,
    MIN_SEMANTIC_CONFIDENCE,
    build_export_document,
    procedural_eligibility,
    semantic_eligibility,
)
from .team_memory_settings import is_team_export_enabled

def _semantic_export_entry(record) -> Optional[dict]:
    if not semantic_eligibility(record)[0]:
        return None
    return {
        "rule": record.rule,
        "category": record.category,
        "abstraction_level": record.abstraction_level,
        "confidence": record.confidence,
        "embedding": record.embedding.tolist() if record.embedding is not None else None,
    }


def _procedural_export_entry(record) -> Optional[dict]:
    if not procedural_eligibility(record)[0]:
        return None
    return {
        "strategy_name": record.strategy_name,
        "description": record.description,
        "priority": record.priority,
        "success_rate": record.success_rate,
        "usage_count": record.usage_count,
        "embedding": record.embedding.tolist() if record.embedding is not None else None,
    }


def build_team_export_payload(store: MemoryStore) -> Dict:
    """从个人 MemoryStore 里筛出符合团队共享条件的记录（供导出/测试复用）。"""
    semantic_entries = []
    for record in store.get_all_semantic():
        entry = _semantic_export_entry(record)
        if entry:
            semantic_entries.append(entry)

    procedural_entries = []
    for record in store.get_all_procedural():
        entry = _procedural_export_entry(record)
        if entry:
            procedural_entries.append(entry)

    # 记录 embedding 后端：不同后端的向量不在同一语义空间，合并去重时需要区分。
    backend = str(getattr(store.embedder, "_backend", "unknown"))
    model = str(getattr(store.embedder, "model_name", "unknown"))
    dimension = int(getattr(store.embedder, "dim", 0))
    for entry in semantic_entries:
        entry["embedding_backend"] = backend
        entry["embedding_model"] = model
        entry["embedding_dimension"] = dimension
        entry["embedding_format_version"] = EMBEDDING_FORMAT_VERSION
    for entry in procedural_entries:
        entry["embedding_backend"] = backend
        entry["embedding_model"] = model
        entry["embedding_dimension"] = dimension
        entry["embedding_format_version"] = EMBEDDING_FORMAT_VERSION

    return {
        "embedding_provenance": {
            "backend": backend,
            "model": model,
            "dimension": dimension,
            "format_version": EMBEDDING_FORMAT_VERSION,
        },
        "semantic": semantic_entries,
        "procedural": procedural_entries,
    }


def export_team_memory(username: str, store: MemoryStore) -> Optional[Path]:
    """把符合条件的个人记忆导出到共享盘，供开发模式「重建团队记忆库」使用。

    若用户已关闭团队记忆共享开关，直接跳过（返回 None）。
    """
    uname = normalize_username(username)
    if not is_team_export_enabled(uname):
        return None

    payload = build_team_export_payload(store)
    payload = build_export_document(
        username=uname,
        exported_at=time.time(),
        semantic=payload["semantic"],
        procedural=payload["procedural"],
    )

    user_paths = UserPaths(uname)
    user_paths.ensure_dirs()
    export_path = user_paths.memory_dir() / "team_export.json"
    tmp_path = export_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(export_path)
    return export_path


def maybe_export_team_memory(username: str, store: Optional[MemoryStore]) -> None:
    """非致命地尝试导出；供睡眠维护周期调用，失败不影响主流程。"""
    if not username or store is None:
        return
    try:
        export_team_memory(username, store)
    except Exception as exc:
        print(f"[TeamMemoryExport] 导出失败 (非致命): {exc}")
