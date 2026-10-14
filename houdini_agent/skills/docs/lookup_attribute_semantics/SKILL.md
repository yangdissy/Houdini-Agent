---
{"name":"lookup_attribute_semantics","category":"docs","description":"Look up a Houdini geometry attribute's documented type, ownership, consumers, priority, and common pitfalls from bundled references and shipped help. Read-only.","risk_level":"low","parameters":{"attribute":{"type":"string","description":"Attribute name such as P, N, orient, pscale, name, or path.","required":true},"top_k":{"type":"integer","description":"Maximum matches per source. Defaults to 5.","required":false,"default":5}},"entrypoint":"scripts/main.py:run"}
---
# Lookup Attribute Semantics

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
