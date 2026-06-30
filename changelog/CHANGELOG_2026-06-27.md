# Houdini-Agent 更新记录（2026-06-27）

## 发布摘要

本次更新主线：**工具硬化 + 节点查询能力补强 + AI 行为引导**，参考 `fxhoudinimcp` 的 senior-artist 哲学，让 AI 真的走 batch 路径而不是逐个建节点。

工具总数从 58 → 53（删 5 个冗余/僵尸 schema），新增 2 个（`verify_network` / `get_node_card`）。

---

## 关键更新

### 1. 工具硬化：从软失败 → 硬失败 + 完整错误清单

之前部分写操作 "只要 1 个成功就 `success=True`"，AI 看到成功就继续往下走，最终 cook 才发现不对。本次统一为**任何失败 = 整体 success=False + 完整错误清单**，并加 did-you-mean 提示。

- **`create_nodes_batch`（`create_network`）四项修复**：
  - 支持显式 `parent_path`，不再依赖"当前网络编辑器焦点"这种不可靠状态；找不到硬报错。
  - 引入 `node_errors` 清单；任何节点/连接失败 → `success=False`；部分成功也算失败。
  - `connections` 端点 id 找不到 → 硬报错并列出可用 id，不再静默跳过。
  - schema 兼容 `parameters` / `parms` 两种字段名，与 `create_node` 一致；未知参数名报错并提示用 `get_parameter_schema`；parm tuple 自动识别（如 `size:[1,2,3]`）。
- **`batch_set_parameters` 软失败修复**：原本 `return len(success) > 0` —— 1 个成功就 True。现在任何节点失败 → 完整错误清单 + did-you-mean 提示。
- **`create_node` 参数静默吞修复**：原本参数设置失败 `except: continue` 静默；现在未知 parm / set 异常 / parm tuple 类型不匹配都报错，失败时 `node.destroy()` 回滚整个创建（原子语义）。

### 2. `create_nodes_batch` 加 Phase 1 预校验 + `dry_run=True`

参考 `fxhoudinimcp.graph.build_network` 的"先校验、再构建、原子回滚"哲学，但保留极简版：

- **Phase 1 校验**（永远跑，`dry_run=True` 也跑）：
  - 节点类型解析：精确匹配 → 去版本号匹配（如 `filecache` → `filecache::2.0`）→ 不存在则 `difflib.get_close_matches` 给 did-you-mean。
  - spec 内 id 重复检测。
  - 显式 `name` 与父网络下已有 child 节点冲突检测（auto-container 场景自动跳过）。
  - `connections` 端点必须指向 spec 内 id。
  - 校验失败 → 一次性返回**全部错误清单**，**不创建任何节点**。
- **`dry_run=True` 早返**：跑完 Phase 1 后返回"dry_run 通过：N 个节点 / M 个连接 / 已校验类型"，让 AI 在用陌生节点时先做一次无副作用的验证。
- **未做**：探针 parm 校验（每个 type 真建一次再 destroy）、Phase 3 cook + evidence —— 先观察 Phase 1 + dry_run 的边际收益，再决定是否补。

### 3. 新增 `verify_network`：一次性核查整张网络

替代逐个 `check_errors`。"中键查每个节点" 的一次性版本。

- 强制 cook display node，让上游错误浮现。
- 返回每个 child 的 errors / warnings / display+render+bypass flags。
- 返回 display 节点的几何 evidence：points / prims / vertices。
- AI 现在可以用 `verify_network(parent_path)` 一次拿到"是否健康 + 几何点数非零"两个关键 evidence，不必再调 5 次 `check_errors`。

### 4. 新增 `get_node_card`：建节点前一站式查类型说明

无需先建节点。补全了之前缺的：`get_parameter_schema` 需要节点实例、`get_node_inputs` 只有端口、`get_houdini_node_doc` 太长。

返回：
- `min_inputs` / `max_inputs` / `max_outputs` / `is_generator`
- `input_labels` / `output_labels`（探针节点：临时 createNode 读 inputLabels 后立刻 destroy）
- 参数名 + label + type + default + **menu items**（enum 合法值，前 15 项）

### 5. 工具清理：删 5 个冗余/僵尸 schema

| 删除 | 替代 | 原因 |
|------|------|------|
| `verify_and_summarize` | `verify_network` | **僵尸 schema**：注册了 schema 但 dispatch 表无对应 handler，AI 调用必然失败 |
| `set_display_flag` | `set_node_flags` | 100% 子集（`set_node_flags` 已支持 display/render） |
| `check_errors` | `verify_network` | 完全被覆盖 |
| `list_children` | `find_nodes(recursive=False)` | 等价 |
| `get_node_parameters` | `inspect_node` + `get_parameter_schema` | 输出 80% 重合 |

