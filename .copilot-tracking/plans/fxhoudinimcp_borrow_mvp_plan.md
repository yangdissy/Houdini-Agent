# 借鉴 fxhoudinimcp 的能力域扩展 — MVP 实现计划

> 来源：[healkeiser/fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp)（179 工具 / 22 类的外挂式 MCP Server）。
> 目标：在**不改动我们嵌入式架构**的前提下，借鉴对方的**能力域覆盖**，补齐我们最缺、ROI 最高的短板。
> 状态：**方案阶段，尚未改动任何代码。**
> 关联：能力扩展遵循 [skill_migration_plan.md](skill_migration_plan.md) 已确立的边界 —— **core=写/高频原子读，skill=组合/低频只读**。

---

## 借鉴分析报告（fxhoudinimcp 对比）

### 一句话总结

对方是 **179 工具 / 22 类的外挂式 MCP Server**，我们是 **48 工具的嵌入式 Agent**。架构路线不同（不用偷架构），但**具体工具都是在调 `hou.*`，可以移植**。

### 架构差异（不用偷架构）

| | 他们 (fxhoudinimcp) | 我们 (Houdini-Agent) |
|---|---|---|
| 形态 | 独立 MCP Server + Houdini 插件（HTTP 8100） | 直接跑在 Houdini 内的嵌入式 Agent |
| 客户端 | Claude Desktop / Cursor 等外部 AI | 内置 UI，自带 AI client |
| 传输 | MCP 协议 · stdio + bridge.py（异步 HTTP） | 进程内直连，无网络层 |
| 线程安全 | `hdefereval.executeInMainThreadWithResult()` | Qt 信号 `BlockingQueuedConnection` + Queue，语义等价且更完整（见下节） |

结论：**架构不偷**（我们嵌入式更快、单端安装）；**工具/能力域可借鉴**（最终都落到 `hou.*`）。

### 我们已有 vs 他们独有

我们 48 个工具集中在：节点 CRUD、参数、SOP 几何、网络布局、wrangle、执行(python/shell)、文档检索、记忆、todo、skill、性能分析、视口捕获。

对方按类别的覆盖（179 工具 / 22 类）与我们的缺口对照：

| 类别 | 他们工具数 | 我们的现状 | 缺口 |
|---|---|---|---|
| Graph Intelligence | 4 | 有 `verify_network` / `validate_node_network` 等 | 基本覆盖 |
| Documentation（Houdini 自带手册） | 2 | 靠手动维护 `Doc/*.txt` + `search_local_doc` | ⭐ **缺版本精确的自带手册源** |
| Scene Management | 7 | 有 `save_hip` / `get_scene_snapshot` 等 | 基本覆盖 |
| Node Operations | 17 | 有 `create_*` / `connect_*` / `delete_node` 等 | 覆盖 |
| Parameters | 11 | 有 `set_node_parameter` / `set_parameter_expression` 等 | 覆盖 |
| Geometry (SOPs) | 12 | 有 `get_geometry_summary` + 多个只读分析 skill | 覆盖 |
| LOPs/USD | 18 | 只读侧已有 `inspect_lop_stage.py` skill | 只读已覆盖，**写侧缺** |
| DOPs | 8 | 无专用工具 | 低频，MVP 不碰 |
| PDG/TOPs | 10 | 有 `analyze_cook_performance.py` skill（性能侧） | 部分覆盖 |
| Materials | 5 | 只读侧已有 `inspect_material_assignments.py` skill | 只读已覆盖 |
| HDAs | 10 | 无专用工具 | 低频，MVP 不碰 |
| Animation | 9 | 有关键帧/表达式相关 core 工具 | 部分覆盖 |
| Rendering | 9 | 有 `capture_viewport` | 部分覆盖 |
| VEX | 5 | 有 `create_wrangle_node` | 覆盖 |
| Code Execution | 4 | 有 `execute_python` / `execute_shell` | 覆盖 |
| Viewport/UI | 13 | 有 `capture_viewport` / `read_selection` 等 | 部分覆盖 |
| Scene Context | 8 | 有 `inspect_scene_context.py` skill + 多个只读工具 | 覆盖 |
| **Workflows（一键搭建）** | 8 | **完全没有等价物** | ⭐ **真实缺口** |
| CHOPs | 4 | 无 | 低频，MVP 不碰 |
| Cache | 4 | 只读侧已有 `cache_node_report.py` skill | 只读已覆盖 |
| Takes | 4 | 无 | 低频，MVP 不碰 |

