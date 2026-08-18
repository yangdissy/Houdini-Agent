# Houdini-Agent 核心 Module 深化总计划

> 日期：2026-08-14  
> 状态：2026-08-17 当前项目范围已完成；共享 Tool Gateway、Standalone local adapter 与全量 UI 回归归属其他项目
> 范围：插件 Tool 权威、Session Workspace lifecycle、Plan lifecycle、Memory 存储 mechanics、上下文装配与裁剪  
> 目标：先固定单一权威，再迁移 callers，最后删除重复路径；提高 locality、leverage 与真实 interface 的 testability。

---

## 1. 背景与结论

本轮选择深化以下五个行为群：

1. 插件 Tool 权威归一。
2. Session Workspace lifecycle。
3. Plan lifecycle。
4. 个人/团队 Memory 的 SQLite 与 embedding mechanics。
5. 上下文装配与预算退化。

这些区域已有可复用 module，但仍存在双重权威、状态分叉或重复 implementation。继续增加 Mixin、pure helper 或泛化 repository 不会解决 friction；应让已有 module 隐藏完整行为，并让 callers 与 tests 穿过同一个 seam。

### 1.1 关键依赖

- Tool Registry 先稳定，Plan quality gate、mode exposure 和上下文 Tool schema 才有可信事实源。
- Session Workspace 先明确权威和序列化，Plan 才能正确归属 session，Memory 才能稳定遵守用户身份与路径语义。
- Plan 与 Memory 的输入稳定后，上下文装配才能成为最终唯一规则。
- Session 的原子提交和单一 orchestration 风险较高，安排在基础权威定义之后、最终收尾之前。

### 1.2 实施顺序

1. 插件 Tool 权威归一。
2. Session Workspace 基础权威与统一序列化。
3. Plan lifecycle。
4. Memory embedding provenance 与存储可靠性。
5. 上下文装配与裁剪统一。
6. Session Workspace 原子提交及单一 orchestration。
7. 删除完成迁移后的旧路径。

---

## 2. 硬约束

### 2.1 Architecture 原则

- 每项先做 deletion test；只删除那些复杂度已被深 module 吸收、不会散回 callers 的路径。
- interface 是 test surface；新增 tests 优先穿过真实 caller 使用的 seam。
- 一个 adapter 只是假设 seam，两个真实 adapter 才建立 seam；不为单个实现新增 Protocol、factory 或通用 repository。
- 优先 composition，不再扩大 `AITab` 的 Mixin 图。
- 每个阶段独立提交、独立验收；不把五项改成一次性大重构。

### 2.2 安全与治理约束

- `ToolExecutionGateway` 继续作为 UI 与 Bridge 共用的 Execution Governance Seam。
- 未注册、禁用、模式不允许或 runtime 不匹配的 Tool 必须 fail closed。
- 插件默认 Tool Runtime Location 继续为 `houdini`，保持旧扩展兼容。
- `on_before_tool` / `on_after_tool` 仅是事件 hook，不能成为绕过 Registry 或 Harness 的执行入口。
- `scene_info` 继续作为受限 transport/read 操作，不纳入 Tool Registry。
- 不改变 ADR-0001 的 Node Path / File Path 分类与 `save_hip.file_path` 约定。
- 不改变 ADR-0002 的 Bridge request correlation、有效单次执行、主线程与 loopback 决策。

### 2.3 兼容性约束

- 旧插件的注册入口和 handler 参数 shape 保持兼容。
- 旧 Plan JSON 和旧 Session Cache Record 必须继续可读。
- 一次只允许一个 Agent 全局在途；切换 tab 后结果仍写回发起 session。
- 旧 `session_*.json`、manifest、clear marker 和 orphan recovery 语义保持兼容。
- 个人 Memory 按用户隔离并留在本地；团队导出的隐私过滤规则不放宽。
- Team Memory 继续只通过显式搜索进入上下文，不自动注入 system prompt。
- 上下文裁剪不得拆断 assistant `tool_calls` 与 tool messages，不字符级截断用户或 assistant 正文。
- Standalone Runtime 的数据路径继续由现有 Data Root 规则决定。

