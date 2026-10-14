---
{"name":"analyze_geometry_attribs","category":"geometry","description":"分析节点几何体属性。支持 point/vertex/prim/detail 四种类别。不传 attrib_name 时返回属性列表；传入时返回统计信息（min/max/mean/std/nan/inf）。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"节点路径，如 /obj/geo1/box1","required":true},"attrib_name":{"type":"string","description":"属性名（如 P, N, uv, Cd）。留空则返回该类别的属性列表","required":false},"attrib_class":{"type":"string","description":"属性类别: point, vertex, prim, detail（默认 point）","required":false},"max_sample":{"type":"integer","description":"最大采样数（默认 100000，超过时随机采样）","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Analyze Geometry Attribs

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
