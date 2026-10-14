---
{"name":"get_node_card","category":"graph","description":"建节点前一站式查节点类型说明（无需先建节点）：min/max inputs、输入/输出端口 label、is_generator、参数名+默认值+menu items（enum 合法值）。第一次用某节点类型、不确定接几个输入、不知道参数是 enum/float/string 时用。只想知道端口用 get_node_inputs skill；查已建好的节点参数用 get_parameter_schema。","risk_level":"low","parameters":{"node_type":{"type":"string","description":"节点类型名，如 'scatter'、'copytopoints'、'rbdbulletsolver'。不带版本号时返回最新版。","required":true},"context":{"type":"string","description":"节点类别，默认 'Sop'（可选 Lop/Dop/Cop/Chop/Top/Object/Driver/Vop）","required":false},"parm_filter":{"type":"string","description":"可选：参数名/label 子串过滤，只返回匹配的参数","required":false},"max_parms":{"type":"integer","description":"参数返回上限，默认 40","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Get Node Card

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
