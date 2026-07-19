# Houdini-Agent 更新记录（2026-07-12 ~ 2026-07-19）

## 发布摘要

本轮改动主要围绕五条主线展开：

1. **Skill 体系继续瘦身与分层** - 低频只读查询从核心工具表迁移到 `run_skill(...)`，新增工作流 guide / blueprint skill，并给现有 skill 补齐 `category` 与 `risk_level` 元数据，方便 `list_skills(category=...)` 分组检索。
2. **Plan 执行策略调整** - 计划执行阶段从“逐节点/逐阶段试探”改为“整图优先、批量创建、整体验证”，减少复杂 Houdini 网络被拆碎执行导致的失败。
3. **Houdini Manual 更新模式与 cook 防护更清晰** - Agent 启动时记录更新模式快照，提示词区分确认模式与直接执行模式；直接执行模式允许临时切 Auto 验证，但框架仍恢复用户原始设置。
4. **安全与稳定性加固** - `cook_node force=true` 继续要求确认；Qt 延迟回调、窗口销毁、空 pixmap、IME 中文输入、未配对 tool calls、分页截断等路径做了防崩溃和防上下文爆炸处理。
5. **奖励、反思与 token 估算调优** - 工具调用效率惩罚改为对数软饱和，低 reward 任务可立即触发深度反思，Kimi Code / k3 订阅模型按 0 成本参考估算。

当前工作区统计约 **47 个已跟踪文件变更，+1252 / -445 行**，另有多份新增 plan、changelog、skill 和测试文件尚未提交。

---

## 一、Skill 迁移与分类体系

### 核心工具表瘦身

以下低频只读工具从核心 function-calling 工具表迁移为 skill，通过 `run_skill(...)` 调用：

| 原核心工具 | 新 Skill | 分类 | 说明 |
|------------|----------|------|------|
| `get_node_card` | `get_node_card.py` | `graph` | 建节点前查看节点类型说明 |
| `get_node_inputs` | `get_node_inputs.py` | `graph` | 查看节点输入端口含义 |
| `get_node_positions` | `get_node_positions.py` | `graph` | 读取节点布局坐标 |
| `list_network_boxes` | `list_network_boxes.py` | `graph` | 列出 NetworkBox 及包含节点 |
| `find_nodes_by_param` | `find_nodes_by_param.py` | `graph` | 按参数搜索节点 |

配套更新：

- `houdini_agent/utils/ai_client.py`、`tool_registry.py`、`streaming_tool_executor.py`、`ui/ai_tab.py` 同步移除已迁移工具名。
- `system_prompt_rules_core.txt`、`system_prompt_rules_extra.txt`、`Doc/tool_selection_guide.md` 中的引用统一改为 `run_skill('...', ...)`。
- `list_skills` 支持 `category` 参数过滤，降低模型在大量 skill 中找工具的 token 成本。

### Skill 元数据规范化

`houdini_agent/skills/__init__.py` 明确新增 skill 必须提供 `category`，并约定现有分类：

| 分类 | 用途 |
|------|------|
| `geometry` | SOP 几何、属性、组、拓扑分析 |
| `graph` | 网络结构、节点卡片、依赖追踪、契约校验 |
| `scene` | 场景上下文、单节点报错诊断 |
| `usd` | LOPs / USD stage 检查 |
| `materials` | 材质指认和材质网络检查 |
| `performance` | cook 性能与缓存报告 |
| `docs` | Houdini 文档检索 |
| `workflow` | 只返回配方的一键搭建蓝图 |

既有分析 skill 补齐了 `category` 与 `risk_level: low`，包括几何分析、USD/material 检查、依赖追踪、网络契约、缓存报告、cook 性能等。

---

## 二、新增 Houdini 工作流 Skill

### Guide Skill

新增三类只读工作流引导，用于在创建或修复场景前先选对 Houdini 作业方式：

