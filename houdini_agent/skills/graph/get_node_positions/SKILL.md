---
{"name":"get_node_positions","category":"graph","description":"获取节点的位置信息（坐标、类型），用于检查布局效果或在手动微调时查看当前状态。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"父网络路径（如 /obj/geo1）。留空时若提供 node_paths 则用之，否则报错。","required":false},"node_paths":{"type":"array","description":"要查询的节点完整路径列表。留空则返回整个网络下所有子节点的位置。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Get Node Positions

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
