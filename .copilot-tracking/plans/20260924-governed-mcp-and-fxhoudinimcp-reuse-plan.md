# Houdini-Agent 受治理 MCP 深化与 fxhoudinimcp 能力复用计划

> 日期：2026-09-24
> 状态：实施中（Phase 1-3 代码完成，待真实 Houdini 验证）
> 参考：[healkeiser/fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp)（当前公开说明为 206 tools、8 resources、9 prompts）
> 范围：外部 FastMCP 接入边界、Tool Registry/Harness 统一治理、运行时能力清单、连接诊断，以及选择性的 Houdini 领域只读能力
> 目标：先消除外部 MCP 对现有治理链的旁路，再借鉴高价值领域 handlers；不整体移植其网络架构或弱安全模型。

---

## 1. 决策摘要

本计划采用以下总策略：

1. **借能力，不借安全模型。** `fxhoudinimcp` 的 Houdini 领域覆盖、命令清单兼容检查和连接诊断值得借鉴；其无鉴权、无逐工具授权、无审计的信任模型不得进入正式路径。
2. **先治理，再扩工具。** 当前项目已有外部 FastMCP server，但它直接注册和执行部分 `hou` 操作，未统一经过 `ToolRegistry`、Harness、主线程 executor 和 append-only audit。任何能力扩展必须以关闭该旁路为前置条件。
3. **一个事实源。** 外部 MCP 暴露的 schema、允许执行的工具和执行语义应从现有 Tool Registry 派生，不继续维护独立 decorator 工具集。
4. **只选择性复用领域逻辑。** 优先引入能力清单、连接诊断、USD/LOP 深度查询、分页几何读取和 TOP 状态查询；不以达到 206 个工具为目标。
5. **高风险默认拒绝。** 外部 MCP 若没有可靠的人机确认通道，则 `execute_python`、shell、文件写入、HDA 安装/卸载、删除、场景装载及其他高影响操作必须 fail closed。

### 1.1 与既有计划的关系

- 本计划不替代 `fxhoudinimcp_borrow_mvp_plan.md` 中已经完成的离线帮助和 workflow blueprint 工作。
- 本计划吸收 `lops_pdg_tools_plan.md` 的领域方向，但重新规定：进入外部 MCP 或 core tool 的能力必须统一经过 Registry/Harness；低频组合式只读能力仍可保留为 skill。
- 本计划完成 `20260817-execution-tools-plugins-docs-deepening-plan.md` 中尚未完成的要求之一：Standalone/Bridge/Houdini adapters 不得绕过 Registry 或 Harness。
- 若旧计划中的数量、结构或结论与本计划冲突，以实现时重新验证的本地代码和 upstream 固定版本为准。

---

## 2. 已确认现状

### 2.1 当前项目内部治理链

内部 Agent 工具已有完整执行链：

```text
HOUDINI_TOOLS
    -> ToolRegistry
    -> Harness Policy / confirmation
    -> StreamingToolExecutor
    -> HoudiniMainThreadExecutor
    -> MCPClient._TOOL_DISPATCH
    -> hou / skill / local implementation
    -> result guardrail + append-only audit
```

关键实现位置：

- `houdini_agent/utils/ai_client.py`：核心工具 schema。
- `houdini_agent/utils/tool_registry.py`：注册、mode/runtime 授权和执行语义。
- `houdini_agent/core/harness_engine.py`：参数校验、风险决策、确认和审计。
- `houdini_agent/core/houdini_main_thread_executor.py`：Houdini 主线程生命周期、超时熔断和 stale-result 防护。
- `houdini_agent/utils/mcp/client.py`：内部 dispatcher 与 Houdini 工具实现。
- `houdini_agent/core/diagnostics_mixin.py`：append-only session diagnostics。

### 2.2 当前外部 MCP 旁路

`houdini_agent/utils/mcp/server.py` 面向外部 MCP 客户端运行 FastMCP HTTP server，并存在以下独立行为：

- 直接用 FastMCP decorators 注册另一套工具。
- 部分工具直接调用 `hou` 或 `hou_core`。
- 独立公开任意 Python 执行能力。
- 没有统一经过 Tool Registry mode/runtime 授权。
- 没有统一经过 Harness policy、确认和 result guardrail。
- 没有进入现有 append-only tool audit。
- 与内部 `HOUDINI_TOOLS`、`MCPClient._TOOL_DISPATCH` 形成平行事实源。