| Skill | 分类 | 说明 |
|-------|------|------|
| `procedural_modeling_guide.py` | `workflow` | SOP 程序化建模路线，强调 Node-first，避免一上来用 VEX/Python 造几何 |
| `usd_scene_assembly_guide.py` | `workflow` | LOPs / Solaris / USD 场景搭建路线，强调 viewport-first lookdev 与 `materiallibrary` 规则 |
| `debug_scene_workflow.py` | `scene` | 全局场景调试路线，要求先定位 scene/node/parm/geometry/USD/simulation 证据再修改 |

新增全局规则 `rules/houdini_work_discipline.md`，沉淀 Node-first、工具优先级、先规划整图、先低精度验证、昂贵阶段缓存、完成声明必须基于验证等纪律。

### Workflow Blueprint Skill

延续“skill 不直接写场景”的安全边界，新增或整理以下蓝图式 skill：

| Skill | 覆盖范围 | 安全边界 |
|-------|----------|----------|
| `setup_pyro_sim.py` | Pyro smoke/fire 蓝图 | 只返回节点/连线/参数配方 |
| `setup_dynamics_sim.py` | RBD / FLIP / Vellum 蓝图 | 只返回配方，写操作交给 core tools |
| `setup_render.py` | Karma LOP / Mantra ROP 渲染配置蓝图 | 只返回配方 |

这些 skill 不 `import hou`、不创建节点、不绕过 harness；AI 拿到配方后仍需通过 `create_nodes_batch`、`connect_nodes`、`batch_set_parameters` 等受管控 core 工具执行。

### Houdini 帮助与单节点诊断

- `search_houdini_help.py`：新增 Houdini 自带帮助检索 / 页面读取 skill，作为 `search_local_doc` 的版本精确补充。
- `explain_node_error.py`：新增单节点错误解释 skill，重点识别 file/path 类参数是否指向缺失文件，补齐整网诊断之外的聚焦排障点。

---

## 三、Plan 执行与 Manual 更新模式

### 整图优先执行

`houdini_agent/ui/i18n.py` 中英文计划执行提示改为：

- 如果计划包含 architecture、节点列表或连接关系，优先用一次 `create_nodes_batch` 创建整张计划图，再做 `verify_network(parent_path)`。
- 不把 S1/S2/S3 当作“每阶段必须 cook 通过”的硬锁；step 用于组织计划状态，不应强迫逐阶段建图。
- 中间 display 几何暂时为 0 时，先补齐下游节点和连接，再验证最终输出或关键里程碑。
- 只有 dry-run 指出无效节点/参数、后续节点依赖动态路径、用户明确要求逐阶段确认或操作高风险时，才拆成多个批次。

新增测试：

- `tests/test_plan_execution_prompt.py`：断言中英文提示都包含整图优先、批量创建和整体验证约束。

### 直接执行模式

新增 `ai.direct_execute_prompt`：

- 用户开启直接执行模式时，Agent 应连续执行完整工作流，不中途要求“回复确认再继续”。
- 若 Houdini 处于 Manual 更新模式且验证仍显示空几何，直接执行模式可临时切 `hou.updateMode.AlwaysUpdate` 后重新验证。
- Agent 结束时框架恢复用户原始更新模式，最终总结应说明曾临时切 Auto 验证。

### 更新模式快照

`AITab._start_agent_run(...)` 成为 Agent 启动的共享入口，用于捕获 `_pre_agent_update_mode`、统一构造参数、启动响应块和后台线程。

新增测试：

- `tests/test_manual_update_mode_directive.py`：覆盖 Manual 模式提示只使用启动快照、不读取运行中实时状态；Plan 执行沿用共享启动入口；计划直接执行不擅自切 Auto。

---

## 四、安全、稳定性与上下文控制

### `cook_node` 高风险确认

`cook_node force=true` 在 agent / plan 模式中继续被 harness 判为需要用户确认，避免模型把重 cook 当成普通验证手段。

配套文档和测试：

- `Doc/tool_selection_guide.md`：强调验证优先用 `inspect_node`、`check_errors`、`verify_network`、`get_geometry_summary`。
- `tests/test_harness_policy.py`：覆盖 force cook 需要确认。

