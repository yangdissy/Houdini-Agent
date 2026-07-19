# Houdini-Agent 更新记录（2026-07-06 ~ 2026-07-11）

## 发布摘要

本周改动围绕三条主线展开：

1. **Skill 系统迁移** — 将 5 个只读查询工具（`get_node_card` / `get_node_inputs` / `get_node_positions` / `list_network_boxes` / `find_nodes_by_param`）从核心 MCP 工具迁移为 Skill，并新增 5 个 Skill（`explain_node_error` / `search_houdini_help` / `setup_pyro_sim` / `setup_dynamics_sim` / `setup_render`）。核心工具表瘦身，模型上下文更聚焦于"建/连/改"写操作。
2. **安全与稳定性加固** — `cook_node force=true` 升级为需用户确认的高风险操作；Qt 延迟回调引入 shiboken 存活校验，修复多起主线程竞态崩溃；IME 中文输入在 Houdini + PySide2 下恢复正常。
3. **新增 `set_parameter_expression` 工具** — 支持设置参数表达式/通道引用（`ch()` / `$F` / `fit01(...)`），补齐"程序化连参"能力。

涉及 25 个文件，+807 / -262 行。无 API / 磁盘格式变化。

---

## 一、Skill 系统迁移

### 背景

`get_node_card`、`get_node_inputs` 等只读查询工具占用核心工具表名额，但调用频率低、且与"建/连/改"写操作在同一个工具列表里会稀释模型的注意力。本周将它们迁移为 Skill，通过 `run_skill(...)` 调用。

### 迁移为 Skill 的工具

| 原核心工具 | 新 Skill 文件 | 说明 |
|------------|---------------|------|
| `get_node_card` | `houdini_agent/skills/get_node_card.py` | 建节点前一站式查节点类型说明 |
| `get_node_inputs` | `houdini_agent/skills/get_node_inputs.py` | 查节点输入端口含义（210 常用节点 JSON 缓存） |
| `get_node_positions` | `houdini_agent/skills/get_node_positions.py` | 读取节点位置信息 |
| `list_network_boxes` | `houdini_agent/skills/list_network_boxes.py` | 列出 NetworkBox 及其包含节点 |
| `find_nodes_by_param` | `houdini_agent/skills/find_nodes_by_param.py` | 按参数搜索节点（类 grep） |

### 新增 Skill

| Skill 文件 | 分类 | 说明 |
|------------|------|------|
| `explain_node_error.py` | scene | 单节点错误诊断，定位可疑参数（如文件路径不存在） |
| `search_houdini_help.py` | docs | Houdini 内置离线帮助全文搜索 / 取页 |
| `setup_pyro_sim.py` | workflow | Pyro 模拟一键蓝图（只产出 recipe，不建节点） |
| `setup_dynamics_sim.py` | workflow | RBD/FLIP/Vellum 动力学模拟蓝图 |
| `setup_render.py` | workflow | 渲染 ROP 配置蓝图 |

> **安全边界**：三个 `setup_*` 蓝图 Skill 不导入 `hou`、不创建节点，只返回结构化 recipe。AI 拿到 recipe 后通过已有的 harness 管控工具（`create_nodes_batch` + `connect_nodes` + `batch_set_parameters`）执行，所有写操作仍在审计 / undo / cook 保护路径内。

### 配套改动

- **`houdini_agent/utils/ai_client.py`**：从核心工具列表移除上述 5 个工具的定义；工具描述中的 `get_node_card` / `get_node_inputs` 引用统一改为 `run_skill('get_node_card', ...)` / `run_skill('get_node_inputs', ...)`。
- **`houdini_agent/utils/tool_registry.py`**：从各意图组（query / create / connect / layout 等）移除已迁移工具，`set_parameter_expression` 加入 parameter 意图组。
- **`houdini_agent/core/streaming_tool_executor.py`**：从流式执行白名单 / 只读白名单移除已迁移工具。
- **`houdini_agent/ui/ai_tab.py`**：`_FAKE_TOOL_PATTERNS` 正则同步移除已迁移工具名。
- **`houdini_agent/prompts/system_prompt_rules_core.txt` / `extra.txt`**：引用改为 `run_skill(...)`。
- **`Doc/tool_selection_guide.md`**：工具选择指南全面更新，`get_node_card` / `get_node_inputs` / `get_node_positions` / `list_network_boxes` 均改为 `run_skill(...)` 形式。
- **`houdini_agent/utils/mcp/client.py`**：`list_skills` 改为按 `category` 分组输出，支持 `category` 参数只看某一类，节省 token。

