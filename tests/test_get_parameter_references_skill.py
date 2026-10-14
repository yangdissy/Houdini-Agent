# -*- coding: utf-8 -*-
"""Tests for the parameter-reference inspection Skill."""

from pathlib import Path

from houdini_agent import skills


_DESCRIPTOR = skills._parse_skill_markdown(
    Path(__file__).resolve().parents[1]
    / "houdini_agent" / "skills" / "graph"
    / "get_parameter_references" / "SKILL.md"
)
get_parameter_references = skills._load_descriptor_entrypoint(_DESCRIPTOR)


class _Parameter:
    def __init__(self, path, incoming=(), expression=None, raw_value="1"):
        self._path = path
        self._incoming = incoming
        self._expression = expression
        self._raw_value = raw_value

    def path(self):
        return self._path

    def parmsReferencingThis(self):
        return self._incoming

    def expression(self):
        if self._expression is None:
            raise RuntimeError("parameter has no expression")
        return self._expression

    def unexpandedString(self):
        return self._raw_value


class _Node:
    def __init__(self, parameter):
        self._parameter = parameter

    def parm(self, name):
        return self._parameter if name == "size" else None


class _Inspection:
    def __init__(self, parameter):
        self._parameter = parameter

    def parameter(self, node_path, parameter_name):
        if self._parameter is None:
            return None, f"节点 {node_path} 不存在标量参数: {parameter_name}"
        return self._parameter, None


def test_reports_sorted_incoming_and_outgoing_evidence():
    incoming = [_Parameter("/obj/geo1/b/ty"), _Parameter("/obj/geo1/a/tx")]
    target = _Parameter("/obj/geo1/control/size", incoming, 'ch("../source/scale")', "2")
    result = get_parameter_references.run(
        "/obj/geo1/control", "size", limit=1, _inspection=_Inspection(target)
    )

    assert result["incoming_count"] == 2
    assert result["incoming"] == ["/obj/geo1/a/tx"]
    assert result["incoming_truncated"] is True
    assert result["outgoing_evidence"]["expression"] == 'ch("../source/scale")'
    assert result["rename_risk"] == "high"


def test_returns_clear_error_for_missing_parameter():
    result = get_parameter_references.run(
        "/obj/geo1/control", "missing", _inspection=_Inspection(None)
    )

    assert "不存在标量参数" in result["error"]