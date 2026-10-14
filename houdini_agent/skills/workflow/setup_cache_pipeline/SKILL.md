---
{"name":"setup_cache_pipeline","category":"workflow","description":"Return a read/write File Cache blueprint with stable path, version, frame range, and OUT node. Does not modify the scene or write cache files.","risk_level":"normal","parameters":{"source_node_path":{"type":"string","description":"Existing SOP node to cache.","required":true},"cache_name":{"type":"string","description":"Cache basename without extension.","required":true},"version":{"type":"integer","description":"Positive cache version; default 1.","required":false,"default":1},"frame_start":{"type":"integer","description":"First cache frame.","required":false,"default":1},"frame_end":{"type":"integer","description":"Last cache frame.","required":false,"default":240}},"entrypoint":"scripts/main.py:run"}
---
# Setup Cache Pipeline

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
