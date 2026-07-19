# fxhoudinimcp Skill 吸收计划

> 目标：吸收 `healkeiser/fxhoudinimcp` 中最有价值的 Houdini 工作流提示与作业纪律，补齐本项目在“正确规划、建网、验证”方面的 guide skill，而不是照搬它的工具体系或扩大写场景权限。
> 状态：第一批已实施并验证；第二批候选保留为后续评估。

---

## 1. 背景判断

fxhoudinimcp 最值得借鉴的部分不是 179 个 MCP tools 本身，而是它围绕 Houdini 作业方式写出的 prompt / workflow guidance：

- SOP 建模时坚持 **Nodes over VEX**，避免一上来写 wrangle 或 Python 造几何。
- LOPs/Solaris 中坚持 **viewport-first lookdev**，材质放在 USD-native 的 `materiallibrary` LOP 中，而不是 `/mat`。
- 模拟任务优先使用现代 SOP-level solver 和 workflow 工具，手工 DOP wiring 只作 fallback。
- TOPs/PDG 优先使用原生 TOP 节点，避免把 pipeline 写成 Python Script 大杂烩。
- 调试时先系统性定位 scene / node / parm / geometry / USD / simulation 问题，再修改。

本项目现有 skill 更偏“查询、诊断、蓝图生成”，例如 `get_node_card`、`search_houdini_help`、`inspect_scene_context`、`explain_node_error`、`setup_pyro_sim`、`setup_dynamics_sim`。缺口是：**在用户要创建或修复 Houdini 内容时，引导 AI 先做正确工作流选择**。

因此本计划采用“两层结构”：

1. 全局规则：沉淀长期有效的 Houdini 工作纪律。
2. Guide skill：为 SOP、LOP、Debug 等高频作业域提供低风险、只读、可路由的实施建议。

---

## 2. 设计原则

### 2.1 不照搬 fxhoudinimcp 工具体系

fxhoudinimcp 的 prompt 依赖它自己的工具名，例如 `build_network`、`create_lop_node`、`capture_screenshot`、`get_stage_info`。本项目应吸收原则和流程，不把这些工具名硬编码成必须存在的调用。

### 2.2 新增 skill 默认只做 guide / route / plan

第一批新增 skill 不直接导入 `hou`，不修改场景，只返回结构化建议。写操作仍通过本项目已有 core tools、harness、undo/cook 保护路径执行。

### 2.3 优先补最高频、最容易犯错的作业域

第一批只做三类：

- SOP procedural modeling
- LOPs / USD scene assembly
- scene debugging workflow

PDG、HDA、simulation 知识增强放到第二批或 backlog。

### 2.4 规则和 skill 分工清晰

- 规则文件负责全局纪律：Node-first、先查再写、验证后声称、先低精度验证、缓存昂贵阶段。
- skill 负责具体作业域：给出推荐节点链、反模式、验证步骤、应调用的现有 skill/core tool。

---

## 3. 第一批新增内容

### 3.1 新增全局规则 `rules/houdini_work_discipline.md`

用途：作为 Houdini 任务的长期行为约束，吸收 fxhoudinimcp `server_instructions.md` 的精华。

建议内容：

1. **Node-first rule**
  - 写 VEX、Python SOP、`execute_python` 前，先查是否有原生节点或现有 skill 能完成。
  - 不确定节点参数、端口、菜单值时，用 `get_node_card` / `get_parameter_schema` / `search_houdini_help` 查证。

2. **Tool priority**
  - 优先级：workflow/blueprint skill > batch/native node operations > VEX wrangle > Python execution。
  - `execute_python` 只作为最后手段，不能绕过安全边界创建、连接、删除节点。

3. **Senior Houdini discipline**
  - 先规划整图，再执行建网。
  - 先 blockout / low-res / low-substep，再 upres。
  - 昂贵阶段以 cache 或明确 checkpoint 结束。
  - 可调参数放在 CTRL null spare parms，避免 magic numbers 深埋节点内部。
  - 完成声明必须基于验证结果，而不是工具返回 success。

4. **Context reminders**
  - SOP：建模、散布、属性、拓扑、UV、体积尽量用 SOP。
  - LOP：材质属于 `materiallibrary`，材质绑定通过 `assignmaterial`，lookdev 优先 viewport preview。
  - DOP/SOP solvers：常见模拟优先用现代 SOP-level solver 或既有 simulation blueprint skill。
  - TOP：pipeline 优先用 File Pattern、Wedge、ROP Fetch、Wait for All、Partition 等原生 TOP。

落地检查：确认规则是否需要被 `rules/MainRules.md` 明确引用，或者当前规则加载机制是否会自动发现新文件。

---

### 3.2 新增 skill `houdini_agent/skills/procedural_modeling_guide.py`