> 复核 skill 目录后修正初版误判：USD / Materials / Cache / Cook 性能的**只读侧我们其实已用 skill 覆盖**。真正缺口收窄为两个（下节）。

### 真实缺口（收窄为两个）

1. **文档检索源**：我们靠手动维护 `Doc/*.txt`，会过时、版本对不上；对方直接检索 Houdini **ship 的离线手册**（零维护、版本精确）。→ MVP-1
2. **一键搭建（写侧 workflow）**：对方 one-call Pyro/RBD/FLIP/Vellum，我们完全没有。→ MVP-2

### 明确不偷

- ❌ MCP 协议 / bridge.py / HTTP 8100 —— 我们嵌入式直连，更快无需网络层。
- ❌ FastMCP、resources、prompts 的 MCP 封装 —— 与我们 UI + ai_client 架构不兼容。
- ❌ 独立进程 + Houdini 插件双端安装 —— 我们单端即可。
- ❌ 一次性移植 179 工具 —— 绝大多数是我们已有工具的重复或低频域。

### 第二次全类复核（2026-07-11，Workflow 收尾后 · "还有什么可偷"）

**结论：读过对方全部 22 类源码后，真正还值得偷、且能低成本以只读 skill 移植的只剩 1 项（已落地）。其余全部已覆盖或低频不值得。**

| 类别 | 对方独有点 | 我们对照 | 决策 |
|---|---|---|---|
| Scene Context · `get_node_errors_detailed` | 单节点报错时**扫描 file 类参数、指出哪个路径指向缺失文件** | `verify_network`/`validate_network_contract` 只做整网列错，**缺单点"可疑文件参数"定位** | ✅ **已偷** → skill `explain_node_error.py` |
| Scene Context · `get_network_overview` / `get_cook_chain` / `get_scene_summary` / `explain_node` | ASCII 网络流 / cook 链 / 场景概览 / 单节点解释 | 已有 `inspect_scene_context` + `trace_node_dependencies` + `verify_network` 等价覆盖 | ❌ 不偷（已覆盖） |
| Graph Intelligence · `build_network` / `verify_network` / `get_node_card` / `find_expensive_nodes` | 原子建网 / 核查 / 节点文档卡 / cook profiling | 已有 `create_nodes_batch` + `verify_network` + `get_node_card` skill + `analyze_cook_performance` | ❌ 不偷（已覆盖） |
| VEX · `validate_vex` | cook wrangle 收集编译错误 | 已有 `create_wrangle_node` + `verify_network`（cook 后浮现错误） | ❌ 不偷（已覆盖） |
| DOPs / CHOPs / Takes / HDAs / PDG 写 | 各自 4~10 工具 | 低频域 | ❌ 不偷（低频，YAGNI） |
| Materials / Cache / USD 只读 | list/inspect | 已有 `inspect_material_assignments` / `cache_node_report` / `inspect_lop_stage` | ❌ 不偷（已覆盖） |

> 说明：对方 `get_node_errors_detailed` 的整网扫描能力我们已由 `validate_network_contract` 覆盖，唯独**"报错节点的文件参数指向缺失文件"这一聚焦排障点**是我们的空白 —— 只偷这一点，落成单节点只读 skill，不重复造整网诊断轮子。

### 主线程安全机制核对（已完成研究 2026-07-11）

**结论：我们已有等价机制，且比 fxhoudinimcp 更完整。无需借鉴，但新增 skill 时必须遵守既有约定。**

#### 对方的做法

fxhoudinimcp 在 Houdini 插件端用 `hdefereval.executeInMainThreadWithResult()` 把所有 `hou.*` 调用弹回主线程执行（因为它的命令来自 hwebserver 的 HTTP 请求线程）。

#### 我们的做法（Qt 信号版，语义等价）

Agent 主循环跑在**后台线程**（[ai_tab.py](../../houdini_agent/ui/ai_tab.py) `_run_agent` 由 `threading.Thread(daemon=True)` 启动）。工具执行的线程调度：

