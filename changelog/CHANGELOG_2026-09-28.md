# Houdini-Agent 更新记录（2026-09-28）

## 发布摘要

本次更新完成外部 MCP 执行链的治理改造，并选择性引入 SOP、USD/LOP 和 TOP/PDG 查询能力。外部 MCP 不再拥有独立的 Houdini 执行旁路；工具暴露、授权、确认、主线程执行、结果清洗和审计统一复用现有 Registry 与 Harness。

同时开放一组受限节点编辑能力。所有外部写操作默认关闭，只有管理员显式配置 allowlist、风险级别和允许写入的节点根路径后才可进入 schema，并且每次调用都必须经过 Houdini 面板确认。

本次不新增运行时依赖，不开放任意 Python、shell、删除节点、文件写入或 HDA 安装能力。

---

## 一、外部 MCP 统一治理

### 统一执行入口

- FastMCP 仅负责协议适配，工具 schema 从 Tool Registry 的显式 external-visible metadata 派生。
- 所有可执行调用统一经过 Registry 授权、Harness policy、确认、主线程 executor、result guardrail 和 append-only audit。
- 移除 legacy server 中直接调用 `hou`、`hou_core` 和任意 Python 执行的平行路径。
- 外部调用使用 server-owned session、client 和 correlation identity，模型不能自行伪造治理身份。
- mutating 工具即使基础 policy 返回 allow，也必须再次经过 Houdini 面板确认；确认缺失、异常、超时或拒绝均 fail closed。

### 资源与生命周期限制

- 增加 per-session 调用总量、并发数和长任务并发上限。
- server shutdown 后拒绝新调用，同时允许已经开始的调用返回真实终态。
- 主线程 executor blocked、shutdown 或状态不可读时，外部调用稳定拒绝。
- 外部 MCP 默认仅监听 loopback，治理配置无效时拒绝启动或只保留 health surface。

---

## 二、能力清单与连接诊断

- 新增确定性的 external MCP capability manifest，并提供生成与 drift 检查脚本。
- 新增 `health`、`session_info` 和 `capabilities` 查询，用于报告 Houdini、Agent、MCP SDK、session、executor 和工具可用状态。
- 启动时比较 Registry、dispatcher、optional feature 和宿主版本；handler 或能力缺失的工具不会被错误暴露。
- 连接状态可区分未启动、SDK 缺失、非 Houdini、executor blocked/shutdown、能力缺失和正常连接。
- manifest 与诊断结果不包含 prompt、参数值、用户路径或其他敏感数据。

---

## 三、SOP 几何分页查询

- 新增 `get_geometry_points` 和 `get_geometry_primitives`。
- 支持 attribute 过滤、group、output index、`start`/`count` 分页及稳定的 `next_start`。
- 单页最多返回 500 个元素，并受 256 KiB payload 上限约束。
- 大结果返回 `truncated`，不会将完整几何无界塞入模型上下文。
- 查询只读取现有几何状态，不切换全局 Update Mode，也不主动修改场景或 cook 状态。

---

## 四、USD/LOP 深度查询

- 新增 `get_usd_prim_info`，提供有界 prim 属性、metadata、prim stack、composition 信息和 resolved material binding。
- 新增 `get_usd_layer_stack`，提供 layer stack、muted layers、sublayers 和有界 composition arc 摘要。
- 现有 LOP inspection skill 复用同一底层实现，避免 core tool 与 skill 各自维护一套遍历逻辑。
- `pxr` 或 stage 不可用时返回结构化能力缺失，并从外部 capabilities 中自动降级。
- 本次仅查询 USD/LOP；写操作仍通过受治理的节点创建、连线和参数修改表达，不提供直接 USD authoring。

---

## 五、TOP/PDG 状态查询

- 新增 `get_top_network_status`、`list_top_work_items` 和 `get_top_errors`。
- 支持 TOP network、scheduler、graph context、状态计数和分页 work item 查询。
- work item attributes、输出文件和错误元数据均有数量与 payload 上限。
- failed item 查询只返回有界错误和日志位置，不读取无限日志正文。
- 查询不会触发 cook、dirty、pause 或 cancel；`pdg` 不可用时通过 capabilities 自动隐藏相关工具。

---

## 六、受限节点写入

### 首批原子编辑

