---
{"name":"validate_memory_against_scene","category":"learning","description":"把一条 Houdini 工作流记忆与当前场景核对，验证其中的节点路径、节点类型、参数名和属性声明是否仍存在，返回 confirmed/contradicted/unknown 证据。只读。","risk_level":"low","parameters":{"memory_text":{"type":"string","description":"要验证的记忆文本。","required":true},"network_path":{"type":"string","description":"当前场景的验证范围，默认 /obj。","required":false},"max_nodes":{"type":"integer","description":"最多扫描节点数，默认 1000。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Validate Memory Against Scene

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
