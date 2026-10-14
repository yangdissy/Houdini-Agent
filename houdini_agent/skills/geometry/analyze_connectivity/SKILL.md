---
{"name":"analyze_connectivity","category":"geometry","description":"分析几何体的连通性：有多少个独立部分，每部分的点数/面数/占比。如果有 class 属性则直接使用，否则用并查集算法计算。适用于检测碎片数量、分离的网格、破碎效果分析等。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"节点路径，如 /obj/geo1/pighead1","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Analyze Connectivity

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
