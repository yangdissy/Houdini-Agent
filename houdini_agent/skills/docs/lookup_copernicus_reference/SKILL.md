---
{"name":"lookup_copernicus_reference","category":"docs","description":"Look up a Copernicus, OpenCL COP, or output-capture concept in Houdini's shipped manual and the bundled production notes. Returns structured evidence; read-only.","risk_level":"low","parameters":{"query":{"type":"string","description":"Copernicus, OpenCL, VEX COP, or output-capture concept.","required":true},"top_k":{"type":"integer","description":"Maximum results from each documentation source. Defaults to 5.","required":false,"default":5}},"entrypoint":"scripts/main.py:run"}
---
# Lookup Copernicus Reference

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
