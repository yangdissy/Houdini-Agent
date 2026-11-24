from types import MappingProxyType

import pytest

from houdini_agent.core.harness_policy_config import SecurityPolicy
from houdini_agent.core.readonly_python import readonly_python_violation


def test_readonly_python_accepts_explicit_queries():
    code = "node = hou.node('/obj')\nprint(node.path())"

    assert readonly_python_violation(code) == ""


def test_readonly_python_rejects_hom_mutation():
    code = "node = hou.node('/obj')\nnode.createNode('geo')"

    assert "createNode" in readonly_python_violation(code)


def test_readonly_python_fails_closed_on_dynamic_calls():
    code = "method = getattr(hou.node('/obj'), 'createNode')\nmethod('geo')"

    assert "explicit method calls" in readonly_python_violation(code)


@pytest.mark.parametrize("code, method", [
    ("hou.hscript('opadd /obj geo')", "hscript"),
    ("hou.node('/obj/geo1').bypass(True)", "bypass"),
    ("hou.hipFile.load('/tmp/test.hip')", "load"),
    ("hou.node('/obj/geo1').revertToDefaults()", "revertToDefaults"),
    ("hou.parm('/obj/geo1/tx').deleteAllKeyframes()", "deleteAllKeyframes"),
    ("hou.setFrame(10)", "setFrame"),
    ("hou.node('/obj/geo1').setFirstInput(hou.node('/obj/box1'))", "setFirstInput"),
    ("hou.undos.performUndo()", "performUndo"),
    ("().__class__.__base__.__subclasses__().__getitem__(0).__call__()", "__"),
])
def test_readonly_python_rejects_mutation_bypasses(code, method):
    assert method in readonly_python_violation(code)


def test_readonly_python_accepts_allowlisted_query_patterns():
    code = """node = hou.node('/obj')
parm = node.parm('tx')
values = [child.geometry().points() for child in node.children()]
print(f'{node.path()}: {parm.eval()} {values[0][0].attribValue("P")}')
"""

    assert readonly_python_violation(code) == ""


def test_readonly_python_rejects_prefix_without_identifier_boundary():
    assert "isolate" in readonly_python_violation("hou.node('/obj').isolate()")


def test_readonly_python_rejects_decorators_without_call_nodes():
    code = "@hou.session.run\ndef inspect():\n    return None"

    assert "decorated" in readonly_python_violation(code)


def test_readonly_python_rejects_when_policy_is_unavailable(monkeypatch):
    unavailable = SecurityPolicy(MappingProxyType({}), "unavailable", "policy_unavailable")
    monkeypatch.setattr("houdini_agent.core.readonly_python.get_security_policy", lambda: unavailable)

    assert "policy" in readonly_python_violation("hou.node('/obj')")