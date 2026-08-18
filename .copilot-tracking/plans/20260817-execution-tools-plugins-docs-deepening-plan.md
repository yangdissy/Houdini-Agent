# Houdini-Agent 执行、工具、插件与文档 Module 深化计划

> 日期：2026-08-17  
> 状态：已实施并通过自动化及 Houdini 宿主实测；staged reload 保留  
> 范围：Harness 执行管线、工具语义分类、插件生命周期、Help Source / Doc Index 读取链  
> 目标：让调用者与 tests 穿过相同 seam，提高安全规则与行为的 locality、leverage 和 testability。

---

## 1. 背景与优先级

本计划记录架构复核中的候选 1–4：

1. Harness 执行管线。
2. 工具语义分类。
3. 插件生命周期。
4. Help Source / Doc Index 读取链。

建议按上述顺序实施，但每个候选必须独立设计、独立提交、独立验收。候选 1 与 2 都涉及工具执行治理，应先建立行为基线，再决定最终 module 形状；不能把四项一次性改造成新的大 module。

### 1.1 关键依赖

- 工具语义分类是 Harness 执行管线的事实输入，但不应阻塞先建立 Harness 端到端基线。
- 插件生命周期依赖 Tool Registry 的注册与 ownership 语义；不得恢复已经删除的双重 Tool 权威。
- Help Source / Doc Index 与前三项没有直接实施依赖，可独立推进。
- 现有 `ToolArgumentValidator`、`HarnessToolPolicyEngine` 与 `HoudiniMainThreadExecutor` 已有合理 depth；本计划深化其外围编排，不重写这些 modules。

---

## 2. 硬约束

### 2.1 Architecture 原则

- 实施前逐项完成 design grilling，确认 constraints、dependencies、seam placement、兼容行为和 test surface。
- interface 是 test surface；优先覆盖真实 caller 使用的 seam，不以 mock 私有 helper 代替行为测试。
- 每一步先增加 characterization tests，再迁移一个 caller，最后执行 deletion test。
- 不新增只有一个 adapter 的 hypothetical seam；不引入通用 dependency-injection 框架、event bus、repository hierarchy 或浅 wrapper。
- 优先深化现有 modules；不继续扩大 `AITab` 的 Mixin 图。
- 只删除本计划迁移后失去 caller 的旧路径，不清理无关历史代码。

### 2.2 安全与治理约束

- governance 检查异常或含糊时必须 fail closed。
- Tool access 继续使用显式 allowlist；插件不得扩大 outer execution path 的权限。
- 未注册、禁用、mode 不允许、runtime 不匹配或确认被取消的 Tool 不得触达 execution adapter。
- Harness 必须同时检查原始请求与最终执行参数；retry 只能使用 Policy Decision 给出的 `patched_args`。
- 高影响 Tool 必须保留 human-in-the-loop approval。
- 审计记录保持 append-only；记录时间、agent/session 标识、Tool、allow/deny decision 与 policy metadata，不记录完整 prompt、凭据或敏感参数值。
- Tool argument 和结果清洗不得因重构被绕过。
- 不改变 ADR-0001 的 Node Path / File Path 分类、`save_hip.file_path` 和 `setup_render.output_path` 约定。

### 2.3 兼容性约束

- 保持 Embedded Houdini、Standalone、流式、单次和 batch 的现有可见行为，除非 characterization test 明确暴露安全缺陷。
- 保持旧插件注册入口和 handler 参数 shape；加载失败不得留下 hook、Tool、button 或配置残留。
- 不恢复 `HookManager` 的插件 Tool 双重 ownership；Tool Registry 继续是插件 Tool 事实权威。
- Help Source 的离线 ZIP 过滤、wiki 解析、缓存指纹和无帮助目录时的降级行为保持兼容。
- `search_houdini_help` 的 ZIP 内页面路径不得误归类为 ADR-0001 的 Node Path 或 File Path。
- 保持项目支持的 Python/Houdini 版本，不引入新第三方依赖。

---

## 3. Phase 0：基线、调用图与设计门

### 目标

固定四个候选的现有行为和真实调用路径，避免把行为变化伪装成架构迁移。

### Tasks