---

## 3. Phase 0：基线与回归护栏

### 目标

先证明现有关键行为，避免把行为变更误当架构迁移。

### Tasks

- [x] 记录五个区域现有测试命令与基线结果。
- [x] 为插件 Tool 增加“注册—暴露—治理—执行—注销”的端到端基线测试。
- [x] 为 Session 增加 normal、periodic、atexit 三条保存路径的 shape 对比测试。
- [x] 为 Plan 增加 Confirm、Reject、running、error 和 session 切换的现状测试。
- [x] 为 Memory 增加 embedding backend/dimension 不匹配的复现测试。
- [x] 为上下文增加 section 顺序、图片保留、tool-call pairing 和裁剪后动态内容的结构测试。

### 验收门

- [x] 所有新增基线测试能明确区分“要保持的兼容行为”和“计划修正的缺陷行为”。
- [x] 当前已有相关测试保持通过。
- [x] 没有通过 mock 内部 helper 来替代真实 interface 测试。

---

## 4. Phase 1：插件 Tool 权威归一

### 当前 friction

插件 Tool 同时保存在 `HookManager._external_tools` 与 Tool Registry；schema 暴露和 MCP handler lookup 也存在双路径。Registry 已是 Tool Runtime Location 的权威，却还不是插件 schema、handler、enabled 与 ownership 的唯一权威。

### Deepening 方向

深化 Tool Registry，使其拥有插件 Tool 的完整 lifecycle。`HookManager` 只保留事件 hooks 与 UI button 扩展；`ToolExecutionGateway` 保持执行治理 seam。

### Tasks

#### T1 — 固定 Registry 插件注册契约

- [x] 保留现有插件注册入口，但内部只写 Tool Registry。
- [x] Registry 保存 schema、handler、plugin owner、source、enabled、modes、risk 和 runtime。
- [x] 注册失败显式失败，不再吞异常后留下孤儿记录。
- [x] 未指定 runtime 的旧插件继续默认为 `houdini`。
- [x] 明确同名 Tool 的兼容策略，禁止无审计的静默漂移。

#### T2 — 迁移 schema 暴露

- [x] 所有 mode 从 Registry 查询 enabled Tool schema。
- [x] 保持现有 Ask、Plan planning、Plan executing 和 Agent 暴露语义。
- [x] 禁用、mode 不匹配或 runtime 不合法的插件 Tool 不得发送给模型。
- [x] 保持意图筛选，但不再无条件追加插件 schema。

#### T3 — 迁移执行 lookup

- [x] MCP dispatcher 的扩展 handler 仅从 Registry 查询。
- [x] `on_before_tool`、handler、`on_after_tool` 的时序保持。
- [x] 未注册或已注销插件 Tool 不能通过 fallback 执行。
- [x] Standalone 根据 Registry runtime 正确选择 local adapter 或 Bridge adapter。

#### T4 — 删除重复 ownership

- [x] 删除 `HookManager._external_tools` 及相关 schema/handler 查询方法。
- [x] 删除 MCP 中 HookManager-first 的执行分支。
- [x] 删除发送路径中插件 schema 的二次合并。
- [x] 只清理本阶段迁移造成的无用 import 和 fallback。

### Tests

- [x] 插件注册后只有 Registry 持有完整 Tool 事实。
- [x] Registry 注册失败时无 HookManager 孤儿状态。
- [x] disabled/mode/runtime 同时约束暴露与执行。
- [x] reload/disable 后旧 handler 消失。
- [x] hook 调用顺序保持。
- [x] local 插件留在 Standalone，默认插件走 Bridge。
- [x] Gateway 对未知或 runtime mismatch Tool fail closed。

### 验收门

- [x] Tool Registry 是插件 Tool schema、handler、enabled、modes、runtime 与 owner 的唯一权威。
- [x] HookManager 删除 Tool storage 后，复杂度没有散回 callers。
- [x] ADR-0002 的治理与 Bridge tests 全部通过。

