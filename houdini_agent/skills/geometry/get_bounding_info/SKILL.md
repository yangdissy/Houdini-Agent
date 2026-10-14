---
{"name":"get_bounding_info","category":"geometry","description":"获取几何体的边界盒信息：min/max/center/size/对角线长度/体积/表面积/长宽比/最长轴/最短轴。适用于检查模型尺寸、对齐、缩放等场景。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"节点路径，如 /obj/geo1/box1","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Get Bounding Info

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
