---
{"name":"explain_node_parameters","category":"docs","description":"Find documented parameters relevant to a goal for one Houdini node type. Returns source-backed parameter excerpts without inspecting or modifying the scene.","risk_level":"low","parameters":{"node_type":{"type":"string","description":"Houdini node type, for example attribwrangle or filecache.","required":true},"goal":{"type":"string","description":"Optional task or parameter concept used to narrow the documentation.","required":false},"top_k":{"type":"integer","description":"Maximum matching node pages. Defaults to 3.","required":false,"default":3}},"entrypoint":"scripts/main.py:run"}
---
# Explain Node Parameters

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