这条路径是本计划的首要控制点。完成 Phase 1 前，不新增外部 MCP 写工具。

### 2.3 fxhoudinimcp 可借鉴点

`fxhoudinimcp` 采用外部 MCP process、HTTP bridge、Houdini `hwebserver` dispatcher 和主线程 handlers 的三层结构。值得借鉴的具体内容：

- `health`、`session_info`、`list_commands` 和多 Houdini 会话发现。
- 从 MCP wrapper 调用点生成 required-command manifest，并检查宿主能力差异。
- SDK 1.x/2.x 兼容集中在一个 import shim。
- graph、USD/LOP、geometry、TOP/PDG、HDA、Takes 等系统化领域 handlers。
- wrapper/bridge/handler 分层测试和结构化错误。

明确不直接复用：

- 无鉴权、无逐工具授权、无审计的安全模型。
- 任意 `execute_python` 暴露。
- 为嵌入式内部 Agent 新增 hwebserver/8100 bridge。
- 一次性复制全部 tool wrappers。
- 绕过现有原子工具和 Harness 的一键写入 workflow handlers。

---

## 3. 硬约束

### 3.1 安全与治理

- 治理信息缺失、policy 异常、确认不可用或身份/session 不可信时必须 fail closed。
- 外部 MCP 使用显式 allowlist；不得把 Registry 中的所有 enabled tools 自动视为外部可调用。
- 外部调用必须校验工具名、mode、runtime、参数 schema、路径种类和风险策略。
- 高影响操作必须有人机确认；若 MCP transport/client 无确认能力，则拒绝执行，不允许静默降级为 allow。
- 外部 agent 不能获得比内部 outer policy 更宽的权限。
- 审计采用 append-only JSONL，记录 session、时间、tool、policy、allow/deny、结果类别和 correlation id；不记录 prompt、凭据、完整代码或敏感参数值。
- 设置 per-session 调用上限和并发上限，防止循环调用与主线程资源耗尽。
- 外部 MCP 默认只监听 loopback；非 loopback 配置必须显式开启并具备独立认证方案，否则不支持。
- 浏览器 `Origin`、异常 `Host` 和 DNS rebinding 风险必须拒绝，不能仅依赖 CORS。

### 3.2 架构

- `ToolRegistry` 继续是工具 schema 和执行语义的事实权威。
- Harness 继续拥有 policy/confirmation 顺序；FastMCP adapter 不复制 policy 判断。
- `HoudiniMainThreadExecutor` 继续只负责主线程 execution lifecycle，不吸收 MCP transport 或 policy。
- `MCPClient._TOOL_DISPATCH` 继续是 core Houdini 工具的内部实现入口，直到有测试证明可进一步深化。
- 不新增第二套领域 dispatcher，不把 upstream dotted commands 原样平移成平行系统。
- 不引入新第三方依赖，除非当前运行环境无法提供所需 MCP SDK 能力且有独立批准。

### 3.3 兼容与范围

- 内部 Agent、Ask、Plan、streaming、batch、plugin 和 skill 可见行为保持兼容。
- 不改变现有会话数据格式、capture store、visual review 或 token 统计协议。
- 不自动打开外部 MCP server；保持配置显式启用。
- 不自动修改 Houdini 场景、相机、更新模式或视口。
- upstream 代码复用遵循 MIT 许可证；复制 substantial portions 时保留对应许可声明和来源记录。

---

## 4. Phase 0：基线与设计门

### 目标

固定外部 MCP 当前暴露面、内部治理不变量和 upstream 参考版本，确保后续是可验证迁移，而不是边改边猜。

### Tasks

- [x] 记录 `fxhoudinimcp` 的固定 commit/tag、许可证、工具/资源/prompt 数量和拟借鉴文件，不以浮动 `main` 作为实现依据。
- [x] 枚举 legacy FastMCP 公开行为、参数来源、直接 `hou`/`hou_core` 调用和任意代码执行入口，并记录迁移后边界。
- [x] 建立外部 MCP characterization/regression tests：治理配置、非 Houdini/SDK/能力降级、健康状态、工具列表、成功、错误和 server stop。
- [x] 证明 legacy 外部写路径曾绕过 Registry/Harness/audit，并用源码回归契约保证旁路不会重新出现。
- [x] 固定内部 `HOUDINI_TOOLS`、Registry、`_TOOL_DISPATCH` 和 handler callable 的现有契约测试。
- [x] 定义外部 MCP 调用上下文：可信 session id、client id、mode、用户名来源、correlation id 和审计归属。
- [x] 决定 human-in-the-loop 机制：使用注入确认回调；确认缺失、异常或拒绝均 fail closed，无隐式 allow。
- [x] 完成 Phase 1 interface 设计门，记录 adapter 输入/输出、线程边界、错误模型和关闭行为。