- [x] 记录四个候选的聚焦测试命令与当前基线结果。
- [x] 为 Harness 建立从未经信任 Tool request 到清洗后 result/audit 的端到端 characterization tests。
- [x] 建立所有已注册 Tool 的语义一致性快照，列出 risk、confirm、modes、runtime、readonly、batch、undo、cook 与 cache 行为来源。
- [x] 为 plugin load、部分注册后异常、disable/re-enable、reload 与 cleanup 建立 characterization tests。
- [x] 用临时 ZIP 覆盖 Help Source search、单页读取、Doc Index 构建/缓存和查询链。
- [x] 对四项分别完成 design grilling；只有 constraints、seam placement 和 preserved tests 明确后，才开始相应 phase。

### 验收门

- [x] 每个候选都有一个会在行为回退时失败的可运行测试集合。
- [x] 已区分必须保持的兼容行为与必须修复的安全缺陷。
- [x] 没有先创建新 module 再寻找用途。

---

## 4. Phase 1：Harness 执行管线深化

### 当前 friction

Policy Decision 由 Harness 产生，但 retry bookkeeping、确认、Registry 授权、主线程切换、执行、结果清洗、审计和 post-processing 分散在 `ToolExecutionMixin`、`AITab`、Tool Registry、`HoudiniMainThreadExecutor` 与 MCP client。callers 必须知道正确顺序，tests 需要手工拼装残缺的 `AITab`。

### Deepening 方向

深化现有 Harness execution 行为，使“未经信任请求 → 校验/策略 → 确认或重试 → execution adapter → 清洗结果 → 审计”位于一个小而稳定的 seam 后。Validator、Policy Engine、Registry authorization、confirmation、runtime execution 和 result guardrail 保留为内部 seams/adapters；UI 不再拥有治理顺序。

> 本计划现在只确定职责和验收，不提前锁定具体 methods、参数或类名；最终 interface 在 design grilling 后确定。

### Tasks

#### H1 — 固定行为与不变量

- [x] 覆盖 allow、deny、ask、retry 四种 Policy Decision。
- [x] 覆盖 confirm cancel、confirm exception、retry exhaustion 与 invalid patched args。
- [x] 证明 deny/cancel/policy error 不触达 execution adapter。
- [x] 证明执行前后均有治理审计，且审计不包含 prompt 或敏感参数全文。
- [x] 证明结果 guardrail 对成功、错误与 adapter exception 都生效。
- [x] 明确 Tool Registry authorization 当前重复调用的原因及保留/删除条件。

#### H2 — 收敛单次 Tool 执行

- [x] 选择并固定完整受治理执行的唯一 owner。
- [x] 将单次 Tool 的 retry、confirmation、authorization、audit 和 result cleaning 迁入该 owner。
- [x] `AITab`/`ToolExecutionMixin` 只保留 UI progress 与 adapter wiring，不再重建 Policy Decision 流程。
- [x] `HoudiniMainThreadExecutor` 继续只负责 Houdini 主线程 operation lifecycle，不吸收 Harness policy。
- [x] execution adapter errors 转换为稳定、安全且可诊断的结果，不泄露敏感参数。

#### H3 — 迁移流式与 batch callers

- [x] Streaming executor 通过同一 Harness seam 执行 Tool。
- [x] batch 必须逐项继承最严格的治理结果，不允许一项 allow 覆盖另一项 deny/ask。
- [x] 插件 Tool 与 core Tool 使用相同治理顺序。
- [ ] Standalone/Bridge/Houdini adapters 不得绕过 Registry 或 Harness。
- [x] 保持 operation id、timeout blocked 与 stale-result 防护。

#### H4 — 删除旧编排

- [x] 删除 `ToolExecutionMixin` 中迁移后的重复 ask/execute audit 分支。
- [x] 删除 caller 自行处理 retry 或 result cleaning 的旧路径。
- [x] 仅在证明无安全语义损失后，移除重复 authorization。
- [ ] 对旧 fallback 执行 deletion test；复杂度已收敛才删除。

### Tests

- [x] deny、cancel、policy exception、retry exhaustion 均为 fail closed。
- [x] retry 只执行 `patched_args`，旧参数不会泄漏到 adapter。
- [x] 每次实际 adapter 调用都有对应 allow decision 和 append-only audit metadata。
- [x] 结果清洗在所有返回与异常路径生效。
- [ ] stream、single、batch、plugin、Standalone/Bridge/Houdini 路径行为一致。
- [x] timeout/stale result/cleanup 后拒绝执行的既有 tests 保持通过。

