<!-- markdownlint-disable-file -->
# Release Changes: Houdini-Agent 核心 Module 深化

**Related Plan**: 20260814-core-modules-deepening-plan.md  
**Implementation Date**: 2026-08-17

## Summary

按当前版本复核结果重新实施 Tool authority、Session Workspace、Plan lifecycle、Memory embedding provenance 与 Context assembly。变更以现有 module 为边界，保持旧插件、Plan JSON、Session Cache、隐私和 Agent session anchor 兼容语义。

## Changes

### Added

- houdini_agent/utils/memory_sqlite.py - 提供个人与团队 Memory 共用的最小 SQLite lifecycle、WAL fallback 和 embedding metadata mechanics。
- tests/test_tool_registry.py - 增加插件注册原子性、owner 冲突、runtime、mode 与注销回归覆盖。
- tests/test_plan_quality_runtime.py - 增加 Confirm/Reject、error/blocked、session 恢复及 Registry quality gate 覆盖。
- tests/test_session_manifest.py - 增加统一保存 owner、原子提交失败和 stale writer 覆盖。
- tests/test_team_memory.py - 增加 embedding provenance、legacy migration、统一重嵌入和原子发布覆盖。
- tests/test_token_optimizer.py - 增加结构化 context sections、动态降级、Tool schema 预算、图片与 pairing 覆盖。
- tests/test_cache_mixin_runtime.py - 增加 `_load_cache()` 静默恢复与 `SessionCacheRecord` 真实运行路径覆盖。
- tests/test_ai_client_thinking.py - 增加 tools-aware 413 recovery、完整 round 与 tool-call pairing 直接覆盖。

### Modified

- houdini_agent/utils/tool_registry.py - Registry 成为插件 schema、handler、owner、enabled、modes、risk 和 runtime 权威，并对执行约束 fail closed。
- houdini_agent/utils/hooks.py - 删除插件 Tool 重复存储并将注册、注销直接委托 Registry。
- houdini_agent/core/send_orchestrator_mixin.py - 通过 Registry 公共 API 选择 Tool，并使用结构化 context assembly 和最终 Tool-aware budget。
- houdini_agent/core/tool_execution_mixin.py - 使用 Registry 公共权限视图替代私有存储读取。
- houdini_agent/utils/mcp/client.py - 删除 HookManager-first 插件执行 fallback，Registry mode/runtime 不匹配时拒绝执行。
- houdini_agent/core/cache_records.py - 增加统一 Session cache record builder。
- houdini_agent/core/cache_mixin.py - 所有保存入口委托统一 owner，以 staging、失败回滚和 manifest-last 协议提交，并延后空 session 删除。
- houdini_agent/core/main_window.py - 集中 restore/save orchestration，并在用户切换时停止旧 writer。
- houdini_agent/ui/ai_tab.py - 移除重复 restore 与退出保存 owner。
- houdini_agent/core/session_manager.py - session 切换时恢复对应 Plan projection，同时保持 Agent run anchor。
- houdini_agent/utils/plan_manager.py - Confirm/Reject 使用 Python 3.7 兼容的原子持久化，写入或归档失败保留旧 active Plan，并修正 error/blocked 总体状态及 quality gate。
- houdini_agent/utils/plan_runtime.py - 从 step 状态派生安全的总体 Plan 状态，并拒绝不可执行 Tool。
- houdini_agent/core/plan_mixin.py - UI phase 从持久化 Plan 派生，删除 running 自动完成。
- houdini_agent/utils/memory_store.py - 保存并校验个人 embedding provenance，legacy/mismatch 停止评分，migration 可备份回滚。
- houdini_agent/utils/team_memory_export.py - 导出完整 backend/model/dimension/format provenance。
- houdini_agent/utils/team_memory_store.py - 统一重嵌入，在 shadow DB 校验后原子发布并刷新 singleton。
- houdini_agent/utils/token_optimizer.py - 建立唯一 prefix/history/dynamic suffix assembly 与 round-safe pruning，并显式报告最终预算是否满足。
- houdini_agent/utils/ai_client.py - 主动压缩和 413 recovery 复用统一 planner，始终计入实际 Tool schema，并在无法安全达标时停止发送或重试。
- houdini_agent/core/context_manager_mixin.py - 手动压缩改用完整 round/tool-chain mechanics。
- tests/test_cache_records.py - 验证 canonical record shape 与兼容图片占位。
- tests/test_manual_update_mode_directive.py - 验证 Confirm adapter 先经过 PlanManager。

### Removed

- houdini_agent/utils/hooks.py - 移除 `_external_tools` 及其 schema/handler/execute 双路径。
- houdini_agent/utils/mcp/client.py - 移除绕过 Registry 的插件 handler fallback。
- houdini_agent/utils/ai_client.py - 移除迁移后的手写 round splitting 和 assistant 正文字符截断。
- houdini_agent/core/cache_mixin.py - 移除无 caller 的图片缓存 wrapper、空 workspace cache metadata 路径及迁移后无用 import。
- houdini_agent/core/context_manager_mixin.py - 移除统一 context mechanics 后失去 caller 的 `_compress_context()`。

## Validation

- AIClient、Context、Registry、Session 与 Memory 聚焦回归：150 tests passed。
- Houdini 18.5/Python 3.7 Cache、Session 与 Plan 聚焦回归：30 tests passed。
- Python 3.7 AST 语法检查：相关生产和测试文件全部通过。
- VS Code workspace diagnostics：0 errors。
- `test_manual_update_mode_directive` 在 Houdini 18.5/PySide2 下有 7 个既有 `object.__new__(AITab)` 构造错误；与本次 Plan lifecycle 逻辑断言无关，未扩展范围修改测试夹具。

## Project Boundary

- UI/MCP/Bridge 共享 `ToolExecutionGateway`、Standalone `local` adapter 与全量 Houdini/PySide UI 回归经用户确认属于其他项目，不计入本计划 Remaining Work。
- 本计划范围内没有剩余实施项。

## Release Summary

本轮完成五个核心 module 的权威归一、可靠持久化、embedding provenance 和统一 context mechanics；删除迁移孤儿并完成 Python 3.7/Houdini 兼容验证。未新增第三方依赖，未改变用户数据保留、Team Memory 隐私或 Agent session anchor 语义。
