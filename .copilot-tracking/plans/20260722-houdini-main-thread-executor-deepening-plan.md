# Houdini 主线程执行模块深化计划

> 日期：2026-07-22
> 状态：第一阶段已实施并通过聚焦回归；建议进入 Houdini 实测观察，再做清理型深化。

---

## 1. 背景

Houdini 工具执行曾散在 `AITab` / `ToolExecutionMixin` 的共享 `self` 状态里：Qt `BlockingQueuedConnection`、结果 queue、timeout busy flag、cook guard、undo group、selection baseline refresh 都由同一个 UI object 隐式协调。

这会放大崩溃风险，尤其是：

- 后台 agent thread 仍持有旧 `AITab` bound method。
- 切用户 / 关闭面板时旧 `AITab` 进入 `deleteLater()`，但后台线程可能继续投递 Houdini 工具。
- 主线程工具 timeout 后，Houdini slot 可能仍在 cook / execute / undo 中迟到返回。
- 旧 result 可能残留在共享 queue 中，污染后续工具调用。

本计划目标是把 Houdini 主线程执行深化成一个明确 module，让 lifecycle、queueing、timeout、operation identity 和主线程 wrapper 规则集中在一个地方。

---

## 2. 已确认设计决策

### 2.1 第一版 module 职责

`HoudiniMainThreadExecutor` 首先负责 **Houdini 主线程操作生命周期**，不是重写所有工具执行逻辑。

第一阶段 scope：

- cleanup 后拒绝执行。
- timeout 后进入 `blocked`。
- `blocked` 后 fail closed，不加手动解除按钮。
- 同一时间只允许一个 active operation。
- 使用 operation id 防止迟到 result 串线。
- 先不改变 `mcp.execute_tool` 的业务语义。

### 2.2 timeout 策略

timeout 后进入 `blocked`，不能由 `_on_agent_done` / `_on_agent_error` / `_on_agent_stopped` 自动清掉。

原因：后台等待 timeout 不代表 Houdini 主线程真实空闲。主线程 slot 可能仍在 cook 或执行 `hou` 操作。自动放行会引入下一次工具排队与旧操作重叠的崩溃风险。

### 2.3 blocked 策略

第一版 `blocked` 后 fail closed，不提供“确认恢复”按钮。

后续如果要做手动解除，需要更明确的 Houdini 空闲判断或用户操作流程；当前先保守拒绝，降低崩溃风险。

---

## 3. 已完成实现

### 3.1 新增 module

文件：`houdini_agent/core/houdini_main_thread_executor.py`

新增：`HoudiniMainThreadExecutor`

当前 interface：

```python
execute(tool_name, kwargs) -> dict
execute_batch(batch) -> list[dict]
run_in_main_thread(...) -> dict
attach_result(operation_id, result) -> dict
shutdown() -> None
is_blocked() -> bool
is_shutdown() -> bool
```

### 3.2 生命周期与 timeout fail closed

已完成：

- `AITab.cleanup()` 调用 executor `shutdown()`。
- shutdown 后新的 Houdini 主线程工具执行直接拒绝。
- timeout 后 executor 进入 `blocked`。
- `blocked` 后新的 Houdini 主线程工具执行直接拒绝。

### 3.3 主线程 wrapper 深化

`HoudiniMainThreadExecutor.run_in_main_thread()` 已接管：

- update-mode cook guard。
- read-before-cook hook。
- undo group begin/end。
- snapshot/diff `_node_changes`。
- selection baseline refresh。
- exception formatting。

`ToolExecutionMixin._on_execute_tool_main_thread` 现在主要是 Qt adapter：

- 做主线程断言。
- pop 私有 `_ha_operation_id`。
- 调 executor wrapper。
- 把 operation envelope 放回 result queue。

### 3.4 operation envelope 防串线

已完成：

- `execute()` / `execute_batch()` 发送请求时附加私有 `_ha_operation_id`。
- slot 执行前移除 `_ha_operation_id`，避免传给 `mcp.execute_tool`。
- slot 返回后用 `attach_result(operation_id, result)` 包成 envelope。
- executor 等待结果时只接受匹配当前 operation id 的 envelope。
- timeout 后迟到的旧 result 会被忽略，不会污染后续执行。

---

## 4. 已补测试

文件：`tests/test_houdini_main_thread_executor.py`

覆盖：