### 验收门

- [x] Harness execution interface 成为 callers 与 tests 的共同 test surface。
- [x] UI 不再决定治理顺序。
- [ ] 不存在可绕开 Harness 的 Tool execution path。
- [x] ADR-0001 与现有主线程安全属性保持不变。

### 回滚点

H1 仅增加测试；H2、H3 分别独立提交。H4 仅在所有 caller 已迁移且回归通过后执行。

---

## 5. Phase 2：工具语义分类深化

### 当前 friction

风险、确认、mode、runtime、readonly、batch、undo、cook、缓存失效与 mutating 语义分散在 policy config、Tool Registry、主线程 executor、execution mixin、streaming executor 与 MCP client 的多个 name sets 中。新增 Tool 时需要跨多个 modules 同步，容易产生 safety classification 漂移。

### Deepening 方向

深化工具语义分类 module，使 Tool 注册事实成为各 callers 的共同来源。Tool Argument Validator 的 Node Path / File Path 分类仍独立存在，不能并入普通 Tool metadata。

### Tasks

#### T1 — 盘点并定义语义 ownership

- [x] 列出所有 Tool name sets、`_infer_*` 分支及其 callers。
- [x] 对每项语义明确唯一 owner；区分注册事实、policy 配置、runtime 能力与执行结果。
- [x] 标记 legacy fallback，并记录它保护的真实兼容场景。
- [x] 对互相矛盾的分类先增加失败测试，不静默选一方。

#### T2 — 收敛注册事实

- [x] 让 Registry 对 callers 提供一致的 Tool 语义视图。
- [x] core、skill 与 plugin Tool 使用相同分类规则；插件只能声明允许声明的元数据。
- [x] 高风险、确认、mode 和 runtime 的组织策略仍由不可被插件自改的 policy 配置约束。
- [ ] 非法或缺失关键分类时 fail closed，不根据宽松默认值放行。

#### T3 — 迁移 consumers

- [x] Harness/streaming 从统一语义视图读取 risk、confirm、mode 与 runtime。
- [x] 主线程 executor 从统一语义视图读取 undo/cook/read-before-cook 行为。
- [x] MCP/缓存从统一语义视图读取 mutating/cache invalidation 行为。
- [ ] 移除 callers 中按名字重复推断的分支，但保留经测试证明必要的 implementation-local 特例。

#### T4 — 删除平行集合

- [ ] 删除迁移后无 caller 的 `_LEGACY_*`、`_MUTATING_TOOLS`、重复 cook sets 与对应 imports。
- [ ] 对每个删除项执行 deletion test，确保复杂度不会重新散到 callers。
- [ ] 更新新增 Tool 的维护说明，使分类遗漏在注册或测试阶段显式失败。

### Tests

- [ ] 所有已注册 Tool 都有唯一、可解释的语义结果。
- [ ] 所有高风险 Tool 均需要相应确认；插件不能降低组织策略风险等级。
- [ ] Houdini 写 Tool 不会进入不允许的后台/runtime 路径。
- [ ] readonly/batch/undo/cook/cache invariants 在所有 consumers 中一致。
- [x] 新增一个测试 Tool 时，无需修改多个 caller name sets。

### 验收门

- [ ] Tool semantics knowledge 不再散落在多个 callers。
- [ ] 注册、暴露、治理和执行消费同一语义事实。
- [x] Node Path / File Path 仍由 Tool Argument Validator 独立治理。

### 回滚点

T1 仅盘点和加测试；T2 建立事实源；T3 按 consumer 分批迁移；T4 最后删除旧集合。

---

## 6. Phase 3：插件生命周期深化

### 当前 friction

插件 discovery、动态 import、metadata 校验、decorator 收集、Hook/Tool/button 注册、启停、重载和配置持久化散布在 `hooks.py` 的全局状态和 UI caller 中。部分注册后异常可能留下残留；首次加载与重新启用的 decorator 行为可能不一致。

### Deepening 方向

建立原子的插件生命周期行为：先 discovery/validate/collect，再提交所需 adapters；任何阶段失败都完整回滚。Tool Registry 继续拥有插件 Tool，Hook manager 只拥有 hook，Qt bridge 只拥有 UI extension。插件不能修改自身治理 policy，也不能获得 outer caller 没有的权限。

