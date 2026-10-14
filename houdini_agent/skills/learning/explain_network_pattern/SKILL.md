---
{"name":"explain_network_pattern","category":"learning","description":"解释指定节点上游网络为什么有效，识别 source/process/branch/output 角色、关键控制点、脚本和参数，输出可复用设计规律及记忆草稿。适合从优秀 HIP 中学习方法，而不只是罗列节点。只读，不直接写记忆。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"要解释的输出或关键节点路径。","required":true},"max_nodes":{"type":"integer","description":"最多分析的上游节点数，默认 30，最大 80。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Explain Network Pattern

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
