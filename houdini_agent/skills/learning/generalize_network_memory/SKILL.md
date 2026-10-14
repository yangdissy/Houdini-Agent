---
{"name":"generalize_network_memory","category":"learning","description":"把具体 HIP 节点记忆泛化为可迁移规则：移除绝对路径、节点编号和项目文件名，保留前置条件、核心流程、输入输出契约、适用边界与验证方法。只生成候选 memory_draft，不直接写入长期记忆。","risk_level":"low","parameters":{"memory_text":{"type":"string","description":"要泛化的原始工作流记忆。","required":true},"contract":{"type":"object","description":"可选：extract_network_contract 的结果。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Generalize Network Memory

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