### 验收门

- [x] 有 regression test 证明 legacy 旁路已移除且不能重新出现。
- [x] 外部调用身份、session、mode 和确认语义没有未决项。
- [x] upstream 参考版本和许可证边界已记录。
- [x] 尚未加入任何新领域写工具。

### 回滚点

本阶段只增加文档和 characterization tests，不改变运行时行为。

---

## 5. Phase 1：统一外部 MCP 治理入口

### 目标

让 FastMCP 只承担协议适配；所有可执行调用进入现有 Registry、Harness、主线程 executor、result guardrail 和审计路径。

### Tasks

#### M1 — 建立外部 MCP policy 配置

- [x] 在不可由 agent 自改的配置中定义外部 MCP allowlist、deny list、风险上限、速率和并发限制。
- [x] 默认 allowlist 仅包含健康检查与低风险只读工具。
- [x] 明确禁止任意 Python/shell、场景装载、删除、HDA 安装/卸载和任意文件写入，除非后续单独设计确认和路径策略。
- [x] 配置读取或解析失败时拒绝启动外部 MCP 或仅暴露 health，不得回退为 unrestricted。

#### M2 — 建立受治理 adapter

- [x] 定义一个窄的 external MCP execution adapter，输入为可信上下文、tool name 和未信任 args。
- [x] adapter 通过 `ToolRegistry.authorize_dispatch()` 校验 enabled、mode 和 runtime。
- [x] adapter 调用完整 Harness seam，覆盖 allow、deny、ask、retry 和 patched args。
- [x] Houdini runtime 工具继续走 `HoudiniMainThreadExecutor`；local runtime 不得因此获得新增权限。
- [x] result guardrail、异常规整和敏感信息清洗与内部 Agent 一致。
- [x] 每次调用写入 policy start/decision/tool result 审计，带 correlation id 但不记录完整参数值。

#### M3 — 迁移 FastMCP tools

- [x] FastMCP schema 从 Registry 中明确标记为 external-MCP-visible 的工具派生。
- [x] 将现有公开只读工具逐个迁到受治理 adapter，每迁移一个即补契约测试。
- [x] 将现有写工具迁移到 adapter；无法满足确认与安全策略的工具从 MCP schema 中移除。
- [x] 删除或默认不注册 `execute_python_code`，并增加 schema 中不存在该工具的回归测试。
- [x] 删除 FastMCP server 中失去 caller 的 `hou`/`hou_core` 直接实现，避免平行行为重新出现。

#### M4 — 生命周期与资源限制

- [x] 为每个外部 session 设置调用总量、并发数和长任务数量上限。
- [x] server stop/shutdown 后拒绝新调用，并正确隔离未开始任务。
- [x] 主线程 executor blocked/shutdown 时外部 MCP 同样 fail closed。
- [x] 动态图片资源具备受控生命周期、大小上限和清理策略，不永久持有临时路径。

### Tests

- [x] 未注册、禁用、mode 不允许、runtime 不匹配和 policy error 均不能触达 handler。
- [x] deny、确认取消、确认不可用和 retry exhaustion 均 fail closed。
- [x] retry 只执行 Harness 返回的 `patched_args`。
- [x] 高风险工具在无确认通道时不出现在 schema，或调用时稳定拒绝。
- [x] 外部调用与内部调用使用相同 handler、主线程和结果清洗行为。
- [x] 每次实际执行都有 allow decision 和 tool result 审计；拒绝也有 policy 审计。
- [x] rate/concurrency limit 可阻止循环和主线程队列堆积。
- [x] server shutdown、executor blocked 和 stale result 路径无挂起。

### 验收门

- [x] 不存在外部 MCP 到 `hou`、`hou_core` 或 core handler 的未治理直接路径。
- [x] FastMCP 不再拥有独立工具行为事实源。
- [x] 任意代码执行默认不可从外部 MCP 到达。
- [ ] 内部 Agent 回归测试保持通过。

