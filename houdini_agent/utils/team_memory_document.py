# -*- coding: utf-8 -*-
"""Team Memory 导出文档与共享资格策略。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .memory_sqlite import EMBEDDING_FORMAT_VERSION

TEAM_EXPORT_SCHEMA_VERSION = 1
LEGACY_EXPORT_SCHEMA_VERSION = 0

MAX_EXPORT_FILE_BYTES = 16 * 1024 * 1024
MAX_SEMANTIC_ENTRIES = 10000
MAX_PROCEDURAL_ENTRIES = 10000
MAX_TEXT_LENGTH = 65536
MAX_EMBEDDING_DIMENSION = 8192
MAX_DIAGNOSTICS = 100

ELIGIBLE_SEMANTIC_CATEGORIES = frozenset({
    "command", "debug", "pitfall", "workflow", "knowledge", "general",
})
ELIGIBLE_ABSTRACTION_LEVELS = frozenset({2, 3, 4})
MIN_SEMANTIC_CONFIDENCE = 0.5
MIN_PROCEDURAL_SUCCESS_RATE = 0.55
MIN_PROCEDURAL_USAGE = 2


@dataclass(frozen=True)
class TeamExportDiagnostic:
    username: str
    entry_type: str
    reason: str
    index: Optional[int] = None

    def to_dict(self) -> dict:
        result = {
            "username": self.username,
            "entry_type": self.entry_type,
            "reason": self.reason,
        }
        if self.index is not None:
            result["index"] = self.index
        return result


@dataclass
class TeamExportParseResult:
    valid_document: bool
    semantic: List[dict] = field(default_factory=list)
    procedural: List[dict] = field(default_factory=list)
    invalid_entries: int = 0
    ineligible_entries: int = 0
    ineligible_reasons: Dict[str, int] = field(default_factory=dict)
    diagnostics: List[TeamExportDiagnostic] = field(default_factory=list)

    def add_diagnostic(self, diagnostic: TeamExportDiagnostic) -> None:
        if len(self.diagnostics) < MAX_DIAGNOSTICS:
            self.diagnostics.append(diagnostic)

    def add_ineligible(self, reason: str) -> None:
        self.ineligible_entries += 1
        self.ineligible_reasons[reason] = self.ineligible_reasons.get(reason, 0) + 1


def semantic_eligibility(entry) -> Tuple[bool, str]:
    if entry.category not in ELIGIBLE_SEMANTIC_CATEGORIES:
        return False, "semantic_category"
    if entry.abstraction_level not in ELIGIBLE_ABSTRACTION_LEVELS:
        return False, "semantic_abstraction_level"
    if entry.confidence < MIN_SEMANTIC_CONFIDENCE:
        return False, "semantic_confidence"
    if not entry.rule:
        return False, "semantic_rule_empty"
    return True, "eligible"


def procedural_eligibility(entry) -> Tuple[bool, str]:
    if entry.usage_count < MIN_PROCEDURAL_USAGE:
        return False, "procedural_usage"
    if entry.success_rate < MIN_PROCEDURAL_SUCCESS_RATE:
        return False, "procedural_success_rate"
    if not entry.strategy_name:
        return False, "procedural_name_empty"
    return True, "eligible"


def build_export_document(username: str, exported_at: float, semantic: List[dict], procedural: List[dict]) -> dict:
    return {
        "schema_version": TEAM_EXPORT_SCHEMA_VERSION,
        "username": username,
        "exported_at": exported_at,
        "semantic": semantic,
        "procedural": procedural,
    }


def _document_failure(username: str, reason: str) -> TeamExportParseResult:
    result = TeamExportParseResult(valid_document=False)
    result.add_diagnostic(TeamExportDiagnostic(username, "document", reason))
    return result


def _finite_number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _integer(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _text(value, allow_empty: bool = False) -> Optional[str]:
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
        return None
    if not allow_empty and not value:
        return None
    return value


def _embedding(item: dict, version: int) -> Optional[Tuple[List[float], str, str, int, int]]:
    raw = item.get("embedding")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_EMBEDDING_DIMENSION:
        return None
    vector = []
    for value in raw:
        number = _finite_number(value)
        if number is None:
            return None
        vector.append(number)

    backend = item.get("embedding_backend")
    model = item.get("embedding_model")
    dimension = item.get("embedding_dimension")
    format_version = item.get("embedding_format_version")
    if version == TEAM_EXPORT_SCHEMA_VERSION:
        if not isinstance(backend, str) or not backend:
            return None
        if not isinstance(model, str) or not model:
            return None
        if _integer(dimension) != len(vector):
            return None
        if _integer(format_version) != EMBEDDING_FORMAT_VERSION:
            return None
    else:
        backend = backend if isinstance(backend, str) and backend else "legacy"
        model = model if isinstance(model, str) and model else "legacy"
        if dimension is None:
            dimension = len(vector)
        if _integer(dimension) != len(vector):
            return None
        if format_version is None:
            format_version = EMBEDDING_FORMAT_VERSION
        if _integer(format_version) is None:
            return None
    return vector, backend, model, dimension, format_version


def _parse_semantic(item, version: int) -> Tuple[Optional[dict], Optional[str], bool]:
    if not isinstance(item, dict):
        return None, "semantic_not_object", True
    rule = _text(item.get("rule"))
    category = item.get("category")
    level = _integer(item.get("abstraction_level"))
    confidence = _finite_number(item.get("confidence"))
    embedding = _embedding(item, version)
    if rule is None:
        return None, "semantic_rule_invalid", True
    if not isinstance(category, str):
        return None, "semantic_category_invalid", True
    if level is None:
        return None, "semantic_level_invalid", True
    if confidence is None or not 0.0 <= confidence <= 1.0:
        return None, "semantic_confidence_invalid", True
    if embedding is None:
        return None, "semantic_embedding_invalid", True
    parsed = {
        "rule": rule,
        "category": category,
        "abstraction_level": level,
        "confidence": confidence,
        "embedding": embedding[0],
        "embedding_backend": embedding[1],
        "embedding_model": embedding[2],
        "embedding_dimension": embedding[3],
        "embedding_format_version": embedding[4],
    }
    eligible, reason = semantic_eligibility(type("SemanticEntry", (), parsed)())
    return (parsed, None, False) if eligible else (None, reason, False)


def _parse_procedural(item, version: int) -> Tuple[Optional[dict], Optional[str], bool]:
    if not isinstance(item, dict):
        return None, "procedural_not_object", True
    name = _text(item.get("strategy_name"))
    description = _text(item.get("description", ""), allow_empty=True)
    priority = _finite_number(item.get("priority"))
    success_rate = _finite_number(item.get("success_rate"))
    usage_count = _integer(item.get("usage_count"))
    embedding = _embedding(item, version)
    if name is None:
        return None, "procedural_name_invalid", True
    if description is None:
        return None, "procedural_description_invalid", True
    if priority is None or not 0.0 <= priority <= 1.0:
        return None, "procedural_priority_invalid", True
    if success_rate is None or not 0.0 <= success_rate <= 1.0:
        return None, "procedural_success_rate_invalid", True
    if usage_count is None or usage_count < 0:
        return None, "procedural_usage_invalid", True
    if embedding is None:
        return None, "procedural_embedding_invalid", True
    parsed = {
        "strategy_name": name,
        "description": description,
        "priority": priority,
        "success_rate": success_rate,
        "usage_count": usage_count,
        "embedding": embedding[0],
        "embedding_backend": embedding[1],
        "embedding_model": embedding[2],
        "embedding_dimension": embedding[3],
        "embedding_format_version": embedding[4],
    }
    eligible, reason = procedural_eligibility(type("ProceduralEntry", (), parsed)())
    return (parsed, None, False) if eligible else (None, reason, False)


def parse_team_export_file(path: Path, source_username: str) -> TeamExportParseResult:
    path = Path(path)
    try:
        if path.stat().st_size > MAX_EXPORT_FILE_BYTES:
            return _document_failure(source_username, "file_too_large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _document_failure(source_username, "file_unreadable")
    if not isinstance(data, dict):
        return _document_failure(source_username, "document_not_object")

    version = data.get("schema_version", LEGACY_EXPORT_SCHEMA_VERSION)
    if version not in (LEGACY_EXPORT_SCHEMA_VERSION, TEAM_EXPORT_SCHEMA_VERSION):
        return _document_failure(source_username, "schema_version_unsupported")
    document_username = data.get("username")
    if version == TEAM_EXPORT_SCHEMA_VERSION and not isinstance(document_username, str):
        return _document_failure(source_username, "username_missing")
    if document_username is not None and document_username != source_username:
        return _document_failure(source_username, "username_mismatch")

    semantic = data.get("semantic")
    procedural = data.get("procedural")
    if not isinstance(semantic, list) or not isinstance(procedural, list):
        return _document_failure(source_username, "entry_collections_invalid")
    if len(semantic) > MAX_SEMANTIC_ENTRIES or len(procedural) > MAX_PROCEDURAL_ENTRIES:
        return _document_failure(source_username, "entry_limit_exceeded")

    result = TeamExportParseResult(valid_document=True)
    for entry_type, entries, parser in (
        ("semantic", semantic, _parse_semantic),
        ("procedural", procedural, _parse_procedural),
    ):
        target = result.semantic if entry_type == "semantic" else result.procedural
        for index, item in enumerate(entries):
            parsed, reason, invalid = parser(item, version)
            if parsed is not None:
                parsed["_source_user"] = source_username
                target.append(parsed)
            elif invalid:
                result.invalid_entries += 1
                result.add_diagnostic(TeamExportDiagnostic(source_username, entry_type, reason or "invalid", index))
            else:
                result.add_ineligible(reason or "ineligible")
    return result