| 环节 | 实现 | 位置 |
|---|---|---|
| 后台→主线程派发 | `_executeToolRequest.emit()` + `QtCore.Qt.BlockingQueuedConnection` → 槽 `_on_execute_tool_main_thread` | ai_tab.py L278 / L1108 |
| 阻塞等待返回 | emit 阻塞后台线程直到主线程槽返回（等价 `executeInMainThreadWithResult` 的同步返回） | — |
| 回值通道 | `queue.Queue` + `threading.Lock`（一次只跑一个工具）+ 120s 超时防死锁 | L900 `_execute_tool_in_main_thread` |
| 后台白名单 | `BG_SAFE_TOOLS` 仅 4 个**明确不碰 `hou`** 的工具允许留后台直跑：`execute_shell` / `search_local_doc` / `list_skills` / `search_memory`；**其余全部强制主线程** | harness_policy_config.py L113 |
| 主线程断言 | 若槽意外不在主线程执行，打印 `[⚠️ THREAD SAFETY]` 警告 | L1127 |

**我们额外有、对方没有的保护**：cook 保护（Agent 期间切 Manual 模式防 cook 阻塞主线程死锁）、读前定向 cook 防 stale 数据、undo group 包裹、before/after 网络快照 diff。

> 注：repo memory `houdini_agent_startup_crash_fix.md` 那次崩溃是 **Qt widget 生命周期 / 延迟布局**问题（`singleShot` 回调对已销毁 widget 计算 sizeHint），**与本节的 `hou.*` 后台线程问题是两回事**，勿混淆。

#### 对本 MVP 两个 skill 的直接影响 ⭐

1. **`run_skill` 已被正确纳入主线程调度**：`run_skill` **不在** `BG_SAFE_TOOLS` 白名单 → 现有 skill（如 `inspect_lop_stage`）执行时已自动走 `_on_execute_tool_main_thread`，在主线程 `import hou`。**新增 skill 天然继承这一保护，无需任何额外线程代码。**

2. **MVP-1 `search_houdini_help`**：只读文本检索。
   - 若数据源是**纯文件读取（不 import hou）** → 理论上可像 `search_local_doc` 一样加入 `BG_SAFE_TOOLS` 后台跑（不阻塞 UI）。但它经由 `run_skill` 调用，而 `run_skill` 走主线程；**MVP 阶段保持走主线程即可**（只读文本快，不阻塞感知），不单独优化。
   - 若数据源需要 **HOM API（`hou.*`）** → 必须走主线程，现状已满足。

3. **MVP-2 `setup_pyro_sim`（蓝图返回式）**：skill 内**不 import hou、不建节点**，只返回纯 dict 配方 → **无任何线程安全顾虑**。实际写操作由 AI 调用现有 core 写工具（`create_nodes_batch` 等）完成，那些工具已在主线程 + undo group + cook 保护下执行。**这进一步印证蓝图式方案 (a) 的正确性**：既不破坏 harness 安全边界，也不碰线程安全边界。

**行动项**：本 MVP **无需新增任何线程安全代码**；只需保证两个新 skill 都通过 `run_skill` 调用（默认即是），并在 skill 内遵循"只读文本 / 返回蓝图，不在后台线程直接写 `hou`"。

---

## 0. 前置事实核对（已确认，非猜测）

- 我们现有 **48 个 core tool**（迁移方案 A 组后），定义在 [ai_client.py](../../houdini_agent/utils/ai_client.py) 的 `HOUDINI_TOOLS`。
- skill 目录 [houdini_agent/skills/](../../houdini_agent/skills/) 已有 **20 个 skill**，扔一个 `.py` 即自动加载，不占 function-calling 名额。
- **对方的"缺失域"我们其实已部分覆盖**（只读侧）：
  - LOPs/USD → 已有 `inspect_lop_stage.py`
  - Materials → 已有 `inspect_material_assignments.py`
  - Cache → 已有 `cache_node_report.py`
  - Cook/PDG 性能 → 已有 `analyze_cook_performance.py`
- **真正的缺口是两类**：
  1. **文档检索源**：我们靠手动维护的 `Doc/*.txt` + `search_local_doc`，会过时、版本对不上；对方直接检索 Houdini **ship 的离线手册**（零维护、版本精确）。
  2. **一键搭建（写侧 workflow）**：对方的 one-call Pyro/RBD/FLIP/Vellum setup，我们完全没有等价物。

---

## 1. MVP 范围界定（只做 2 件事）

按 ROI 排序，MVP **只落地两个最高价值项**，其余列入"后续可选"不做。

### MVP-1：Houdini 自带手册检索 skill —— `search_houdini_help` ⭐ 最高 ROI

