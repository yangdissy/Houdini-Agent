---
{"name":"lookup_expression_reference","category":"docs","description":"Look up HScript expressions, channel references, local variables, and VEX snippet syntax, preserving the documented execution context and source. Read-only.","risk_level":"low","parameters":{"query":{"type":"string","description":"Expression function, variable, syntax, or use case to look up.","required":true},"top_k":{"type":"integer","description":"Maximum matches per source. Defaults to 5.","required":false,"default":5}},"entrypoint":"scripts/main.py:run"}
---
# Lookup Expression Reference

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
