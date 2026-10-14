---
{"name":"setup_instance_scatter","category":"workflow","description":"Return a SOP or USD point-instancing blueprint with density, orientation, variation, and output stages. Does not modify the scene.","risk_level":"normal","parameters":{"surface_node_path":{"type":"string","description":"Existing surface node used for scattering.","required":true},"instance_node_path":{"type":"string","description":"Existing geometry or asset to instance.","required":true},"mode":{"type":"string","description":"'sop' or 'usd'. Default sop.","required":false,"default":"sop"},"count":{"type":"integer","description":"Target point count for SOP scatter.","required":false,"default":1000}},"entrypoint":"scripts/main.py:run"}
---
# Setup Instance Scatter

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
