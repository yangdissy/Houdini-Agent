# Houdini-Agent 更新记录（2026-07-20）

## Manual 空几何误诊修复

本次修复 Direct Execute 模式下 Houdini 处于 Manual 更新时，Agent 遇到几何连续为空却继续普通 cook、查参数或替换 Sphere/Box 的误诊路径。

### 改动

- `get_geometry_summary` 新增结构化验证信号：`update_mode`、`manual_mode`、`is_empty_geometry`、`validation_confidence`、`recommended_next_action`。
- `verify_network` 工具返回保留原文本报告，同时附加 `validation_signal`，方便 Agent 机器读取 Manual + 空几何状态。
- 执行层新增轻量 loop guard：同一节点/网络出现“空几何 -> 普通 cook -> 仍为空”时，在工具结果中加入 `recovery_hint`，并写入 bounded diagnostics 事件。
- diagnostics export 增加 session audit 记录数、最后记录时间和 stale 标记，避免 audit 路径存在但内容来自旧 run 时误导排查。
- 工具描述与工具选择指南强调：普通 `cook_node` 成功不能排除 Manual 空几何；应优先遵循 `recommended_next_action=temporary_auto_validate`。

### 安全边界

- loop guard 只提示和审计，不自动切换 Houdini update mode。
- Direct Execute 模式仍可临时 Auto 验证，但结束时由框架恢复用户原始 update mode。
- Confirm / 逐步确认模式不得擅自切 Auto，只能请求用户授权或说明需要手动 cook。

### 验证

```text
python -m unittest tests.test_geometry_validation_signals tests.test_harness_execution_boundary tests.test_manual_update_mode_directive tests.test_diagnostics_export tests.test_harness_policy tests.test_tool_contracts tests.test_tool_registry
```

结果：93 tests passed。