### Qt 与 UI 稳定性

- `houdini_agent/qt_compat.py` 新增 QObject 存活校验与 `safe_single_shot(...)`。
- `cursor_widgets.py` 中的延迟布局/滚动/折叠回调改用安全 singleShot，避免 widget 已销毁后继续访问 C++ 对象。
- `main_window.py`、`main.py` 在重建或关闭窗口时先 `hide()` 再 `deleteLater()`。
- `chat_view.py`、`image_mixin.py` 跳过加载失败或 null pixmap，避免空 pixmap 进入布局。
- `cursor_widgets.py`、`header.py` 增加 IME 友好输入控件与非模态 rules editor，修复 Houdini + PySide2 下中文输入不稳定。

### 消息清洗和分页截断

- `ai_client.py` 的 tool message 清洗补齐未配对 tool call 的占位响应，减少 OpenAI-compatible API 的 400 错误。
- 对自带分页信息的大结果增加软截断与 `offset` 翻页提示，纠正模型误用 `pattern` 代替分页。

### 自动读取上下文去重

`action_commands_mixin.py`、`ai_tab.py`、`session_manager.py` 添加 `_last_auto_read_context`，避免同一场景上下文重复注入历史浪费 token。

---

## 五、工具能力与布局体验

### `set_parameter_expression`

新增 `set_parameter_expression` core tool，支持设置 HScript / Python 参数表达式和通道引用，例如 `ch("../ctrl/scale")`、`$F` 等。

该工具接入：

- `ai_client.py` schema
- `mcp/client.py` 分发与撤销快照
- `mcp/server.py` MCP 注册
- `harness_engine.py` / `harness_policy_config.py` 场景变更治理
- `tool_registry.py` parameter 意图组

### 布局锚点

`create_nodes_batch` 后的 tidy layout 会尝试使用当前 NetworkEditor `visibleBounds().center()` 作为锚点，让新节点落在用户可视区域，而不是默认原点。

新增测试：

- `tests/test_tidy_layout.py`：覆盖 anchor position 优先于原始中心。

### 搜索增强

`search_nodes()` 增加 `category` 参数，可按 sop / obj / dop / vop 等节点类别过滤。

---

## 六、Reward / Reflection / Token 调优

### Reward 效率评分

`houdini_agent/utils/reward_engine.py` 将工具调用数惩罚从线性改为 `log1p` 软饱和：

- 复杂建图任务需要大量正当工具调用时，不再被线性惩罚压到接近 0。
- retry 仍保留线性惩罚，因为它更接近真实试错成本。

### 低分任务立即反思

`houdini_agent/utils/reflection.py` 新增 `LOW_REWARD_REFLECT_THRESHOLD = 0.4`。单个任务 reward 低于阈值时可立即触发深度反思，不必等满 5 个任务或错误率 spike。

### Kimi Code 成本估算

`houdini_agent/utils/token_optimizer.py` 增加 `k3` 与 `kimi-for-coding` 前缀，按订阅套餐参考估算为 0 成本，避免成本面板误报。

---

## 七、计划与文档记录

新增计划文档：

- `.copilot-tracking/plans/skill_migration_plan.md`：fxhoudinimcp skill 吸收和第一批 guide skill 计划。
- `.copilot-tracking/plans/fxhoudinimcp_borrow_mvp_plan.md`：借鉴 fxhoudinimcp 能力域的 MVP 计划。
- `.copilot-tracking/plans/lops_pdg_tools_plan.md`：LOPs / PDG 只读检查 skill 的后续实现计划。

新增实现记录：

- `.copilot-tracking/changes/20260719-skill-migration-changes.md`：第一批 skill migration 的实施记录和 release summary。

新增本轮 changelog：

- `changelog/CHANGELOG_2026-07-19.md`

---

## 涉及文件概览

### 主要新增文件

