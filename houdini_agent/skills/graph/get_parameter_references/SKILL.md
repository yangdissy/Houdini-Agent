---
{"name":"get_parameter_references","category":"graph","description":"查询一个 Houdini 标量参数的引用关系。返回直接引用该参数的参数（incoming），以及目标参数自身的表达式和原始值证据（outgoing_evidence）。适合在重命名节点/参数、修改控制器或排查 ch()/chs()依赖前使用。只读，不修改场景。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"目标节点的完整路径。","required":true},"parameter_name":{"type":"string","description":"目标标量参数名。","required":true},"limit":{"type":"integer","description":"最多返回的 incoming 引用数，默认 200。","required":false,"default":200}},"entrypoint":"scripts/main.py:run"}
---
# Get Parameter References

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
