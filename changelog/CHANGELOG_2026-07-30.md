# Houdini-Agent 更新记录（2026-07-30）

## 发布摘要

本次更新主要围绕 token / context compression 架构深化展开。

核心目标是在不改变调用方可见行为的前提下，把 token 估算、上下文轮次规划、旧工具结果压缩、轮次裁剪与消息重组从调用方路径中沉淀到 `token_optimizer.py` 的共享 helper 接口里，降低 `send_orchestrator_mixin.py` 与 `context_manager_mixin.py` 的重复逻辑。

---

## 一、Token 估算与统计拆分

### 改动

- 新增 `TokenEstimate`，按文本、图片、tool call、message overhead 与工具定义分别统计 token 估算来源。
- 新增 `TokenOptimizer.estimate_message_tokens(messages, tools=None)`，返回结构化 token breakdown。
- `TokenOptimizer.calculate_message_tokens(messages, tools=None)` 改为委托 `estimate_message_tokens(...).total`，保持旧调用方可继续取得整数总量。
- 工具 schema / function parameters 现在也进入上下文窗口估算，避免发送前 token 预算低估。
- `AIClient._estimate_messages_tokens(messages, tools=None)` 委托 `TokenOptimizer().calculate_message_tokens(...)`，统一估算口径。

---

## 二、上下文轮次规划与压缩 helper

### 改动

- 新增 `CompressionStats`，用于表达压缩前后 token、节省数量、节省百分比与移除轮次数，并保持 dict 兼容形态。
- 新增 `ContextRoundPlan`，把 system messages、历史 rounds、当前 incomplete round 拆分为明确结构。
- 新增 `plan_context_rounds(messages, protect_recent_rounds=2)`，统一上下文轮次解析逻辑。
- 新增 `flatten_context_rounds(rounds)`，用于将 round 结构还原为消息列表。
- 新增 `compress_old_round_tool_results(...)`，只压缩未受保护旧轮次中的 tool result，保留最近交互的完整上下文。
- 新增 `prune_context_rounds_to_token_target(...)`，把按 token 目标裁剪历史轮次的逻辑收敛到共享 helper。
- 新增 `assemble_context_messages(...)`，统一 system、summary、保留历史与当前轮次的组装顺序。
- 新增 `TokenOptimizer.compress_context_rounds(...)`，作为 round compression 的面向对象入口。

---

## 三、发送路径与上下文管理路径复用

### 改动

- `send_orchestrator_mixin.py` 改为使用共享 helper 完成发送前 round planning、旧工具结果压缩、轮次裁剪与最终消息组装。
- `context_manager_mixin.py` 的 `_manage_context()` 对应路径改为复用同一组 helper。
- 保留调用方现有 side effects，包括 UI status、chat notice、diagnostics append 与 `tr(...)` 文案所有权。
- 保留两个调用路径原本不同的裁剪语义：一个路径先检查 token target 再 pop，另一个路径先 pop 再检查；该差异通过 `check_before_pop` 显式表达。

---

## 四、测试覆盖

### 新增 / 更新测试

- 工具 schema token accounting。
- token breakdown total 与旧整数总量的一致性。
- `CompressionStats` 的 dict 兼容性。
- context round planning。
- round flattening。
- old-round tool compression 只修改未保护轮次。
- pruning 的 check-before-pop 与 pop-before-check 两种语义。
- context message assembly 的顺序。

---

## 五、测试与验证

本次已运行以下聚焦回归：

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_token_optimizer -v
```

结果：39 tests passed。

```powershell
C:/rez/rez_2.112.0/Scripts/python.exe -m py_compile houdini_agent/utils/token_optimizer.py houdini_agent/core/send_orchestrator_mixin.py houdini_agent/core/context_manager_mixin.py tests/test_token_optimizer.py
```

结果：passed。

VS Code diagnostics 对本次触及文件未报告错误。

---

## 已知注意事项

- 本轮刻意停在低风险 deepening 层：共享算法进入 `token_optimizer.py`，调用方副作用仍留在原 mixin 中。
- 下一轮如果要继续抽取完整 compression pass，建议先设计 result object，用于表达压缩后消息、原始/新 token 估算、节省 token、移除轮次、策略标签、UI notice/status 需求与 diagnostics payload。
- 当前工作树中 `houdini_agent/utils/ai_client.py` 等文件存在与本轮 token optimizer 深化混在一起的其他未提交改动；不要把整个 diff 都归因到本次 changelog 条目。
- 在 Python 3.8 环境中直接运行到 `AIClient` import 时，可能仍会被 vendored `lib/urllib3` 的 `tuple[...]` 类型语法阻断；这是既有环境/依赖兼容问题，不代表本轮 context compression 改动失败。