---
{"name":"houdini_hip_qc","category":"workflow","description":"对当前已打开的 Houdini HIP 工程执行只读流程规范 QC，检查版本、命名、集成缓存/导出路径、VDB 发布路径和外部引用，并将无法从场景证明的 ChooseTask、Daily、SubmitTool、Publish 等条目明确列为存疑。适用于“检查工程规不规范”“QC 这个 Houdini 文件”“过一遍流程规范”。","risk_level":"low","parameters":{"project_fps":{"type":"number","description":"项目要求的帧率；不提供时只报告当前帧率并标为存疑。","required":false,"default":null},"max_nodes":{"type":"integer","description":"最多扫描的节点数，默认 10000。","required":false,"default":10000}},"entrypoint":"scripts/main.py:run"}
---
# Houdini Hip Qc

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
