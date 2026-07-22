# Houdini-Agent 更新记录（2026-07-22）

## 发布摘要

本次更新主要围绕 Houdini 运行稳定性、Manual/Auto 验证路径、Cursor 风格 UI 模块拆分与调试开关治理展开。

核心目标是降低 Houdini 主线程工具执行与 Qt 生命周期交错时的崩溃风险，同时让团队可以关闭旧的 Selection Watch 自动停止保护，真实压测新的 lifecycle-safe main-thread executor。

---

## 一、Lifecycle-safe Houdini 主线程执行器

新增 `houdini_agent/core/houdini_main_thread_executor.py`，将 Houdini 主线程工具执行从 `AITab` / `ToolExecutionMixin` 的散落状态中收敛到 `HoudiniMainThreadExecutor`。

### 改动

- 新增 `HoudiniMainThreadExecutor.execute(...)` / `execute_batch(...)`，集中管理主线程工具请求、结果队列、timeout、blocked 和 shutdown 状态。
- `AITab.cleanup()` 触发 executor `shutdown()`；关闭或切换生命周期后，新的 Houdini 主线程工具执行会 fail closed。
- 工具执行 timeout 后 executor 进入 `blocked`，后续 Houdini 工具请求直接拒绝，避免旧 cook / hou 操作仍在主线程执行时继续堆新的 BlockingQueuedConnection。
- 单工具与批量工具请求都附加私有 `_ha_operation_id`，slot 返回时通过 operation envelope 入队，executor 只接受当前 operation 的结果，忽略 timeout 后迟到的旧结果。
- `run_in_main_thread(...)` 接管 update-mode cook guard、read-before-cook、undo group、节点变更快照、selection baseline refresh 和异常格式化。
- `ToolExecutionMixin._on_execute_tool_main_thread` 收敛为 Qt adapter：主线程断言、移除私有 operation id、调用 executor wrapper、写回结果 envelope。

### 安全边界

- timeout 不自动恢复执行许可；当前策略是 blocked 后需要停止当前 Agent 或重启面板。
- 不在 blocked 后提供“强制继续”按钮，避免误判 Houdini 主线程已空闲。
- 私有 `_ha_operation_id` 会在进入实际 tool implementation 前移除，不暴露给 `mcp.execute_tool` 业务参数。

---

## 二、Manual / Auto 更新模式验证修复

本次继续收紧 Manual 更新模式下“空几何”验证路径，减少 stale cook 结果导致的误判。

### 改动

- 新增受限工具 `temporary_auto_validate_geometry`：临时切到 Auto update，强制 cook 目标 SOP，读取 geometry summary，然后恢复原 update mode。
- 新增受限工具 `set_update_mode`：允许 Agent 在受管控路径中显式切换 `auto` / `manual`，用于 Manual 空几何持续阻塞后的真实验证。
- `set_update_mode(mode="auto")` 支持 `auto`、`Auto Update`、`auto-update` 等别名。
- 修复 Houdini update mode 枚举解析：优先使用真实常见枚举 `hou.updateMode.AutoUpdate`，并兼容旧代码中的 `AlwaysUpdate` / `Auto` fallback。
- `get_geometry_summary` / `verify_network` / harness loop guard 继续返回结构化信号：`manual_mode`、`validation_blocked`、`validation_block_reason`、`recommended_next_action=temporary_auto_validate`。
- Plan / Direct Execute 提示强调：Manual 模式下连续空几何时，应先检查 update mode，再走受限 Auto 验证路径，不要继续普通 cook、猜参数或替换 generator。

### 修复的问题

- 修复 `set_update_mode(mode="auto")` 在真实 Houdini 中因 `hou.updateMode.Auto` 不存在而返回枚举解析异常的问题。
- 修复外层 snippet 已更新但内部 attrib/VEX 节点仍可能沿用旧 cook 缓存时，Agent 继续误诊几何为空的问题。

---

## 三、Selection Watch Auto Stop 改为默认关闭

为了让团队实测新的 lifecycle-safe main-thread executor 是否仍会触发崩溃，`Selection Watch Auto Stop` 现在改为 opt-in。

### 改动

- 新增 dev feature toggle 配置模块 `houdini_agent/utils/dev_feature_toggles.py`。
- `Selection Watch Auto Stop` 默认值从 enabled 改为 disabled。
- 不设置 `HOUDINI_AGENT_SELECTION_WATCH` 时，溢出菜单中的 `Dev Feature Toggles > Selection Watch Auto Stop` 默认不勾选。
- 默认情况下 `_start_selection_watch()` 不再注册 Houdini selection event loop callback。
- 如需恢复旧保护，可手动勾选菜单，或设置 `HOUDINI_AGENT_SELECTION_WATCH=true`。

