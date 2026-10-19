---
{"name":"get_workflow_guide","category":"workflow","description":"Return an on-demand, read-only Houdini workflow guide for a SideFX help scope. Use before designing an unfamiliar multi-node setup or after repeated failed fixes. The guide provides decisions, order of work, failure signatures, official help scopes, and local Skill handoffs; it does not modify the scene.","risk_level":"low","parameters":{"topic":{"type":"string","description":"Workflow topic or common simulation alias, such as pyro, smoke, model, solaris, troubleshooting, or ocean.","required":true},"description":{"type":"string","description":"Optional task or problem used to frame the guide.","required":false,"default":""}},"entrypoint":"scripts/main.py:run"}
---
# Get Workflow Guide

Fetch this Skill on demand. Treat its output as design guidance, not proof that scene work is complete. Execute any recommended scene changes through existing harness-managed tools and blueprint Skills.