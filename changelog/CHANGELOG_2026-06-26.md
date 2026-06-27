# Houdini-Agent 更新记录（2026-06-26）

## 发布摘要

本次更新主要聚焦两条线：

- Harness 工具调用安全边界升级：防绕过、输入 guardrails、输出 guardrails、敏感信息脱敏。
- 文档检索索引稳定性与性能改进：修复缓存判断边界，减少重复计算，并加固全局索引初始化。

更细的 Harness 安全治理记录见：`changelog/CHANGELOG_harness_guardrails_2026-06-26.md`。

---

## 关键更新

### 1. Harness 执行边界加固

- 工具公开入口与内部执行实现分离。
- 模型传入的 `_harness_policy_checked`、`_harness_skip_confirm` 不再被信任。
- Harness V2 启用时，公开工具调用必须先进入 policy gate。
- Policy wrapper 内部直接调用内部执行方法，避免通过 kwargs 私有标志防递归。

### 2. Tool input guardrails

- 新增统一输入检查，覆盖：
  - 敏感参数 key：API key、token、password、secret、private key 等。
  - 敏感值模式：API key、Bearer token、private key block、敏感字段赋值。
  - 危险 Python：文件删除、递归删除、系统命令、动态导入、写文件、退出 Houdini、清空 HIP。
  - 危险 Shell：递归/强制删除、格式化磁盘、注册表修改、关机重启、提权、网络配置修改、强杀进程、PowerShell `Invoke-Expression`、`diskpart`、fork bomb。
  - 路径异常：路径穿越、NUL 字符、非 Houdini 支持 root 的绝对节点路径。
- `execute_python.code` 与 `execute_shell.command` 现在在 Harness 层统一做缺参检查。
- 底层 MCP client 原有安全检查保留，作为第二道防线。

### 3. Tool output guardrails

- 新增工具结果规范化与脱敏：
  - 工具结果统一为 `{success: bool, result/error: ...}`。
  - 非 dict 结果会转为失败结果，防止异常结构继续流入 UI/LLM。
  - 成功结果缺 `result` 时补空字符串。
  - 失败结果缺 `error` 时从 `result` 兜底，仍缺失时提供默认错误。
  - 递归脱敏 dict/list/tuple/string 中的 secret、token、password、API key、Bearer token、private key。
- 工具执行返回后立即规范化，减少 UI、历史和回调接触敏感输出的机会。
- 工具结果进入 LLM 上下文前，在 `_compress_tool_result()` 再做一次规范化与脱敏。

### 4. 文档检索索引稳定性与性能改进

- 更新 `houdini_agent/utils/doc_rag.py`：
  - 修复 `help_dir is None` 时缓存判断可能因字符串 `"None"` 产生错误命中的问题。
  - 缓存保存时将空 help_dir 写为空字符串，避免后续判断歧义。
  - 为知识库搜索预构建小写标题、正文和关键词集合，减少每次搜索时的重复计算。
  - 为 node / VEX / HOM 名称搜索预构建小写索引，加快 substring fallback 查询。
  - 将 Labs catalog 缓存改为实例变量，避免类变量共享语义不清。
  - 为全局文档索引单例增加锁，降低并发初始化风险。
  - 抽出 context 优先级常量，保持节点短名冲突选择逻辑一致。

### 5. 测试与测试环境

- 新增 `tests/test_harness_execution_boundary.py`：覆盖工具策略不可被模型伪造私有参数绕过。
- 扩展 `tests/test_harness_policy.py`：覆盖 input guardrails 与 output guardrails。
- 扩展 `tests/test_ai_client_thinking.py`：覆盖工具结果进入 LLM 前的脱敏与结果形状规范化。
- 更新 `tests/test_import_smoke.py`：补充 `numpy` stub，使无完整运行依赖环境下的 UI 导入测试更稳。

---

## 验证结果

目标回归测试通过：

