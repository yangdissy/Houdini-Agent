# -*- coding: utf-8 -*-
"""Read-only parameter reference inspection Skill."""




def _safe_text(func):
    try:
        value = func()
        return value if isinstance(value, str) else None
    except Exception:
        return None


def run(node_path, parameter_name, limit=200, _inspection=None):
    """Return direct incoming references and raw outgoing expression evidence."""
    if _inspection is None:
        from .._inspection import inspection
        _inspection = inspection()

    parameter, error = _inspection.parameter(node_path, parameter_name)
    if error:
        return {"error": error}

    limit = max(1, min(int(limit), 1000))
    try:
        all_incoming = sorted({item.path() for item in parameter.parmsReferencingThis()})
    except Exception as exc:
        return {"error": f"查询参数引用失败: {exc}"}

    expression = _safe_text(parameter.expression)
    raw_value = _safe_text(parameter.unexpandedString)
    return {
        "target_parameter": parameter.path(),
        "read_only": True,
        "incoming_count": len(all_incoming),
        "incoming": all_incoming[:limit],
        "incoming_truncated": len(all_incoming) > limit,
        "outgoing_evidence": {
            "expression": expression,
            "raw_value": raw_value,
            "has_expression": expression is not None,
        },
        "rename_risk": "high" if all_incoming else "low",
    }