### 回滚点

先引入 adapter 和只读迁移，再迁移/移除写工具。旧 server 注册仅在所有对应 tests 转绿后删除。

---

## 6. Phase 2：能力清单、连接诊断与版本兼容

### 目标

借鉴 `fxhoudinimcp` 的 command manifest 机制，快速识别 schema、Registry、dispatcher、运行时依赖和 Houdini 宿主能力不一致。

### Tasks

#### C1 — 静态能力 manifest

- [x] 从 external-visible Registry entries 生成所需工具及 handler manifest，不手工重复录入工具名。
- [x] manifest 至少包含 tool name、runtime、风险级别、只读/写、所需 handler、可选 Houdini feature/version。
- [x] 添加生成结果稳定性测试；未提交的 manifest drift 必须在 CI 中失败。
- [x] 保持 manifest 不包含 prompt、参数值、路径或用户数据。

#### C2 — 运行时 capabilities

- [x] 实现只读 `health`、`session_info` 和 `capabilities` 查询。
- [x] 返回 Houdini version/build、Agent version、MCP SDK version、session id、executor 状态和可用工具名。
- [x] 检查 Registry entry、dispatcher handler、可选模块（`pxr`、`pdg` 等）和宿主 feature 是否真实可用。
- [x] 能力缺失使用结构化 degradation，不把部分加载伪装为健康。

#### C3 — 兼容差异诊断

- [x] 启动时比较 exposed manifest 与运行时 capabilities。
- [x] schema 有工具但 handler/feature 缺失时不暴露该工具，并记录明确诊断。
- [x] 提供结构化连接状态：未启动、SDK 缺失、非 Houdini、executor blocked、版本不兼容、能力缺失。
- [x] 诊断不得通过一次实际写调用探测能力。

### Tests

- [x] Registry 新增 external-visible tool 但无 handler 时契约测试失败。
- [x] dispatcher handler 缺失、不可调用或 optional module 缺失时能力正确降级。
- [x] health 不依赖主线程写操作，且不会因工具不可用而返回虚假全健康。
- [x] manifest 和 capability 输出有上限、顺序稳定且不包含敏感数据。

### 验收门

- [x] 工具暴露与真实可执行能力之间不存在静默漂移。
- [x] 用户能从一次连接诊断区分配置、端口、SDK、Houdini 和 handler 问题。
- [x] 新增工具时无需手工同步多份名字列表。

### 回滚点

先以只读 diagnostics 增量加入；自动隐藏不兼容工具在差异测试稳定后启用。

---

## 7. Phase 3：第一批高价值只读领域能力

### 目标

在统一治理和 capabilities 完成后，以最小工具集补齐真实缺口。每类先实现只读查询，不添加写 API。

### 选择标准

- 当前项目没有等价行为，或现有 summary/skill 无法回答精确问题。
- 能通过稳定 HOM/USD/PDG API 实现。
- 返回可分页、可截断，不会把完整大场景塞进模型上下文。
- 可在无 Houdini 环境做 mock/contract tests，并能在真实宿主做条件集成测试。
- 能明确归类为 readonly、Ask-safe、无确认或低风险。

### 3A — 分页几何查询

- [x] 增加 point 查询：attributes 过滤、start/count、group、output index。
- [x] 增加 primitive 查询：attributes 过滤、start/count、group、output index。
- [x] 设置硬 count 上限、序列化大小上限和 `truncated`/`next_start`。
- [x] 读取遵循现有只读 geometry 获取语义，不切换全局更新模式或主动改变 cook 状态。
- [x] 与 `get_geometry_summary` 保持分工：summary 用于概览，分页工具用于精确抽样。

### 3B — USD/LOP 深度查询

- [x] 查询 prim 基本信息、属性、metadata 和 authored opinions（通过有界 prim stack 摘要）。
- [x] 查询 layer stack、muted layers 和 sublayers。
- [x] 查询 composition arcs/prim stack，并对大结果截断。
- [x] 查询 resolved material binding、binding purpose 和具体 relationship 来源。
- [x] `pxr` 或 stage 不可用时返回结构化能力缺失，不抛裸异常。
- [x] 复用或深化现有 USD skills，避免 core tool 与 skill 实现同一遍历逻辑。

### 3C — TOP/PDG 状态查询