### 回滚点

T1、T2、T3 分别独立提交；只有 T1–T3 全部通过后才执行 T4 删除。

---

## 5. Phase 2：Session Workspace 基础权威与统一序列化

### 当前 friction

Session 同时存在于 `AITab` 当前字段、`_sessions` 开放 dict、Qt tabs、session files 与 manifest。保存逻辑分散在 normal、all-sessions 和 atexit 路径；MainWindow 与 AITab 还会重复触发 restore。

### 本阶段边界

本阶段先固定权威并统一 cache record 生成，不立即合并所有退出 hook，也不立即改变磁盘提交协议。

### Authority 决定

- `sessions_manifest.json`：打开 session 集合与 active session 的权威。
- `session_<id>.json`：可恢复 session 内容的权威。
- `workspace.json`：只保存窗口状态，不决定会话恢复。
- agent run anchor：仅为内存 runtime 状态，不持久化。
- Plan 文件：Plan 内容权威；Session 只保留或派生引用，不复制完整 Plan。

### Tasks

#### S1 — 固定 Session state ownership

- [x] 列出 session-owned、agent-run-owned、window-owned 和 derived UI state。
- [x] 保留全局单 Agent 在途和 `_agent_session_id` 写回锚点。
- [x] 明确 Plan projection、token stats、context summary 等是否属于 session。
- [x] 删除空的 cache metadata 更新路径，或明确其仅为显示派生值。

#### S2 — 统一序列化核心

- [x] normal、periodic、all-sessions 与 atexit 复用同一个纯 Python record builder。
- [x] Qt widget 抽取、cache record 生成和文件写入分开。
- [x] 保持 base64 图片替换、空 session 不保存和旧版本读取行为。
- [x] atexit 继续使用无 Qt backup，但数据 shape 必须与正常保存一致。

### Tests

- [x] 四条保存入口产生一致的 `SessionCacheRecord` shape。
- [x] 空 session、缺失 id、图片占位和 token stats 兼容。
- [x] running Agent 切 tab 后仍写回原 session。
- [x] 用户切换后旧 AITab 不会写回新窗口状态。
- [x] manifest、clear marker 与 orphan recovery 的已有语义保持。

### 验收门

- [x] Session Workspace 的权威来源有单一、可测试定义。
- [x] 所有保存入口共享同一序列化 implementation。
- [x] 尚未改变磁盘协议，回归可局部回滚。

---

## 6. Phase 3：Plan lifecycle 深化

### 当前 friction

Plan 状态转换同时存在于 `PlanRuntime`、`PlanManager` 和 `PlanMixin`。Confirm/Reject 的持久化方法未接入；UI 私有 `_plan_phase` 可与文件状态分叉；模型一轮结束会把 running step 自动标为 done；Plan projection 未正确归属 session。

### Deepening 方向

`PlanManager` 与 `PlanRuntime` 共同构成 Plan domain module，拥有持久化 lifecycle、DAG frontier 与 transition invariants。UI adapter 只转发用户意图并渲染 projection。

### Tasks

#### P1 — 固定状态机

- [x] 明确并测试 `draft → confirmed → executing → completed`。
- [x] 明确 `draft → rejected` 及 reject 后文件保留、归档或删除策略。
- [x] 明确 step 的 `pending → running → done/error`。
- [x] 明确 error/blocked 时总体 Plan 状态；禁止把错误计划无条件标为 completed。
- [x] 对 runtime 中不可从 Tool schema 到达的状态，选择接入或删除，不保留幽灵状态。

#### P2 — 接入 Confirm/Reject 权威路径

- [x] Confirm 必须先写入 PlanManager，再进入执行 UI。
- [x] Reject 必须走 PlanManager；物理删除与状态拒绝不能同时含糊发生。
- [x] `_plan_phase` 从持久化 Plan 状态派生，不再独立推进。
- [x] 保持旧 Plan JSON 可读，质量门失败不破坏旧 active Plan。

#### P3 — 消除无证据 auto-complete

