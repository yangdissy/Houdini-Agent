---
{"name":"trace_node_dependencies","category":"graph","description":"追溯节点的上游依赖树或下游影响范围。upstream: 查看该节点依赖了哪些上游节点；downstream: 查看修改该节点会影响哪些下游。返回层级分组列表和可视化树形文本。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"节点路径，如 /obj/geo1/OUT","required":true},"direction":{"type":"string","description":"追溯方向: upstream(上游依赖) 或 downstream(下游影响)，默认 upstream","required":false},"max_depth":{"type":"integer","description":"最大追溯深度，默认 10","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Trace Node Dependencies

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