---

## 二、新增 `set_parameter_expression` 工具

### 动机

原 `set_node_parameter` 只能写入静态值，无法建立参数间的表达式链接（如 `ch("../box1/sizex")`、`$F`、`fit01(@P.x, 0, 1)`）。程序化连参是 Houdini 核心工作流，此前只能靠 `execute_python` 绕路。

### 改动

| 文件 | 改动 |
|------|------|
| `houdini_agent/utils/ai_client.py` | 新增工具定义，支持 `hscript` / `python` 两种表达式语言 |
| `houdini_agent/utils/mcp/client.py` | 新增 `set_parameter_expression()` 方法 + `_tool_set_parameter_expression()` 分发器，设置前自动快照旧状态支持撤销 |
| `houdini_agent/utils/mcp/server.py` | 注册 MCP tool |
| `houdini_agent/core/harness_engine.py` | 注册为场景变更工具，要求 `node_path` + `param_name` |
| `houdini_agent/core/harness_policy_config.py` | 加入 `SCENE_MUTATION_TOOLS` |
| `houdini_agent/utils/tool_registry.py` | 加入 parameter 意图组 |

### 行为细节

- 仅对标量参数有效；遇到 tuple 参数（如 `t`）会报错并提示用分量名（`tx` / `ty` / `tz`）分别调用。
- 设置前快照旧状态（可能是表达式也可能是静态值），供 UI 撤销使用，不发给 AI。

---

## 三、`cook_node` 安全加固

### 问题

`cook_node` 在 Houdini 主线程强制计算，重节点（模拟 / VDB / 大 scatter / 循环依赖）会阻塞 UI 甚至卡死。模型常拿它当"验证"手段，但验证应改用只读工具。

### 改动

- **`houdini_agent/core/harness_engine.py`**：`cook_node force=true` 在 `agent` / `plan` 模式下强制返回 `ask` 决策，要求用户确认，防止模型绕过工具描述直接硬 cook。
- **`houdini_agent/utils/ai_client.py`**：`cook_node` 工具描述重写为高风险警告，明确"不要用它验证刚创建/改参数的节点"，引导改用 `inspect_node` / `check_errors` / `verify_network` / `get_geometry_summary`。
- **`Doc/tool_selection_guide.md`**：`cook_node` 列入高风险工具清单，验证列改为只读工具。
- **`tests/test_harness_policy.py`**：新增 `cook_node force_requires_confirmation` 测试，移除已迁移的 `get_node_inputs` 测试。

---

## 四、循环检测阈值调整

> 详细记录见 [CHANGELOG_2026-07-08.md](./CHANGELOG_2026-07-08.md)，此处汇总。

- 硬熔断（`_LOOP_SAME_TOOL_HARD_ABORT`）已临时禁用，常量保留供恢复。
- `_LOOP_SAME_TOOL_SOFT_HINT`：6 → 15（批量操作常见 10+ 次连续调用）。
- `_LOOP_SAME_TOOL_HARD_ABORT`：8 → 25（已禁用，保留常量）。
- 软提示文案区分查询类 / 写操作类工具：查询类保留"结果截断/offset 翻页"引导；写操作类改为"批量操作请继续，若反复失败请检查参数或改用 execute_python"。

---

## 五、消息清洗与分页提示

### 5.1 未配对 tool_calls 补发占位消息

**文件**：`houdini_agent/utils/ai_client.py`（`_sanitize_tool_messages`）

**问题**：循环熔断 / 错误中断时，assistant 已发出 N 个 tool_calls，但只执行了部分，剩余的 `tool_call_id` 缺少响应 → API 400 `"An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'"`。

