# -*- coding: utf-8 -*-
"""Rank governed memory-search results for reuse in the current task."""

import re
from typing import Any, Dict, List




def _tokens(text: str) -> set:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}", (text or "").lower()))


def rank_memories(task_description: str, memory_records: List[Dict[str, Any]], scene_node_types: List[str] = None, top_k: int = 3) -> List[Dict[str, Any]]:
    task_tokens = _tokens(task_description)
    scene_types = {str(item).lower() for item in (scene_node_types or [])}
    ranked = []
    for record in memory_records or []:
        text = str(record.get("rule") or record.get("content") or record.get("text") or "")
        record_tokens = _tokens(text)
        lexical = len(task_tokens & record_tokens) / max(1, len(task_tokens))
        type_matches = sorted(node_type for node_type in scene_types if node_type in text.lower())
        source_score = float(record.get("score", record.get("similarity", 0.0)) or 0.0)
        score = min(1.0, 0.5 * lexical + 0.35 * source_score + 0.15 * min(len(type_matches), 1))
        ranked.append({
            "id": record.get("id"),
            "score": round(score, 4),
            "memory": text,
            "matching_node_types": type_matches,
            "reuse": "复用流程骨架和已验证契约，不直接照搬绝对路径或参数值。",
            "validation": "执行前检查节点类型、输入属性、外部依赖和当前 Houdini 版本。",
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:max(1, min(int(top_k), 10))]


def run(task_description: str, memory_records: List[Dict[str, Any]], scene_node_types: List[str] = None, top_k: int = 3) -> Dict[str, Any]:
    if not (task_description or "").strip():
        return {"error": "task_description 不能为空。"}
    ranked = rank_memories(task_description, memory_records, scene_node_types, top_k)
    return {"task": task_description, "candidate_count": len(ranked), "candidates": ranked}