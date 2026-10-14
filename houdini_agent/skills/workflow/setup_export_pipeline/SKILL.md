---
{"name":"setup_export_pipeline","category":"workflow","description":"Return an Alembic, USD, FBX, BGEO, or VDB export blueprint with a delivery path and frame range. Does not write files.","risk_level":"normal","parameters":{"source_node_path":{"type":"string","description":"Existing node to export.","required":true},"format":{"type":"string","description":"abc, usd, fbx, bgeo, or vdb.","required":true},"asset_name":{"type":"string","description":"Delivery basename.","required":true},"frame_start":{"type":"integer","description":"First export frame.","required":false,"default":1},"frame_end":{"type":"integer","description":"Last export frame.","required":false,"default":240}},"entrypoint":"scripts/main.py:run"}
---
# Setup Export Pipeline

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
