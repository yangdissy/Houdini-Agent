---
{"name":"build_hip_learning_report","category":"learning","description":"汇总当前 HIP 的已有只读分析结果，生成学习报告：精华子图、设计规律、重复模式、接口契约、脆弱引用、资产化候选和记忆候选。它负责编排结果，不重复修改或扫描场景。","risk_level":"low","parameters":{"hip_name":{"type":"string","description":"HIP 文件名。","required":true},"analysis_results":{"type":"object","description":"其他学习 Skill 返回结果的字典。","required":true}},"entrypoint":"scripts/main.py:run"}
---
# Build Hip Learning Report

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