- [x] 查询 TOP network、scheduler 和 graph context 概览。
- [x] 分页列出 work items、状态、关键 attributes 和输出文件元数据。
- [x] 汇总 failed work items、错误和日志位置，不读取无限日志正文。
- [x] 明确这些工具只观察状态，不触发 cook、dirty、pause 或 cancel。
- [x] `pdg` 不可用时通过 capabilities 隐藏工具并提供结构化诊断。

### Tests

- [x] Geometry 遍历工具有硬上限、`truncated` 和稳定 pagination contract；USD/TOP 待对应阶段实现。
- [x] 无节点、错误上下文、空 geometry/stage/graph 和缺失 optional module 均有明确结构化结果；真实宿主 fixture 已验证只读查询路径。
- [x] Geometry 分页工具 Ask 模式可用且 Registry 明确标记 readonly、非 mutating、无需 undo/confirmation。
- [x] Geometry 分页实现不改变场景、selection、frame、camera、update mode 或 cook 状态。
- [x] 真实 Houdini 条件测试覆盖至少一个 SOP、LOP 和 TOP fixture；环境不具备时返回明确 skip。

### 验收门

- [x] 第一批能力补齐分页 geometry、精确 USD composition/binding 和 PDG 状态查询缺口；已有 USD skill 复用共享 implementation。
- [x] 所有新增遍历均有条目和 payload 硬上限，不产生无界结果。
- [x] 外部 MCP 与内部 Agent 复用同一领域 implementation 和治理元数据。

### 回滚点

Geometry、USD 和 TOP 三类分别提交、分别验收；任一类别不阻塞其他类别。

---

## 8. Phase 4：分级开放写能力（重新评估）

### 重新评估结论

Phase 1 已经提供 Registry 授权、Harness policy/confirmation、主线程执行、undo/cook 语义、调用限额和 append-only audit，因此外部 MCP 没有必要永久停留在只读模式。但这些基础设施只说明“可以受治理地执行”，并不自动证明任意写工具都适合对外暴露。

本阶段改为三层准入，而不是按 upstream 领域列表整体移植：

1. **第一层：可撤销的原子场景编辑。** 优先复用内部 Agent 已稳定使用的节点创建、连线和参数修改；这是最直接的外部 MCP 用户价值，也是当前架构最成熟的写路径。
2. **第二层：有状态或异步操作。** TOP cook、current take 等必须先建立 operation/state 协议，不能伪装成普通同步工具。
3. **第三层：持久化或代码执行能力。** 文件保存、HDA definition、Shelf/Python 执行维持默认拒绝，除非有独立需求、受限路径/固定命令和事务化恢复设计。

调整配置中的 `mcp_max_risk_level` 或 allowlist 不能替代逐工具评审。工具必须同时满足 `external_mcp_visible`、显式 allowlist、风险上限、可靠确认和下述写后验证契约。

### 实施优先级

#### P4A — 原子场景编辑 MVP（优先，建议实施）

- [ ] 用真实外部 MCP 工作流固定首批需求：创建节点、设置单个参数、连接节点；没有实际调用方的能力不进入首批。
- [x] 首批仅评估 `create_node`、`set_node_parameter` 和 `connect_nodes`；每个工具独立设置 `external_mcp_visible`，不得批量开放所有 normal-risk 工具。
- [x] 外部写调用仅允许 `agent` 或 `plan` 执行态，禁止通过 Ask/规划态获得写权限。
- [x] 每次写调用必须使用 server-owned correlation/session 身份并触发 Houdini 面板确认；确认回调缺失、异常、超时或拒绝时 fail closed，确认请求使用独立 queue 防止并发覆盖。
- [x] 限制 node path 在显式配置的 `mcp_write_node_roots` 下；默认空配置拒绝写入，`create_node` 必须显式传 `parent_path`，并拒绝 `..` 与前缀碰撞越界。
- [x] 复用现有主线程 undo group、cook guard、execution barrier 和 audit，不新增外部专用 handler。
- [x] 为每个工具定义有界写后验证：创建回读新增节点路径/类型，设参返回实际值，连接回读端点与 input index；无法可靠回读时返回 `applied_unknown`，不伪装为 verified。
- [x] MCP 返回有界 mutation result 和结构化 `verification` facts，不返回任意代码、完整场景或无界节点数据。
- [x] 不把 `delete_node`、批量创建/批量设参、copy、rename、layout、display flag 或 network box 混入 MVP；根据真实使用证据逐项晋级。