```text
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_harness_policy tests.test_harness_execution_boundary tests.test_ai_client_thinking tests.test_diagnostics_export

Ran 32 tests in 0.008s
OK
```

相关文件通过 VS Code Problems 检查，无语法或静态诊断错误。

---

## 影响范围

主要改动文件：

```text
houdini_agent/core/harness_engine.py
houdini_agent/core/harness_policy_config.py
houdini_agent/ui/ai_tab.py
houdini_agent/utils/ai_client.py
houdini_agent/utils/doc_rag.py
tests/test_ai_client_thinking.py
tests/test_harness_policy.py
tests/test_import_smoke.py
tests/test_harness_execution_boundary.py
```

新增 changelog：

```text
changelog/CHANGELOG_2026-06-26.md
changelog/CHANGELOG_harness_guardrails_2026-06-26.md
```

---

## 兼容性说明

- 本次不引入新依赖。
- 不迁移运行时框架。
- 不改变底层 Houdini 工具 handler 的业务逻辑。
- Harness output guardrails 会规范化异常工具结果形状；如果某个外部插件依赖非标准返回结构，后续应调整为 `{success, result/error}` 合同。
- Doc RAG 缓存判断逻辑更严格，部分环境首次运行可能触发一次缓存重建。

---

## 后续建议

- 将敏感字段、危险命令和脱敏规则迁移到 `config/` 下的 JSON 策略文件。
- 为 Harness trace/span 增加更标准的 schema，便于后续诊断导出和回放。
- 为 Doc RAG 增加检索性能基准和 TopK 命中率回归样本。

---

## 今日补充：Houdini 节点与场景工具增强

### 1. 高频只读 core tools

- 新增 `get_parameter_schema`：结构化读取参数名、标签、类型、tuple 尺寸、当前值、默认值、菜单 token/label，并支持 pattern 与分页。
- 新增 `find_nodes`：按 root、名称 glob、节点类型、类别检索节点，避免递归 `list_children` 浪费上下文。
- 新增 `get_geometry_summary`：读取 SOP 几何摘要、bbox、属性 schema、groups 与可选属性抽样。
- 新增 `get_scene_snapshot`：读取指定 root 下结构化场景快照，用于规划、对比和理解网络结构。
- 新增 `inspect_node`：快速读取单节点状态、flags、连接、错误和非默认参数摘要。

### 2. 节点处理工具增强

- 增强 `set_node_parameter`：参数名错误时返回 did-you-mean 建议。
- 增强 `set_node_parameter`：tuple 参数增加长度校验，菜单参数支持 token/label 解析。
- 增强 `connect_nodes`：支持 `output_index` 与 `replace=false`，并增加输入端口范围校验。
- 保留 `disconnect_nodes` 的指定端口/全部输入断开能力，避免新增重复别名工具。
- 增强 `set_node_flags`：统一支持 `display` / `render` / `bypass` / `template` / `lock` / `select` / `current`。
- 新增 `cook_node`：显式 cook 节点并返回 errors / warnings / messages。

### 3. 节点布局行为修正

- `connect_nodes` 现在只负责接线，不再隐式收集相邻 connected component 并重排一片已有节点。
- `create_nodes_batch` 仍保留自动布局，但仅整理本次新建节点，避免破坏用户已有手工排布。
- 扩展 `tests/test_tidy_layout.py`，覆盖 tidy layout 对新建批量节点的 anchor 保持行为。

### 4. 工具注册与安全边界同步

- 同步 `HOUDINI_TOOLS` schema、`ToolRegistry` 模式与意图分组、MCP dispatch、Harness required args、StreamingToolExecutor legacy sets、AI Tab 伪造工具调用检测。
- 新增只读工具加入 Ask / Plan planning 可用范围。
- `cook_node` 纳入 scene mutation / confirm policy 范围，避免确认模式下静默触发潜在昂贵 cook。
- 新增工具均复用现有 MCP client / ToolRegistry / Harness 架构，不引入外部 MCP 服务或新依赖。

