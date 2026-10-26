"""Memory policy and append-only, content-free quality measurements."""

from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any


_AUDIT_LOCK = threading.RLock()
_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "memory_quality_policy.json"


def load_quality_policy() -> dict[str, Any]:
    policy = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
    for key in ("trial_confidence_cap", "unused_decay", "confidence_increment"):
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"Invalid memory policy: {key}")
    for key in ("promotion_citations", "min_rule_chars", "max_rule_chars"):
        if type(policy[key]) is not int or policy[key] < 1:
            raise ValueError(f"Invalid memory policy: {key}")
    if policy["min_rule_chars"] > policy["max_rule_chars"]:
        raise ValueError("Invalid memory rule length limits")
    for key in ("blocked_patterns", "generic_rules"):
        if not isinstance(policy[key], list) or not all(isinstance(item, str) for item in policy[key]):
            raise ValueError(f"Invalid memory policy: {key}")
    for pattern in policy["blocked_patterns"]:
        re.compile(pattern)
    return policy


def append_quality_audit(memory_dir: Path, event_type: str, event: dict[str, Any]) -> None:
    if event_type not in {"recall", "write"}:
        raise ValueError("Unsupported memory audit type")
    target = memory_dir / "audit"
    with _AUDIT_LOCK:
        target.mkdir(parents=True, exist_ok=True)
        with (target / f"memory_{event_type}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), **event}, ensure_ascii=True, allow_nan=False) + "\n")


def summarize_quality(memory_dir: Path, days: int = 30) -> dict[str, Any]:
    cutoff = time.time() - days * 86400
    groups: dict[str, dict[str, Any]] = {}
    writes: dict[str, int] = {}
    unknown = total = invalid = 0
    for event_type in ("recall", "write"):
        path = memory_dir / "audit" / f"memory_{event_type}.jsonl"
        if not path.exists():
            continue
        with _AUDIT_LOCK, path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                    if event["ts"] < cutoff:
                        continue
                    if event_type == "write":
                        decision = event["decision"]
                        writes[decision] = writes.get(decision, 0) + 1
                        continue
                    total += 1
                    unknown += event["status"] == "unknown"
                    for item in event["memories"]:
                        for group in ("all", item["kind"], f"L{item['layer']}" if item.get("layer") is not None else item["kind"] + ":unlayered"):
                            counts = groups.setdefault(group, {"injected": 0, "known": 0, "cited": 0})
                            counts["injected"] += 1
                            if event["status"] == "known":
                                counts["known"] += 1
                                counts["cited"] += bool(item["cited"])
                except (ValueError, KeyError, TypeError):
                    invalid += 1
    for counts in groups.values():
        counts["declared_use_rate"] = counts["cited"] / counts["known"] if counts["known"] else None
        counts["uncited_rate"] = 1 - counts["declared_use_rate"] if counts["known"] else None
    return {"groups": groups, "writes": writes, "rounds": total,
            "unknown_rate": unknown / total if total else None, "invalid_events": invalid}