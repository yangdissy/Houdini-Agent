---
{"name":"lookup_vex_reference","category":"docs","description":"Look up a VEX function, concept, or error in Houdini's shipped VEX manual and the bundled snippet reference. Returns source paths and structured evidence; read-only.","risk_level":"low","parameters":{"query":{"type":"string","description":"VEX function name, concept, or error text to look up.","required":true},"top_k":{"type":"integer","description":"Maximum results from each documentation source. Defaults to 5.","required":false,"default":5}},"entrypoint":"scripts/main.py:run"}
---
# Lookup Vex Reference

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