### 5. 影响范围

```text
houdini_agent/core/harness_engine.py
houdini_agent/core/harness_policy_config.py
houdini_agent/core/streaming_tool_executor.py
houdini_agent/ui/ai_tab.py
houdini_agent/utils/ai_client.py
houdini_agent/utils/mcp/client.py
houdini_agent/utils/mcp/hou_core.py
houdini_agent/utils/tool_registry.py
tests/test_harness_policy.py
tests/test_import_smoke.py
tests/test_tidy_layout.py
tests/test_tool_contracts.py
tests/test_tool_registry.py
```

### 6. 验证结果

节点工具增强目标测试通过：

```text
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_tool_contracts tests.test_harness_policy tests.test_tool_registry tests.test_tidy_layout tests.test_import_smoke

Ran 71 tests in 0.673s
OK
```

工具注册 sanity check 通过：

```text
cook_schema True
cook_dispatch True
cook_registered True
connect_options True
```

### 7. 后续建议

- 在真实 Houdini 会话中继续观察 `layout_nodes(tidy)` 的视觉效果；如仍显拥挤，可进一步优化主链垂直排布、多输入节点汇合与分支间距。
- `set_display_flag` 暂时保留兼容；后续可逐步引导模型优先使用统一的 `set_node_flags`。

---

## 今日补充：节点布局算法改进

### 1. tidy 布局算法改进（hou_core.py）

- **增大水平/垂直基础间距**：`h_sp` 从 `3.6×spacing` 改为 `4.5×spacing`，`v_sp` 从 `1.7×spacing` 改为 `2.0×spacing`，减少同层节点重叠。
- **标签感知间距**：每个节点估算宽度 `max(3.5, len(name) * 0.13 + 2.8)`，长名称节点（如 `OUT_VARIANTS_GEO`）之间保留更大间距。
- **碰撞检测 pass**：`_resolve_collisions()` 对每层节点 bbox 扫描，推开相互重叠的节点对，解决截图中文字盖文字的问题。
- **新增 `method="native"` 策略**：对指定节点子集调用 Houdini 原生 `layoutChildren(items=nodes, ...)`；旧版 Houdini fallback 为逐个 `node.moveToGoodPosition()`（借鉴 capoomgit/houdini-mcp 思路）。
- **`create_named_null` 位置修正**：有 `connect_from` 时 y offset 从 `1.5` 改为 `2.2`，避免 null 与上游节点重叠。

### 2. 新增 `preview_layout_nodes` 工具（client.py + ai_client.py）

- dry-run 预览布局结果，返回每个节点的旧坐标、新坐标、位移量和是否移动。
- AI 可先预览再决定是否实际调用 `layout_nodes`，减少对用户手工布局的意外破坏。
- 注册为只读工具（Ask / Plan planning 可用，不进入 confirm policy）。

### 3. 工具链同步

- `ai_client.py`：`layout_nodes` schema 中 method enum 增加 `"native"`；插入 `preview_layout_nodes` schema。
- `tool_registry.py`：三处白名单（`_ASK_TOOLS`、`_PLAN_PLANNING_TOOLS`、`_READONLY_TOOLS`）加入 `preview_layout_nodes`；`_INTENT_TOOL_GROUPS['layout']` 加入 `preview_layout_nodes`。
- `streaming_tool_executor.py`：`_LEGACY_DEDUP_TOOLS` 和 `_LEGACY_BATCH_READONLY` 加入 `preview_layout_nodes`。
- `ai_tab.py`：`_ALL_TOOL_NAMES` 加入 `preview_layout_nodes`。
- `tests/test_tool_registry.py`：新增 `preview_layout_nodes` 布局工具只读模式断言。

### 4. 验证结果

```text
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_tool_contracts tests.test_harness_policy tests.test_tool_registry tests.test_tidy_layout tests.test_import_smoke

Ran 78 tests in 1.634s
OK
```

