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