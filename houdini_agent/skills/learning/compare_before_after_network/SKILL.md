---
{"name":"compare_before_after_network","category":"learning","description":"比较修改前后的 Houdini 网络快照，报告新增、删除、类型变化、参数变化和健康状态变化，并生成可审核的经验草稿。快照应来自 get_scene_snapshot 或等价只读采集。","risk_level":"low","parameters":{"before_snapshot":{"type":"object","description":"修改前快照。","required":true},"after_snapshot":{"type":"object","description":"修改后快照。","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Compare Before After Network

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
