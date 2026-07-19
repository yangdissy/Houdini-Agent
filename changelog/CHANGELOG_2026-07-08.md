# Houdini-Agent 更新记录（2026-07-08）

## 发布摘要

临时禁用 AI Client 的循环检测**硬熔断**机制。起因是 `get_parameter_schema` 工具在合理探索不同 `pattern` 参数时被硬熔断误杀（连续 8 次同工具调用即强制终止 agent loop），导致正常的参数 schema 查询流程被中断。

改动仅涉及一个文件：`houdini_agent/utils/ai_client.py`。无 API / 磁盘格式变化。

---

## 问题现象

Agent 运行日志出现：

```
[MCP Client] 执行工具: get_parameter_schema, 参数: ['node_path', 'pattern', 'limit', 'include_hidden']
[MCP Client] 执行工具: get_parameter_schema, 参数: ['node_path', 'pattern', 'limit', 'include_hidden']
...
[AI Client] ⚠️ 循环检测：get_parameter_schema 已连续 6 次调用（参数在变），注入换策略提示
[AI Client] ⚠️ 循环检测：get_parameter_schema 已连续 7 次调用（参数在变），注入换策略提示
[AI Client] ⛔ 循环检测硬熔断：get_parameter_schema（连续相同 1 次 / 窗口内 1 次 / 同工具 8 次），强制终止
```

模型在用不同 `pattern` 反复查询同一节点的参数 schema（属于合理的多参数探索），但 `_LOOP_SAME_TOOL_HARD_ABORT = 8` 阈值只看工具名不看参数变化是否合理，到第 8 次直接强制终止整个 agent loop。

## 根因

循环检测有三条硬熔断触发条件（任一达阈值即强制终止）：

| 条件 | 常量 | 阈值 | 捕获场景 |
|------|------|------|----------|
| 连续相同调用（含参数） | `_LOOP_HARD_ABORT_THRESHOLD` | 5 | A→A→A→A→A 死循环 |
| 窗口内同签名出现次数 | `_LOOP_WINDOW_HIT_THRESHOLD` | 4 | A→B→A→B 交替死循环 |
| 同工具名连续调用（不看参数） | `_LOOP_SAME_TOOL_HARD_ABORT` | 8 | 换 pattern 反复调同一工具 |

前两条针对真正的死循环（签名完全相同），误杀风险低。第三条只看工具名，会把"同工具换不同参数合理探索"也判为循环——本次误杀即由此触发。

## 改动

**文件**：`houdini_agent/utils/ai_client.py`

**两处对称修改**（非 JSON 模式 ~4882 行、JSON 模式 ~5689 行）：

注释掉硬熔断触发块，不再设置 `should_break_tool_limit = True` / `should_break_limit = True` + `break`。

### 保留的内容

- 所有循环检测常量原样保留（`_LOOP_HARD_ABORT_THRESHOLD`、`_LOOP_WINDOW_HIT_THRESHOLD`、`_LOOP_SAME_TOOL_HARD_ABORT` 等），方便后续恢复
- 窗口维护代码继续运行（`recent_call_signatures` 滑动窗口、`consecutive_same_calls` / `consecutive_same_tool` 计数）
- **软提示**照常工作（`⚠️ 循环检测...注入换策略提示`），仍会给模型换策略的引导
- `_loop_abort_reason` 变量仍初始化为 `None`，下游 `if _loop_abort_reason is not None` 分支自然走"达到次数限制"的默认消息，逻辑无副作用

### 效果

- `get_parameter_schema` 这类同工具多参数的合理探索不再被强制终止，只会收到软提示
- 仍受 `max_tool_calls` 总量上限保护，不会真正无限循环

## 待办 / 后续

- [ ] 这是**临时措施**。后续应改进第三条硬熔断条件的判定逻辑，而非简单禁用——例如：
  - 对"同工具换参数"场景提高阈值（如 15-20 次）而非 8 次
  - 或区分工具类型：只读查询类工具（`get_parameter_schema`、`search_node_types`、`search_local_doc`）放宽阈值，写操作类工具保持严格
  - 或在软提示多次无效后再升级为硬熔断（分级干预）
- [ ] 恢复方式：取消 `houdini_agent/utils/ai_client.py` 中两处注释块即可（搜索 `硬熔断已临时禁用`）

## 后续调整（同日）

禁用硬熔断后，发现软提示对批量写操作（如 `set_node_parameter` 连续设置多个节点参数）仍有误报——从第 6 次起每次都注入"返回结果被截断""用 offset 翻页"的提示，但写操作根本没有分页概念，文案会误导模型。

### 改动

1. **提高同工具软提示阈值**：`_LOOP_SAME_TOOL_SOFT_HINT` 从 6 → 15，`_LOOP_SAME_TOOL_HARD_ABORT` 从 8 → 25（后者已禁用，保留常量供恢复）。批量操作常见 10+ 次连续调用，原阈值过低。

2. **区分查询类/写操作类工具的软提示文案**（两处对称）：
   - 查询类工具（`get_parameter_schema`、`search_node_types`、`search_local_doc`、`list_node_parameters`、`get_node_info`、`search_parameters`）：保留原"结果被截断/用 offset 翻页"引导
   - 写操作类工具（`set_node_parameter` 等）：改为"如果是批量操作请继续但注意效率；若反复尝试同一操作得不到预期结果，请检查参数值/节点路径，或改用 execute_python 一次性完成批量操作"

### 效果

- `set_node_parameter` 连续设置 10 个节点参数不再触发软提示（阈值 15）
- 即使触发，文案也不再误导模型去"翻页"，而是引导检查参数或改用批量执行

## 验证

- [x] `get_errors` 检查无编译错误
- [ ] 实际运行 Agent 验证 `get_parameter_schema` / `set_node_parameter` 多参数操作不再被误报（待用户确认）
