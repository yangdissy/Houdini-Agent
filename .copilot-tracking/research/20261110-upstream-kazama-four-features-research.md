<!-- markdownlint-disable-file -->

# Research: Kazama-Suichiku/Houdini-Agent (upstream) — Four Candidate Features vs. This Repo

## Task

限定四项来源研究：(1) NetworkBox 感知的节点整理、(2) Plan 模式 DAG 图、
(3) 六种模型 Provider、(4) 模型目录自动刷新。对照上游
`Kazama-Suichiku/Houdini-Agent` 的 `main` 分支源码、README、提交记录，逐项与本仓库
（`yangdissy/Houdini-Agent`，fork 自 `HOUDINI_HIP_MANAGER` 早期代际）当前实现比较。
只研究，不修改产品代码。

## Research Status

- 上游仓库：`Kazama-Suichiku/Houdini-Agent`（public，374★，Python，`main` 默认分支）。
  本文所有上游引用均固定在 `main` HEAD 提交
  `c8c8f8a7b79aea7bfed47921cd6559e8989dcff5`（2026-11-06T08:08:29Z，发布 v2.1.0 官网
  同步提交；`list_commits` 确认为 `main` 最新一条）。
- 工具与方法：`github/search_repositories`、`github/search_code`、
  `github/get_file_contents`（直接按路径整文件拉取，而非仅片段）、
  `github/list_commits`（按文件路径过滤，取引入/最近变更提交）。
  `web_fetch` 对 `raw.githubusercontent.com` 在本沙箱环境持续返回
  transport-level 失败（DNS/连接/TLS），与此前
  `.copilot-tracking/research/20261110-houdini-mcp-landscape-research.md` 记录的已知限制
  一致；改为完全通过 GitHub API (`get_file_contents`) 读取源码，未发生信息缺口。
- 本仓库对照：直接 `view`/`grep` 读取
  `houdini_agent/utils/mcp/hou_core.py`、`houdini_agent/utils/mcp/client.py`、
  `houdini_agent/utils/tool_registry.py`、`houdini_agent/utils/plan_manager.py`、
  `houdini_agent/ui/cursor_plan_widgets.py`、`houdini_agent/ui/header.py`、
  `houdini_agent/utils/ai_client.py`、`tests/test_network_box_comment.py`、
  `VERSION`（本仓库为 `1.5.3`）、`CONTEXT.md`。
- 未验证/未覆盖：上游 QML 侧 `PlanDag.qml` 的渲染实现（只读取到 README 对其功能的描述
  与 `controller.py`/`plan_manager.py` 的数据契约，未逐行拉取 `.qml` 源码——
  本仓库是 PySide/QPainter 架构而非 QML，逐行比较 QML 价值有限）；上游 `codex` /
  `claude_sub` 订阅型 provider 的刷新实现模块未定位（`model_catalog.py` 注释中提及
  "由 subscription 模块单独刷新"，但未取得该模块路径，不计入本次四项范围）。

## 1. Summary

上游在 2026-02 至 2026-11 期间，在同一代际祖先（`HOUDINI_HIP_MANAGER` →
`houdini_agent` 改名，commit `eccc2dfba9c9e118713a201e3f7de395ba8b1628`）之后持续演进，
而本仓库定格在 `VERSION=1.5.3`（约对应上游 v1.5.x 时间线，早于 v2.0 的
QML/独立应用重写）。四项中，**NetworkBox 感知整理**与**Plan 模式 DAG** 本仓库已有对等
甚至更强的实现（同宗代码，本仓库在后续演进出自己的质量门禁与 PySide DAG 组件）；
**六种模型 Provider** 本仓库的后端分支更多但 UI 暴露的是另一套组织定制 Provider
（SiliconFlow/Kimi Coding/OF3D），并非上游文档里的六个；**模型目录自动刷新**
（`model_catalog.py`，上游 2026-11-06 新增，commit `2826f758752a712031d49da78c529dcb6cc0b2ed`）
是本仓库完全没有的能力——本仓库的模型列表是纯硬编码的静态 dict
（`houdini_agent/ui/header.py:36-70` 附近），无 `/v1/models` 探测、无缓存、无过期刷新。
四项中真正值得"采用/改造"的是模型目录自动刷新；NetworkBox 与 Plan DAG 建议只做小幅
"改造"（补齐 `box_name` 概览折叠、补 `set_network_box_comment` 对齐——实际上本仓库已有
后者）；六 Provider 列表本身是组织特定选择，不建议照搬上游具体 Provider 清单，但其
**可插拔 Provider 注册表 + 预编译静态表 + 运行时 merge** 的架构模式值得整体借鉴。

## 2. NetworkBox 感知的节点整理

### 2.1 用户价值

大型 Houdini 网络（100+ 节点）会迅速把节点拓扑的 JSON/文本表示膨胀到数万 token，
让 AI 在每次读图时浪费上下文、增大成本、增加幻觉风险。NetworkBox（Houdini 原生的
"分组框"对象）天然承载了美术师/TD 对节点的语义分组；把这个分组信息喂给 AI 的查询工具，
可以让 AI 优先看到"这个网络有哪几组、每组大概是干什么的"的概览，再按需钻取细节，
而不必每次都展开全部节点。

### 2.2 实际行为（上游）

- 三个独立 MCP 工具（`houdini_agent/README.md:168-174`，固定于 commit
  `c8c8f8a7b79aea7bfed47921cd6559e8989dcff5`）：
  - `create_network_box` — 创建 NetworkBox，支持语义颜色预设
    （input/processing/deform/output/simulation/utility），可选直接把节点塞进去。
  - `add_nodes_to_box` — 把节点追加进已有 box，支持 `auto_fit`。
  - `list_network_boxes` — 列出网络内所有 box 及其内容/元数据。
