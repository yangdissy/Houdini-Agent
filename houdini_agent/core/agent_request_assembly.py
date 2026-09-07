# -*- coding: utf-8 -*-
"""Pure-ish assembly of provider messages and tool schemas for an agent request."""

import copy
import re

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from houdini_agent.utils.token_optimizer import (
    ContextAssembly,
    ContextPruneResult,
    DynamicContextSection,
    build_context_assembly,
    prune_context_assembly_to_token_target,
)


_INTERNAL_FIELDS = frozenset({
    '_reply_content', '_tool_summary', 'thinking',
    'python_shells', 'system_shells',
})


@dataclass
class AgentRequest:
    """The authoritative provider payload produced by request assembly."""

    messages: List[dict]
    tools: List[dict]
    budget_result: ContextPruneResult


def normalize_history(
    history: Sequence[dict],
    supports_vision: bool,
    fix_alternation: Callable[[List[dict]], List[dict]],
    tool_result_text: Callable[[str, str], str],
    image_placeholder: str,
) -> List[dict]:
    """Remove internal metadata and keep images only on the current vision turn."""
    last_user_idx = None
    for idx in range(len(history) - 1, -1, -1):
        if history[idx].get('role') == 'user':
            last_user_idx = idx
            break

    normalized = []
    for idx, msg in enumerate(history):
        role = msg.get('role', '')
        if role == 'tool':
            if msg.get('tool_call_id'):
                normalized.append({k: v for k, v in msg.items() if k not in _INTERNAL_FIELDS})
            else:
                tool_name = msg.get('name', 'unknown')
                content = msg.get('content', '')
                normalized.append({
                    'role': 'assistant',
                    'content': tool_result_text(tool_name, content[:500]),
                })
        elif role == 'assistant':
            normalized.append({k: v for k, v in msg.items() if k not in _INTERNAL_FIELDS})
        elif role == 'user':
            content = msg.get('content')
            if isinstance(content, list) and not (idx == last_user_idx and supports_vision):
                text_parts = [
                    part.get('text', '') for part in content
                    if isinstance(part, dict) and part.get('type') == 'text'
                ]
                normalized.append({
                    'role': 'user',
                    'content': '\n'.join(text for text in text_parts if text) or image_placeholder,
                })
            else:
                normalized.append(msg)
        elif role == 'system':
            normalized.append(msg)
    return fix_alternation(normalized)


def normalize_provider_messages(messages: Sequence[dict], is_reasoning_model: bool) -> List[dict]:
    """Reduce messages to provider fields and normalize assistant reasoning/content."""
    normalized = []
    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content')
        has_tool_calls = 'tool_calls' in msg
        clean_msg = {'role': role}
        if role == 'assistant' and has_tool_calls:
            clean_msg['content'] = content
        else:
            clean_msg['content'] = content if content is not None else ''
        if is_reasoning_model and role == 'assistant':
            clean_msg['reasoning_content'] = msg.get('reasoning_content', '')
        for field in ('tool_calls', 'tool_call_id', 'name'):
            if field in msg:
                clean_msg[field] = msg[field]
        if role == 'assistant' and clean_msg.get('content'):
            cleaned_content = re.sub(
                r'<think>[\s\S]*?</think>', '', clean_msg['content']
            ).strip()
            clean_msg['content'] = cleaned_content or None
        normalized.append(clean_msg)
    return normalized


def finalize_tools(
    selected_tools: Sequence[dict],
    registry_tools: Sequence[dict],
    supports_vision: bool,
) -> List[dict]:
    """Merge registry schemas and degrade viewport capture for non-vision models."""
    tools = list(selected_tools)
    existing_names = {tool.get('function', {}).get('name', '') for tool in tools}
    for schema in registry_tools:
        name = schema.get('function', {}).get('name', '')
        if name not in existing_names:
            tools.append(schema)
            existing_names.add(name)
    if supports_vision:
        return tools

    degraded = []
    for tool in tools:
        tool_name = tool.get('function', {}).get('name')
        if tool_name == 'visual_review':
            continue
        if tool_name == 'capture_viewport':
            tool = copy.deepcopy(tool)
            tool['function']['description'] = (
                "截取当前 Houdini 3D 视口快照并保存到文件。"
                "当前模型不支持图片分析，截图将保存到 output_path 指定的路径供用户查看。"
                "必须指定 output_path 参数。"
            )
        degraded.append(tool)
    return degraded


def build_context(
    prefix_messages: Sequence[dict],
    history_messages: Sequence[dict],
    dynamic_sections: Sequence[DynamicContextSection],
) -> ContextAssembly:
    """Create mutable budgeting state before optional sleep side effects occur."""
    return build_context_assembly(
        prefix_messages=list(prefix_messages),
        history_messages=list(history_messages),
        dynamic_sections=list(dynamic_sections),
    )


def finalize_context_request(
    assembly: ContextAssembly,
    selected_tools: Sequence[dict],
    registry_tools: Sequence[dict],
    supports_vision: bool,
    is_reasoning_model: bool,
    context_limit: int,
    count_tokens: Callable[[List[dict], Optional[List[dict]]], int],
    summarize_tool_content: Optional[Callable[[str, int], str]],
) -> AgentRequest:
    """Finalize an existing context while preserving one owner of provider messages."""
    tools = finalize_tools(selected_tools, registry_tools, supports_vision)
    budget_result = prune_context_assembly_to_token_target(
        assembly,
        context_limit,
        count_tokens,
        tools=tools,
        min_rounds=2,
        summarize_fn=summarize_tool_content,
        keep_current_image=supports_vision,
    )
    return AgentRequest(
        messages=normalize_provider_messages(assembly.messages(), is_reasoning_model),
        tools=tools,
        budget_result=budget_result,
    )