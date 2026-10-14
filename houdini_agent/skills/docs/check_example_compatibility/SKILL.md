---
{"name":"check_example_compatibility","category":"docs","description":"Check VEX or Houdini example identifiers against shipped documentation for the current bundled manual. Does not execute code or modify the scene.","risk_level":"low","parameters":{"example":{"type":"string","description":"VEX snippet or Houdini recipe text to check.","required":true},"language":{"type":"string","description":"Example language: vex or houdini. Defaults to vex.","required":false,"default":"vex"}},"entrypoint":"scripts/main.py:run"}
---
# Check Example Compatibility

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