- 底层实现分两层：
  - `Kazama-Suichiku/Houdini-Agent:houdini_agent/utils/mcp/tools/network_inspect.py`
    （commit `a1307d94a1b9ae1b0ec7d5a04b74ba386b695aa1` 引用）：
    `get_network_structure(network_path=None)` 返回节点+连接+**`network_boxes`**
    （name/comment/node_count/nodes）+ `boxed_node_paths` 原始数据（约第 15-176 行）。
  - 同文件 `get_network_structure_text(network_path=None, box_name=None)`
    （约第 177-260 行）实现"三模式"文本渲染：
    1. **概览模式**（无 `box_name` 且存在 box）：每个 box 只渲染
       `📦 **name**: comment — N 个节点 [type×count, type×count …]`
       一行，并在末尾提示
       `使用 get_network_structure(box_name="box名称") 查看某个分组的详细节点`；
       未分组节点仍完整展开。
    2. **钻入模式**（传 `box_name`）：只展示该 box 内节点的完整细节
       + box 内部连接 + "跨组连接"（box 与外部的连接单独列出）。
    3. **传统全展开模式**：网络里没有任何 NetworkBox 时，退化为逐节点全展开
       （向后兼容）。
  - `Kazama-Suichiku/Houdini-Agent:houdini_agent/utils/mcp/hou_core.py`
    （commit `9647e02097265dcd2163d05e3ddb3dc3044f10b6` 引用，约第 847-1020 行）：
    纯 Houdini API 调用层——`create_network_box` 用 `hou.NetworkBox` 构造并设置
    comment/color/位置；`add_nodes_to_box` 按名称查找已有 box 再 `addNode` +
    可选 `fitAroundContents`；`list_network_boxes` 直接遍历
    `parent.networkBoxes()` 取 `name()/comment()/nodes()/isMinimized()`。

### 2.3 架构 / 依赖

- 纯 `hou` Python API（`hou.NetworkBox`、`node.networkBoxes()`），无第三方依赖，
  无网络调用。
- 文本渲染层（`get_network_structure_text`）与数据层
  （`get_network_structure`）解耦——数据层先拿到完整 `nodes`/`connections`/
  `network_boxes`/`boxed_node_paths`，渲染层再根据 `box_name` 做视图切片。这个分层
  使得"省 token"逻辑完全在字符串拼装阶段完成，不污染数据结构本身，便于其他消费者
  （例如 QML 卡片）复用同一份结构化数据。

### 2.4 可移植边界

- 100% 可移植：NetworkBox 是 Houdini 核心对象模型的一部分（`hou.NetworkBox`,
  `node.networkBoxes()`），与上游/本仓库的架构差异（QML vs PySide、standalone vs
  内嵌）无关，只依赖 `hou` 模块可用。
- 概览折叠逻辑（`get_network_structure_text`）是纯字符串生成，与 UI 框架无关，
  可直接整段移植。

### 2.5 安全 / 兼容性风险

- 低风险。全部是只读查询（`list_network_boxes`、概览/钻入渲染）或创建型纯节点整理
  操作（`create_network_box`/`add_nodes_to_box`），不删除节点、不执行代码。
  `create_network_box`/`add_nodes_to_box` 属于会改变场景布局的 mutating 工具，
  应纳入本仓库既有的 confirm-mode / harness 风险分级（与本仓库对其余创建类工具的
  处理一致），上游对此类工具没有额外的权限分级描述（README 未提及风险等级）。
- 兼容性：`node.networkBoxes()` 在部分非 `/obj` 容器网络类型下可能不可用（上游
  `network_inspect.py` 用 `try/except` 吞掉该异常——即隐式承认此 API 并非在所有
  network category 下都保证存在）。

### 2.6 本仓库现状

**已有对等实现，且在部分维度更强**：

- `create_network_box` / `add_nodes_to_box` / `list_network_boxes` 三个工具已存在
  （`U:\...\Houdini-Agent\houdini_agent\utils\mcp\hou_core.py:847-1020`），与上游
  是同宗代码（本仓库 `houdini_agent/utils/mcp/hou_core.py` 的函数签名、文档字符串、
  错误提示文案与上游几乎逐字相同，印证二者来自共同的历史提交——上游 v6.6.0
  commit `e281158e8f14ae85676f73fff2e4c86ca88cc49c`，2026-02-12，提交信息明确写了
  "NetworkBox Tools (3 new)" 与 "`get_network_structure` enhanced: box_name
  drill-in + overview mode"）。
- `list_network_boxes` 额外被封装为技能
  `houdini_agent/skills/graph/list_network_boxes/SKILL.md` +
  `scripts/main.py`，这是上游 README 未描述的额外封装层（Skill 系统），不是退步。
- 本仓库额外有 `set_network_box_comment` 工具
  （`houdini_agent/utils/mcp/hou_core.py:956-990`，`tool_registry.py:149`，
  测试 `tests/test_network_box_comment.py`），**上游 README 列出的三个 NetworkBox
  工具表里没有这一个**——这是本仓库相对上游公开文档的增量能力。
- **缺口**：本仓库的 `get_network_structure`
  （`U:\...\Houdini-Agent\houdini_agent\utils\mcp\client.py:282-400`）虽然已经
  收集了 `network.children()` 全量节点/连接，**但没有 `box_name` 参数、没有概览
  折叠、没有"跨组连接"渲染**——纯粹逐节点全展开，等价于上游的"传统全展开模式"
  （上游三模式里最旧的一个）。本仓库确实创建/查询 box 的工具存在，但 **"用 box
  折叠网络结构摘要、省 token"这条能力链路缺失**，这正是题目点名的"NetworkBox 感知
  的节点整理"的核心差异点——本仓库目前是"能建 box、能列 box"，但"查看网络结构"
  工具并不感知 box。

