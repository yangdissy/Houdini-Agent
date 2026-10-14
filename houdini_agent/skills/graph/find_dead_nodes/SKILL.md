---
{"name":"find_dead_nodes","category":"graph","description":"查找网络中的死节点（无下游连接且非显示/渲染节点）。区分孤立节点（无输入无输出）和链末端未使用节点。适用于清理网络、优化管线等场景。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"网络路径，如 /obj/geo1","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Find Dead Nodes

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