#### P4B — 批量与破坏性场景编辑（后续按需求）

- [ ] 批量操作必须有节点数/参数数硬上限、全量预检和单一 undo 边界；已为 `create_nodes_batch` 增加 25 节点/50 连接/100 参数硬上限和有界 verification，但真实 Houdini 证明一次 undo 只撤连接、不会撤本批节点，因此在事务恢复设计完成前不设为 external-visible。
- [ ] `delete_node` 等破坏性操作保持 high-risk 和默认 deny；即使 Houdini undo 可用，也必须显示精确目标并单独确认。
- [x] 对 `rename_node`、`layout_nodes` 和受限 `set_node_flags` 分别定义边界并独立开放：rename 仅接受合法叶子名并由 Houdini 报告碰撞，layout 仅允许显式网络内 1..50 个指定节点且不改 selection，flags 仅允许 bypass/template/lock 并保持 display/render/current/select 不可达；`copy_node` 因新增拓扑仍未开放，不使用“场景编辑”总开关。

#### P4C — TOP cook 生命周期（独立设计）

- [ ] 区分 command accepted、cook running、completed、failed 和 cancelled。
- [x] operation registry 明确区分 accepted、running、completed、failed 和 cancelled；TOP cook handler 尚未接入。
- [x] 工具 timeout 不得被解释为 cook 已取消；查询仍返回 running，只有明确终态迁移才能变为 cancelled。
- [ ] pause/cancel/dirty 均为独立高风险或确认策略，不与只读查询混合。
- [ ] 已实现有界、session-owned operation id、进度和重新查询基础；仍需定义 TOP cook 的后台执行、宿主回调和 session shutdown 终态后才能注册工具。

#### P4D — USD/LOP 写操作（有用但非 MVP）

- [x] USD 写操作优先通过现有 LOP 节点创建、连线和参数设置表达；不新增直接 USD authoring 工具。
- [ ] LOP 批量编辑必须显式指定 `/stage` 下的允许 parent root、节点/连接/参数上限、单一 undo 边界和失败回滚。
- [ ] 直接 USD layer/prim authoring 必须逐项定义 mutation scope、edit target、layer ownership、确认及写后 composition 验证；在这些语义明确前不开放。
- [x] Takes 不在本计划范围内，不新增 list/current/override/create/switch 工具。

#### P4E — HDA、文件与 Shelf/Python（维持默认拒绝）

- [ ] HDA 先加入 list/info/definition sections 等有界只读能力。
- [ ] install/uninstall/edit definition 必须限制 project root、验证扩展名、要求独立确认，并定义部分失败后的回滚或稳定错误状态。
- [ ] `save_hip`、场景装载和任意文件写入需要 canonical path、允许根、覆盖策略和原子提交，不能沿用仅有参数类型检查的普通写路径。
- [ ] Shelf tool 只允许固定 allowlist 中无任意代码/kwargs 注入的命令；否则仅提供只读查看。
- [ ] `execute_python`、`execute_shell` 及任何等价通用后门永久不作为外部 MCP 写能力的兜底方案。

### 验收门

- [ ] 至少有一个真实外部客户端工作流证明 P4A 的需求和参数形态，不以“upstream 已有”作为加入理由。
- [x] 每个写工具都有独立可见性、allowlist、最小权限、确认绑定、undo/恢复、写后验证和可运行测试。
- [x] 普通写工具默认仍不暴露；仅在管理员显式配置 allowlist 与 `mcp_max_risk_level` 后进入 schema。
- [x] 无确认能力的外部 MCP client 无法执行任何写操作，而不只是 high-risk 操作。
- [x] 自动测试证明 policy deny、确认失败、路径越界、handler 异常和验证不确定均不会产生虚假 verified 审计；`applied_unknown` 保留 mutation success 并记录 `verification_inconclusive`。
- [x] 真实 Houdini 与自动测试覆盖成功、撤销、Manual/Auto update、部分失败和 server shutdown 边界。Houdini 21.0.596 hython 已通过 create/set/connect、结构化 verification、Manual guard、显式 Auto 保持和 connect undo；并通过 rename、显式子集 grid layout、受限 bypass flag 及 display/render 状态不变验证；并发测试证明在途调用可完成且 shutdown 后新调用拒绝。

---

## 9. 测试与验证矩阵

### 9.1 无 Houdini 单元测试

