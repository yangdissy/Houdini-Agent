# Houdini-Agent 更新记录（2026-09-30）

## 发布摘要

本次更新选择性引入参数引用、Multiparm、Object Merge 和 PDG 表达式相关能力。新增工具全部复用现有 Tool Registry、Harness、确认、Houdini 主线程、Undo 和审计执行链，不导入第三方项目的菜单、UI、环境变量或会话状态。

新增能力包括精确参数反向引用查询、参数引用助手、Multiparm 实例枚举与增删、Object Merge 批量引用，以及受白名单约束的 PDG 表达式构建器。

本次不新增运行时依赖，不开放任意 Python 或 shell 执行，也不通过表达式文本扫描猜测参数引用关系。

---

## 一、精确参数引用查询

- 新增 `find_parameter_references`，用于查询直接引用指定标量参数的参数路径。
- 查询使用 Houdini HOM `parmsReferencingThis()` 作为引用关系真源，不解析或猜测表达式文本。
- 返回参数组件级完整路径，并执行去重和稳定排序。
- 节点或参数不存在、Houdini API 不可用以及查询异常时返回结构化错误。
- 工具为只读能力，可在 Ask 和 Plan 规划阶段使用，不修改场景或触发 cook。

---

## 二、参数引用助手

- 新增 `set_parameter_reference`，将目标标量参数设置为指向来源标量参数的相对 HScript 通道引用。
- 使用 `hou.text.relpath()` 计算相对参数路径，并生成 `ch("...")` 表达式。
- 实际写入复用现有 `set_parameter_expression`，保留表达式语言处理和旧值快照。
- tuple 参数需显式使用具体分量名，避免隐式广播或错误引用整个参数元组。
- 工具被标记为场景变更，需要确认并支持 Houdini Undo，不会进入 Ask 模式。

---

## 三、Multiparm 实例管理

### 实例查询

- 新增 `list_multiparm_instances`，返回实例数量、零基索引和每个实例的实际参数路径。
- 使用 `multiParmInstanceIndices()` 作为实例分组依据，不假设每个实例具有固定参数数量。
- 查询不读取实例参数值，不修改场景。
- 缺少实例索引信息时 fail closed，不根据参数命名猜测所属实例。

### 实例插入与删除

- 新增 `insert_multiparm_instance`，允许在 $0 \le i \le count$ 的零基索引处插入实例。
- 新增 `remove_multiparm_instance`，允许删除 $0 \le i < count$ 的实例。
- 两个写工具均在调用 HOM 前完成类型转换和索引边界检查。
- 越界、参数类型不匹配或底层 HOM 调用失败时不会伪造成功结果。
- 插入和删除均纳入确认、Undo、mutation、execution barrier 和缓存失效执行语义。

---

## 四、Object Merge 批量引用

- 新增 `create_object_merges_batch`，在目标 SOP 网络中为多个来源节点分别创建 Object Merge。
- 每个节点的 `objpath1` 使用相对于目标网络的路径，减少场景层级变化时的绝对路径耦合。
- 单次最多创建 25 个 Object Merge。
- 目标网络和全部来源节点必须先通过验证；任一来源不存在时保持零写入。
- 全部验证通过后使用一次 `create_network` 事务执行批量创建。
- `source_paths` 数组由 Harness 逐项规范化和验证，错误可定位到具体数组索引。
- 工具需要确认并支持 Houdini Undo，不会进入 Ask 模式。

---

## 五、PDG 表达式助手

- 新增 `build_pdg_expression`，在不访问 PDG graph 的情况下生成受白名单约束的表达式文本。
- 首版支持 `attribute` 类型和 HScript `@attribute` 语法。
- 属性名只允许符合 `^[A-Za-z_][A-Za-z0-9_]*$` 的安全标识符。
- 支持 `int`、`float` 和 `string` 值类型声明。
- 不支持的语法、表达式类型、值类型和非法属性名均返回稳定错误码。
- 返回结果明确标记表达式需要有效 work item 上下文。
- 工具为纯函数，不读取或修改 PDG graph，也不触发 cook。

---

## 六、治理与安全边界

