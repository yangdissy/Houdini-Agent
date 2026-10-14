---
{"name":"compare_network_patterns","category":"learning","description":"比较两个节点的完整上游实现，找出共同节点类型、仅各自存在的步骤、连接规模和脚本差异，并生成可审核的通用规律记忆草稿。适合从两个成功案例中提炼稳定方法。只读，不直接写记忆。","risk_level":"low","parameters":{"first_node_path":{"type":"string","description":"第一个输出或关键节点路径。","required":true},"second_node_path":{"type":"string","description":"第二个输出或关键节点路径。","required":true},"max_nodes":{"type":"integer","description":"每条上游链最多分析节点数，默认 50。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Compare Network Patterns

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
