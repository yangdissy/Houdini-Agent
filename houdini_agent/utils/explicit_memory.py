# -*- coding: utf-8 -*-
"""Governed service for explicit, user-requested long-term memories."""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .memory_store import MemoryStore, SemanticRecord, get_memory_store


_MAX_CONTENT_LENGTH = 2000
_SENSITIVE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|secret|password|passwd|私钥|密码)\s*[:=]"
)
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SAVE_INTENT_PATTERN = re.compile(
    r"(记住|记得住|记下来|保存为长期记忆|以后都按|以后按照|remember this|save this)"
)
_RECALL_ONLY_PATTERN = re.compile(
    r"(还记得|你记得|查一下记忆|回忆一下|do you remember|recall)"
)
# 否定守卫：用户在“否定/抱怨”语境中提到“记住/remember”时不视为保存请求。
# 例如 “我根本记不住你说的话” 含子串“记住”，但绝不能放行 remember_memory 工具（fail-closed）。
_NEGATED_INTENT_PATTERN = re.compile(
    r"(记不住|不记得|记不得"
    r"|(?:别|不要|不用|不必|请勿|不需要|千万别)[^。！？!?.\n]{0,12}(?:记住|记得|记下来)"
    r"|(?:do\s+not|don't|dont|never)[^\n]{0,20}remember)"
)


@dataclass(frozen=True)
class ExplicitMemoryResult:
    status: str
    memory_id: Optional[str] = None
    message: str = ""


class ExplicitMemoryService:
    """Validate, deduplicate, persist, and verify explicit memories."""

    def __init__(self, store: MemoryStore):
        self._store = store

    def remember(self, content: str) -> ExplicitMemoryResult:
        text = (content or "").strip()
        rejection = self._validate(text)
        if rejection:
            return ExplicitMemoryResult("rejected", message=rejection)

        try:
            duplicate = self._store.find_duplicate_semantic(text)
            if duplicate is not None:
                existing = duplicate.rule
                if len(existing) > 50:
                    existing = existing[:50] + "…"
                return ExplicitMemoryResult(
                    "already_exists", duplicate.id,
                    f"该记忆已存在：{existing}",
                )

            category, level = self._classify(text)
            memory_id = self._store.add_semantic(SemanticRecord(
                rule=text,
                confidence=1.0,
                category=category,
                abstraction_level=level,
            ))
            saved = self._store.get_semantic(memory_id)
            if saved is None or saved.rule != text:
                return ExplicitMemoryResult("failed", message="写入后回读验证失败。")
            return ExplicitMemoryResult("created", memory_id, "已写入长期记忆。")
        except Exception as exc:
            return ExplicitMemoryResult("failed", message=f"写入长期记忆失败: {exc}")

    @staticmethod
    def content_fingerprint(content: str) -> str:
        return hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()

    @staticmethod
    def has_explicit_save_intent(user_message: str) -> bool:
        text = (user_message or "").strip()
        if not text:
            return False
        if _NEGATED_INTENT_PATTERN.search(text):
            return False
        if _RECALL_ONLY_PATTERN.search(text) and not _SAVE_INTENT_PATTERN.search(text):
            return False
        return bool(_SAVE_INTENT_PATTERN.search(text))

    @staticmethod
    def _validate(text: str) -> str:
        if not text:
            return "记忆内容不能为空。"
        if len(text) > _MAX_CONTENT_LENGTH:
            return f"记忆内容不能超过 {_MAX_CONTENT_LENGTH} 个字符。"
        if _CONTROL_PATTERN.search(text):
            return "记忆内容包含不允许的控制字符。"
        if _SENSITIVE_PATTERN.search(text):
            return "为保护安全，不保存密码、密钥或访问令牌。"
        return ""

    @staticmethod
    def _classify(text: str):
        # /remember 是用户手动钉住的核心记忆，统一写 L0 以进入每轮 system prompt；category 仅用于分类展示。
        lowered = text.lower()
        if any(token in lowered for token in ("偏好", "喜欢", "始终", "总是", "always", "prefer")):
            return "preference", 0
        if any(token in lowered for token in ("步骤", "流程", "工作流", "workflow")):
            return "workflow", 0
        return "knowledge", 0


def remember_explicit_memory(
    username: str,
    content: str,
    session_id: str = "",
    audit_dir: Optional[Path] = None,
) -> ExplicitMemoryResult:
    """Persist an explicit memory in the current user's authoritative store."""
    result = ExplicitMemoryService(get_memory_store(username)).remember(content)
    _append_explicit_memory_audit(
        username=username,
        session_id=session_id,
        content=content,
        result=result,
        audit_dir=audit_dir,
    )
    return result


def _append_explicit_memory_audit(
    username: str,
    session_id: str,
    content: str,
    result: ExplicitMemoryResult,
    audit_dir: Optional[Path] = None,
) -> None:
    record = {
        "ts": round(time.time(), 3),
        "username": username,
        "session_id": session_id,
        "status": result.status,
        "memory_id": result.memory_id,
        "content_sha256": ExplicitMemoryService.content_fingerprint(content),
    }
    try:
        if audit_dir is not None:
            target_dir = Path(audit_dir)
        else:
            from shared.user_paths import UserPaths
            target_dir = UserPaths(username).memory_dir() / "audit"
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / "explicit_memory.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        # audit 是合规设施：写入失败必须可观测，不能静默断链。
        print(f"[ExplicitMemory] audit 写入失败（{result.status}, user={username}）: {exc}")

