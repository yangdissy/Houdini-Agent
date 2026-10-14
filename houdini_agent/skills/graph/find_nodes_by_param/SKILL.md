---
{"name":"find_nodes_by_param","category":"graph","description":"在网络中搜索具有特定参数值的节点，类似 grep 搜索。适用于定位使用了某参数（或某参数值）的节点。","risk_level":"low","parameters":{"param_name":{"type":"string","description":"参数名","required":true},"value":{"type":["string","number"],"description":"要匹配的值（可选，留空则列出所有有此参数的节点）","required":false},"network_path":{"type":"string","description":"搜索的网络路径，留空使用 /obj","required":false},"recursive":{"type":"boolean","description":"是否递归搜索子网络，默认 true","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Find Nodes By Param

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