- timeout 后进入 blocked，后续执行被拒绝。
- shutdown 后拒绝新执行。
- `cleanup()` 后，再调用 `_execute_tool_in_main_thread()` 不 emit Qt signal，直接拒绝。
- 主线程 wrapper 会切 Manual、开关 undo group、写 `_node_changes`、刷新 selection baseline。
- 单工具 operation envelope 会忽略 stale result。
- batch operation envelope 会附加 `_ha_operation_id` 并返回匹配结果。

聚焦回归命令：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_houdini_main_thread_executor tests.test_harness_execution_boundary tests.test_import_smoke tests.test_manual_update_mode_directive
```

最近结果：

```text
Ran 18 tests in 0.318s
OK
```

---

## 5. 当前改动涉及文件

- `houdini_agent/core/houdini_main_thread_executor.py`
- `houdini_agent/core/tool_execution_mixin.py`
- `houdini_agent/core/runtime_state_mixin.py`
- `houdini_agent/ui/ai_tab.py`
- `tests/test_houdini_main_thread_executor.py`

注意：`houdini_agent/ui/ai_tab.py` 中存在一段 import 拆分 diff，疑似本轮之前已有工作区改动；后续清理时不要误回滚用户已有改动。

---

## 6. 建议的实测观察项

先在 Houdini 中观察一轮，再继续重构：

1. 跑一个容易 cook 很久的工具，看 timeout 后是否稳定进入 fail closed。
2. timeout 后继续发 Agent 命令，确认不会继续堆主线程 Houdini 工具。
3. 切用户 / 关闭面板 / 重开面板，观察是否还出现崩溃。
4. 创建 / 改节点后确认 undo group 正常。
5. 修改节点后确认 `_node_changes`、selection baseline、manual update mode 行为正常。

崩溃复现 / 压测时可临时禁用选择监视自动停止策略：

```powershell
$env:HOUDINI_AGENT_SELECTION_WATCH = "false"
```

默认值仍是启用；禁用只建议用于专门测试 Houdini 崩溃路径。

当 `HOUDINI_AGENT_DEV_RELOAD=1` 时，溢出菜单中会显示 `Dev Feature Toggles` 子菜单，可直接切换 dev-only runtime feature toggles（当前包括 `Selection Watch Auto Stop` 与 `Harness V2`）。

---

## 7. 后续深化路线

### 7.1 清理旧 fallback queue 逻辑

候选：`ToolExecutionMixin._execute_tool_in_main_thread()` 与 `_execute_tools_batch_in_main_thread()` 里没有 executor 时的旧 queue fallback。

建议：实测稳定后删除或收缩 fallback，让主线程执行状态只由 `HoudiniMainThreadExecutor` 决定。

### 7.2 收敛 `_main_thread_busy` 双状态

当前仍保留 `_main_thread_busy` 作为兼容状态。长期应避免它和 executor `blocked` 形成双状态源。

建议：让 caller 只问 executor `is_blocked()` / `is_shutdown()`，逐步删除 `_main_thread_busy` 对主线程执行许可的决定权。

### 7.3 更明确的 blocked 恢复策略

当前 blocked 后 fail closed，需要重启面板或 cleanup。

后续如果要加恢复操作，应先设计：

- 恢复操作是否需要用户显式确认。
- 是否能检测 Houdini 主线程已经空闲。
- 是否需要清空 queue 和 active operation。
- 是否应该写 diagnostics 事件。

### 7.4 诊断与可观测性

可考虑给 executor 增加轻量 diagnostics：

- operation_id
- tool_name
- start_ts / timeout_ts / finish_ts
- state transition: idle -> executing -> blocked / idle / shutdown
- stale result ignored count

注意：不要记录敏感参数全文；记录 tool name 和 args keys 足够。

### 7.5 与 policy/harness deepening 汇合

原 Candidate 2 的 policy-governed execution 仍然值得做，但优先级低于 Houdini 主线程崩溃风险。

后续可以让 tool policy module 调用 `HoudiniMainThreadExecutor` 作为 Houdini adapter，而不是直接触碰 `AITab`。

---

## 8. 接手提醒

相关 repo memory：`/memories/repo/houdini_main_thread_executor_deepening.md`

继续前先跑聚焦回归：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_houdini_main_thread_executor tests.test_harness_execution_boundary tests.test_import_smoke tests.test_manual_update_mode_directive
```

如果修改了选择监视策略，也跑：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_selection_watch_policy
```

如果修改了 dev feature toggle 菜单或环境变量解析，也跑：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_dev_feature_toggles tests.test_import_smoke
```

如果要继续改 production code，优先补一个能抓住具体风险的测试，再做小步改动。