定位：SOP 程序化建模工作流引导。

类别：`workflow`

风险：`low`

副作用：无；不导入 `hou`，不修改场景。

输入建议：

| 参数 | 类型 | 说明 |
|---|---|---|
| `description` | string | 用户想创建的几何或资产描述 |
| `output_context` | string | 默认 `/obj` |
| `complexity` | string | `simple` / `medium` / `complex`，用于控制建议粒度 |

输出建议：

- `recommended_workflow`：步骤化 SOP 建模流程。
- `suggested_node_chain`：推荐节点链，例如 `box -> polybevel -> boolean -> scatter -> copytopoints`。
- `node_search_keywords`：建议查询的节点关键词，例如 `bevel`、`boolean`、`scatter`。
- `anti_patterns`：VEX/Python 反模式及替代节点。
- `verification`：建完后应检查 display flag、geometry summary、错误节点、节点参数。
- `fallbacks`：没有合适原生节点时才考虑 wrangle，并要求先验证 VEX。

吸收 fxhoudinimcp 要点：

- “Your job is to build SOP node chains, not VEX code.”
- 常见 SOP 节点速查：primitives、modeling、deformation、copy/instance、scatter、group/filter、attributes、topology、UV。
- 反模式：用 wrangle 造 box、删点、做 boolean、做 extrusion、做随机属性等，都应优先换成 SOP。

---

### 3.3 新增 skill `houdini_agent/skills/usd_scene_assembly_guide.py`

定位：LOPs/Solaris USD 场景搭建引导。

类别：`workflow` 或 `usd`；推荐 `workflow`，因为它是搭建流程而不是单纯检查。

风险：`low`

副作用：无；不导入 `hou`，不修改场景。

输入建议：

| 参数 | 类型 | 说明 |
|---|---|---|
| `scene_description` | string | 用户想搭建的 USD 场景 |
| `renderer` | string | `karma` / `storm` / `usd_preview`，默认 `karma` |
| `lookdev_first` | boolean | 默认 true，强调先 viewport preview |

输出建议：

- `recommended_workflow`：从 scene inspect、stage planning、LOP chain、material、lighting、camera 到 verification。
- `lop_node_plan`：推荐使用 `sublayer`、`reference`、`sopimport`、`materiallibrary`、`assignmaterial`、`light`、`camera`、`karmarendersettings` 等节点类型。
- `material_rules`：材质不要放 `/mat`，应放 `materiallibrary` LOP 中；绑定用 `assignmaterial`。
- `lookdev_rules`：预览阶段使用 viewport / Hydra，不先写磁盘渲染。
- `anti_patterns`：Python LOP 建 prim、Python LOP 绑材质、手改 USD layer、为预览做 final render。
- `verification`：检查 stage、prim hierarchy、material bindings、viewport screenshot / preview。

吸收 fxhoudinimcp 要点：

- Viewport-first lookdev。
- LOP 材质容器规则。
- LOPs build USD stage layer by layer。
- Display flag 决定当前查看的 stage 输出。

---

### 3.4 新增 skill `houdini_agent/skills/debug_scene_workflow.py`

定位：全局场景调试路线，不替代单节点诊断。

类别：`scene`

风险：`low`

副作用：无；不主动 cook heavy 节点，不修改场景。

输入建议：

| 参数 | 类型 | 说明 |
|---|---|---|
| `problem_description` | string | 用户描述的问题 |
| `scope` | string | `scene` / `node` / `sop` / `usd` / `simulation` / `performance`，默认 `scene` |

输出建议：

- `diagnostic_route`：按优先级排列的诊断步骤。
- `recommended_skills`：建议调用的现有 skill，例如 `inspect_scene_context`、`explain_node_error`、`trace_dependencies`、`validate_network_contract`、`analyze_cook_performance`。
- `common_causes`：缺输入、参数错误、文件路径缺失、display flag 错、group 名不匹配、VEX 编译失败、USD material binding 错等。
- `stop_conditions`：如果连续两次尝试失败，应停止盲改，回到证据收集。
- `verification`：修复后应重新检查错误节点、依赖链、geometry summary、stage 或 viewport。

吸收 fxhoudinimcp 要点：

- 系统化 debug workflow。
- Cooking errors 先查 upstream。
- VEX `ch()` / `chi()` 路径错会静默返回 0。
- 材质不显示要查材质路径、绑定路径和 viewport renderer。
- USD composition 问题要查 layer stack 和 prim hierarchy。

---

## 4. 第二批候选

### 4.1 `houdini_agent/skills/pdg_pipeline_guide.py`

优先级：中。
触发条件：如果近期用户经常要求批量导出、wedge、缓存、ROP 批处理、TOPs pipeline，再做。

核心内容：

