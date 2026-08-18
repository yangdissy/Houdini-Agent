# -*- coding: utf-8 -*-
"""Pure-Python domain state for a chat session."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping

from .cache_records import DEFAULT_TOKEN_STATS, SessionCacheRecord


@dataclass
class SessionState:
    """Persistent chat state without Qt widgets or agent-run anchors."""

    session_id: str
    created_at: str
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    context_summary: str = ''
    token_stats: Dict[str, Any] = field(default_factory=lambda: DEFAULT_TOKEN_STATS.copy())
    todo_data: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_legacy_dict(cls, session_id: str, data: Mapping[str, Any]) -> "SessionState":
        return cls(
            session_id=session_id,
            created_at=data.get('created_at') or datetime.now().isoformat(),
            conversation_history=data.get('conversation_history', []),
            context_summary=data.get('context_summary', ''),
            token_stats=data.get('token_stats') or DEFAULT_TOKEN_STATS.copy(),
            todo_data=data.get('todo_data', []),
        )

    @classmethod
    def from_cache_record(cls, record: SessionCacheRecord) -> "SessionState":
        return cls(
            session_id=record.session_id,
            created_at=record.created_at,
            conversation_history=record.conversation_history,
            context_summary=record.context_summary,
            token_stats=record.token_stats,
            todo_data=record.todo_data,
        )

    def update_legacy_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update domain keys in-place without disturbing Qt/runtime keys."""
        data.update({
            'conversation_history': self.conversation_history,
            'created_at': self.created_at,
            'context_summary': self.context_summary,
            'token_stats': self.token_stats,
        })
        return data

    def to_cache_record(self) -> SessionCacheRecord:
        """Use SessionCacheRecord as the sole persistence schema."""
        return SessionCacheRecord(
            session_id=self.session_id,
            created_at=self.created_at,
            conversation_history=self.conversation_history,
            context_summary=self.context_summary,
            todo_data=self.todo_data,
            token_stats=self.token_stats,
        )