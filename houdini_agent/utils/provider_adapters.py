# -*- coding: utf-8 -*-
"""Provider protocol adapters used by AIClient."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from houdini_agent.utils.provider_normalization import payload_temperature


class AnthropicRequestAdapter:
    """Build Anthropic Messages protocol requests from OpenAI-shaped inputs."""

    VERSION = "2023-06-01"
    KIMI_USER_AGENT = "claude-code/0.1.0"

    def __init__(self, requires_temperature_one: Optional[Callable[[str], bool]] = None):
        # The optional argument is retained for caller compatibility.
        self._requires_temperature_one = requires_temperature_one

    def convert_messages(self, messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        system_text = ""
        anthropic_msgs: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "")

            if role == "system":
                system_text += (("\n\n" if system_text else "") + (msg.get("content", "") or ""))
                continue

            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    anth_content = []
                    for part in content:
                        if part.get("type") == "text":
                            anth_content.append({"type": "text", "text": part["text"]})
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                match = re.match(r"data:(image/\w+);base64,(.+)", url, re.DOTALL)
                                if match:
                                    anth_content.append({
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": match.group(1),
                                            "data": match.group(2),
                                        },
                                    })
                            else:
                                anth_content.append({
                                    "type": "image",
                                    "source": {"type": "url", "url": url},
                                })
                    anthropic_msgs.append({"role": "user", "content": anth_content})
                else:
                    anthropic_msgs.append({"role": "user", "content": str(content or "")})
                continue

            if role == "assistant":
                content_blocks: List[Dict[str, Any]] = []
                text = msg.get("content")
                if text:
                    content_blocks.append({"type": "text", "text": str(text)})
                for tool_call in (msg.get("tool_calls") or []):
                    func = tool_call.get("function", {})
                    try:
                        input_obj = json.loads(func.get("arguments", "{}"))
                    except (json.JSONDecodeError, ValueError):
                        input_obj = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tool_call.get("id", ""),
                        "name": func.get("name", ""),
                        "input": input_obj,
                    })
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})
                anthropic_msgs.append({"role": "assistant", "content": content_blocks})
                continue

            if role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content", "")),
                }
                if anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
                    last_content = anthropic_msgs[-1]["content"]
                    if isinstance(last_content, list):
                        last_content.append(tool_result_block)
                    else:
                        anthropic_msgs[-1]["content"] = [
                            {"type": "text", "text": last_content},
                            tool_result_block,
                        ]
                else:
                    anthropic_msgs.append({
                        "role": "user",
                        "content": [tool_result_block],
                    })
                continue

        if anthropic_msgs and anthropic_msgs[0]["role"] == "assistant":
            anthropic_msgs.insert(0, {"role": "user", "content": "请继续。"})

        merged: List[Dict[str, Any]] = []
        for message in anthropic_msgs:
            if merged and merged[-1]["role"] == message["role"]:
                prev_content = merged[-1]["content"]
                curr_content = message["content"]
                if isinstance(prev_content, str):
                    prev_content = [{"type": "text", "text": prev_content}]
                if isinstance(curr_content, str):
                    curr_content = [{"type": "text", "text": curr_content}]
                if not isinstance(prev_content, list):
                    prev_content = [prev_content]
                if not isinstance(curr_content, list):
                    curr_content = [curr_content]
                merged[-1]["content"] = prev_content + curr_content
            else:
                merged.append(message)

        return system_text, merged

    @staticmethod
    def convert_tools(tools: List[dict]) -> List[dict]:
        if not tools:
            return []
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", tool)
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def build_payload(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        provider: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
        tools: Optional[List[dict]],
        tool_choice: str,
        enable_thinking: bool,
        stream: bool,
    ) -> Dict[str, Any]:
        system_text, anth_messages = self.convert_messages(messages)
        resolved_max_tokens = max_tokens or 16384
        payload: Dict[str, Any] = {
            "model": model,
            "messages": anth_messages,
            "max_tokens": resolved_max_tokens,
        }
        if stream:
            payload["stream"] = True

        resolved_temperature = payload_temperature(model, temperature)
        if resolved_temperature is not None:
            payload["temperature"] = resolved_temperature

        if system_text:
            payload["system"] = system_text

        if enable_thinking:
            if provider == "kimi_coding":
                if (model or "").lower().startswith("kimi-for-coding"):
                    payload["thinking"] = {"type": "enabled", "budget_tokens": min(resolved_max_tokens, 10000)}
            else:
                payload["thinking"] = {"type": "enabled", "budget_tokens": min(resolved_max_tokens, 10000)}

        if tools:
            payload["tools"] = self.convert_tools(tools)
            tool_choice_payload = self.convert_tool_choice(tool_choice)
            if tool_choice_payload:
                payload["tool_choice"] = tool_choice_payload

        return payload

    @staticmethod
    def convert_tool_choice(tool_choice: str) -> Optional[Dict[str, str]]:
        if tool_choice == "auto":
            return {"type": "auto"}
        if tool_choice == "none":
            return {"type": "none"}
        if tool_choice == "required":
            return {"type": "any"}
        return None

    def build_headers(self, api_key: str, provider: str, stream: bool) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": self.VERSION,
        }
        if stream:
            headers["Accept"] = "text/event-stream"
        if provider == "kimi_coding":
            headers["User-Agent"] = self.KIMI_USER_AGENT
        return headers

    def normalize_response(self, response_obj: Dict[str, Any], parse_usage: Callable[[dict], Dict[str, Any]]) -> Dict[str, Any]:
        content_text = ""
        tool_calls_list = []
        for block in response_obj.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls_list.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })

        stop_reason = response_obj.get("stop_reason", "end_turn")
        finish = self.normalize_stop_reason(stop_reason)

        return {
            "ok": True,
            "content": content_text or None,
            "tool_calls": tool_calls_list or None,
            "finish_reason": finish,
            "usage": parse_usage(response_obj.get("usage", {})),
            "raw": response_obj,
        }

    @staticmethod
    def normalize_stop_reason(stop_reason: Optional[str]) -> str:
        if stop_reason == "end_turn":
            return "stop"
        if stop_reason == "tool_use":
            return "tool_calls"
        return stop_reason or "stop"


class AnthropicStreamEventParser:
    """Normalize Anthropic SSE events into AIClient stream chunks."""

    def __init__(self, parse_usage: Callable[[dict], Dict[str, Any]], enable_thinking: bool):
        self._parse_usage = parse_usage
        self._enable_thinking = enable_thinking
        self._content_blocks: Dict[int, Dict[str, Any]] = {}
        self._tool_args_acc: Dict[int, str] = {}
        self._pending_usage: Dict[str, Any] = {}
        self._last_stop_reason: Optional[str] = None
        self._got_thinking = False

    @property
    def pending_usage(self) -> Dict[str, Any]:
        return self._pending_usage

    @property
    def last_stop_reason(self) -> Optional[str]:
        return self._last_stop_reason

    def process_event(self, event_type: str, data_str: str) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return results

        ev_type = data.get("type", event_type)

        if ev_type == "message_start":
            msg = data.get("message", {})
            usage = msg.get("usage", {})
            if usage:
                self._pending_usage = self._parse_usage(usage)

        elif ev_type == "content_block_start":
            idx = data.get("index", 0)
            block = data.get("content_block", {})
            self._content_blocks[idx] = {
                "type": block.get("type", "text"),
                "id": block.get("id", ""),
                "name": block.get("name", ""),
            }
            if block.get("type") == "tool_use":
                self._tool_args_acc[idx] = ""

        elif ev_type == "content_block_delta":
            idx = data.get("index", 0)
            delta = data.get("delta", {})
            delta_type = delta.get("type", "")
            block_info = self._content_blocks.get(idx, {})

            if delta_type == "text_delta":
                text = delta.get("text", "")
                if text:
                    results.append({"type": "content", "content": text})

            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking", "")
                if thinking:
                    self._got_thinking = True
                    if self._enable_thinking:
                        results.append({"type": "thinking", "content": thinking})

            elif delta_type == "input_json_delta":
                partial = delta.get("partial_json", "")
                if partial and idx in self._tool_args_acc:
                    self._tool_args_acc[idx] += partial
                    tool_name = block_info.get("name", "")
                    if tool_name:
                        results.append({
                            "type": "tool_args_delta",
                            "index": idx,
                            "name": tool_name,
                            "delta": partial,
                            "accumulated": self._tool_args_acc[idx],
                        })

        elif ev_type == "content_block_stop":
            idx = data.get("index", 0)
            block_info = self._content_blocks.get(idx, {})
            if block_info.get("type") == "tool_use":
                results.append({
                    "type": "tool_call",
                    "tool_call": {
                        "id": block_info.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block_info.get("name", ""),
                            "arguments": self._tool_args_acc.get(idx, "{}"),
                        },
                    },
                })

        elif ev_type == "message_delta":
            delta = data.get("delta", {})
            self._last_stop_reason = delta.get("stop_reason")
            usage = data.get("usage", {})
            if usage:
                parsed = self._parse_usage(usage)
                for key, value in parsed.items():
                    if isinstance(value, (int, float)):
                        self._pending_usage[key] = self._pending_usage.get(key, 0) + value

        elif ev_type == "message_stop":
            results.append({
                "type": "done",
                "finish_reason": self.finish_reason(),
                "usage": self._pending_usage,
            })

        elif ev_type == "error":
            err_msg = data.get("error", {}).get("message", str(data))
            results.append({"type": "error", "error": err_msg})

        return results

    def finish_reason(self) -> str:
        if self._last_stop_reason == "max_tokens":
            return "length"
        return AnthropicRequestAdapter.normalize_stop_reason(self._last_stop_reason)