### 5. 影响范围

```text
houdini_agent/utils/mcp/hou_core.py
houdini_agent/utils/mcp/client.py
houdini_agent/utils/ai_client.py
houdini_agent/utils/tool_registry.py
houdini_agent/core/streaming_tool_executor.py
houdini_agent/ui/ai_tab.py
tests/test_tool_registry.py
```

### 6. 后续建议

- 在 Houdini 中用包含长标签 null 的网络（如截图中的 OUT_GROUND_GEO / OUT_VARIANTS_GEO 场景）做烟测，验证碰撞检测效果。
- 如果仍有节点聚集，可尝试 `layout_nodes(method="native", spacing=1.2)` 直接用 Houdini 原生排布。
- 输出 null 的分 lane 布局（统一放最底部输出行）可作为下一轮改进点。

---

## 今日补充：工具选择说明与按需工具暴露

### 1. AI 工具选择说明

- 新增 `Doc/tool_selection_guide.md`，面向 AI 代理说明什么情况下使用什么 Houdini 工具。
- 文档覆盖 Ask / Plan / Agent 模式边界、先查后改原则、写操作预览、验证步骤和高风险工具边界。
- 增加任务路由矩阵，按“前置查询 -> 核心操作 -> 验证工具”描述参数修改、节点创建、连接/断开、命名 null、flags、cook/cache、布局、文档搜索等常见工作流。

### 2. ToolRegistry 按需选择增强

- 新增 `select_tools_for_request(user_message, mode)`，统一入口根据用户请求分类并返回当前模式允许的最小工具 schema 集。
- 扩展意图分类：`connection`、`parameter`、`flags`、`validate`、`cook`、`null`。
- 新增工具依赖补全：例如 `connect_nodes` 自动带上 `get_node_connections`、`get_node_inputs`、`suggest_connection`、`preview_node_operation`；`set_node_parameter` 自动带上 `inspect_node` 与 `get_parameter_schema`；`create_named_null` 自动带上连接预览与网络验证工具。
- 高风险工具仍仅在明确 `code` / `file` 等意图下进入候选集合，并继续由 Harness policy 兜底。

### 3. UI 工具暴露收敛

- Agent 模式工具选择改为调用 `ToolRegistry.select_tools_for_request()`。
- Plan 执行阶段从全量 `HOUDINI_TOOLS` 改为按当前步骤意图暴露工具，并保留 `update_plan_step`。
- Ask 模式继续保持只读工具边界。

### 4. 验证结果

```text
C:/rez/rez_2.112.0/Scripts/python.exe -m unittest tests.test_tool_registry tests.test_tool_contracts tests.test_import_smoke

Ran 48 tests in 2.278s
OK
```

---

## 今日新增工具汇总

下面把今天新进入 `HOUDINI_TOOLS` 的工具按类别列一次，便于以后查阅。所有工具均已同步到 schema、`ToolRegistry`、MCP `_TOOL_DISPATCH`、`StreamingToolExecutor`、`harness_engine` required args、`ai_tab._ALL_TOOL_NAMES` 和测试。

### 只读 / 查询类（11 个）

- `get_parameter_schema` — 结构化读取节点参数 schema，含 tuple 尺寸、菜单 token/label、默认值和分页。
- `find_nodes` — 按 root、名称 glob、节点类型、类别检索节点，替代递归 `list_children`。
- `get_geometry_summary` — SOP 几何摘要，含 bbox、属性 schema、groups 和可选属性抽样。
- `get_scene_snapshot` — 指定 root 下结构化场景快照，用于规划与对比。
- `inspect_node` — 单节点状态、flags、连接、错误和非默认参数摘要。
- `get_node_connections` — 列出节点的输入/输出连接面板与来源 output index。
- `suggest_connection` — 根据目标 input 标签和占用情况推荐 `input_index`、`output_index`，并提示是否需要替换。
- `preview_node_operation` — dry-run 预览 `connect_nodes` / `disconnect_nodes` / `set_node_flags` / `delete_node` / `cook_node` / `create_named_null` 的影响。
- `validate_node_network` — 汇总 errors / warnings、missing required input、isolated nodes、display/render 节点。
- `preview_layout_nodes` — dry-run 预览 `layout_nodes` 将把节点移到何处，含重叠检测。
- `cook_node`（写但只触发 cook） — 显式 cook 节点并返回 errors / warnings / messages，纳入 confirm policy。

