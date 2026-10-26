# -*- coding: utf-8 -*-
"""Pure-ish assembly of provider messages and tool schemas for an agent request."""

import copy
import re
import threading
import uuid
import time

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from houdini_agent.utils.token_optimizer import (
    ContextAssembly,
    ContextPruneResult,
    DynamicContextSection,
    build_context_assembly,
    compress_old_round_tool_results,
    flatten_context_rounds,
    plan_context_rounds,
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


class ToolExposureState:
    """Own one run's permission-filtered, bounded provider tool schemas."""

    def __init__(self, registry, initial_tools: Sequence[dict], mode: str = "agent",
                 use_web: bool = True, supports_vision: bool = True,
                 max_schema_tokens: int = 16000, record_event=None):
        from houdini_agent.utils.token_optimizer import TokenOptimizer

        self.registry = registry
        self.mode = mode
        self.use_web = use_web
        self.supports_vision = supports_vision
        self.max_schema_tokens = max_schema_tokens
        self._record_event = record_event
        self._lock = threading.RLock()
        self._counter = TokenOptimizer().calculate_message_tokens
        initial_names = {tool.get("function", {}).get("name", "") for tool in initial_tools}
        self._names = [meta["name"] for meta in registry.list_all() if meta["name"] in registry._expand_tool_dependencies(initial_names)]
        if self._counter([], tools=self.snapshot()) > self.max_schema_tokens:
            raise ValueError("Initial tool schemas exceed the request tool budget")

    def _allowed(self, name: str) -> bool:
        if self.registry.policy.error or not self.registry.is_tool_allowed_in_mode(name, self.mode):
            return False
        if not self.use_web and name in {"web_search", "fetch_webpage"}:
            return False
        return self.supports_vision or name != "visual_review"

    def _schemas(self, names: Sequence[str]) -> List[dict]:
        from houdini_agent.utils.ultra_optimizer import UltraOptimizer

        schemas = [self.registry.get_meta(name).schema for name in names if self._allowed(name)]
        return finalize_tools(UltraOptimizer.optimize_tool_definitions(schemas), [], self.supports_vision)

    def snapshot(self) -> List[dict]:
        with self._lock:
            return self._schemas(self._names)

    def load(self, query: str = "", tags=None, mode: str = "", limit: int = 5) -> dict:
        if mode and mode != self.mode:
            return {"success": False, "error": "Discovery cannot change the host execution mode"}
        contracts = self.registry.search_contracts(query=query, mode=self.mode, tags=set(tags or ()), limit=min(20, max(1, limit)), enabled_only=True)
        matches = [contract for contract in contracts if self._allowed(contract["name"])]
        if not matches:
            return {"success": False, "error": "No enabled, permitted tools match this query"}
        with self._lock:
            requested = self.registry._expand_tool_dependencies({contract["name"] for contract in matches})
            added = [meta["name"] for meta in self.registry.list_all()
                     if meta["name"] in requested and meta["name"] not in self._names and self._allowed(meta["name"])]
            candidate = self._names + added
            schemas = self._schemas(candidate)
            tokens = self._counter([], tools=schemas)
            if tokens > self.max_schema_tokens:
                return {"success": False, "error": "Tool schema budget exceeded; narrow the query", "error_code": "tool_schema_budget"}
            self._names = candidate
        self._record({"event_type": "tool_exposure", "action": "load", "loaded_tools": added,
                      "schema_count": len(schemas), "schema_tokens": tokens})
        return {"success": True, "result": {
            "matches": [{"name": contract["name"], "description": contract["schema"]["function"].get("description", "")[:200]}
                        for contract in matches],
            "loaded_tools": added, "schema_count": len(schemas), "schema_tokens": tokens,
            "available": "Loaded tools are callable in the next model request, not in this response.",
        }}

    def reject(self, name: str, provider_tool_call_id: str = "") -> dict:
        call_id = uuid.uuid4().hex
        self._record({"event_type": "tool_policy", "tool": name, "action": "deny",
                      "reason_code": "tool_not_exposed", "call_id": call_id,
                      "provider_tool_call_id": provider_tool_call_id,
                      "execution_status": "not_started"})
        self._record({"event_type": "tool_call", "phase": "result", "tool": name,
                      "call_id": call_id, "provider_tool_call_id": provider_tool_call_id,
                      "success": False, "execution_status": "not_started", "error_code": "tool_not_exposed"})
        return {"success": False, "error": "Tool was not exposed in this request; search and load it for the next request.",
                "error_code": "tool_not_exposed"}

    def record_skip(self, name: str, reason: str, provider_tool_call_id: str = "") -> None:
        self._record({"event_type": "tool_call", "phase": "result", "tool": name,
                      "call_id": uuid.uuid4().hex, "provider_tool_call_id": provider_tool_call_id,
                      "success": reason == "cache_hit", "execution_status": reason})

    def record_link(self, name: str, result: dict, provider_tool_call_id: str) -> None:
        if result.get("audit_call_id"):
            self._record({"event_type": "tool_call_link", "tool": name,
                          "call_id": result["audit_call_id"], "provider_tool_call_id": provider_tool_call_id})

    def _record(self, record: dict) -> None:
        if self._record_event is not None:
            self._record_event(dict(record, schema_version=2, timestamp=round(time.time(), 3)))


def has_prior_completed_turn(history: Sequence[dict]) -> bool:
    """Return whether history contains an assistant response before the current turn."""
    return any(message.get('role') == 'assistant' for message in history)


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


def prepare_history_for_request(
    history: Sequence[dict],
    supports_vision: bool,
    fix_alternation: Callable[[List[dict]], List[dict]],
    tool_result_text: Callable[[str, str], str],
    image_placeholder: str,
    summarize_tool_content: Optional[Callable[[str, int], str]],
    protect_recent_rounds: int = 3,
) -> List[dict]:
    """Normalize a request copy and compact stale tool output outside recent rounds."""
    normalized = normalize_history(
        history,
        supports_vision=supports_vision,
        fix_alternation=fix_alternation,
        tool_result_text=tool_result_text,
        image_placeholder=image_placeholder,
    )
    rounds = plan_context_rounds(normalized, protect_recent_rounds=0).rounds
    compress_old_round_tool_results(
        rounds,
        protect_recent_rounds=protect_recent_rounds,
        summarize_fn=summarize_tool_content,
    )
    return flatten_context_rounds(rounds)


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