对标对方 `search_help` + `get_help_page`。

- **形态**：新增 **1 个 skill**（`houdini_agent/skills/search_houdini_help.py`），**不新增 core tool**（低频、只读、组合式，符合 skill 边界）。
- **数据源**：Houdini 随附的离线帮助。嵌入式运行可直接读取，候选路径（实现时需先探测确认，见 R1）：
  - `$HFS/houdini/help/` 下的 `.zip`/纯文本内容，或
  - 通过 HOM `hou.qt`/help server 接口（若存在稳定 API），或
  - `$HH/help` 目录树。
- **能力**：
  - `search(query, top_k)`：全文关键词检索，返回命中页标题 + 路径 + 摘要。
  - `get_page(path)`：拉取指定帮助页的正文（纯文本化）。
  - 合并进单个 skill，用 `mode` 参数区分（`search` / `page`），避免拆两个 skill 增加 AI 漏调风险（沿用迁移方案 B2 的"成对合一"教训）。
- **与现有 `search_local_doc` 的关系**：
  - **不替换**、**先并存**。`search_local_doc` 保留（高频、部分自动注入上下文）。
  - 新 skill 作为**版本精确的兜底/补充源**，`get_houdini_node_doc` 的降级链可增加一环。
  - MVP 阶段**不动** `search_local_doc` 和 `Doc/*.txt`，避免牵动高频路径（外科手术式）。

### MVP-2：一键 workflow 搭建 skill —— ✅ Workflow 类已全覆盖

对标对方 Workflow 类（8 工具）。Pyro 验证通过后，已按同一蓝图模板扩展至 RBD/FLIP/Vellum 与 render config。**已落地 3 个 skill：**

| skill | 覆盖 | 状态 |
|---|---|---|
| `setup_pyro_sim.py` | Pyro（smoke/fire） | ✅ 已实现并自检 |
| `setup_dynamics_sim.py` | RBD / FLIP / Vellum（cloth/softbody/grain） | ✅ 已实现并自检 |
| `setup_render.py` | render config（Karma LOP 链 / Mantra ROP） | ✅ 已实现并自检 |
| ~~SOP chains~~ | —— | ❌ 有意跳过：`create_nodes_batch` 已覆盖，再包一层是冗余抽象（YAGNI） |

- **形态**：3 个纯蓝图 skill，均**不 `import hou`、不建节点**，只返回与 `create_nodes_batch` 1:1 对齐的蓝图 dict。
- **⚠️ 关键定性问题（需先决策，见 R2）**：这是**写操作**（创建节点/连线/设参）。
  - 现有 20 个 skill **全部是只读**；迁移方案明确"写操作留 core 受 harness 管控"。
  - **写 skill 是新范式**，必须先确认 harness 安全策略如何覆盖 skill 内部的写操作，否则会绕过 `HIGH_RISK_TOOLS` 审计 → 违反 agent-safety 指令。
  - **候选方案**（实现前二选一定档）：
    - (a) skill 内部**不直接建节点**，而是**返回一个节点搭建蓝图**（节点列表+连线+参数的结构化 dict），由 AI 用现有受管控的 `create_nodes_batch` / `connect_nodes` 执行 → **零安全边界改动，推荐**。
    - (b) skill 直接 `import hou` 建节点 → 需给 skill 执行路径接入 harness 审计，改动面大、风险高。
  - **推荐 (a)**：符合"最小权限"，写动作仍走 core 受管控工具，skill 只提供"配方"。

---

## 2. 分步实施顺序

### 阶段一：MVP-1 手册检索（先做，链路最干净）

1. **探测数据源**（R1）：在真实 Houdini 内跑一段探测脚本，确认离线帮助的实际存放位置与可解析格式（zip / html / 纯文本），落定后再写 skill。**未确认数据源前不写正式代码。**
2. **实现 skill** `search_houdini_help.py`：`SKILL_INFO`（`mode` / `query` / `path` / `top_k`）+ `run(...)`。参照 [inspect_lop_stage.py](../../houdini_agent/skills/inspect_lop_stage.py) 的结构与错误返回约定（`{"error": ...}`）。
3. **自检**：`list_skills` 能列出；`run_skill('search_houdini_help', {mode:'search', query:'attribwrangle'})` 返回命中；`mode:'page'` 能取正文。
4. **降级链接入**（可选，低风险）：在 `get_houdini_node_doc` 的降级路径文档里补一句"可用 search_houdini_help 兜底"，**仅改说明不改逻辑**。

