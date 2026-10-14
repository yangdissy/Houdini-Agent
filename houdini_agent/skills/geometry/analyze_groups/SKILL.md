---
{"name":"analyze_groups","category":"geometry","description":"Analyze SOP geometry point, primitive, and edge groups. Reports group sizes, empty groups, and compact membership samples. Read-only.","risk_level":"low","parameters":{"node_path":{"type":"string","description":"SOP node path, for example /obj/geo1/OUT.","required":true},"include_members":{"type":"boolean","description":"Include limited member number samples for each group.","required":false,"default":false},"max_members":{"type":"integer","description":"Maximum sampled member numbers per group when include_members is true.","required":false,"default":20}},"entrypoint":"scripts/main.py:run"}
---
# Analyze Groups

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
