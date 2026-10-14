---
{"name":"explain_node_error","category":"scene","description":"Diagnose ONE node's errors/warnings in depth and pinpoint the suspect parameters (especially file/path parameters pointing at missing files on disk). Read-only. Use when a specific node reports an error and you need to find the root cause fast — for whole-network health use verify_network / validate_network_contract instead.","risk_level":"low","parameters":{"node_path":{"type":"string","description":"Path of the node to diagnose, e.g. '/obj/geo1/file1'.","required":true},"cook":{"type":"boolean","description":"Force a read-only cook first so upstream errors surface. Default true. Set false on heavy nodes to only read already-present errors.","required":false,"default":true}},"entrypoint":"scripts/main.py:run"}
---
# Explain Node Error

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