### 2.7 建议：改造（小）

不建议整体移植（核心三工具已等价存在），建议仅补齐
`get_network_structure`/其文本渲染路径的 box 感知折叠逻辑，移植范围局限于
`client.py` 内 `get_network_structure` 方法周边（新增可选 `box_name` 参数 + 概览/
钻入分支），工作量与风险都很小（纯本地字符串生成，无新依赖）。

### 2.8 可验证验收标准

- 对一个创建了 ≥2 个 NetworkBox、且有 ≥1 个未分组节点的测试网络调用
  `get_network_structure()`（不传 `box_name`）：输出必须包含每个 box 的
  `name`/`comment`/`node_count` 概览行，且**不**包含 box 内部节点的逐条展开；
  未分组节点仍需完整列出。
- 对同一网络调用 `get_network_structure(box_name="<existing_box>")`：输出必须
  只包含该 box 内节点的完整细节 + 该 box 与外部节点之间的连接（跨组连接），且不
  包含其他 box 的节点细节。
- 对一个不存在任何 NetworkBox 的网络调用 `get_network_structure()`：输出应与
  当前未改造前的全展开行为逐字节一致（回归测试，防止破坏无 box 场景）。
- 新增/传入不存在的 `box_name`：必须返回失败 + 列出当前可用 box 名称列表（不得
  抛未捕获异常）。
- 对一个 200+ 节点、10+ box 的合成网络做概览输出的 token/字符数采样对比：概览模式
  应比全展开模式显著更短（上游定性声称"省 token"，验收时应有可复现的定量对比脚本
  或测试断言长度比例，而非仅凭观感）。

## 3. Plan 模式 DAG 图

### 3.1 用户价值

复杂任务（例如"重建整条地形生成管线"）如果让 AI 直接摸黑执行，容易中途卡住、漏步骤、
或者改错已有节点。Plan 模式先让 AI 做只读调研 + 澄清问题，再产出一份带依赖关系、
风险等级、预估操作数的结构化计划，用户在**执行前**就能看到一张"步骤如何依赖/并行"的
流程图并确认，把"黑盒执行"变成"先审查蓝图再放行"。DAG 可视化是这份计划能不能被
非技术用户快速审阅的关键——纯文字的步骤列表很难让人一眼看出"第 5 步卡住会不会
影响第 8 步"。

### 3.2 实际行为（上游）

- 三个 Plan 工具（`README.md:203-209`）：`create_plan`（创建含 phases/steps/
  dependencies/risk/DAG 的计划，以交互卡片展示供确认）、`update_plan_step`
  （更新某步状态与结果摘要）、`ask_question`（规划阶段向用户提问，带选项与推荐）。
- 三阶段工作流（`README.md:423-431`）：Deep Research（只读调研）→ Clarify
  Requirements（`ask_question` 交互澄清）→ Structured Plan（产出 phases/steps/
  dependencies/risk/预估操作数的工程级计划）。
