# ai_tab.py 拆分重构计划

日期：2026-06-24

## 背景

`houdini_agent/ui/ai_tab.py` 目前同时承担主窗口装配、系统提示词构建、工具执行、诊断导出、slash command、缓存恢复、节点操作等职责。文件体量已经过大，后续修改容易互相碰撞，也让测试边界不清晰。

这次重构目标不是重写 `AITab`，而是按现有 mixin 风格把几个最稳定、最容易独立验证的区域移出去。每一步都保持行为不变，先搬家，再做小幅整理。

## 目标

1. 降低 `ai_tab.py` 的行数和职责密度。
2. 保持 `AITab` 的外部行为不变。
3. 复用现有 mixin 架构，不引入新框架或依赖。
4. 每个阶段都能单独回滚、单独验证。
5. 优先拆出低风险、边界清晰的逻辑。

## 非目标

1. 不重写 UI 架构。
2. 不改变 agent loop、tool policy、Plan、Memory 的用户可见行为。
3. 不顺手清理无关历史代码。
4. 不引入依赖注入框架、事件总线或大型抽象。
5. 不在第一轮拆缓存恢复、节点 undo 等高耦合区域。

## 当前主要职责分布

| 区域 | 当前位置 | 问题 |
| --- | --- | --- |
| Prompt 构建 | `ai_tab.py` 顶部全局常量、`_load_prompt_template()`、`_build_system_prompt()` | 和 UI 类混在一起，但逻辑主要是纯文本拼装 |
| Tool 执行 | `_execute_tool_with_policy()`、`_execute_tool_with_todo()`、`_execute_tool_in_main_thread()`、`_on_execute_tool_main_thread()` | 逻辑长，包含 policy、todo、主线程桥接、结果格式化 |
| Diagnostics | `_append_policy_timeline()`、`_export_diagnostics_json()` 等 | 独立性较好，适合 mixin |
| Slash commands | `_execute_slash_command()`、`_slash_*()` | 命令分发集中，适合拆成 mixin 或命令表 |
| Cache/session | `_save_cache()`、`_restore_all_sessions()` 等 | 和 UI 状态耦合较深，建议后置 |
| Node/context | `_get_current_network_context()`、节点 undo、路径解析等 | 和 Houdini runtime 耦合较深，建议后置 |

## 建议文件结构

```text
houdini_agent/
  core/
    prompt_builder.py
    tool_execution_mixin.py
    diagnostics_mixin.py
    slash_commands.py
  ui/
    ai_tab.py
```

说明：

- `prompt_builder.py` 放纯函数和轻量缓存，不依赖 Qt。
- `diagnostics_mixin.py`、`slash_commands.py`、`tool_execution_mixin.py` 放现有 `AITab` 方法，继续通过 `self` 访问 UI 状态。
- 暂时不拆更深层服务对象，避免把一次搬家变成架构重写。

## 阶段 1：拆 Prompt Builder

### 新文件

`houdini_agent/core/prompt_builder.py`

### 移动内容

- `_PROMPTS_DIR`
- `_PROMPT_TEMPLATE_CACHE`
- `_CORE_RULES_FALLBACK`
- `_load_prompt_template()`
- `_build_system_prompt()`

### 目标接口

```python
def build_system_prompt(context_text, enable_thinking=False, labs_enabled=False, core_only=False):
    ...
```

### `ai_tab.py` 改动

- 删除顶部 prompt 相关全局和函数。
- 改为导入：

```python
from houdini_agent.core.prompt_builder import build_system_prompt
```

- 原调用点从 `_build_system_prompt(...)` 改为 `build_system_prompt(...)`。

### 验证

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/core/prompt_builder.py houdini_agent/ui/ai_tab.py
```

可选增加纯函数测试：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_prompt_builder -v
```

### 风险

低。该区域主要是字符串拼装和模板读取，最容易独立测试。

## 阶段 2：拆 DiagnosticsMixin

### 新文件

`houdini_agent/core/diagnostics_mixin.py`

### 移动内容

- `_append_policy_timeline()`
- `_set_thinking_visible()` 如只服务诊断 UI，可一起评估
- `_export_diagnostics_json()`
- 相关 diagnostics/policy timeline helper 方法

### `ai_tab.py` 改动

- 导入 `DiagnosticsMixin`。
- `class AITab(...)` 的继承列表加入 `DiagnosticsMixin`。
- 删除原文件内对应方法。

### 验证

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/core/diagnostics_mixin.py houdini_agent/ui/ai_tab.py
```

手工验证：

- Diagnostics 导出菜单仍能打开。
- JSON 导出字段不变。
- Policy timeline 仍能显示最近 tool approval/deny 记录。

### 风险

中低。诊断方法依赖 UI 字段，但调用面较窄。

## 阶段 3：拆 SlashCommandsMixin

### 新文件

`houdini_agent/core/slash_commands.py`

### 移动内容

- `_execute_slash_command()`
- `_slash_*()` 系列方法
- 与 slash command 分发直接相关的小 helper

### 建议整理

先只搬方法，不改命令语义。等搬完稳定后，再考虑把长 `if/elif` 分发压成命令表。

第一轮保持这种形态即可：

```python
class SlashCommandsMixin:
    def _execute_slash_command(self, command):
        ...