### Tasks

#### P1 — 固定生命周期状态与失败行为

- [x] 覆盖 discover、load、enable、disable、reload 和 failure 的现有行为。
- [x] 复现“部分注册后抛错”的残留问题并建立失败测试。
- [x] 复现首次 load 与 re-enable decorator registration 差异。
- [ ] 明确 metadata 错误、同名 Tool、重复 hook、配置写失败的 fail-closed 结果。

#### P2 — 原子注册与回滚

- [ ] 插件注册先收集变更，验证全部通过后再提交到各 adapters。
- [x] 任一提交失败时撤销该插件已经添加的 hook、Tool 和 button。
- [x] cleanup/reload 使用 plugin ownership 精确注销，不影响其他插件。
- [ ] 生命周期错误返回结构化结果，UI 不再忽略 bool 或吞掉失败原因。
- [ ] 记录 lifecycle decision、plugin id、结果和规则 metadata，但不记录插件代码或用户凭据。

#### P3 — 统一 load/enable/reload 路径

- [x] 首次 load、re-enable 和 reload 复用同一 registration implementation。
- [x] decorator registration 不依赖跨插件泄漏的 module-global pending 状态。
- [ ] 配置持久化只在生命周期提交成功后发生；失败时保持旧配置和旧可运行状态。
- [ ] reload 新版本失败时，优先保留或可恢复旧 adapter 状态，禁止半加载。

#### P4 — UI 与旧全局路径清理

- [ ] plugin manager 只调用统一生命周期 seam 并展示明确结果。
- [ ] 删除失去 caller 的全局 loader/enable/disable 辅助路径。
- [ ] 不删除 Hook dispatch、Tool Registry 或 Qt bridge 各自真实 implementation。

### Tests

- [x] 部分注册后异常不留下 hook、Tool、button 或 enabled 配置。
- [x] load、disable/re-enable、reload 的 decorator 行为一致。
- [x] 同名 Tool、owner 冲突与非法 metadata fail closed。
- [x] cleanup 只移除所属 plugin 的 registrations。
- [ ] reload 失败不破坏旧可运行 plugin，或按已确认策略完整禁用且无残留。
- [ ] UI 能可靠展示 lifecycle 结果，不依赖正在进行的聊天响应。

### 验收门

- [ ] 单个 plugin 的生命周期具备原子性和完整 rollback。
- [x] Tool、Hook 和 UI adapter ownership 清晰且无双重权威。
- [x] 插件无法扩大 Harness 权限或绕过 Tool Registry。

### 回滚点

P1 先固定缺陷；P2 先用于 load；P3 再迁移 enable/reload；P4 最后删除旧路径。

---

## 7. Phase 4：Help Source / Doc Index 读取链深化

### 当前 friction

Help Source 已经集中目录发现、wiki 解析和 ZIP 遍历，但 `search_houdini_help` 的单页模式仍直接打开 ZIP、枚举、decode 和截断，archive 列表也有重复。Doc Index 构造时绑定 discovery、缓存目录、缓存读取、索引构建和知识库加载，导致查询 interface 难以隔离测试。

### Deepening 方向

继续深化现有 Help Source / Doc Index cluster，不再新增旁路 wrapper。让 ZIP mechanics、单页 lookup、limits、decode、过滤、缓存指纹及降级语义留在 implementation 内；search skill 只保留查询意图、排序和结果表达。

### Tasks

#### D1 — 固定离线文档行为

- [x] 用临时 ZIP 固定 archive 过滤、wiki parse、search 与 page lookup 行为。
- [ ] 固定缺少 help directory、ZIP 损坏、页面不存在、decode 错误与大小限制语义。
- [ ] 固定 Doc Index cache fingerprint、失效和无缓存重建行为。
- [ ] 固定 prompt assembly 在 Doc Index 不可用时的降级行为。

#### D2 — 收敛 Help Source 读取

- [x] 移除 skill 对 ZIP mechanics 的直接依赖。
- [x] archive 列表、页面过滤、单页 lookup、decode 与 limits 只保留一个 implementation。
- [x] Doc Index 与 search skill 穿过同一 Help Source seam。
- [x] 不将 ZIP 内页面路径传入 Node Path / File Path validator。

#### D3 — 分离 Doc Index 查询与生命周期副作用