### 阶段二：MVP-2 一键 workflow（✅ 已完成）

5. ✅ **定档安全方案**（R2）：采用 (a) 蓝图返回式。
6. ✅ **实现 skill**：`setup_pyro_sim.py`（Pyro）→ `setup_dynamics_sim.py`（RBD/FLIP/Vellum）→ `setup_render.py`（Karma/Mantra）。均 `run(...)` 返回蓝图 dict，**不直接改场景、不 import hou**。
7. **prompt 衔接**：蓝图 `execution.notes` 已内嵌执行引导（用 `create_nodes_batch` 落地、先 `dry_run=True`、失败用 `search_node_types`/`get_parameter_schema` 兜底）；无需改 system prompt。
8. ✅ **自检**：三个 skill 均通过 `list_skills` 列出，各仿真/渲染类型返回合法蓝图，非法参数（sim_type/renderer/resolution/空 source）均被拦截。

> ⚠️ 遗留验证项：solver/render 节点名（`rbdbulletsolver`/`flipsolver`/`vellumsolver`/`karmarendersettings`/`usdrender_rop`/`ifd` 等）随 Houdini 版本可能变化，蓝图已引导先 `dry_run`；建议在真实 Houdini 内跑一遍确认节点名后微调默认参数。

---

## 3. 明确不做（YAGNI，避免范围蔓延）

- ❌ MCP 协议 / bridge / HTTP 传输层 —— 我们嵌入式直连，不需要。
- ❌ 一次性移植 179 个工具 —— 绝大多数是我们已有工具的重复或低频域。
- ❌ CHOPs / Takes / PDG 写操作类 —— 使用频率低，MVP 不碰。
- ❌ 重写 `search_local_doc` / 替换 `Doc/*.txt` —— 高频路径，MVP 阶段只并存不替换。
- ~~❌ RBD/FLIP/Vellum 一键搭建~~ —— ✅ 已按 Pyro 模板扩展完成（`setup_dynamics_sim.py`）。
- ❌ SOP chains 通用链搭建 skill —— `create_nodes_batch` 已完全覆盖，再包一层是冗余抽象。

---

## 4. 风险与注意事项

- **R1 — 手册数据源不确定**：Houdini 离线帮助的存放格式/路径随版本可能变化。**必须先在真实 Houdini 内探测确认**，不能假设路径。探测失败则该项降级为"仅在线兜底"或暂缓。
- **R2 — 写 skill 破坏安全边界**（最高风险）：写操作绕过 harness `HIGH_RISK_TOOLS` 审计违反 agent-safety 指令。**MVP-2 必须采用"蓝图返回 + core 工具执行"方案 (a)**，让写动作仍走受管控路径。若坚持 skill 内直接写，必须先设计 skill→harness 审计通道（超出 MVP 范围）。
- **R3 — 与 search_local_doc 职责重叠**：两个文档检索源可能让 AI 困惑该调哪个。MVP 通过 description 明确分工（`search_local_doc`=快/常用/自动注入，`search_houdini_help`=版本精确/深度兜底）。
- **R4 — 主线程安全**：skill 在 Houdini 内运行，若涉及 `hou.*` 且从后台线程调用需确认主线程保护（参考 repo memory `houdini_agent_startup_crash_fix.md`）。MVP-1 只读文本、MVP-2 只返回蓝图不碰 `hou` 写，风险低，但仍需核对现有 skill 执行线程。

---

## 5. 收益预估

- **MVP-1**：文档检索从"手动维护、会过时"升级为"Houdini 自带、版本精确、零维护"，且**零 core tool 占用**（纯 skill）。
- **MVP-2**：为 AI 提供"一句话搭仿真"的配方能力，且**不触动安全边界**（写动作仍走受管控 core 工具）。
- **架构**：两项都以 skill 形式落地，延续"扔 1 个 `.py` 即扩展"的低成本模式，不增加 function-calling schema 负担。

---

## 6. 待你确认

1. MVP 范围是否就锁定这两项（手册检索 + Pyro 一键）？还是先只做 MVP-1？
2. MVP-2 是否同意采用"蓝图返回式"（方案 a，不动安全边界）？
3. 是否需要我先写一段**只读探测脚本**去真实 Houdini 里确认手册数据源（R1），作为动手前的第 0 步？