```

### 验证

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/core/slash_commands.py houdini_agent/ui/ai_tab.py
```

手工验证：

- 输入框 slash command 菜单仍能触发。
- `/memory`、`/plan`、`/diagnostics`、`/help` 等常用命令行为不变。

### 风险

中。slash command 通常横跨 memory、plan、diagnostics、UI 输出，需注意 mixin 继承顺序和方法名。

## 阶段 4：拆 ToolExecutionMixin

### 新文件

`houdini_agent/core/tool_execution_mixin.py`

### 移动内容

- `_execute_tool_with_policy()`
- `_execute_tool_with_todo()`
- `_execute_tool_in_main_thread()`
- `_on_execute_tool_main_thread()`
- 工具结果摘要/格式化相关 helper

### 拆分策略

这一段风险最高，建议分两步：

1. 只移动方法，不改逻辑。
2. 通过 `py_compile` 和现有 tool selection/policy 测试后，再考虑局部简化。

### 继承顺序建议

`ToolExecutionMixin` 应放在 `AgentRunnerMixin` 之前或附近，因为 agent runner 会设置/调用 tool executor。最终顺序以实际方法解析需求为准。

示例：

```python
class AITab(
    QWidget,
    HeaderMixin,
    InputAreaMixin,
    ChatViewMixin,
    ImageMixin,
    StreamingParserMixin,
    MemoryMixin,
    PlanMixin,
    ToolExecutionMixin,
    AgentRunnerMixin,
    SessionManagerMixin,
    DiagnosticsMixin,
    SlashCommandsMixin,
):
    ...
```

### 验证

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/core/tool_execution_mixin.py houdini_agent/ui/ai_tab.py
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_agent_tool_selection tests.test_harness_policy -v
```

手工验证：

- 普通 tool call 可执行。
- 被 policy 拦截的 tool call 仍拒绝。
- todo 包装仍能更新进度。
- 主线程执行路径仍能返回结果。

### 风险

中高。该区域涉及线程、policy、UI 输出和 agent runner 回调，必须小步提交。

## 阶段 5：后续可选拆分

这些不要放进第一轮，等前四阶段稳定后再做。

### Cache/session

候选文件：`houdini_agent/core/cache_session_mixin.py`

候选内容：

- `_on_cache_menu()`
- `_save_cache()`
- `_restore_all_sessions()`
- 会话摘要/缓存菜单相关 helper

风险：中高，依赖 UI 状态和历史数据格式。

### Node/context

候选文件：`houdini_agent/core/node_context_mixin.py`

候选内容：

- `_get_current_network_context()`
- `_get_enhanced_node_context()`
- `_undo_node_operation()`
- 节点路径解析和 session node map 更新逻辑

风险：高，依赖 Houdini runtime，局部测试困难。

## 推荐执行顺序

1. `prompt_builder.py`
2. `diagnostics_mixin.py`
3. `slash_commands.py`
4. `tool_execution_mixin.py`
5. 观察一轮后再考虑 cache/session 和 node/context

这个顺序从低风险到高风险，且每一步都能减少 `ai_tab.py` 的体量。

## 每阶段完成标准

每个阶段都需要满足：

1. `ai_tab.py` 不再保留同名重复实现。
2. 原有调用点全部更新。
3. `py_compile` 通过。
4. 能跑的相关 `unittest` 通过。
5. 没有引入新依赖。
6. 没有改变用户可见行为。

## 回滚策略

每个阶段只移动一组职责。如果某阶段出问题：

1. 保留前面已完成阶段。
2. 只回滚当前阶段新增文件和 `ai_tab.py` 对应继承/import 变更。
3. 优先不要跨阶段混改，避免回滚范围变大。

## 已知注意点

1. 本地环境缺少 PySide2/PySide6 和 Houdini `hou`，不要依赖完整 UI import 做唯一验证。
2. 使用 `unittest`，当前环境没有 `pytest`。
3. PowerShell 不支持 Bash 风格 `python - <<'PY'` here-doc，临时脚本请用 `python -c` 或 PowerShell here-string。
4. 工作区已有一些非本轮改动，重构时不要顺手覆盖无关文件。
5. `agent-safety` 规则要求 tool policy 相关逻辑保持 fail closed，不要在搬 `ToolExecutionMixin` 时放宽拒绝路径。

## 建议下一步

先执行阶段 1：拆 `prompt_builder.py`。它收益明确、风险最低，而且能给后续 mixin 搬迁建立一个小而稳定的模式。