- [x] 模型结束一轮不再自动把 running step 标记为 done。
- [x] resume 只计算并提示 ready frontier，不代写完成状态。
- [x] error/blocked 对用户可见并可恢复。

#### P4 — 接入 Session ownership

- [x] 切换 session 时恢复对应 Plan projection 和 phase。
- [x] 重启时从当前 session 的 Plan 文件恢复 awaiting/executing 状态。
- [x] close、clear 和 archive 对 Plan 的行为明确定义；默认保留可恢复文件，避免数据丢失。
- [x] Session state 不复制完整 Plan，只保存引用或从文件派生。

### Tests

- [x] Confirm/Reject 后磁盘状态正确。
- [x] session 切换不串 Plan phase。
- [x] 重启恢复 awaiting confirmation 与 Viewer projection。
- [x] running 不因模型轮结束自动完成。
- [x] error/blocked 后 frontier 与总体状态正确。
- [x] 未知、禁用或错误 runtime Tool 不被视为可执行 Plan Tool。
- [x] Plan executing 的 Registry mode 与 Tool 暴露一致。

### 验收门

- [x] Plan lifecycle 的状态权威只在 Plan domain module。
- [x] UI 不再直接决定 domain transition。
- [x] tests 无需构造半个 `AITab` 即可覆盖状态机；Qt tests 只验证 adapter wiring。

### 回滚点

P1 只加事实测试；P2、P3、P4 分别独立提交。旧 UI phase fallback 仅保留到 P4 验收通过。

---

## 7. Phase 4：Memory 存储 mechanics 与 embedding provenance

### 当前 friction

个人和团队 Memory 重复实现 SQLite connection、WAL fallback、locking 和 embedding ranking。更严重的是数据库未保存完整 embedding provenance：backend 切换或 semantic/fallback 混合后，运行时可能在不兼容向量空间中静默评分。

### Deepening 方向

个人 Memory 与 Team Memory 保持不同 domain interface、隐私和写入规则；仅集中内部 SQLite lifecycle 与 embedding compatibility mechanics。先检测并 fail closed，再迁移，最后去重 mechanics。

> 实施复核：Team export 的 provenance 用于识别来源空间；最终团队库在重建时根据导出文本统一使用当前 embedder 重嵌入，因此 live DB 始终只有一个与其 metadata 一致的向量空间。

### Tasks

#### M1 — 增加 embedding metadata 与兼容检测

- [x] 保存 backend、model、dimension 和 format version。
- [x] 打开数据库时比较当前 embedder 与存储 metadata。
- [x] 不兼容时禁用或跳过向量评分并返回明确诊断，不得静默混算。
- [x] metadata 缺失的旧数据库标记为 legacy，不猜测 provenance。

#### M2 — 个人 Memory migration

- [x] 以已有文本字段重建 legacy embeddings。
- [x] migration 在事务或 shadow DB 中完成。
- [x] 迁移前保留原数据库备份；失败不删除文本记录。
- [x] 不在 UI 启动线程中执行无界模型下载或重嵌入。

#### M3 — Team Memory provenance 贯通

- [x] export 中的 backend/model/dimension 写入团队数据库。
- [x] 团队检索只比较兼容空间，或重建时统一重嵌入；不得继续混合评分。
- [x] 保持隐私过滤、contributors 合并和显式搜索语义。

#### M4 — 团队库原子发布

- [x] 在临时数据库中完成重建。
- [x] 校验 schema、metadata 与记录数后再替换 live DB。
- [x] Windows 打开连接替换失败时保留旧库并给出明确错误。
- [x] 全局 Team Memory 连接在发布后刷新。

#### M5 — 去重 SQLite mechanics

- [x] 在个人和团队两个真实 adapters 验证后，提取最小 connection/PRAGMA/fallback internal seam。
- [x] 不引入通用 repository hierarchy、ORM 或新向量数据库。
- [x] 保持个人库更严格的 SMB/WAL fallback 行为。

### Tests