- TOP 原生节点优先：File Pattern、Range Generate、Wedge、ROP Fetch、ROP Geometry、Wait for All、Partition、File Copy、FFmpeg Encode。
- 反模式：用 Python Script 列文件、复制文件、跑 ROP、做 wedge、partition frame。
- 验证：先 generate static items，再 inspect work item states，再 cook。

### 4.2 增强 `setup_pyro_sim.py` 与 `setup_dynamics_sim.py`

优先级：中。
不新增完整 `simulation_setup` 拷贝版。更好的做法是在现有 blueprint skill 的描述和返回结果里补充：

- SOP-level solver 优先。
- RBD/FLIP/Vellum/Pyro 的常见节点与反模式。
- source geometry 验证、low-res test、cache checkpoint、simulation inspect 步骤。

### 4.3 `houdini_agent/skills/hda_development_guide.py`

优先级：低。
触发条件：明确开始频繁让 AI 封装 HDA。

核心内容：subnet -> internal network -> promote parameters -> test -> create HDA -> inspect sections -> add help。

---

## 5. 不做事项

- 不搬运 fxhoudinimcp 的 MCP server、bridge、hwebserver 架构。
- 不引入新的外部依赖。
- 不把 guide skill 做成写场景工具。
- 不完整复制 fxhoudinimcp prompt 原文，避免工具名和本项目不匹配。
- 不创建一个泛泛的 `workflow_router` 浅封装，除非后续 guide skill 数量明显增多且路由问题真实出现。

---

## 6. 相关文件

第一批新增：

- `rules/houdini_work_discipline.md`
- `houdini_agent/skills/procedural_modeling_guide.py`
- `houdini_agent/skills/usd_scene_assembly_guide.py`
- `houdini_agent/skills/debug_scene_workflow.py`

第一批可能检查或轻量更新：

- `rules/MainRules.md`
- `houdini_agent/skills/__init__.py`
- `houdini_agent/skills/search_houdini_help.py`
- `houdini_agent/skills/get_node_card.py`

第二批候选：

- `houdini_agent/skills/pdg_pipeline_guide.py`
- `houdini_agent/skills/setup_pyro_sim.py`
- `houdini_agent/skills/setup_dynamics_sim.py`
- `houdini_agent/skills/hda_development_guide.py`

---

## 7. 实施顺序

### Phase 1：规则落地 [x]

1. [x] 新建 `rules/houdini_work_discipline.md`。
2. [x] 检查规则加载路径，必要时在 `rules/MainRules.md` 中引用它。
3. [x] 确认规则只约束决策，不引入新工具权限。

### Phase 2：第一批 guide skill [x]

1. [x] 新增 `procedural_modeling_guide.py`。
2. [x] 新增 `usd_scene_assembly_guide.py`。
3. [x] 新增 `debug_scene_workflow.py`。
4. [x] 确认三个 skill 都有 `SKILL_INFO`、`category`、`risk_level`、`run()`。

### Phase 3：验证 [x]

1. [x] 对新增 Python skill 执行语法检查。
2. [x] 通过 skill loader 确认它们能被注册和列出。
3. [x] 分别调用 `run()` 示例，确认返回结构包含 workflow、anti_patterns、verification。
4. [x] 确认新增 skill 不导入 `hou`，不修改场景。
5. [x] 检查 Markdown 规则没有与现有规则冲突。

### Phase 4：第二批评估 [ ]

1. [ ] 根据实际使用频率决定是否新增 `pdg_pipeline_guide.py`。
2. [ ] 增强 simulation blueprint skill 的文案和返回建议。
3. [ ] 如果 HDA 封装需求出现，再做 HDA guide。

> 备注：Phase 4 是后续候选范围，不包含在本次第一批实施中。

---

## 8. 验收标准

- `list_skills` 能显示新增 guide skill，分类正确。
- `run_skill` 调用新增 guide skill 时返回稳定 dict，不依赖 Houdini UI 状态。
- 新增 skill 不绕过 harness，不产生 scene mutation。
- SOP/LOP/Debug 三类任务中，AI 能从 guide skill 获得明确步骤、反模式和验证建议。
- 新规则让 AI 更倾向“先查节点 / 先规划 / 后执行 / 再验证”，而不是直接写 VEX/Python。

---

## 9. 推荐第一批提交范围

建议第一批只包含 4 个文件：

1. `rules/houdini_work_discipline.md`
2. `houdini_agent/skills/procedural_modeling_guide.py`
3. `houdini_agent/skills/usd_scene_assembly_guide.py`
4. `houdini_agent/skills/debug_scene_workflow.py`

如果规则加载需要显式入口，再额外修改 `rules/MainRules.md`。

这样改动面小，验证简单，且收益覆盖最常见的 Houdini AI 失败模式。

