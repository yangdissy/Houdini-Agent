---
{"name":"inspect_material_assignments","category":"materials","description":"Scan material libraries and material-like parameter references to find assigned, missing, and unused material paths. Read-only.","risk_level":"low","parameters":{"root_path":{"type":"string","description":"Root network to scan, usually /, /obj, or /stage. Defaults to /.","required":false,"default":"/"},"max_nodes":{"type":"integer","description":"Maximum scanned nodes to avoid huge scene dumps. Defaults to 2000.","required":false,"default":2000}},"entrypoint":"scripts/main.py:run"}
---
# Inspect Material Assignments

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
