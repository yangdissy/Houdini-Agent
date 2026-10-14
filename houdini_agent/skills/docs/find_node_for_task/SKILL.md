---
{"name":"find_node_for_task","category":"docs","description":"Find Houdini node candidates whose shipped documentation matches a task. Use when the desired operation is known but the node type is not. Read-only.","risk_level":"low","parameters":{"task":{"type":"string","description":"Operation or workflow to accomplish.","required":true},"context":{"type":"string","description":"Optional Houdini context filter such as sop, lop, dop, or cop.","required":false},"top_k":{"type":"integer","description":"Maximum candidates. Defaults to 8.","required":false,"default":8}},"entrypoint":"scripts/main.py:run"}
---
# Find Node For Task

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