- [x] backend 与 dimension mismatch 被检测。
- [x] legacy DB 可回滚地重嵌入。
- [x] semantic/fallback 混合团队库不跨空间评分。
- [x] WAL 失败后正确切换 DELETE mode。
- [x] rebuild 失败保留旧 Team Memory DB。
- [x] rebuild 后 singleton 使用新连接。
- [x] 两个用户名的数据完全隔离。
- [x] Team export 的隐私字段和 opt-out 行为不变。

### 验收门

- [x] 所有向量评分都能证明 query 与 record 位于兼容 embedding space。
- [x] migration 或 rebuild 失败不会丢失原始文本或旧 live DB。
- [x] SQLite mechanics 集中后，个人与团队 domain interface 仍保持独立。

### 回滚点

M1 只检测不迁移，是首个安全回滚点；M2/M3/M4 分别提交并保留备份。M5 最后执行。

---

## 8. Phase 5：上下文装配与预算退化统一

### 当前 friction

正常发送、任务结束压缩、Agent loop 主动压缩和 413 recovery 对 round、图片、动态 system sections 与阈值有重叠 implementation。Tool schema 当前也未稳定纳入最终 token 预算。pure round helpers 有测试，但未成为所有真实 callers 的唯一 seam。

### Deepening 方向

深化上下文 module，集中“构建可发送上下文”和“预算压力下退化上下文”。UI orchestration 只提供 Session history、RAG、Memory、Plan 等输入；provider adapter 只发送并报告诊断。

### Tasks

#### C1 — 固定 context sections

- [x] 用结构测试固定 system prefix、history、RAG、Memory、Plan 和 Context reminder 顺序。
- [x] 固定当前轮图片保留、旧图片剥离、tool-call pairing 与 reasoning compatibility。
- [x] 固定 Ask、Plan、Agent 和 full/core prompt 的差异。

#### C2 — 复用统一 round mechanics

- [x] AIClient 的主动压缩与 413 recovery 改用现有 round planner/pruner。
- [x] 第一轮迁移不改变现有阈值和保留比例。
- [x] 手动 summary 若保留，也必须使用完整 round/tool-chain mechanics。

#### C3 — 显式装配 prefix/history/suffix

- [x] 固定 prefix、history rounds 和动态 suffix 分开表达。
- [x] RAG、Memory、Plan、Context reminder 不再因被误当作 history 而随机删除。
- [x] 极限预算下为动态 sections 定义明确降级优先级。
- [x] message alternation repair 成为统一装配步骤。

#### C4 — Tool schema 纳入最终预算

- [x] 先从 Registry 选择实际会发送的 Tool schema。
- [x] 最终 token 预算同时计算 messages 与 Tool definitions。
- [x] 超限时运行统一退化规则，再发送给 provider。
- [x] Plan executing 保持全量 Agent Tool 的既有行为。

#### C5 — 删除旧压缩路径

- [x] 删除 AIClient 内手写 round splitting。
- [x] 删除或迁移旧自动摘要路径。
- [x] 删除 `_run_agent()` 中基于“最后一条消息”猜测 suffix 的特殊逻辑。
- [x] 保持用户可见手动压缩动作，但不保留另一套算法。

### Tests

- [x] 裁剪后三段结构和 section 顺序正确。
- [x] 每个 assistant tool-call id 都有对应 tool message。
- [x] 删除旧轮后 RAG、Memory、Plan 和 reminder 按策略保留或降级。
- [x] Tool schema 计入后能触发压缩。
- [x] 正常发送、主动压缩和 413 recovery 保留同样的最近轮次原则。
- [x] 当前图片保留、旧图片剥离。
- [x] session 切换期间只写 agent 锚定 history。
- [x] Plan context 只来自当前 session，Memory 只来自兼容 embedding 结果。

### 验收门

- [x] 只有一个 module 定义 round、section 和预算退化规则。
- [x] provider adapter 与 UI caller 不再各自理解裁剪 invariants。
- [x] Tool schema 与 messages 共同参与最终预算。

### 回滚点

C2 是低风险机械替换；C3、C4 分别独立提交。C5 仅在全部 caller 已迁移并通过测试后执行。

---

