---
{"name":"debug_scene_workflow","category":"scene","description":"Return a read-only Houdini debugging route with recommended existing skills, common causes, stop conditions, and verification steps. Use when a scene, node, SOP network, USD stage, simulation, or performance problem is reported.","risk_level":"low","parameters":{"problem_description":{"type":"string","description":"Problem or failure the user reports.","required":true},"scope":{"type":"string","description":"scene, node, sop, usd, simulation, or performance. Default scene.","required":false,"default":"scene"}},"entrypoint":"scripts/main.py:run"}
---
# Debug Scene Workflow

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
