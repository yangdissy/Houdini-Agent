---
{"name":"validate_network_contract","category":"graph","description":"Validate a Houdini network for common pipeline contract issues: OUT/null naming, display/render flags, missing inputs, bypass/locked nodes, errors/warnings, and dead nodes. Read-only.","risk_level":"low","parameters":{"network_path":{"type":"string","description":"Network path to validate, for example /obj/geo1.","required":true},"recursive":{"type":"boolean","description":"Whether to include child subnet contents. Defaults to false.","required":false,"default":false},"max_nodes":{"type":"integer","description":"Maximum nodes to inspect before truncating. Defaults to 1000.","required":false,"default":1000}},"entrypoint":"scripts/main.py:run"}
---
# Validate Network Contract

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
