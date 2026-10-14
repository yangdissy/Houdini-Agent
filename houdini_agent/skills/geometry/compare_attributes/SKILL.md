---
{"name":"compare_attributes","category":"geometry","description":"对比两个节点的属性差异（哪些属性多了/少了/类型不同）。覆盖 point/vertex/prim/detail 四种类别。适用于调试管线、检查节点前后数据变化等场景。","risk_level":"low","parameters":{"node_path_a":{"type":"string","description":"第一个节点路径","required":true},"node_path_b":{"type":"string","description":"第二个节点路径","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Compare Attributes

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