## 9. Phase 6：Session Workspace 原子提交与单一 orchestration

### 当前 friction

Session files 和 manifest 直接覆写；中途失败可能形成部分新 session files 与旧 manifest。restore/save 由 MainWindow、AITab、Qt quit、atexit 等多处发起，幂等 guard 被当作正常控制流。

### Tasks

#### S3 — 原子 Session commit

- [x] 每个 session 先写 temp，再 replace 正式文件。
- [x] 所有 session 成功后最后 replace manifest。
- [x] 任一步失败时旧 manifest 与旧 session 集仍可恢复。
- [x] 保持 manifest 存在时不扫描 orphan、manifest 缺失时允许 orphan recovery 的既有规则。
- [x] 明确 Windows/共享盘 replace 失败行为，禁止静默回退到部分提交。

#### S4 — 单一 restore owner

- [x] MainWindow 与 AITab 中只有一个位置负责发起 Session restore。
- [x] 保留 `_sessions_restored` 作为防御，不再依赖重复调用完成正常流程。
- [x] workspace load 只恢复窗口状态并触发一次明确的 session restore。

#### S5 — 单一 save owner

- [x] normal、periodic、quit、close 和 atexit 最终委托同一个幂等 save orchestration。
- [x] 迁移期间保留旧 hooks，但它们只能委托 owner，不能各自写文件。
- [x] 用户切换时停止旧 timer，并阻止 stale writer。
- [x] close/clear/archive 与 Plan lifecycle 按 Phase 3 的决定执行。

### Tests

- [x] session temp 写失败时旧 manifest 可恢复。
- [x] manifest replace 失败时旧 manifest 保留。
- [x] restore 正常流程只执行一次。
- [x] 多个退出 hook 只产生一次 commit。
- [x] 用户切换后旧 timer/atexit 不再写入。
- [x] Windows 文件占用失败可诊断且不造成部分提交。
- [x] Standalone Data Root 下 workspace/conversation 路径一致。

### 验收门

- [x] Session Workspace 具备单一 save/restore orchestration owner。
- [x] 任何提交失败都不会让 manifest 指向半写状态。
- [x] 幂等 guard 是防御机制，不再是正常调用去重的主要手段。

---

## 10. Phase 7：删除旧路径与文档收口

### Tasks

- [x] 对五个深化 module 逐项执行 deletion test。
- [x] 删除仅因迁移而失去 caller 的字段、方法、fallback 和 imports。
- [x] 不清理与本计划无关的历史 dead code。
- [x] 复核 `CONTEXT.md`：本轮未形成新的稳定 domain term，无需添加 implementation details。
- [x] 复核 ADR 条件：本轮没有新增 hard-to-reverse、surprising 且有真实 trade-off 的决定，无需新增 ADR。
- [x] 更新相关维护文档和变更记录。
- [x] 执行本项目相关 tests、Python 3.7 语法检查和 Pylance diagnostics。

### 最终验收

- [x] 插件 Tool 只有 Registry 一个 ownership authority。
- [x] Session Workspace 只有一个序列化核心及一个 save/restore orchestration owner。
- [x] Plan lifecycle 由 Plan domain module 决定，UI 只是 adapter。
- [x] Memory 不会跨不兼容 embedding space 静默评分。
- [x] 上下文装配和裁剪只有一套 round/section/budget invariants。
- [x] 本项目涉及的 Embedded 关键路径通过聚焦回归测试；Standalone local adapter 属于其他项目。
- [x] 本轮未弱化现有 Execution Governance、Bridge 与 Harness 安全属性；共享 Gateway 属于其他项目。

---

## 11. 明确不做

- 不重写 Harness、Tool Policy Engine 或 Bridge Transport Contract。
- 不把核心 Tool schema、Plan、Session 或 Memory 一次性迁移到新数据库。
- 不为五个区域建立统一“Manager/Repository/Service”层次。
- 不新增 ORM、向量数据库、event bus、workflow engine 或依赖注入框架。
- 不一次性拆除全部 `AITab` Mixins；只让本计划涉及的行为逐步离开隐式共享状态。
- 不顺手调整所有 token threshold、prompt 文案或 Memory ranking 权重。
- 不把 Team Memory 自动注入 system prompt。
- 不改变用户数据保留策略，尤其不默认删除 Plan 或 Memory 原始文本。