底层 `_tool_xxx` 方法 + dispatch 表全保留 —— 不破坏 `tests/test_harness_policy.py` 引用、不破坏 changelog 历史、不破坏旧 prompt 缓存。仅 schema 不再暴露给 AI。

### 6. 节点查询五件套 description 重写

`search_node_types` / `semantic_search_nodes` / `get_node_inputs` / `get_node_card` / `get_houdini_node_doc` 之前 description 互相打架，AI 选择困难。本次每个工具明确"何时用 / 何时不用"决策路径：

- 不知道节点叫什么 → `semantic_search_nodes`
- 已经有关键词 → `search_node_types`
- 建节点前一站式查 → `get_node_card`（最丰富）
- 只查接线端口、对方是 210 常用节点 → `get_node_inputs`（JSON 缓存最快）
- 看长文档 → `get_houdini_node_doc`

### 7. AI 行为引导：Senior Artist Discipline + 反模式禁令

参考 `fxhoudinimcp` 的 `server_instructions.md` 风格，在 `system_prompt_rules_core.txt` 新增 3 条最高优先级规则：

1. **PLAN THE WHOLE GRAPH, THEN BUILD IT ATOMICALLY**：任何创建 **2 个或以上**节点的任务，第一个 tool call 就必须是 `create_nodes_batch`；陌生节点先 `dry_run=True`。明列 ANTI-PATTERN：`create_node(box) → create_node(scatter) → connect_nodes(...)` ❌、"让我先建第一个看看" ❌。
2. **NEVER GUESS PARAMETER NAMES**：陌生类型先调 `get_node_card(node_type, context)`；已有节点用 `get_parameter_schema`。猜参数名是 #1 沉默 bug 来源。
3. **VERIFY, THEN CLAIM**：build 完调 `verify_network(parent_path)`，必须看到 `healthy=True` 且几何点数非零才能回报用户成功。工具 `success` ≠ 网络真的工作。

配套加固 `create_node` 的 schema description：明确"**仅用于** 1 个孤立节点"，列反模式 + 例外。

### 8. 稳定性：抑制 Houdini Qt 主窗口在批量节点操作期间的 layout 抖动

崩溃排查发现 Houdini 20.5.684 在 agent 高频写节点期间偶发 `QHeaderView::logicalIndexAt` / `QLayout::activate` 路径 SIGSEGV（crash log 栈底是 `QWidget::setStyleSheet` → 全树样式重算）。根因是高频 OPchange + UI pane layout race。

- 新增 `_SuspendHoudiniUIRedraw` 上下文管理器（`utils/mcp/client.py` 模块级）：进入时 `hou.qt.mainWindow().setUpdatesEnabled(False)`，退出时一次性恢复并合并刷新。失败静默 fallback。
- 在 7 个高频批量工具入口套上：`_tool_create_nodes_batch` / `_tool_connect_nodes` / `_tool_copy_node` / `_tool_batch_set_parameters` / `_tool_layout_nodes` / `_tool_create_network_box` / `_tool_add_nodes_to_box`。
- 不碰 cook 模式（已有 Manual 守护）、不碰 undo group、不碰只读工具。单次 `create_node` 不在范围 —— 单次响应感更重要。

### 9. 稳定性：消除 agent 运行期高频 `setStyleSheet` 抖动

crash log（18:17 那次）直接栈是 `setStyleSheet → setStyle_helper → inheritStyle → QHeaderView::logicalIndexAt → SIGSEGV`。agent 跑工具时每轮 policy decision 都会刷新模式守卫 UI，即便文本/样式完全没变也照样调 `setText` / `setStyleSheet`，触发 Qt 全树样式重算。

- `core/diagnostics_mixin.py` `_refresh_mode_guard_ui`：加 `_mode_guard_cache` 状态快照，文本/样式/tooltip 任一项未变就跳过对应 Qt 调用。
- `ui/ai_tab.py`：删除重复的 `_refresh_mode_guard_ui` 覆盖实现（与 mixin 完全相同），让 mixin 的去重版生效。
- `ui/cursor_widgets.py` `PlanCard._refresh_ui` / `PlanViewer._refresh_ui`：`_status_badge` 同样加 `_badge_text_cache` / `_badge_style_cache` —— plan 步骤每次状态变化不再无差别重设 stylesheet。

### 10. Plan 模式 step 粒度修正：按子系统拆，禁止按节点拆

观察到 4 节点小网络被 LLM 拆成 5 个 step（每节点一步 + 验证一步），原因是 plan 规划提示词只说"粒度适中"，schema description 也没禁止按节点拆，LLM 默认走"一节点 = 一原子操作 = 一 step"的直觉。