- 数据模型 `Kazama-Suichiku/Houdini-Agent:houdini_agent/utils/plan_manager.py`
  （commit `5439334b60769f0b0ddb07bb0688571355cdc9f1` 引用，约第 1-56 行 docstring
  即完整 JSON Schema）：顶层含 `plan_id`/`session_id`/`title`/`overview`/
  `complexity`/`estimated_total_operations`/`phases`/`status`/**`architecture`**
  （`{"nodes": [...], "connections": [...], "groups": [...]}`，正是 DAG 渲染数据
  源）/`steps`（每步含 `id`/`depends_on`/`risk`/`fallback`/`status` 等）。
  持久化路径 `cache/plans/plan_{session_id}.json`
  （README.md:243, README.md:431），一个 session 一个 active plan，重复创建自动
  归档旧 plan。
- QML 渲染组件 `PlanCard.qml`/`PlanDag.qml`/`PlanStreamBlock.qml`
  （`README.md:278`，仅通过目录树与文件名确认存在，未逐行拉取 `.qml` 源码）。
  README 变更日志中两条直接证据：
  - v1.2.9（`README.md:631`）—— "Plan DAG fix"：移除了此前 DAG 容器
    `setFixedHeight(400px)` 的高度上限，使架构图不再被裁切，说明 DAG 渲染先于
    v1.2.9 就已存在，此条只是修 UI bug。
  - v1.2.5（`README.md:635`）—— README 改版明确写出 "interactive PlanViewer with
    DAG flow diagram" 作为既有能力的文档化。
  - v1.3.0（`README.md:630`）—— **auto-resume 机制**：当 AI 在 plan 未完成时
    提前输出纯文本终止回复，系统在 `agent_loop_stream` 里注入
    `on_plan_incomplete` 回调，强行拼一条"继续执行"的 resume 消息（带最新
    `update_plan_step` 进度，如"3/10 steps completed"），最多重试 3 次防止死循环。
    这是 DAG 之外、Plan 模式工程化成熟度的核心佐证（README 把它与 DAG 列在同一
    功能簇下，二者共同构成"结构化计划能被执行到底"的闭环）。

### 3.3 架构 / 依赖

- 数据层（`plan_manager.py`）纯 stdlib（`json`/`uuid`/`datetime`/`pathlib`），无
  第三方依赖，文件系统持久化，无网络调用。
- 渲染层依赖 QML/Qt Quick（上游 v2.0 起的前端技术栈），`PlanDag.qml` 消费
  `architecture.nodes`/`architecture.connections`/`architecture.groups` 画图。

### 3.4 可移植边界

- **数据模型 100% 可移植**（纯 JSON schema + stdlib CRUD），与 UI 技术栈无关。
- **渲染实现不可直接移植**：上游是 QML 组件，本仓库前端是 PySide 自绘 widget
  （`QtWidgets.QWidget` + `QPainter`），架构不同，需要重新实现渲染逻辑，但数据契约
  （`architecture: {nodes, connections, groups}`）可以直接复用/对齐。
- auto-resume 回调机制（`on_plan_incomplete`）依赖上游自己的 `agent_loop_stream`
  编排结构，移植前需要先确认本仓库 agent loop 是否有等价的"流结束时检查计划完成度"
  钩子点。

### 3.5 安全 / 兼容性风险

- 低风险：Plan 本身是只读调研 + 数据持久化到本地 JSON 文件，不直接执行 mutating
  工具（执行阶段仍要经过正常的工具调用与风险分级）。
- 文件持久化到 `cache/plans/plan_{session_id}.json` 若 `session_id` 来自不可信
  输入且未做路径穿越校验，存在路径穿越风险——上游源码片段未展示 `_plan_path` 的
  校验细节；本仓库若移植应复用本仓库既有的 harness 路径校验约定
  （`CONTEXT.md` 中 "Node Path"/"File Path" 校验集合）而非照抄上游写法。

### 3.6 本仓库现状

**已有对等实现，且在质量把关上更严格**：

- `houdini_agent/utils/plan_manager.py`（本仓库）：`PlanManager` 类，CRUD 方法
  `create_plan`/`load_plan`/`update_step`/`confirm_plan`/`reject_plan`/
  `delete_plan`/`get_plan_for_context`，JSON schema（`title`/`overview`/
  `complexity`/`estimated_total_operations`/`phases`/`status`/`steps`/
  **`architecture`**）与上游**几乎逐字段一致**（同宗代码）。
- **本仓库独有、上游片段未展示的增量能力**：
  - `PlanQualityGate` + `PlanQualityError`
    （`houdini_agent/utils/plan_manager.py:83-90, 422`）：`create_plan` 在持久化
    前先跑质量门禁评分（`_quality_gate().evaluate(plan)`），不合格直接抛
    `PlanQualityError(diagnostics)` 阻止写入——即计划质量不达标时**拒绝创建**，
    而不是先落盘再事后检查。
  - `validate_plan_questions` / `normalize_plan_answers`
    （`houdini_agent/utils/plan_manager.py:22-82`）：对 `ask_question` 阶段的
    问题/答案结构做显式规范化与校验，上游 README 未描述对应的校验层。
  - `归档旧 plan` 的事务顺序本仓库做了错误恢复（`create_plan` 第 208-220 行左右）：
    先过质量门禁，再 rename 旧 plan 为归档，写新 plan 失败时把归档 rename 回去——
    比单纯"创建即覆盖"更安全。
  - DAG 渲染：`houdini_agent/ui/cursor_plan_widgets.py` 的 `PlanDAGWidget`
    （约第 70-130 行）是一个 **PySide `QPainter` 自绘 DAG 流程图组件**
    （`# PlanDAGWidget — QPainter 自绘 DAG 流程图`），而非 QML；
    `StreamingPlanCard._build_step_dag(steps)`（约第 1368-1398 行）在 plan 数据
    没有显式 `architecture` 字段时，**从 `steps[].depends_on` 自动推导出
    `{nodes, connections, groups}` 格式的 DAG 数据**作为回退——这是上游 README
    片段里没有提到的容错路径。
- 本仓库的 Plan 执行侧另有 `houdini_agent/core/plan_mixin.py`、
  `houdini_agent/utils/plan_runtime.py`，命名暗示存在独立的"计划运行时"模块，
  这部分未在本次研究范围内逐行核对是否包含等价的 auto-resume 机制（见 §Gaps）。

### 3.7 建议：拒绝整体移植 / 仅做针对性核对

本仓库的 Plan 数据模型与 DAG 可视化已经是**同宗且更严格**的实现（质量门禁、
depends_on 自动回退生成 DAG 都是上游公开文档未提及的加固）。不建议移植上游的
QML `PlanDag.qml`（架构不匹配，本仓库是 PySide）。唯一值得确认的具体点：上游
v1.3.0 的 **auto-resume**（`on_plan_incomplete`，AI 提前结束但计划未完成时强制
续跑，最多 3 次）——需要专项核实本仓库 `plan_runtime.py`/`plan_mixin.py` 是否已有
等价机制；若没有，这是唯一值得单独引入的子功能（不依赖 DAG 本身）。

### 3.8 可验证验收标准

- （确认现状，非引入新代码）对本仓库 `PlanManager.create_plan` 传入一个
  `steps[].depends_on` 相互成环（A→B→A）的计划：应有明确诊断/拒绝行为（质量门禁
  `_quality_gate().evaluate` 应覆盖环检测——若当前未覆盖，这是一个可报告的质量
  门禁缺口，而非本次四项范围内的"移植"项，建议作为后续独立 ticket）。
- 若决定移植 auto-resume：构造一个测试，使 AI 流式响应在 plan 仍有
  `status == "pending"` 的步骤时返回纯文本结束；断言系统注入了一条包含
  "剩余步骤数" 的续跑用户消息，且同一 session 内该注入最多发生 3 次后不再重试
  （验证"max 3 resume attempts"上限，防止死循环）。
- DAG 渲染侧（现状验证）：对一个 10 步、3 层依赖深度的 plan 调用
  `PlanDAGWidget`/`_build_step_dag`，断言生成的 `connections` 数量与
  `steps[].depends_on` 总条目数一致，且每个 `connections[i].from` 都能在
  `nodes[].id` 中找到。

## 4. 六种模型 Provider

### 4.1 用户价值

不同用户/机构能拿到的 API Key 不同（有人只有 DeepSeek 国内直连额度，有人只有
聚合中转如 Duojie/OpenRouter），多 Provider 支持让同一套 Agent 能力不被单一厂商
锁死，也让用户按价格/延迟/能力自由切换模型而不用换工具。

### 4.2 实际行为（上游）

- README "Supported AI Providers" 表（`README.md:35-44`）列出 6 个用户可见
  Provider：**DeepSeek**（`deepseek-v4-flash`/`deepseek-v4-pro`/
  `deepseek-v4-flash-vision-exp`，V4 系列显式 `thinking`/`reasoning_effort`
  参数，1M 上下文，旧 `deepseek-chat`/`deepseek-reasoner` 已于 2026/07/24 退役）、
  **GLM (Zhipu AI)**（`glm-4.7`，国内稳定，原生推理与工具调用）、**OpenAI**
  （`gpt-5.6-sol`/`terra`/`luna`/`gpt-5.5`，1M 上下文）、**Duojie**（relay 中转，
  11 个模型含 Claude/GPT/Grok/GLM，模型清单**由 relay 的 `/v1/models` 实时发现**）、
  **OpenRouter**（17 个模型，单一 Key 访问全主流厂商）、**Custom**（用户自填
  URL/Key/模型名/上下文上限/vision/Function Calling，兼容任意 OpenAI 协议端点，如
  LM Studio、vLLM）。
- 引入时间线（提交证据）：Duojie 对应上游 v1.2.2（`README.md:638`，Anthropic
  Messages 协议适配层），OpenRouter 对应 v1.4.0（`README.md:625`，"New OpenRouter
  provider: 16 models ... via single API key"），Custom 对应 v1.5.0
  （`README.md:622`）。
- `houdini_agent/utils/model_catalog.py`（见第 5 节）的 `STATIC_MODELS` dict
  实际上注册了 **8 个 provider key**：`duojie`/`openrouter`/`openai`/`codex`/
  `claude_sub`/`deepseek`/`glm`/`custom`——`codex`（本机 ChatGPT 订阅 + Codex
  OAuth）与 `claude_sub`（本机 Claude Code OAuth 订阅）是 README 表格里**未出现**
  的两个订阅型 Provider，源码注释明确写 "实际列表由 subscription 模块单独刷新，
  这里只做兜底"——即 README 的"六种 Provider"只是**用户可见文档里**的六个，源码
  实际可处理的 Provider 身份有 8 个。

### 4.3 架构 / 依赖

- 每个 Provider 对应：(a) `STATIC_MODELS`/`STATIC_CONTEXT`/`STATIC_VISION`/
  `STATIC_FEATURES` 里的一条静态兜底记录、(b) 协议适配分支（OpenAI 协议 vs
  Anthropic Messages 协议——Duojie 的部分模型走 Anthropic 协议转换层，见
  README v1.2.2 条目）、(c) 可选的 `PROVIDER_SOURCES` 动态刷取注册
  （仅 duojie/openrouter/openai/deepseek/glm 五个在注册表内，见第 5 节）。
- 无单独"Provider 插件"抽象类/接口描述——从 `model_catalog.py` 看，Provider
  身份更多是字符串 key 驱动的 dict 分发，而非面向对象的 Provider 子类层级。

### 4.4 可移植边界

- Provider **身份清单本身不可移植**（DeepSeek/GLM/OpenAI/Duojie/OpenRouter 是
  上游维护者自己的商业关系/中转账号选择，`Duojie` 更是上游作者自营或合作的中转
  服务，不具备通用性，直接照搬没有意义）。
- 可移植的是**架构模式**：静态兜底表 + 可选动态刷取注册表 + 统一的
  `merged_models(provider)` 合并函数 + 按 provider 分类的 key 解析顺序
  （环境变量 → ini 配置）。这套模式与具体 Provider 身份解耦，可以直接套用本仓库
  现有的 Provider 集合（DeepSeek/Kimi Coding/SiliconFlow/OF3D/Custom）。

### 4.5 安全 / 兼容性风险

- API Key 解析顺序（环境变量优先于 ini 配置，见第 5 节 `resolve_api_key`）与
  本仓库现有 `config/houdini_ai.ini` 约定需核对字段名是否冲突。
- Custom Provider（用户自填任意 OpenAI 兼容端点）意味着信任边界完全交给用户
  输入的 URL——上游没有描述对该 URL 做 SSRF/内网地址防护；若本仓库已有的 Custom
  Provider（`houdini_agent/ui/header.py:627` 起的 `_CustomProviderDialog`）同样
  缺少此类校验，这是一个独立于本次四项范围、但值得旁证的风险点（本次仅作记录，
  不展开修复方案）。

### 4.6 本仓库现状

**后端分支数量上更多，但用户可见 Provider 清单与上游不同，也更少**：

- `houdini_agent/ui/header.py:36-50` 的 `provider_combo` 实际启用项：
  `DeepSeek`、`Kimi Coding`、`SiliconFlow`、`OF3D`、`Custom`（5 个）；
  `GLM`/`OpenAI`/`Duojie`/`OpenRouter` 四行在源码里以 `#` **注释掉**，并非删除
  （`# self.provider_combo.addItem("OpenAI", 'openai')` 等，header.py:41-44），
  说明历史上这四个 Provider 曾经可用，是后续被本仓库组织定制禁用，而非从未实现。
- `houdini_agent/utils/ai_client.py` 中仍保留 `deepseek`/`glm`/`ollama`/
  `duojie`/`openrouter`/`kimi_coding`/`siliconflow`/`of3d`/`custom` 共 9 个
  provider 分支判断（约 24 处 `provider ==`/`provider in (...)` 命中，含
  `ai_client.py:3397-3415` 的集中分支、`3967`/`4357` 的 OpenRouter 专属分支、
  `5012`/`5916` 的 reasoning-model 判断），即**后端协议适配层并未随 UI 隐藏而
  删除**，只是被 header.py 的组合框屏蔽掉了用户入口。
- 本仓库没有 `model_catalog.py` 这样的统一 Provider 注册表——`STATIC_MODELS`
  式的静态表直接写死在 `header.py:67` 起的 `self._model_map` dict 里
  （例如 `'deepseek': ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat',
  'deepseek-reasoner']`，仍保留已被上游标记"2026/07/24 弃用"的
  `deepseek-chat`/`deepseek-reasoner` 两个旧模型名，未同步上游的弃用节奏）。

### 4.7 建议：拒绝（照搬具体 Provider 清单）/ 可选改造（统一注册表模式）

不建议直接采用上游"六种 Provider"的具体清单（Duojie/OpenRouter 等是上游自己的
商业选择，与本仓库已确立的 SiliconFlow/Kimi Coding/OF3D 组织定制路线冲突，贸然
合并会制造两套并存的 Provider 身份体系）。若要改造，建议仅借鉴**架构模式**：
把 `header.py:_model_map` 的死代码表格重构成类似 `model_catalog.py` 的
"静态表 + provider 注册表" 分离结构，为第 5 节的模型目录自动刷新打基础——但这应
作为"自动刷新"落地的前置重构，而不是单独为了"凑六个 Provider"去做。

### 4.8 可验证验收标准

- 现状基线测试：对 `header.py` 当前 5 个启用 Provider + `ai_client.py` 里存在
  但 UI 隐藏的 4 个 Provider 分支（glm/openai/duojie/openrouter）逐一跑一次
  `ai_client.py` 对应分支的单元测试（mock HTTP 响应），确认这些"隐藏"分支目前
  仍是可工作代码而非已腐化的死代码——这是决定"要不要在 UI 里重新暴露"之前必须
  先验证的前提。
- 若决定重构为统一注册表：新结构下，`header.py` 现有 5 个 Provider 的
  `_model_map`/上下文上限/vision 判定必须与重构前逐条比对一致（快照测试），
  不允许在重构过程中静默改变现有 5 个 Provider 的行为。

## 5. 模型目录自动刷新

### 5.1 用户价值

模型型号迭代很快（本文观察窗口内，上游自己的静态表就因为"2026-11 对齐
`/v1/models` 实测"而移除了已下线的 `kimi-k3`/`deepseek-v4-pro`/
`deepseek-v4.1-flash` 并新增 `glm-5.3-flashx`/`kiro-auto`，见
`model_catalog.py` 顶部注释）。如果模型清单永远靠人工改代码+发版才能更新，用户会
长期看到"选了一个已经下线的模型导致 400 错误"或者"看不到刚发布的新模型"。自动
刷新把这个维护负担从"改代码" 降为"后台悄悄打一次 API"。

### 5.2 实际行为（上游）

引入提交：`2826f758752a712031d49da78c529dcb6cc0b2ed`（2026-11-06T07:46:56Z，
message: "feat(models): 模型目录自动拉新（/v1/models + 缓存 + Provider 刷新入口）"）。
模块：`Kazama-Suichiku/Houdini-Agent:houdini_agent/utils/model_catalog.py`
（540 行，纯 stdlib：`json`/`os`/`re`/`threading`/`time`/`urllib.request`，无
`requests` 依赖）。

- **TTL 与缓存**：`MODEL_CATALOG_TTL_SECONDS = 6 * 3600`（6 小时），缓存文件
  `<cache_dir>/model_catalog.json`（`default_cache_path()`），`CACHE_VERSION = 1`；
  `save_cache` 用"先写 `.tmp` 再 `os.replace`"原子落盘，`load_cache` 对
  `OSError`/`ValueError`/结构不符一律安全返回空结构，不抛异常。
- **Provider 注册表**（`PROVIDER_SOURCES`，仅 5 个做网络拉取）：
  `duojie`（`https://api.duojie.games/v1/models`，需 Key，`merge` 策略）、
  `openrouter`（`https://openrouter.ai/api/v1/models`，无需 Key，`enrich` 策略）、
  `openai`（`https://api.openai.com/v1/models`，需 Key，`merge`）、`deepseek`
  （`https://api.deepseek.com/v1/models`，需 Key，`merge`）、`glm`
  （`https://open.bigmodel.cn/api/paas/v4/models`，需 Key，`merge`）。`codex`/
  `claude_sub`/`custom` 不在注册表内，始终用静态表。
- **过滤规则** `is_chat_model(model_id, supported_endpoint_types)`：
  (1) 若提供了 `supported_endpoint_types`，必须与 `_CHAT_ENDPOINTS =
  {openai, anthropic, gemini, openai-response, openai-response-compact}` 有交集；
  (2) 无论如何按"词边界 + 忽略大小写"正则排除非对话家族
  （`gpt-image`/`dall-e`/`flux`/`stable-diffusion`/`sdxl`/`whisper`/`tts`/
  `embedding`/`embed`/`rerank`/`moderation`/`ocr`/`sora`/`veo`/`kling`/
  `midjourney`/`video`）；(3) 排除 OpenRouter 变体后缀 `:batch`/`:thinking`
  （保留 `:free`）；(4) 空 id 返回 False。
- **两种合并策略**：
  - `merge`（duojie/openai/deepseek/glm）：存活的静态项保持原顺序在前，新发现
    的模型按字母序追加在后，已下线的静态项被剔除（`merged_models()` 函数，约
    第 365-380 行）。
  - `enrich`（openrouter）：永远返回人工精挑的静态顺序（不直接铺开 455 条 live
    数据），live 数据只用于补 `context_length`/`architecture.input_modalities`
    等元数据。
- **网络失败处理**：`fetch_provider_models` 对缺 Key、非 200、JSON 解析失败、
  `data` 为空、未知 provider 一律 `except Exception` 捕获后返回 `None`，**绝不
  抛异常**——调用方（`refresh_provider`/`refresh_all`）据此判断"这次刷新是否
  成功"，失败不影响其它 Provider（`refresh_all` 逐个 try/except）。
- **Key 解析**（`resolve_api_key`）：环境变量优先（`_ENV_KEY_VARS`，如
  `DUOJIE_API_KEY`/`OPENAI_API_KEY`/`DEEPSEEK_API_KEY`/`GLM_API_KEY`/
  `ZHIPU_API_KEY`/`OPENROUTER_API_KEY`），否则回退 `config/houdini_ai.ini`
  对应字段。
- **可测试性钩子**：模块级 `_TRANSPORT`（`set_transport`/`reset_transport`），
  测试可注入假传输函数替代 `urllib.request.urlopen`，import 时不联网、不落盘
  （见 `tests/test_model_catalog.py` 开头文档字符串："全程无网络、无真实 config
  写入"）；该测试文件存在且以 38 个用例覆盖
  "过滤规则、静态表、transport 注入拉取 + 缓存、merge/enrich 合并、元数据回退、
  TTL、key 解析"（引入提交 message 自述为 38 例）。
- **UI 接入**：`controller.py` 的 `@Slot() refreshModels()` →
  `_start_models_refresh(quiet=False)`；`ProviderManager.qml` 的"刷新模型"
  按钮 (`Pill`) 绑定 `controller.refreshModels()`，`modelsRefreshing` 状态位
  驱动按钮文案在"刷新模型"/"刷新中…"之间切换并在刷新期间 disable；启动时的
  "stale cache 静默刷新"走同一内部方法但 `quiet=True`（README.md:46：
  "A stale cache is refreshed silently in the background on startup"，与
  `_start_models_refresh(quiet)` 的参数设计互相印证）。
- `provider_model_ids(provider, cache_path)` 是 `merged_models` 的记忆化版本
  （按 `(provider, 缓存文件路径, mtime_ns)` 做 key），供 QML 菜单频繁调用时不
  反复读盘，内建简单的 LRU 式上限（`_PROVIDER_IDS_CACHE` 超过 64 项清空重建）。

### 5.3 架构 / 依赖

- 纯 stdlib：`urllib.request`（不引入 `requests`，与仓库"不新增网络库依赖"的
  克制态度一致）、`threading.Lock`（`_CACHE_LOCK`，允许后台线程并发调 fetch
  而不互相覆盖缓存文件）、`json`、`re`、`time`。
- 分层清晰：常量/静态表 → provider 注册表 → 过滤规则（纯函数）→ key 解析（纯
  函数）→ 磁盘缓存（原子写）→ 网络拉取（单一入口 `fetch_provider_models`）→
  合并策略（`merged_models`）→ 记忆化包装（`provider_model_ids`）→ 元数据回退
  （缓存 meta → 静态表 → 家族推断三级回退，模块末尾，本次未逐行展开）。
  每一层都可独立单元测试（测试文件自述离线、无副作用）。

### 5.4 可移植边界

- **高度可移植**：模块本身零第三方依赖，`_TRANSPORT` 钩子使其天然可测试，
  不依赖上游的 QML/standalone 架构，也不依赖 Meshy/Plan 等上游专属子系统。
  移植的主要工作量在于：(a) 把 `PROVIDER_SOURCES` 的 URL/key 字段换成本仓库
  实际使用的 5 个 Provider（DeepSeek/Kimi Coding/SiliconFlow/OF3D/Custom——
  需要先确认 Kimi Coding/SiliconFlow/OF3D 是否真的提供 OpenAI 兼容的
  `/v1/models` 端点，这是移植前必须验证的前提，本次研究未逐一核实这三个
  org-specific 端点的 `/v1/models` 可用性，记为 Gap）；(b) 把 `STATIC_MODELS`/
  `STATIC_CONTEXT`/`STATIC_VISION`/`STATIC_FEATURES` 的内容替换成本仓库
  `header.py:_model_map`/相关常量里现有的数据（迁移而非新造）；(c) UI 接入点
  需要对齐本仓库是 PySide（`header.py` 的 `QComboBox`）而非 QML——"刷新模型"
  按钮与 `modelsRefreshing` 状态位的等价物需要用 PySide 信号/槽重新实现，
  但底层 `model_catalog.py` 模块本身不需要改。

### 5.5 安全 / 兼容性风险

- **网络请求目标可控性**：`PROVIDER_SOURCES["models_url"]` 是硬编码的厂商官方
  端点（非用户可控），风险等同于现有的直连 API 调用，不新增攻击面。
- **凭证泄露面**：`resolve_api_key` 读取环境变量/ini 配置后拼进
  `Authorization: Bearer` 头——与现有调用模型 API 的凭证使用方式一致，不是新
  增风险点，但移植时要确保 `_debug()` 的调试打印（`HAGENT_MODEL_CATALOG_DEBUG`
  环境变量开启时）不会把 Key 打进日志（上游代码里 `_debug` 打印的是状态文案
  如"缺少 API key，跳过拉取"，未发现打印 Key 本身的调用点，但移植后应补一条
  测试断言"debug 日志不包含 Authorization 头内容"）。
- **缓存文件信任边界**：`load_cache` 对结构不符的缓存文件安全降级为空结构，
  不会因为缓存文件被篡改/损坏而导致代码路径崩溃或执行任意内容（纯数据，
  JSON 反序列化后只读取字符串/数字字段拼模型列表，不 `eval`/不动态 import）。
- **兼容性**：`is_chat_model` 的非对话家族排除列表是硬编码英文关键词列表
  （`gpt-image`/`whisper`/...），若本仓库要接入的 Provider 模型命名习惯不同
  （例如中文厂商可能用拼音或别的命名规则标记图片模型），直接套用这份排除表
  可能漏判——移植时需要针对本仓库实际 Provider 的模型命名重新验证这份正则，
  不能假定上游的家族关键词覆盖面同样适用。

### 5.6 本仓库现状

**完全没有等价能力**——`grep` 全仓库 `model_catalog|MODEL_CATALOG|
refresh_provider|PROVIDER_SOURCES` **零命中**。本仓库的模型列表机制是：

- `houdini_agent/ui/header.py:67-70` 起的 `self._model_map`：纯 Python dict
  字面量，模型清单完全硬编码，没有任何运行时刷新路径。
- 已确认该硬编码表仍含有上游已标记弃用的旧模型名
  （`'deepseek-chat', 'deepseek-reasoner'`，`header.py` 附近），印证"纯静态表
  没有自动淘汰机制"这一具体负面后果已经在本仓库真实发生，而不只是理论风险。
- 没有磁盘缓存、没有 TTL、没有"刷新模型"按钮、没有后台静默刷新、没有
  merge/enrich 策略、没有 `is_chat_model` 过滤、没有可注入 transport 的测试
  钩子。

### 5.7 建议：采用（高优先级）

这是四项中**唯一值得直接采用**的能力：收益明确（解决已经在本仓库真实发生的
"静态表模型名过期"问题）、实现成本低（纯 stdlib、无新依赖、模块本身可整体
迁移）、风险低（§5.5 已逐条核实无新增攻击面）、且有完整的离线测试样板可参考
（上游 38 例测试覆盖面可作为移植后测试清单的起点）。移植顺序建议：先把
`header.py:_model_map` 等静态数据迁移进等价的 `STATIC_MODELS` 结构（不改变
现有行为的重构），再接入 `PROVIDER_SOURCES` + 刷新入口（新增行为），分两步走
以便每一步都可独立回归验证。

### 5.8 可验证验收标准

- **离线安全性**：在没有网络、没有任何 API Key 的环境下调用移植后模块的
  `refresh_all()`/`refresh_provider()`：必须返回 `None`/空结果而不抛异常，且
  `merged_models(provider)` 必须原样返回静态表（不因刷新失败而清空或损坏
  已有模型列表）。
- **TTL 行为**：构造一个 `fetched_at` 为 7 小时前的缓存文件，断言"是否需要
  刷新"的判定（若移植了对应判定函数）返回 True；5 小时前的缓存判定返回 False
  （对齐"TTL 6 小时"的具体数值）。
- **过滤正确性**：对一个混合了 ≥1 个已知非对话家族 ID（如含 `embedding`/
  `whisper` 子串）和 ≥1 个正常对话模型 ID 的模拟 `/v1/models` 响应调用过滤
  函数：断言非对话 ID 被剔除、对话 ID 被保留，且 `glm-5.3-flash` 这类"含 flash
  但不应被当非对话模型排除"的边界用例必须保留（对齐上游注释里专门提到的
  "flash 不在排除列表"这条已验证过的边界条件）。
- **合并策略**：模拟一次 live 拉取，其中包含一个"已在静态表但对应 live 列表
  缺失"的模型 ID（已下线）与一个"live 独有、静态表没有"的模型 ID（新发布）：
  断言 `merged_models` 的结果里已下线 ID 被剔除、新 ID 被追加在剩余静态项
  之后且保持字母序。
- **并发安全**：并发调用两次 `refresh_provider`（同一 provider，不同线程）：
  断言缓存文件不损坏（能被 `load_cache` 正常解析）、无死锁、无写入过程中
  读到半截 JSON 的竞态（验证 `_CACHE_LOCK` + 原子 `os.replace` 写入的组合
  确实生效）。
- **UI 接入**（若同步移植 PySide 侧"刷新模型"入口）：点击刷新按钮后按钮必须
  立即进入不可重复点击状态（等价 `modelsRefreshing` 语义），刷新完成（无论
  成功与否）后必须恢复可点击，且同一时间只允许一次刷新在途（重入安全）。

## Gaps / Follow-ups

- 未逐行拉取上游 `PlanDag.qml`/`PlanCard.qml` 源码（架构不匹配，判定逐行比较
  价值有限，已在 §3 用 README + `plan_manager.py` 数据契约 + 本仓库 PySide
  实现做了等效比较；如需彻底确认 QML 渲染算法细节，应作为单独的小范围跟进）。
- 上游 `codex`/`claude_sub` 订阅型 Provider 的刷新实现模块路径未定位（题目
  四项范围未要求，仅在 §4.2/§5.2 作为背景事实记录）。
- `houdini_agent/core/plan_mixin.py`/`houdini_agent/utils/plan_runtime.py`
  是否已包含与上游 v1.3.0 等价的 auto-resume 机制，本次未逐行核对（已在
  §3.7 标注为后续专项核实项，不影响本文四项的主结论）。
- 本仓库 Kimi Coding/SiliconFlow/OF3D 三个组织定制 Provider 是否提供 OpenAI
  兼容的 `/v1/models` 端点，本次未逐一核实（已在 §5.4 标注为移植前必须验证
  的前提，不影响"该不该采用自动刷新架构"这一结论，但会影响具体落地范围）。