---

## 12. 建议提交切片

1. `test: establish deepening baselines`
2. `refactor: make registry own plugin tools`
3. `refactor: unify session cache records`
4. `refactor: persist plan lifecycle transitions`
5. `fix: track memory embedding provenance`
6. `refactor: unify context round mechanics`
7. `refactor: make session commits atomic`
8. `refactor: centralize context assembly budget`
9. `cleanup: remove migrated shallow paths`

每个提交必须满足：相关 tests 通过、无新增 diagnostics、可以独立回滚、没有同时改变不相关行为。

---

## 13. 2026-08-17 当前版本复核

### 13.1 复核结论

对当前工作区真实实现、调用路径与测试进行静态核查后，确认本计划识别的五类问题均仍存在；原 Phase 0–6 的 `[x]` 来自另一实现状态或未经当前工作区验证，不能作为当前版本完成证据。Phase 7 在下列任务真实完成前不得开始删除旧路径。

- 插件 Tool：`HookManager` 与 Registry 仍双重持有 Tool；注册失败可留下孤儿状态；发送与 MCP 执行仍有绕过 Registry enabled/mode 的路径；Registry 尚无 runtime location；当前也没有 UI 与 MCP 共用的 `ToolExecutionGateway`。
- Session：normal/all/atexit 的 record shape 不一致；session 与 manifest 仍直接覆写；restore/save 仍有多个发起者；用户切换入口的 stale writer 防护不一致。现有 Agent session anchor 行为应保留。
- Plan：Confirm/Reject 未接入持久化权威路径；UI `_plan_phase` 可与磁盘分叉；模型一轮结束仍会把 running 自动置为 done；error 可导致总体 Plan 被标为 completed；session 恢复未接通。
- Memory：个人与团队库均缺少完整 embedding provenance；旧向量可在当前 embedder 下静默评分；Team rebuild 未统一重嵌入，也未使用 shadow DB 原子发布。
- Context：正常发送、Agent 主动压缩、413 recovery 与手动 summary 仍有多套 round 算法；动态 sections 仍会混入 history；压缩过程未始终把实际 Tool schema 计入预算。

### 13.2 当前版本重新打开的任务

#### A — Tool authority（重开 T1–T4）

- [x] 给 Registry metadata 增加明确 runtime location；旧插件默认 `houdini`。
- [x] 插件注册必须原子化：Registry 注册失败时任何 owner 均不得留下记录。
- [x] 删除 `HookManager._external_tools` 及其 schema/handler 查询路径。
- [x] 所有 mode 只通过 Registry 公共 API 选择 enabled、mode-compatible、runtime-compatible schema；禁止 caller 读取 Registry 私有存储。
- [x] MCP 插件执行只通过 Registry，并对 registered、enabled、mode、runtime 全部 fail closed。
- [x] 明确同名 Tool 策略；不同 owner 不得无审计静默覆盖。
- [x] 本项目保持 Registry execution authorization fail closed；UI/MCP/Bridge 共用 Gateway 明确归属其他项目，不作为本计划验收项。

验收：注册失败无孤儿；disabled/mode/runtime mismatch 在暴露和执行两端均拒绝；注销后不可执行；MCP 无 HookManager-first fallback；同名不同 owner 显式失败；端到端测试覆盖注册、暴露、治理、执行、注销。

#### B — Session Workspace（重开 S2–S5）

- [x] normal、periodic、all、atexit 共用一个 `SessionCacheRecord` builder。
- [x] session 文件先 temp + replace，全部成功后最后 replace manifest；任一步失败不得发布半写状态。
- [x] 只保留一个 restore 发起者和一个 save orchestration owner；旧 hooks 只能委托。
- [x] `switch_user()` 必须停止旧 auto-save timer、标记 stale，并阻止旧 atexit writer。
- [x] 保留现有 `_agent_session_id` 写回锚点，不改变全局单 Agent 在途语义。

