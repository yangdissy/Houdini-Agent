---
{"name":"usd_scene_assembly_guide","category":"workflow","description":"Return a read-only LOPs/USD scene assembly guide with stage planning, LOP node plan, USD-native material rules, viewport-first lookdev guidance, anti-patterns, and verification steps. Use before building Solaris scenes or lookdev setups.","risk_level":"low","parameters":{"scene_description":{"type":"string","description":"USD scene or lookdev setup the user wants to assemble.","required":true},"renderer":{"type":"string","description":"karma, storm, or usd_preview. Default karma.","required":false,"default":"karma"},"lookdev_first":{"type":"boolean","description":"Whether to prioritize viewport/Hydra preview before final renders. Default true.","required":false,"default":true}},"entrypoint":"scripts/main.py:run"}
---
# Usd Scene Assembly Guide

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
