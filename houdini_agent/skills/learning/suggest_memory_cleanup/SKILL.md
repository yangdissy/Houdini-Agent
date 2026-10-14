---
{"name":"suggest_memory_cleanup","category":"learning","description":"审查传入的记忆记录，建议合并重复项、标记潜在冲突、泛化过度具体项和复核低价值项。只返回建议，不打开其他用户数据库，不修改、降权或删除任何记忆。","risk_level":"low","parameters":{"memory_records":{"type":"array","description":"从记忆管理器导出的记录列表。","required":true},"duplicate_threshold":{"type":"number","description":"文本重复阈值，默认 0.86。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Suggest Memory Cleanup

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
