---
{"name":"analyze_normals","category":"geometry","description":"检测几何体法线质量。检查是否存在法线属性、NaN/Inf 值、零向量、未归一化法线以及翻转面等问题。返回逐项诊断报告。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"节点路径，如 /obj/geo1/box1","required":true},"tolerance":{"type":"number","description":"归一化容差（默认 0.001，长度偏离 1.0 超过此值视为未归一化）","required":false},"flip_angle_threshold":{"type":"number","description":"翻转检测角度阈值（度，默认 120，相邻面法线夹角超过此值视为翻转）","required":false},"max_sample":{"type":"integer","description":"最大采样数（默认 200000，超过时随机采样）","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Analyze Normals

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
