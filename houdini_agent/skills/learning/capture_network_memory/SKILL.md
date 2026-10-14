---
{"name":"capture_network_memory","category":"learning","description":"分析当前 HIP 中选中节点或指定网络，找出值得长期记住的节点连接精华。按连接结构、VEX/Python、表达式、非默认参数、注释和输出角色评分，返回候选子图、连接、关键参数及可审核的 memory_draft。此 Skill 只读且不会直接写入记忆；用户确认后再调用 remember_memory。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"可选根节点或网络路径；留空时使用当前选中节点。","required":false},"max_nodes":{"type":"integer","description":"每个候选子图最多包含的节点数，默认 20，最大 50。","required":false},"candidate_count":{"type":"integer","description":"最多返回多少个候选，默认 3，最大 5。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Capture Network Memory

用于只读分析当前 Houdini 网络并生成可审核的记忆候选。调用前应明确 `node_path`，或确认当前节点选择符合用户意图。返回的 `memory_draft` 只是候选，不得自动写入长期记忆；只有用户明确确认后才能调用记忆写入工具。