### 目的

- 旧 Selection Watch 会在用户改变 Houdini 选择时自动停止 Agent，能规避一类崩溃，但也可能掩盖新的主线程执行器是否真的解决了生命周期问题。
- 默认关闭后，团队可以在真实交互中压测 executor 的 timeout、blocked、shutdown 和 stale-result 隔离能力。

---

## 四、Cursor UI 模块拆分

`houdini_agent/ui/cursor_widgets.py` 从大型混合实现文件拆成更聚焦的 UI 模块，降低维护和排障时的上下文成本。

### 新增模块

- `cursor_theme.py`：Cursor 风格 UI 主题常量。
- `cursor_rich_content.py`：Markdown、代码块、语法高亮、富文本与 shell 输出渲染。
- `cursor_chat_widgets.py`：聊天响应、状态、工具调用展示、图片预览、参数 diff、折叠内容等。
- `cursor_plan_widgets.py`：Plan 卡片、DAG、Plan viewer、ask-question 卡片。
- `cursor_input_widgets.py`：输入框、节点补全、slash command、状态栏、VEX preview dialog。
- `cursor_analytics_widgets.py`：todo list 与 token analytics panel。
- `cursor_plugin_manager_dialog.py`：插件管理与插件设置对话框。
- `cursor_rules_editor_dialog.py`：规则编辑器与 IME 友好编辑控件。
- `cursor_utility_widgets.py`：发送/停止按钮与更新通知 banner。

### 兼容性

- `cursor_widgets.py` 保留为 compatibility facade，继续 re-export 旧导入名。
- 现有调用方已逐步迁移到 focused-module imports，包括 `ai_tab.py`、`input_area.py`、`chat_view.py`、`header.py`、`image_mixin.py`、`tool_result_mixin.py`、`agent_runner.py`、`plan_mixin.py`、`session_manager.py` 等。
- 本轮只做机械拆分与 import 收敛，不 redesign Plan、插件、规则、富文本或输入行为。

---

## 五、Cache / History 记录与渲染整理

新增缓存记录相关模块和测试，继续把会话历史与缓存渲染从 UI 大文件中拆出来。

### 改动

- 新增 `houdini_agent/core/cache_records.py`，沉淀缓存记录结构与处理逻辑。
- 新增 `houdini_agent/ui/history_rendering_mixin.py`，把历史渲染逻辑从会话/UI 主体中抽离。
- 补充 `tests/test_cache_records.py` 与 `tests/test_cache_history_rendering.py`。
- README / README_CN 同步更新相关说明。

---

## 六、上下文、提示词与工具契约调整

### 改动

- `context_manager_mixin.py`、`ai_client.py`、`tool_registry.py` 中的工具说明同步更新 `set_update_mode` 与 Manual/Auto 验证约束。
- `harness_engine.py` / `harness_policy` 继续保持受限工具策略：`set_update_mode` 可用但不是通用代码执行，`cook_node force=true` 仍按高风险处理。
- `ui/i18n.py` / Plan prompt 补充 Manual update mode 下的验证纪律。
- `token_optimizer.py` 与相关测试继续修正模型成本估算与 token 统计逻辑。
- thinking / tool-call 清洗相关测试覆盖 OpenAI-compatible 消息格式的边界。

---

## 七、测试与验证

本次已运行以下聚焦回归：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_geometry_validation_signals
```

结果：9 tests passed。

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_geometry_validation_signals tests.test_manual_update_mode_directive tests.test_harness_execution_boundary tests.test_harness_policy tests.test_tool_contracts
```

结果：60 tests passed。

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_selection_watch_policy tests.test_dev_feature_toggles
```

结果：6 tests passed。

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_houdini_main_thread_executor tests.test_harness_execution_boundary tests.test_import_smoke tests.test_manual_update_mode_directive tests.test_selection_watch_policy tests.test_dev_feature_toggles
```

结果：27 tests passed。

---

## 已知注意事项

- 当前 Selection Watch 默认关闭是为了压测新的主线程执行器；如果实测仍出现崩溃，可临时重新开启 `Selection Watch Auto Stop` 对比。
- executor timeout 后 blocked 是保守策略，不代表 Houdini 主线程一定已经恢复安全；不要在同一面板里强行继续排 Houdini 工具。
- Cursor UI 拆分保留兼容 facade，后续可以继续清理旧 facade import，但应作为单独变更处理。