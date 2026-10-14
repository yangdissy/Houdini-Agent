---
{"name":"analyze_cook_performance","category":"performance","description":"分析网络中所有节点的 cook 性能：耗时排名、几何体膨胀点、错误/警告节点、总 cook 时间统计。适用于性能诊断和优化场景。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"网络路径，如 /obj/geo1","required":true},"top_n":{"type":"integer","description":"返回最慢的前 N 个节点（默认 10）","required":false},"force_cook":{"type":"boolean","description":"分析前是否强制重新 cook 以获取最新数据（默认 false）","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Analyze Cook Performance

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
