---
{"name":"setup_copernicus_pipeline","category":"workflow","description":"Return a Copernicus texture generation and channel-packing blueprint. Does not modify the scene or write images.","risk_level":"normal","parameters":{"texture_name":{"type":"string","description":"Texture-set basename.","required":true},"resolution":{"type":"integer","description":"Square texture resolution; default 2048.","required":false,"default":2048},"output_format":{"type":"string","description":"exr, png, or tif; default exr.","required":false,"default":"exr"}},"entrypoint":"scripts/main.py:run"}
---
# Setup Copernicus Pipeline

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
