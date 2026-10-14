---
{"name":"extract_network_contract","category":"learning","description":"从指定 Houdini 网络或输出节点提取可复用接口契约：边界输入、输出、必需输入数、读取和写入的几何属性、时间依赖、外部文件与脆弱路径。适合保存工作流记忆或封装 HDA 前审核。只读，不修改网络。","risk_level":"low","parameters":{"node_path":{"type":"string","description":"网络容器或输出节点路径。","required":true},"max_nodes":{"type":"integer","description":"最多分析节点数，默认 200，最大 2000。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Extract Network Contract

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
