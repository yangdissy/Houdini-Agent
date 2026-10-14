---
{"name":"find_repeated_subgraphs","category":"learning","description":"扫描网络中的重复节点类型链，找出多次出现、可能值得封装为 HDA、Subnet 或保存记忆的模式。返回重复次数、实例路径和资产化建议。只读，不创建或修改资产。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"要扫描的网络路径。","required":true},"chain_length":{"type":"integer","description":"重复链长度，默认 3，范围 2-6。","required":false},"max_nodes":{"type":"integer","description":"最多扫描节点数，默认 1000。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Find Repeated Subgraphs

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
