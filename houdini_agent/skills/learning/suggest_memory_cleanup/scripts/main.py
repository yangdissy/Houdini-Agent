# -*- coding: utf-8 -*-
"""Suggest non-destructive cleanup actions for memory records."""

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List




_CONCRETE_PATTERN = re.compile(r"/(?:obj|stage|out|mat)/|\b[^\s]+\.hip(?:nc|lc)?\b|\b[A-Za-z_]+\d+\b", re.IGNORECASE)
_NEGATION_PATTERN = re.compile(r"(?:不要|不能|避免|禁止|not|never|do not)", re.IGNORECASE)


def suggest_cleanup(memory_records: List[Dict[str, Any]], duplicate_threshold: float = 0.86) -> List[Dict[str, Any]]:
    records = []
    for index, record in enumerate(memory_records or []):
        text = str(record.get("rule") or record.get("content") or record.get("text") or "").strip()
        if text:
            records.append({"id": record.get("id", str(index)), "text": text, "record": record})
    suggestions = []
    for index, first in enumerate(records):
        if _CONCRETE_PATTERN.search(first["text"]):
            suggestions.append({
                "action": "generalize", "ids": [first["id"]],
                "reason": "记忆包含具体 HIP、节点路径或编号，跨项目复用性较低。",
            })
        activation = int(first["record"].get("activation_count", 0) or 0)
        confidence = float(first["record"].get("confidence", 1.0) or 0.0)
        if activation == 0 and confidence < 0.4:
            suggestions.append({
                "action": "review_low_value", "ids": [first["id"]],
                "reason": "低置信度且从未激活，建议人工复核，不自动删除。",
            })
        for second in records[index + 1:]:
            ratio = SequenceMatcher(None, first["text"].lower(), second["text"].lower()).ratio()
            if ratio >= duplicate_threshold:
                suggestions.append({
                    "action": "merge_duplicates", "ids": [first["id"], second["id"]],
                    "similarity": round(ratio, 4), "reason": "两条记忆文本高度相似。",
                })
            elif ratio >= 0.55 and bool(_NEGATION_PATTERN.search(first["text"])) != bool(_NEGATION_PATTERN.search(second["text"])):
                suggestions.append({
                    "action": "review_conflict", "ids": [first["id"], second["id"]],
                    "similarity": round(ratio, 4), "reason": "主题相似但一条包含否定约束，可能相互冲突。",
                })
    return suggestions


def run(memory_records: List[Dict[str, Any]], duplicate_threshold: float = 0.86) -> Dict[str, Any]:
    threshold = max(0.5, min(float(duplicate_threshold), 0.99))
    suggestions = suggest_cleanup(memory_records, threshold)
    return {
        "record_count": len(memory_records or []),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "note": "这些是只读建议；任何合并、降权或删除都必须由用户通过受治理的记忆管理流程确认。",
    }