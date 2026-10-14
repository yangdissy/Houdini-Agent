---
{"name":"find_fragile_references","category":"learning","description":"扫描 Houdini 网络中的脆弱引用：绝对节点路径、相对通道引用、op: URI、外部文件、环境变量、跨节点 detail/point/prim 读取以及脚本硬编码路径。返回风险级别、证据和修复建议。只读，不修改参数。","risk_level":"low","parameters":{"network_path":{"type":"string","description":"要扫描的网络路径。","required":true},"recursive":{"type":"boolean","description":"是否递归扫描子网络，默认 true。","required":false},"max_nodes":{"type":"integer","description":"最多扫描节点数，默认 2000。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Find Fragile References

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