以下工具可作为 external-visible 候选，但默认 allowlist 仍保持只读：

- `create_node`
- `set_node_parameter`
- `connect_nodes`
- `rename_node`
- `layout_nodes`
- `set_node_flags`

### 边界与写后验证

- 节点写入只能发生在显式配置的 `mcp_write_node_roots` 下；默认空配置拒绝所有写入。
- `create_node` 必须显式传入 parent path，并拒绝路径穿越和前缀碰撞越界。
- `rename_node` 只接受合法叶子名，不允许通过重命名改变父路径。
- `layout_nodes` 必须指定 network 和 1 至 50 个节点，只布局明确列出的子集，不执行整网重排。
- `set_node_flags` 仅允许 `bypass`、`template` 和 `lock`；`display`、`render`、`select`、`current` 保持不可达。
- 每次 mutation 返回有界 `verification` facts。可靠回读时为 `verified`；写入可能完成但无法验证时为 `applied_unknown`，不会伪装成功验证。
- `applied_unknown` 在审计中记录为 `verification_inconclusive`，同时保留 mutation 已执行这一事实。

---

## 七、异步 Operation 基础

- 新增 session-owned operation registry，为后续 TOP cook 生命周期提供基础状态机。
- 状态明确区分 `accepted`、`running`、`completed`、`failed` 和 `cancelled`。
- 调用 timeout 不会被解释为操作已取消；只有明确终态迁移才会进入 `cancelled`。
- operation id、查询结果和终态保留数量均有界，并执行 session ownership 校验。

当前 TOP cook 尚未接入该状态机，本次不注册 cook、pause、cancel 或 dirty 写工具。

---

## 八、安全与兼容性

- 默认外部 MCP allowlist 保持低风险只读，不因 Registry 新增工具而自动扩大权限。
- `execute_python`、`execute_shell`、删除节点、场景装载、HDA 安装/卸载和任意文件写入继续默认拒绝。
- 外部 agent 不能获得比内部 outer policy 更宽的权限。
- audit 记录 session、tool、policy decision、结果类别和 correlation id，不记录 prompt、完整参数或凭据。
- lazy `server`/`hou_core` 导入改用 `importlib.import_module`，修复包级 `__getattr__` 自递归导致的 `maximum recursion depth exceeded`。
- 内部 Agent、Ask、Plan 和现有 MCP handler 继续复用同一执行实现。

---

## 九、测试与真实 Houdini 验证

### 自动化结果

- 外部 MCP、Registry、Harness、工具契约和 import 聚焦回归：`134 tests passed`。
- capability manifest drift 检查通过。
- 修改文件通过 workspace diagnostics。
- staged patch 通过 `git diff --check`。

### Houdini 21.0.596

- SOP：8 点 Box fixture 的分页读取通过。
- USD：`/stage` fixture 的 prim 与 13 层 composed layer stack 查询通过。
- PDG：TOP graph context 与状态查询通过。
- 原子 mutation：create、set parameter、connect 的结构化 verification 通过。
- Update Mode：默认 Manual guard 与显式 Auto 保持通过。
- Undo：单次 connect undo 可恢复原输入状态。
- 节点修改：rename、两节点 subset grid layout 和 restricted bypass flag 验证通过。
- subset layout 未移动未列出的节点，flag mutation 未改变 display/render 状态。

### 相关提交

- `c5c9917` — `feat: add governed external MCP capabilities`

---

## 已知范围

- 真实 external MCP HTTP client transport 尚未完成端到端验证；当前 Rez Python 未安装 `fastmcp`，本次未引入未跟踪依赖。
- Houdini GUI 中的实际面板确认点击仍需人工验收。
- `create_nodes_batch` 已有硬上限和 verification，但真实 Houdini 证明单次 undo 不能撤销整个批次，因此未设为 external-visible。
- `copy_node` 会新增拓扑，仍需独立评估碰撞、undo 和恢复语义。
- `delete_node` 等破坏性操作继续保持 high-risk/default deny。
- `display`、`render`、`select` 和 `current` flags 不对外开放。
- TOP cook、pause、cancel、dirty 尚未接入 operation lifecycle。
- 文件保存、场景装载、HDA definition 修改、Shelf 和任意 Python/shell 不在本次开放范围。