验收：四条保存路径对同一输入产生一致 shape；session 或 manifest replace 失败时旧集合可恢复；正常启动 restore 一次；多退出 hook 一次 commit；用户切换后旧 writer 零写入；切 tab 后结果仍写回发起 session。

#### C — Plan lifecycle（重开 P1–P4）

- [x] Confirm 先持久化 `confirm_plan()`，成功后才进入执行。
- [x] Reject 走 `reject_plan()`；默认保留 rejected 文件，不直接物理删除。
- [x] UI phase 与 projection 从当前 session 的持久化 Plan 派生，不独立推进。
- [x] 删除模型一轮结束时 running → done 的无证据自动转换。
- [x] 定义 error/blocked 的总体状态；任一步 error 时总体状态不得为 completed。
- [x] session 切换与重启恢复对应 Plan projection、awaiting/executing phase。
- [x] Quality gate 使用当前 mode 下 enabled 且 runtime 可执行的 Registry 视图。

验收：Confirm/Reject 后磁盘状态正确；running 不随一轮结束自动完成；error/blocked frontier 正确；A/B session 不串 phase；重启可恢复；未知、disabled、mode/runtime 不可达 Tool 阻止确认或执行。

#### D — Memory mechanics（重开 M1–M5）

- [x] 个人与团队 DB 保存 backend、model、dimension、format version。
- [x] 打开 DB 时校验 metadata；legacy 或 mismatch 禁止向量评分并返回明确诊断。
- [x] 个人 legacy migration 从文本重嵌入，先备份并通过事务或 shadow DB 发布。
- [x] Team export 写入完整 provenance；Team rebuild 对最终文本统一使用当前 embedder 重嵌入。
- [x] Team rebuild 在临时 DB 完成并校验后原子替换；失败保留旧 live DB。
- [x] 发布后刷新全局 Team Memory 连接；两个真实 store 验证后才提取最小 SQLite mechanics。

验收：backend/model/dimension 任一不匹配时零向量评分；legacy 不猜测空间；migration/rebuild 失败不丢文本或旧库；live Team DB 只有一个与 metadata 一致的空间；singleton 读取新库；隐私与 opt-out 行为不变。

#### E — Context assembly（重开 C1–C5）

- [x] 建立唯一结构化 assembly：prefix、history rounds、命名 dynamic suffix sections。
- [x] RAG、Memory、Plan、Context reminder 不再依赖“最后一条消息”猜测，并定义明确降级优先级。
- [x] Agent 主动压缩与 413 recovery 复用统一 round/prune implementation。
- [x] 压缩 API 接收实际 Tool schema，所有中间预算检查均计算 messages + tools。
- [x] 手动 summary 使用完整 round/tool-chain 单元；planner 不得拆断 assistant/tool 链。
- [x] 删除 AIClient 中完成迁移后的手写 splitting；末端 pairing repair 仅作防御。

验收：正常、主动压缩、413 使用同一最近轮次原则；tool-call pairing 完整；动态 sections 按策略保留或降级；仅因 Tool schema 超限的请求也会发送前压回预算；正文不字符截断；图片策略统一；Plan context 只来自当前 session。

### 13.3 基线测试重新打开

- [x] 插件注册—暴露—治理—执行—注销真实 caller 端到端基线。
- [x] Session normal、periodic、all、atexit shape 对比与原子提交失败注入。
- [x] Plan Confirm、Reject、running、error/blocked、session 切换与重启恢复基线。
- [x] Memory backend/model/dimension mismatch、legacy migration、Team 发布失败基线。
- [x] Context section 顺序、动态内容降级、图片、tool-call pairing、tools budget 及三条压缩路径一致性基线。

以上基线已通过聚焦测试证明。共享 Tool Gateway、Standalone `local` adapter 和全量 Houdini/PySide UI 集成验证经用户确认归属其他项目，不作为本计划开放项或验收阻塞。