### 写操作 / 创建类（2 个）

- `create_named_null` — 创建语义化 null（`OUT_` / `IN_` / `CTRL_` / `CACHE_` 前缀），可选连接上游并设置 display/render；连接时垂直 offset 修正避免重叠。
- `cook_node` — 见上（既是写操作也属于触发型工具）。

### 增强（已有工具新增能力，不属"新增工具"但今日生效）

- `set_node_parameter` — did-you-mean 建议、tuple 长度校验、菜单 token/label 解析。
- `connect_nodes` — 支持 `output_index` 与 `replace=false`，输入端口范围校验；不再隐式重排相邻节点。
- `set_node_flags` — 统一支持 `display` / `render` / `bypass` / `template` / `lock` / `select` / `current`。
- `layout_nodes` — method enum 新增 `"native"`（调用 Houdini `layoutChildren(items=…)` 或 `moveToGoodPosition()`）；tidy 算法加入 label-aware spacing 与碰撞检测 pass。

### 工具路由 / 选择基础设施

- `Doc/tool_selection_guide.md` — AI 工具选择说明，覆盖模式边界、任务路由矩阵和安全注意事项。
- `ToolRegistry.select_tools_for_request(user_message, mode)` — 按请求意图返回最小工具 schema 集，并补齐写工具所需的前置只读工具。
- `_INTENT_TOOL_GROUPS` 扩展：`connection`、`parameter`、`flags`、`validate`、`cook`、`null`、`layout` 等子组。
- `_TOOL_DEPENDENCIES` 表 — 写工具自动补前置：例如 `connect_nodes` → `get_node_connections` / `get_node_inputs` / `suggest_connection` / `preview_node_operation`；`create_named_null` → 连接预览与网络验证工具。

### 注册同步检查清单

每个新增 core 工具都已经在以下位置同步过，新增类似工具时建议照此清单：

```text
houdini_agent/utils/ai_client.py            # HOUDINI_TOOLS schema、_QUERY_TOOLS、_OP_TOOLS、_SIMPLE_SUCCESS_TOOLS、_DEEP_THINK_TOOLS、_STALEABLE_TOOLS
houdini_agent/utils/mcp/client.py           # 业务方法、_tool_xxx handler、_TOOL_DISPATCH
houdini_agent/utils/mcp/hou_core.py         # 共享底层函数（如布局算法）
houdini_agent/utils/tool_registry.py        # _ASK_TOOLS、_PLAN_PLANNING_TOOLS、_READONLY_TOOLS、_INTENT_TOOL_GROUPS、_TOOL_DEPENDENCIES
houdini_agent/core/streaming_tool_executor.py  # _LEGACY_DEDUP_TOOLS、_LEGACY_BATCH_READONLY、_LEGACY_NETWORK_MUTATING_TOOLS、_LEGACY_CACHE_INVALIDATE_TOOLS
houdini_agent/core/harness_engine.py        # _REQUIRED_ARG_KEYS、必要时 _NORMALIZE_KEYS
houdini_agent/core/harness_policy_config.py # SCENE_MUTATION_TOOLS 等策略列表
houdini_agent/ui/ai_tab.py                  # _ALL_TOOL_NAMES（fake tool call 检测）
tests/                                      # test_tool_contracts、test_tool_registry、test_harness_policy
```