- 所有新增工具均通过 `HOUDINI_TOOLS`、Tool Registry 和 MCP dispatch 注册。
- 节点路径继续由 Harness 统一规范化并拒绝 traversal、null byte 和非法根路径。
- `source_paths` 被纳入节点路径参数集合，数组成员逐项执行相同校验。
- 只读工具可进入 Ask/Plan；参数引用、Multiparm 增删和 Object Merge 批量创建等写工具不会泄漏到 Ask 模式。
- 所有写工具均进入 `SCENE_MUTATION_TOOLS`，要求确认并使用现有 Undo group 和 execution barrier。
- 不使用 `execute_python` 作为实现或回退路径。
- 未新增文件系统、网络、HDA、场景装载或删除节点权限。

---

## 七、测试与验证

### 新增或更新覆盖

- 参数反向引用的精确组件路径、去重和稳定排序。
- 参数引用助手的相对路径表达式和现有写入原语委托。
- Multiparm 实例索引分组、插入、删除和越界预拒绝。
- Object Merge 批量 plan、相对 `objpath1` 和来源缺失时零写入。
- PDG 属性表达式白名单和非法属性名拒绝。
- 工具 schema、dispatch、Ask 隔离、mutation、确认、Undo 和数组路径元数据。
- Harness 节点路径数组逐项规范化和校验。

### 自动化结果

- 本次相关聚焦回归：`74 tests passed`。
- 覆盖 Object Merge、Multiparm、参数引用、Harness、PDG 和工具注册合同。
- 测试环境为 Python 3.8.10。

---

## 八、团队记忆运行时增强

### 团队记忆自动激活

- 将团队语义记忆接入现有每轮长期记忆激活流程，不再完全依赖模型主动调用 `search_memory`。
- 每轮根据用户消息和场景关键词，从团队库自动召回最多 3 条相关语义经验。
- 团队记忆与个人 L1-L3、情景和策略记忆共同进入现有候选选择器，共享 900 字符注入预算，避免整库常驻导致上下文膨胀。
- 注入内容使用 `[Team Memory]` 标记，并附带置信度和贡献者，便于模型区分个人经验与团队经验。
- 团队库加载或检索失败时按非致命错误降级，不阻断个人记忆激活和正常对话。
- 团队策略记忆暂不自动注入，继续通过 `search_memory` 显式检索，避免当前小规模策略库在无关问题中产生噪声。

### 修复记忆工具 runtime 不匹配

- 修复 `search_memory` 和 `remember_memory` 被错误注册为 `local` runtime 的问题。
- 两个工具实际由 MCP Client 的 Houdini dispatch 路径执行；旧注册会在进入 handler 前被 runtime 授权拒绝，并返回“工具 runtime 不匹配”。
- 现统一注册为 `houdini` runtime，使工具声明、授权和真实分派路径保持一致。
- 新增注册级回归测试，验证两个记忆工具在 Agent 模式下可通过 Houdini runtime 授权。

### 验证结果

- 团队记忆自动激活与团队库测试：`20 tests passed`。
- 工具注册、调度、外部 MCP、团队记忆和自动激活联合回归：`93 tests passed`。
- 使用真实团队库查询 Pyro 火焰末端蘑菇头问题，成功自动召回相关团队经验，并排除无关团队策略注入。
- 修改后需重载 Houdini Agent 面板，使内存中的 Tool Registry 重新初始化。

---

## 已知范围

- 尚未在真实 Houdini 进程中完成本次新增工具的端到端冒烟测试。
- 当前 PDG 表达式助手仅支持 HScript 属性表达式，不包含文件、工作项索引、输入引用或 Python 表达式模板。
- Multiparm 管理当前提供实例枚举、单实例插入和单实例删除，不包含移动、复制或批量赋值。
- Object Merge 批量工具当前固定创建 `object_merge` 并设置 `objpath1`，不自动配置 transform、group、pack 或其他节点参数。
- 参数引用助手当前只生成 HScript `ch()` 引用，不自动选择 `chs()`、`chramp()` 或其他按参数类型区分的函数。
- 工具的 Houdini GUI 确认交互和单次 Undo 行为仍需在真实宿主中人工验收。