**改动**：清洗逻辑从一遍改为四遍：
1. 收集所有有效 `tool_call_id`
2. 收集已存在的 tool 响应 `tool_call_id`
3. 构建清洗后消息列表（跳过孤儿 tool 消息）
4. 为未配对的 assistant tool_calls 补发占位 tool 消息（`[工具执行被中断，无结果返回]`）

### 5.2 自带分页工具的软上限截断

**文件**：`houdini_agent/utils/ai_client.py`（`_soft_cap_with_offset_hint`）

**问题**：`get_parameter_schema` 等自带分页的工具，184 参数节点序列化后 2600+ 行撑爆上下文。

**改动**：
- 新增 `_SELF_PAGED_SOFT_CAP = 600`，超过则截断并追加 offset 翻页提示。
- 尝试从 JSON 结果中提取 `offset` / `limit` / `next_offset` / `node_path`，生成精确翻页指令。
- 提示明确区分 `pattern`（过滤，按名匹配）vs `offset`（翻页），纠正模型"换 pattern 重复调用"的误用。

---

## 六、Qt 稳定性加固

### 6.1 shiboken 存活校验

**文件**：`houdini_agent/qt_compat.py`

新增：
- `is_qobject_alive(obj)` — 通过 shiboken `isValid` 判断 QObject 底层 C++ 实例是否已删除。
- `safe_single_shot(msec, receiver, method_name)` — `QTimer.singleShot` 的安全封装，回调触发前校验 receiver 存活，避免对半销毁 widget 计算布局 / sizeHint 触发 Houdini Qt messageHandler 崩溃。

**`houdini_agent/ui/cursor_widgets.py`**：所有 `QTimer.singleShot(0, self._update_height / _scroll_to_bottom / _maybe_collapse / _adjust_height)` 替换为 `safe_single_shot`。

### 6.2 窗口删除前先隐藏

**文件**：`houdini_agent/core/main_window.py`、`houdini_agent/main.py`

`AITab` 重建 / 主窗口退出时，先 `hide()` 再 `setParent(None)` + `deleteLater()`，避免已进入删除流程的旧窗口及其子按钮继续参与布局 / 绘制事件。

### 6.3 空 pixmap 防护

**文件**：`houdini_agent/ui/chat_view.py`、`houdini_agent/ui/image_mixin.py`

`QPixmap.loadFromData()` 返回 `False` 或 pixmap 为 null 时直接跳过，避免空 pixmap 进入布局在 sizeHint 阶段触发 Qt 告警甚至崩溃。

---

## 七、IME 中文输入修复

**文件**：`houdini_agent/ui/cursor_widgets.py`、`houdini_agent/ui/header.py`

### 问题

PySide2 嵌入 Houdini 时，原生 `QLineEdit` / `QPlainTextEdit` 的 `inputMethodQuery` 可能返回错误值导致 IME 无法激活；且 `RulesEditorDialog` 用模态 `exec_()` 会启动独立事件循环，输入法上下文无法正确附加，中文无法输入。

### 改动

- 新增 `IMELineEdit` / `IMEPlainTextEdit`：显式启用 `WA_InputMethodEnabled`，覆写 `inputMethodQuery` 返回正确的光标矩形 / 字体 / 周围文本 / 当前选区，`focusInEvent` 中再次确保属性开启。
- `RulesEditorDialog` 的标题 / 内容编辑框改用 IME 控件。
- `header.py`：`RulesEditorDialog` 从模态 `exec_()` 改为非模态 `show()` + `NonModal`，持有引用避免被 GC。

---

## 八、自动读取上下文去重

**文件**：`houdini_agent/ui/action_commands_mixin.py`、`houdini_agent/ui/ai_tab.py`、`houdini_agent/core/session_manager.py`

新增 `_last_auto_read_context` 字段，记录上次自动读取的 `(mode, label, text)`。相同上下文不重复注入对话历史，避免 token 浪费。新建 / 加载 / 切换会话时重置该字段。

---

## 九、布局锚点