- `utils/plan_manager.py` `PLAN_TOOL_CREATE` schema description 顶部加铁律：**"Group steps by SUBSYSTEM, not by individual node"**、**"Per-node steps are FORBIDDEN"**，附自检公式 `step_count >= node_count → 拆得太细`。这条进 OpenAI function tool schema，比系统提示词的细节优先级更高。
- `ui/i18n.py` 中/英 `plan_mode_planning_prompt` 同步：
  - "粒度适中" → "按子系统/阶段拆 step"，带 ✗/✓ 反例对照（Grid/Box/Scatter/CopyToPoints 应聚合为 1 个 step）
  - tools 例子从 `run_python, create_node, set_parms` 改为 `create_nodes_batch, batch_set_parameters` 优先
  - 复杂度档位调降：简单 2-3 → **1-3** 步，中等 4-7 → **3-5** 步，加入"step ≥ node 数 = 拆太细"自检

---

## 影响范围

```text
houdini_agent/utils/mcp/client.py              # 工具硬化 + Phase 1 校验 + verify_network + get_node_card + _SuspendHoudiniUIRedraw 上下文 + 7 个批量工具 wrap
houdini_agent/utils/ai_client.py               # schema 增删改 + 节点查询五件套 description 重写
houdini_agent/utils/plan_manager.py            # create_plan schema 加 subsystem-not-node 铁律
houdini_agent/prompts/system_prompt_rules_core.txt   # Senior Artist Discipline 3 条 + ANTI-PATTERN
houdini_agent/core/diagnostics_mixin.py        # _refresh_mode_guard_ui 加状态快照去重
houdini_agent/ui/ai_tab.py                     # 删除重复的 _refresh_mode_guard_ui 覆盖
houdini_agent/ui/cursor_widgets.py             # PlanCard / PlanViewer _refresh_ui 加 _status_badge 去重
houdini_agent/ui/i18n.py                       # plan_mode_planning_prompt 中英版同步:子系统粒度 + 批量工具优先 + 复杂度档位下调
README.md / README_CN.md                       # 工具清单同步
Doc/tool_selection_guide.md                    # Task Routing Matrix 全表更新 + Flags 段更新
```

底层未改（保留向后兼容）：
- `tools/test_harness_policy.py` 等测试里 `get_node_parameters` / `check_errors` 等老工具名仍可调用，因为 dispatch 表 + `_tool_xxx` 全保留。
- `changelog/` 历史记录原样保留。

---

## 兼容性说明

- AI 看到的 schema 减少 5 个，但底层 handler 全部保留，旧 prompt 缓存或自定义脚本调用旧工具名仍能 work。
- `create_nodes_batch` 的返回语义变化：**部分成功现在算失败**（`success=False` + 错误清单）。若有外部脚本依赖旧"软成功"行为，需改判断逻辑。
- `create_node` 的返回语义变化：**参数设置失败现在销毁节点回滚**。原本 "节点建出来了但参数没设" 的中间态不会再出现。
- 新增 schema：`verify_network` / `get_node_card`，无破坏。
- `dry_run` 字段：`create_nodes_batch` 新增可选参数，缺省 `False`，旧调用不受影响。

---

## 验证

```text
python -c "import ast; ast.parse(open('houdini_agent/utils/mcp/client.py',encoding='utf-8').read()); ast.parse(open('houdini_agent/utils/ai_client.py',encoding='utf-8').read()); print('OK')"
OK

schema count: 58 → 53
```

无 pytest 环境，仅 ast 语法校验；运行时验证留待 Houdini 内集成测试。

---

## 后续建议

- 实跑典型场景（box → scatter → copytopoints）观察 AI 是否真的第一手就 `create_nodes_batch`；如果仍倾向单建，加 `create_nodes_batch` 失败惩罚机制或 prompt 加例子。
- 观察 `dry_run` 真实使用率：如果 AI 多轮在 `create_nodes_batch` 上反复试错，证明 `dry_run` 提示不够强，可在 `_TOOL_USAGE` 加更具体示例。
- 视情况补 fxhoudinimcp 的另外几个工具：
  - `find_expensive_nodes`（perfMon 性能分析）— 等用户喊"网络慢"
  - `find_error_nodes` 全场景递归 — 等 AI 经常误判"建好了"
  - ASCII flow `get_network_overview` 改造 — 等 AI 多轮查关系
- `get_node_card` 的探针节点临时建 + destroy 有微小副作用（可能触发 OnCreated）；如果出问题，改用 `parmTemplateGroup()` 静态查（牺牲 input_labels）。
