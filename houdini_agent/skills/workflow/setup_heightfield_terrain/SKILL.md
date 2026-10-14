---
{"name":"setup_heightfield_terrain","category":"workflow","description":"Return a heightfield terrain blueprint with noise, erosion, masks, scatter preparation, and output. Does not modify the scene.","risk_level":"normal","parameters":{"terrain_name":{"type":"string","description":"Terrain output name.","required":true},"size":{"type":"number","description":"Terrain world size; default 1000.","required":false,"default":1000},"resolution":{"type":"integer","description":"Heightfield resolution; default 1024.","required":false,"default":1024},"erosion":{"type":"boolean","description":"Include erosion stage; default true.","required":false,"default":true}},"entrypoint":"scripts/main.py:run"}
---
# Setup Heightfield Terrain

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
