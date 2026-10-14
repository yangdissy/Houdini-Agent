---
{"name":"inspect_lop_stage","category":"usd","description":"Inspect a LOP node's USD stage: layers, prim type counts, cameras, lights, material-binding candidates, payloads, and references. Read-only.","risk_level":"low","parameters":{"node_path":{"type":"string","description":"LOP node path, for example /stage/OUT.","required":true},"max_prims":{"type":"integer","description":"Maximum prims to inspect before truncating. Defaults to 5000.","required":false,"default":5000}},"entrypoint":"scripts/main.py:run"}
---
# Inspect Lop Stage

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
