# -*- coding: utf-8 -*-
"""Serializable cache records for chat sessions."""

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


DEFAULT_TOKEN_STATS = {
    'input_tokens': 0,
    'output_tokens': 0,
    'reasoning_tokens': 0,
    'cache_read': 0,
    'cache_write': 0,
    'total_tokens': 0,
    'requests': 0,
    'estimated_cost': 0.0,
}


def new_session_id() -> str:
    return str(uuid.uuid4())[:8]


def strip_images_for_cache(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return cache-safe history with inline base64 image payloads replaced."""
    stripped = []
    for msg in history:
        content = msg.get('content')
        if isinstance(content, list):
            new_parts = []
            for part in content:
                if part.get('type') == 'image_url':
                    url = part.get('image_url', {}).get('url', '')
                    if url.startswith('data:'):
                        media_type = url.split(';')[0].replace('data:', '')
                        new_parts.append({
                            'type': 'text',
                            'text': f'[Image: {media_type}]',
                        })
                    else:
                        new_parts.append(copy.copy(part))
                else:
                    new_parts.append(copy.copy(part))
            new_msg = msg.copy()
            new_msg['content'] = new_parts
            stripped.append(new_msg)
        else:
            stripped.append(msg)
    return stripped


@dataclass
class SessionCacheRecord:
    session_id: str
    created_at: str
    conversation_history: List[Dict[str, Any]]
    context_summary: str = ''
    todo_data: List[Dict[str, Any]] = field(default_factory=list)
    token_stats: Dict[str, Any] = field(default_factory=lambda: DEFAULT_TOKEN_STATS.copy())
    version: str = '1.0'
    estimated_tokens: Optional[int] = None
    todo_summary: Optional[str] = None

    @classmethod
    def from_cache_data(cls, cache_data: Dict[str, Any]) -> "SessionCacheRecord":
        return cls(
            version=cache_data.get('version', '1.0'),
            session_id=cache_data.get('session_id') or new_session_id(),
            created_at=cache_data.get('created_at') or datetime.now().isoformat(),
            conversation_history=cache_data.get('conversation_history', []),
            context_summary=cache_data.get('context_summary', ''),
            todo_data=cache_data.get('todo_data', []),
            token_stats=cache_data.get('token_stats', DEFAULT_TOKEN_STATS.copy()),
            estimated_tokens=cache_data.get('estimated_tokens'),
            todo_summary=cache_data.get('todo_summary'),
        )

    def to_cache_data(self, strip_images: bool = True) -> Dict[str, Any]:
        history = self.conversation_history
        if strip_images:
            history = strip_images_for_cache(history)

        cache_data = {
            'version': self.version,
            'session_id': self.session_id,
            'created_at': self.created_at,
            'message_count': len(history),
            'conversation_history': history,
            'context_summary': self.context_summary,
            'todo_data': self.todo_data,
            'token_stats': self.token_stats.copy(),
        }
        if self.estimated_tokens is not None:
            cache_data['estimated_tokens'] = self.estimated_tokens
        if self.todo_summary is not None:
            cache_data['todo_summary'] = self.todo_summary
        return cache_data


def build_session_cache_record(
    session_id: str,
    session_data: Dict[str, Any],
    todo_data: Optional[List[Dict[str, Any]]] = None,
    estimated_tokens: Optional[int] = None,
    todo_summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical on-disk record used by every session save path."""
    return SessionCacheRecord(
        session_id=session_id,
        created_at=session_data.get('created_at') or datetime.now().isoformat(),
        conversation_history=session_data.get('conversation_history', []),
        context_summary=session_data.get('context_summary', ''),
        todo_data=todo_data or [],
        token_stats=session_data.get('token_stats') or DEFAULT_TOKEN_STATS.copy(),
        estimated_tokens=estimated_tokens,
        todo_summary=todo_summary,
    ).to_cache_data()