**文件**：`houdini_agent/utils/mcp/client.py`、`houdini_agent/utils/mcp/hou_core.py`

`create_nodes_batch` 完成后的 tidy 布局，尝试获取当前 NetworkEditor 的 `visibleBounds().center()` 作为锚点，新节点布局后落在用户可视区域内，而非默认原点。`_compute_tidy_layout` / `_layout_columns` 新增 `anchor_position` 参数，优先于 `original_positions` 中心。

**`tests/test_tidy_layout.py`**：新增 `test_anchor_position_overrides_original_center`。

---

## 十、其他

- **`houdini_agent/utils/mcp/client.py`**：`search_nodes()` 新增 `category` 参数，支持按节点类别（sop/obj/dop/vop 等）过滤。
- **`rules/houdini_progressive_template.md`**：重写五阶段协议第 1 / 3 节，强调"批量优先"（默认 `create_nodes_batch`）和"验证单元是阶段而非单个节点"，单批上限从 5 调整为 8。
- **`houdini_agent/core/streaming_tool_executor.py`**：流式执行白名单同步移除已迁移工具。
- **`tests/test_tool_registry.py`**：意图分组测试更新，新增 `_AGENT_ALWAYS_TOOLS` 始终包含测试。

---

## 涉及文件清单

```
 Doc/tool_selection_guide.md                        |  20 +-
 houdini_agent/core/harness_engine.py               |  12 +-
 houdini_agent/core/harness_policy_config.py        |   1 +
 houdini_agent/core/main_window.py                  |   6 +
 houdini_agent/core/session_manager.py              |   2 +
 houdini_agent/core/streaming_tool_executor.py      |   6 -
 houdini_agent/main.py                              |   6 +
 houdini_agent/prompts/system_prompt_rules_core.txt |   2 +-
 houdini_agent/prompts/system_prompt_rules_extra.txt|   4 +-
 houdini_agent/qt_compat.py                         |  51 ++
 houdini_agent/ui/action_commands_mixin.py          |   5 +
 houdini_agent/ui/ai_tab.py                         |  10 +-
 houdini_agent/ui/chat_view.py                      |   4 +-
 houdini_agent/ui/cursor_widgets.py                 |  99 ++++-
 houdini_agent/ui/header.py                         |   9 +-
 houdini_agent/ui/image_mixin.py                    |  11 +-
 houdini_agent/utils/ai_client.py                   | 445 ++++++++++++++-------
 houdini_agent/utils/mcp/client.py                  | 175 +++++++-
 houdini_agent/utils/mcp/hou_core.py                |  26 +-
 houdini_agent/utils/mcp/server.py                  |  32 ++
 houdini_agent/utils/tool_registry.py               |  48 +-
 rules/houdini_progressive_template.md              |  26 +-
 tests/test_harness_policy.py                       |  29 +-
 tests/test_tidy_layout.py                          |  13 +
 tests/test_tool_registry.py                        |  27 +-
 25 files changed, 807 insertions(+), 262 deletions(-)
```

新增未跟踪文件：

```
 houdini_agent/skills/explain_node_error.py
 houdini_agent/skills/find_nodes_by_param.py
 houdini_agent/skills/get_node_card.py
 houdini_agent/skills/get_node_inputs.py
 houdini_agent/skills/get_node_positions.py
 houdini_agent/skills/list_network_boxes.py
 houdini_agent/skills/search_houdini_help.py
 houdini_agent/skills/setup_dynamics_sim.py
 houdini_agent/skills/setup_pyro_sim.py
 houdini_agent/skills/setup_render.py
```

---

## 待办 / 后续

- [ ] 循环检测硬熔断恢复：改进第三条判定逻辑（分级干预 / 按工具类型区分阈值），而非简单禁用。详见 [CHANGELOG_2026-07-08.md](./CHANGELOG_2026-07-08.md)。
- [ ] Skill 迁移后观察模型是否正确路由到 `run_skill(...)`，必要时补充系统提示词引导。
- [ ] `set_parameter_expression` 后续可考虑支持批量设置（类似 `batch_set_parameters`）。
