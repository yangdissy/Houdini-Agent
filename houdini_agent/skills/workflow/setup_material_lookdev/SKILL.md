---
{"name":"setup_material_lookdev","category":"workflow","description":"Return a MaterialX/Karma or classic SOP material lookdev blueprint with material binding and preview lighting. Does not modify the scene.","risk_level":"normal","parameters":{"material_name":{"type":"string","description":"Name for the material.","required":true},"mode":{"type":"string","description":"'karma' or 'sop'. Default karma.","required":false,"default":"karma"},"source_node_path":{"type":"string","description":"Optional existing geometry source path.","required":false,"default":""}},"entrypoint":"scripts/main.py:run"}
---
# Setup Material Lookdev

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
