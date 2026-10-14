---
{"name":"setup_kinefx_pipeline","category":"workflow","description":"Return a KineFX skeleton, rig-pose, capture, or retarget blueprint. Does not modify the scene.","risk_level":"normal","parameters":{"source_node_path":{"type":"string","description":"Existing skeleton or character geometry source.","required":true},"mode":{"type":"string","description":"rig, capture, or retarget. Default rig.","required":false,"default":"rig"}},"entrypoint":"scripts/main.py:run"}
---
# Setup Kinefx Pipeline

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
