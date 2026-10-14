---
{"name":"find_attribute_references","category":"geometry","description":"查找网络中所有引用了某个属性的节点。检查范围: VEX 代码（wrangle）、参数表达式、字符串参数值。适用于追踪属性使用、重构属性名、调试管线等场景。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"网络路径，如 /obj/geo1","required":true},"attr_name":{"type":"string","description":"属性名称，如 P, Cd, class, piece","required":true},"recursive":{"type":"boolean","description":"是否递归搜索子网络，默认 False","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Find Attribute References

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
