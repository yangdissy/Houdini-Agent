<!-- markdownlint-disable-file -->
# Release Changes: 执行、工具、插件与文档 Module 深化

**Related Plan**: 20260817-execution-tools-plugins-docs-deepening-plan.md  
**Implementation Date**: 2026-08-17

## Summary

深化受治理 Tool 执行、Registry 工具语义、插件注册生命周期和离线 Help Source 读取链，保留 Registry 双重授权、Houdini 主线程 operation lifecycle、ADR-0001 路径分类及 cache v2 格式。

## Changes

### Added

- houdini_agent/core/harness_engine.py - 增加 `GovernedToolExecutor`，统一 policy、confirmation、retry、adapter、result guardrail 和安全审计顺序。
- tests/test_harness_execution_boundary.py - 增加 allow/deny/ask/retry、policy/confirm/adapter exception、敏感审计和 batch 逐项治理覆盖。
- tests/test_tool_registry.py - 增加代表性工具语义快照、默认/Registry profile 一致性和 metadata-driven plugin Tool 覆盖。
- tests/test_plugin_lifecycle.py - 增加部分注册失败完整回滚、decorator disable/re-enable 和 owner-scoped cleanup 覆盖。
- houdini_agent/utils/help_source.py - 增加统一过滤、decode 和 size limit 的 `get_page()` 单页读取 seam。
- tests/test_help_source.py - 增加同一临时 ZIP 驱动 page、search、Doc Index 与隔离 cache 的贯通测试。

### Modified

- houdini_agent/core/tool_execution_mixin.py - UI 委托受治理 execution owner，batch 每项穿过同一 Harness，caller 不再重建 policy decision 流程。
- houdini_agent/utils/tool_registry.py - `ToolMeta` 增加 mutating、undo、cook、read-before-cook 和 cache invalidation 事实，稳定 profile 从 metadata 派生。
- houdini_agent/core/houdini_main_thread_executor.py - undo/cook/read-before-cook 优先读取 Registry 语义，Registry 不可用时保留兼容 fallback。
- houdini_agent/utils/hooks.py - 首次 load/re-enable 共享 decorator registration，register 失败完整 cleanup，pending decorator import 结束必清理。
- houdini_agent/skills/search_houdini_help.py - search/page 共用 Help Source archive、过滤、decode 和 limits，不再直接读取 ZIP。
- houdini_agent/utils/doc_rag.py - constructor 可注入 cache/doc 生命周期路径并关闭 knowledge load，默认行为和 cache version 2 不变。

### Removed

- houdini_agent/core/tool_execution_mixin.py - 移除重复 ask/retry/audit/result-cleaning 编排。
- houdini_agent/skills/search_houdini_help.py - 移除直接 `ZipFile` 单页读取和重复 archive 常量。

## Validation

- 实施前聚焦基线：144 tests passed。
- 完整测试套件：310 tests passed。
- Python 3.7 AST：8 个修改的生产文件全部通过。
- VS Code workspace diagnostics：0 errors。
- Registry 双授权保留：Harness 前置授权保护 runtime 分流，MCP 授权保护直接 caller 与 TOCTOU；未证明可安全删除。
- Houdini 内确认、拒绝、长 cook timeout、插件 reload 与离线帮助查询已由用户完成宿主实测并确认通过。

## Remaining Scope

- 插件常规 reload 宿主实测通过；“新版本 reload 失败保留旧实例”仍需要能隔离 Registry/Hook/UI staged ownership 的后续切片。
- 完整组织级语义矩阵仍保留少量兼容 fallback；本次先统一有多个真实 consumer 的 mutating/undo/cook/cache 事实。
- `action_commands_mixin.py` 的用户显式创建 Wrangle 动作仍直接进入 MCP/Registry，不属于 LLM Tool request，未强行套 Harness confirmation。

## Release Summary

**Total Files Affected**: 13

### Files Created (2)

- tests/test_plugin_lifecycle.py - 插件生命周期 characterization 与 rollback 回归。
- .copilot-tracking/changes/20260817-execution-tools-plugins-docs-deepening-changes.md - 实施与验证记录。

### Files Modified (11)

- houdini_agent/core/harness_engine.py - 受治理 Tool execution owner。
- houdini_agent/core/tool_execution_mixin.py - UI caller 委托与 batch 逐项治理。
- houdini_agent/core/houdini_main_thread_executor.py - Registry-driven execution semantics。
- houdini_agent/utils/tool_registry.py - 统一 Tool semantics facts。
- houdini_agent/utils/hooks.py - 插件失败 rollback 与 decorator path 统一。
- houdini_agent/utils/help_source.py - 唯一 page lookup implementation。
- houdini_agent/skills/search_houdini_help.py - 删除 ZIP mechanics 泄漏。
- houdini_agent/utils/doc_rag.py - 可隔离的 cache/doc lifecycle inputs。
- tests/test_harness_execution_boundary.py - Harness 端到端回归。
- tests/test_tool_registry.py - Tool semantics 回归。
- tests/test_help_source.py - Help Source/Doc Index 贯通回归。

### Files Removed (0)

### Dependencies & Infrastructure

- **New Dependencies**: 无运行时依赖；仅在选定开发环境安装 pytest 以执行现有 tests。
- **Updated Dependencies**: 无。
- **Infrastructure Changes**: 无。
- **Configuration Updates**: 无。

### Deployment Notes

无需用户数据迁移；Tool Registry、plugin registration API、cache version 2 与现有配置文件格式保持兼容。上线前建议在 Houdini 宿主中完成 Remaining Scope 所列交互验证。