```text
.copilot-tracking/changes/20260719-skill-migration-changes.md
.copilot-tracking/plans/fxhoudinimcp_borrow_mvp_plan.md
.copilot-tracking/plans/lops_pdg_tools_plan.md
.copilot-tracking/plans/skill_migration_plan.md
changelog/CHANGELOG_2026-07-19.md
houdini_agent/skills/debug_scene_workflow.py
houdini_agent/skills/explain_node_error.py
houdini_agent/skills/find_nodes_by_param.py
houdini_agent/skills/get_node_card.py
houdini_agent/skills/get_node_inputs.py
houdini_agent/skills/get_node_positions.py
houdini_agent/skills/list_network_boxes.py
houdini_agent/skills/procedural_modeling_guide.py
houdini_agent/skills/search_houdini_help.py
houdini_agent/skills/setup_dynamics_sim.py
houdini_agent/skills/setup_pyro_sim.py
houdini_agent/skills/setup_render.py
houdini_agent/skills/usd_scene_assembly_guide.py
rules/_houdini_progressive_template.md
rules/houdini_work_discipline.md
tests/test_manual_update_mode_directive.py
tests/test_plan_execution_prompt.py
```

### 主要修改区域

```text
Doc/tool_selection_guide.md
houdini_agent/core/harness_engine.py
houdini_agent/core/harness_policy_config.py
houdini_agent/core/main_window.py
houdini_agent/core/plan_mixin.py
houdini_agent/core/session_manager.py
houdini_agent/core/streaming_tool_executor.py
houdini_agent/main.py
houdini_agent/prompts/system_prompt_rules_core.txt
houdini_agent/prompts/system_prompt_rules_extra.txt
houdini_agent/qt_compat.py
houdini_agent/skills/*.py
houdini_agent/ui/action_commands_mixin.py
houdini_agent/ui/ai_tab.py
houdini_agent/ui/chat_view.py
houdini_agent/ui/cursor_widgets.py
houdini_agent/ui/header.py
houdini_agent/ui/i18n.py
houdini_agent/ui/image_mixin.py
houdini_agent/utils/ai_client.py
houdini_agent/utils/mcp/client.py
houdini_agent/utils/mcp/hou_core.py
houdini_agent/utils/mcp/server.py
houdini_agent/utils/plan_manager.py
houdini_agent/utils/reflection.py
houdini_agent/utils/reward_engine.py
houdini_agent/utils/token_optimizer.py
houdini_agent/utils/tool_registry.py
tests/test_harness_policy.py
tests/test_tidy_layout.py
tests/test_tool_registry.py
```

---

## 验证记录

本轮新增/更新的测试覆盖点包括：

- `tests/test_plan_execution_prompt.py`：Plan 执行提示必须强调整图优先、批量创建和整体验证。
- `tests/test_manual_update_mode_directive.py`：Manual 更新模式提示和 Agent 启动快照行为。
- `tests/test_harness_policy.py`：`cook_node force=true` 需要确认。
- `tests/test_tidy_layout.py`：NetworkEditor 可视区域锚点布局。
- `tests/test_tool_registry.py`：工具意图分组与始终可用工具集合。

> 注：部分 Houdini / HOM 相关 skill 仍建议在真实 Houdini 会话内做一次集成验证，尤其是蓝图 skill 中的节点类型名和 LOP / render 默认参数。

---

## 待办 / 后续

- [ ] 观察迁移后模型是否稳定使用 `list_skills` / `run_skill(...)`，必要时继续收紧工具选择提示。
- [ ] 循环检测硬熔断仍处于临时放宽状态，后续应按工具类型做分级干预，而不是简单恢复旧阈值。
- [ ] 在真实 Houdini 中验证 `setup_pyro_sim`、`setup_dynamics_sim`、`setup_render` 的节点类型名和默认参数。
- [ ] 按 `lops_pdg_tools_plan.md` 评估是否实现 USD prim / layer / composition 与 TOP work item 只读检查 skill。
- [ ] 如果 `set_parameter_expression` 使用频率上升，可考虑补一个批量表达式设置工具，但目前先保持单点工具，避免过早抽象。