- FastMCP schema 由 Registry 派生。
- external allowlist 与风险策略 fail closed。
- Harness allow/deny/ask/retry、确认不可用和 patched args。
- manifest/capabilities 差异检测。
- pagination、payload limit、序列化和结构化错误。
- MCP SDK 缺失、版本兼容 shim 和 server lifecycle。

### 9.2 Qt/Houdini adapter 测试

- 外部调用到达同一主线程 executor。
- operation id、timeout blocked、shutdown 和 stale-result 防护保持有效。
- undo、cook guard、read freshness 与内部 Agent 一致。
- audit 记录存在且不包含 prompt、代码全文或敏感参数值。

### 9.3 真实 Houdini 手工/条件集成测试

- 显式启用/禁用外部 MCP server。
- MCP client 连接、health、capabilities 和只读调用。
- 第二个 Houdini session 的识别策略；若当前架构不支持自动发现，必须给出明确诊断，不能连错会话。
- SOP 分页读取、LOP material binding/composition、TOP graph/work item 状态。
- Manual/Auto update、subframe、空场景和大场景边界。
- server stop 后无残留回调、线程、临时资源或可执行端点。

### 9.4 建议聚焦命令

实现时优先运行最窄测试文件，再执行完整回归。具体命令以仓库当前 Python 环境和测试配置为准，不在计划阶段硬编码未经验证的解释器路径。

---

## 10. 交付拆分与成本预估

| 交付 | 内容 | 预估 |
|---|---|---:|
| A | Phase 0 基线和设计门 | 1-2 人日 |
| B | Phase 1 统一外部 MCP 治理 | 5-9 人日 |
| C | Phase 2 manifest、capabilities、连接诊断 | 2-4 人日 |
| D | Phase 3A 分页 geometry | 2-4 人日 |
| E | Phase 3B USD/LOP 深度查询 | 4-7 人日 |
| F | Phase 3C TOP/PDG 状态查询 | 4-6 人日 |
| G1 | Phase 4A 原子场景编辑 MVP | 4-7 人日，需真实工作流批准 |
| G2 | Phase 4B-E 其他写能力 | 每类 3-8+ 人日，分别批准 |

估算不包含真实生产资产适配、跨 Houdini 大版本校准和外部 MCP client 的供应商特有兼容问题。

### 推荐提交顺序

1. `test: characterize external MCP governance bypass`
2. `refactor: route external MCP through governed execution`
3. `feat: add MCP capability manifest and diagnostics`
4. `feat: add paginated geometry inspection`
5. `feat: deepen read-only USD inspection`
6. `feat: add read-only TOP status inspection`

每个提交必须可单独回滚，且不得把工具扩展和治理迁移混在同一提交。

---

## 11. 完成标准

- [x] 外部 FastMCP 不存在绕过 Registry、Harness、主线程 executor、result guardrail 或 audit 的执行路径。
- [x] 外部 MCP 使用显式 allowlist、调用/并发限制，并在治理异常时 fail closed。
- [x] 任意 Python/shell 和高风险写操作默认不对外暴露。
- [x] schema、Registry、dispatcher 和 runtime capabilities 的差异可自动检测。
- [x] health/connection diagnostics 能准确区分启动、SDK、Houdini、executor 和能力问题。
- [x] 第一批领域工具均为只读、有界、可分页，并复用统一 implementation。
- [ ] 内部 Agent、Ask、Plan、streaming、batch、plugin、visual review 和 capture 回归保持通过。
- [x] 真实 Houdini 宿主验证完成：Houdini 21.0.596，SOP/LOP/TOP smoke 全部通过；其他大版本仍按 capabilities 和条件测试降级。
- [x] 实施期间按 `.github/instructions/task-implementation.instructions.md` 维护对应 changes 文件；仅在全部阶段完成后添加 Release Summary。

---

## 12. 明确不做

- 不整体 vendor 或安装 `fxhoudinimcp` 作为运行时依赖。
- 不为了工具数量一次性复制 206 个 wrappers/handlers。
- 不把内部嵌入式 Agent 改造成外部 HTTP bridge 架构。
- 不允许外部 MCP client 自行修改 governance policy。
- 不以正则黑名单替代授权、allowlist、确认和路径边界。
- 不让单张 viewport 截图替代 geometry、cook、network 或 material binding 的技术验证。
- 不在本计划中加入 perceptual diff、像素差分、自动 framing 或 quick render。