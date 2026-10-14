---
{"name":"get_node_inputs","category":"graph","description":"查节点输入端口含义（210 个常用节点已 JSON 缓存，毫秒级返回）。连接现有节点前确认 input_index 含义、只关心端口不关心参数时用。需要参数信息或 menu items 用 get_node_card；查冷门节点也可退回 get_node_card。","risk_level":"low","parameters":{"node_type":{"type":"string","description":"节点类型名称，如 'copytopoints', 'boolean', 'scatter'","required":true},"category":{"type":"string","description":"节点类别，默认 'sop'（可选 obj/dop/vop）","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Get Node Inputs

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
