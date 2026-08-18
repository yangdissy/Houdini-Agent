# Houdini-Agent 更新记录（2026-08-17～2026-08-18）

## 发布摘要

本次更新聚焦核心可靠性与治理深化：会话工作区改为可回滚的事务式提交，Plan 生命周期与 UI 状态统一由持久化状态驱动，插件工具通过 Tool Registry 与 Harness 的单一授权链执行，同时补强 Memory embedding 兼容性、上下文预算、插件注册回滚和离线帮助读取。

本次不提升版本号，当前版本仍为 `1.5.3`；未新增运行时依赖，也不需要迁移用户配置。

---

## 一、会话工作区可靠性

### 改动

- 新增纯 Python `SessionState` 与统一 `SessionCacheRecord` 转换，分离持久化状态、Qt widget 和 Agent runtime anchor。
- 普通保存、定时保存、保存全部、退出保存和 `atexit` 统一委托同一个工作区保存入口。
- 保存时先 staging 各会话文件，逐个发布后最后提交 manifest；任一会话或 manifest 提交失败都会回滚已发布文件，避免留下部分更新的工作区。
- 空工作区写入 clear marker，防止旧孤儿会话在下次启动时重新出现。
- manifest 存在时严格按 manifest 恢复；仅在 manifest 缺失时兼容恢复旧孤儿文件。
- 用户切换后，旧 `AITab` 无权继续写盘，避免旧窗口覆盖新用户工作区。
- Agent 运行期间即使切换标签页，结果仍写回发起请求的 session。
- Qt 对象已销毁时可使用纯 Python 备份完成退出保存。

### 用户影响

- 降低退出、用户切换、Windows 文件占用或中途写入失败造成会话历史与 manifest 不一致的风险。
- 已清空的会话不会因遗留缓存文件意外复活。

---

## 二、Plan 生命周期正确性

### 改动

- Confirm 先由 `PlanManager` 持久化，成功后才开始执行；Reject 进入明确的 rejected 状态并保留可恢复记录。
- UI phase 从持久化 Plan 状态派生，切换 session 或重启后恢复对应 Plan projection。
- 删除模型结束一轮后将 `running` 步骤自动标记为 `done` 的路径；步骤必须有实际完成证据。
- `error` 和 `blocked` 不再错误归类为整体 `completed`。
- Plan quality gate 只接受当前 Tool Registry 中已启用且符合 mode/runtime 的可执行工具。

---

## 三、Tool Registry 与 Harness 治理

### 改动

- Tool Registry 成为插件工具 schema、handler、owner、enabled、mode、risk 和 runtime 的唯一权威。
- 删除 HookManager 重复工具存储和 MCP 中绕过 Registry 的旧 fallback；未注册、禁用或 mode/runtime 不匹配均 fail closed。
- 不同插件 owner 的同名工具不再静默覆盖。
- 新增 `GovernedToolExecutor`，统一以下执行顺序：参数校验与策略 → allow/deny/ask/retry → 人工确认 → Registry 授权 → execution adapter → 结果清洗 → append-only 安全审计。
- deny、确认取消或策略异常不会触达执行 adapter；retry 只执行策略返回的修补参数。
- batch 中每一项独立经过同一治理链。
- `ToolMeta` 统一提供 mutating、undo、cook、read-before-cook 与 cache invalidation 语义，主线程执行器优先使用 Registry metadata。

---

## 四、Memory 与上下文管理

### Memory

- 个人与 Team Memory 持久化 embedding backend、model、dimension 和 format version。
- legacy 或 embedding metadata 不兼容时停止向量评分，避免跨向量空间比较产生无意义的相似度。
- 个人旧库重嵌入前保留备份；Team Memory 使用 shadow DB 重建并校验，成功后再原子发布。
- 发布失败时保留旧 live DB，成功后刷新 singleton。

### Context

- 上下文统一为 prefix、history rounds 和 dynamic suffix sections，不再依赖“最后一条消息”猜测 RAG、Memory、Plan 或 reminder 的位置。
- 普通发送、主动压缩和 HTTP 413 recovery 共用同一套 round-safe 规划与裁剪规则。
- 工具定义 schema 计入最终 token budget，避免发送前低估上下文占用。
- 裁剪不会拆散 assistant `tool_calls` 与对应 tool messages。
- 保留当前轮图片并剥离旧轮图片；无法安全压到预算时停止发送或重试，而不是破坏消息结构。

---

## 五、插件生命周期与离线帮助

### 插件

- 首次 load、disable/re-enable 和普通 reload 共用 decorator registration 路径。
- 插件在部分注册后失败时，会按 owner 清理已添加的 hook、Tool 和 button，不影响其他插件。
- pending decorator import 状态在注册结束后始终清理。

### 离线帮助

- `help_source.py` 提供统一单页读取入口，集中处理页面过滤、decode、size limit 和 archive 访问。
- `search_houdini_help` 不再直接打开 ZIP，搜索和单页读取共用同一 Help Source。
- Doc Index 支持注入 cache/doc lifecycle 路径，测试不再依赖本机 Houdini Help 安装。
- 保持 cache v2 与默认行为兼容。

---

## 六、兼容性

- 当前版本保持 `1.5.3`。
- 无新增运行时依赖。
- 保持旧插件注册入口、旧 Plan JSON、旧 Session Cache、cache v2 和现有配置格式兼容。
- 用户数据保留规则、Team Memory 隐私边界和 Agent session anchor 语义不变。
- Python 3.7 / Houdini 18.5 兼容语法保持不变。

---

## 七、测试与验证

- AIClient、Context、Registry、Session 与 Memory 聚焦回归：150 tests passed。
- Houdini 18.5 / Python 3.7 Cache、Session 与 Plan 聚焦回归：30 tests passed。
- 执行、插件与文档完整测试套件：310 tests passed。
- Python 3.7 AST 检查：相关生产文件通过。
- VS Code workspace diagnostics：0 errors。
- Houdini 宿主实测通过：工具确认、拒绝、长 cook timeout、插件普通 reload、离线帮助查询。
- 当前工作区随后再次运行完整测试：通过，退出码为 0。

### 已知测试限制

- `test_manual_update_mode_directive` 在 Houdini 18.5 / PySide2 下仍有 7 个既有 `object.__new__(AITab)` fixture 构造错误；该问题与本次 Plan lifecycle 逻辑断言无关。

---

## 已知范围

- 插件普通 reload 已通过宿主验证，但“新插件版本 reload 失败后保留旧可运行实例”尚未实现，不能视为完整事务式 reload。
- 完整组织级工具语义矩阵仍保留少量兼容 fallback；本次统一的是已有多个真实 consumer 的 mutating、undo、cook 和 cache 语义。
- 用户显式创建 Wrangle 的 UI 动作不是 LLM Tool request，仍直接进入 MCP/Registry，不强制套用 Harness confirmation。
