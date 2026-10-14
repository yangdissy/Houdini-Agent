---
{"name":"procedural_modeling_guide","category":"workflow","description":"Return a read-only SOP procedural modeling guide with recommended workflow, node-chain suggestions, node-search keywords, anti-patterns, verification steps, and fallbacks. Use before creating geometry assets so the build favors native SOP nodes over VEX or Python.","risk_level":"low","parameters":{"description":{"type":"string","description":"Geometry or asset the user wants to create.","required":true},"output_context":{"type":"string","description":"Target network context. Default '/obj'.","required":false,"default":"/obj"},"complexity":{"type":"string","description":"simple, medium, or complex. Controls recommendation detail.","required":false,"default":"medium"}},"entrypoint":"scripts/main.py:run"}
---
# Procedural Modeling Guide

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