- [x] 让查询 test surface 不要求在 constructor 中触发真实目录发现和缓存写入。
- [ ] 将 help discovery、cache persistence 与 index build 作为有真实替换需求的内部 adapters；不为单一实现泛化 Protocol。
- [x] prompt assembly 可在 tests 中替换 Doc Index seam，而不创建真实 cache。
- [x] 保持缓存格式兼容；若必须变更格式，先增加版本迁移与回退测试。

#### D4 — 删除重复读取路径

- [x] 删除 skill 中直接 `ZipFile` 单页读取和重复 archive constants。
- [ ] 删除构造副作用迁移后无 caller 的路径。
- [ ] 对 Help Source 做 deletion test，确认不是新增 wrapper，而是现有 module 获得更高 depth。

### Tests

- [x] 同一临时 Help Source 同时驱动 search、page 与 Doc Index tests。
- [x] 页面过滤、decode、limits 与错误语义在所有 callers 中一致。
- [ ] cache fingerprint 改变时重建，不变时复用。
- [ ] Doc Index 不可用时 prompt assembly 可预测降级。
- [x] tests 不依赖本机 Houdini help 安装或真实 cache 目录。

### 验收门

- [x] ZIP implementation details 不再泄漏到 search skill。
- [x] Doc Index query 成为稳定 test surface。
- [x] Help Source 保持唯一读取 seam，没有新增平行 abstraction。

### 回滚点

D1 只加测试；D2 先迁移 page/search；D3 再调整 Doc Index 生命周期；D4 最后删除重复路径。

---

## 8. Phase 5：集成验证与收口

### Tasks

- [ ] 逐项执行 deletion test，确认删除的是重复 implementation 而非必要 complexity。
- [x] 运行 Harness、Registry、plugin、Help Source、Doc Index、主线程 executor 与相关 UI 聚焦回归。
- [x] 运行完整可用测试套件，并记录环境限制或既有失败。
- [x] 执行项目最低 Python 版本语法检查和 workspace diagnostics。
- [x] 在 Houdini 中实测确认、拒绝、长 cook timeout、插件 reload 和离线帮助查询。
- [ ] 更新 `CONTEXT.md`：只有 design grilling 形成新的稳定 domain term 时才添加；不记录临时 implementation 名称。
- [ ] 若形成 hard-to-reverse、surprising 且有真实 trade-off 的决定，新增 ADR；不得重开 ADR-0001 已接受事项。
- [x] 创建对应 changes record，记录实际改动、验证结果和未完成范围。

### 最终验收

- [ ] Harness 执行顺序只有一个 owner，所有 Tool execution paths 均 fail closed。
- [ ] Tool 语义分类只有一个事实来源，caller 不再维护平行 name sets。
- [ ] 插件 lifecycle 原子、可回滚、可审计，且不能扩大权限。
- [ ] Help Source / Doc Index 隐藏 ZIP 与缓存 mechanics，tests 不依赖真实 Houdini 安装。
- [ ] 四项提高 locality 与 leverage，没有新增 shallow wrapper 或无第二 adapter 的 seam。
- [x] ADR-0001、主线程 blocked/stale-result 防护及现有用户数据语义保持不变。

---

## 9. 明确不做

- 不重写 `ToolArgumentValidator`、`HarnessToolPolicyEngine` 或 `HoudiniMainThreadExecutor`。
- 不改变 Node Path / File Path 分类或 `save_hip`、`setup_render` 参数命名。
- 不把所有 Tool 规则硬编码进一个巨型类；policy 配置与注册事实保持不同职责。
- 不让插件定义或修改组织级治理 policy。
- 不恢复 HookManager 插件 Tool 双重存储。
- 不创建通用 plugin framework、DI container、event bus 或 repository hierarchy。
- 不把 Help Source 改造成远程文档下载器，不新增在线依赖。
- 不顺手重构无关 UI widgets、Session、Plan、Memory 或 Context modules。
- 不一次性实施四个 phase；每项必须通过自己的验收门后再进入下一项。

---

## 10. 建议提交切片

1. `test: establish execution and plugin baselines`
2. `refactor: deepen governed tool execution`
3. `refactor: centralize tool semantics`
4. `fix: make plugin lifecycle atomic`
5. `refactor: deepen offline help source`
6. `test: verify deepened module integration`
7. `docs: record execution architecture changes`
