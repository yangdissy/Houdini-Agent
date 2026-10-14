---
{"name":"recall_workflow_for_task","category":"learning","description":"根据当前 Houdini 任务和场景节点类型，对 search_memory 返回的候选记忆二次排序，说明可复用部分、差异和验证步骤。不会自行打开其他用户数据库，也不会修改场景。","risk_level":"low","parameters":{"task_description":{"type":"string","description":"当前要完成的任务。","required":true},"memory_records":{"type":"array","description":"由 search_memory 返回的候选记忆列表。","required":true},"scene_node_types":{"type":"array","description":"可选：当前场景已有节点类型。","required":false},"top_k":{"type":"integer","description":"最多返回候选数，默认 3。","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Recall Workflow For Task

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
