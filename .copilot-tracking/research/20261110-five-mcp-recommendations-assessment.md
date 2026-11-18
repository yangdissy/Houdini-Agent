# 五项 MCP 建议事实核验报告

- 日期：2026-11-10
- 范围：仅研究/核验，未修改任何产品代码
- 背景：本报告核验的 5 项建议，其雏形来自同日稍早的
  `.copilot-tracking/research/20261110-houdini-mcp-landscape-research.md`
  第 8 节「Recommendations, Ranked By Impact/Cost」。该文档已对部分问题做了
  初步判断，但对“FastMCP 是否已有 Origin/Host 防护”明确标注为
  **“review item, not an assumed-missing gap...was not confirmed absent by
  full-file review”**——本报告的主要增量价值，就是把这类“未确认”问题，通过
  一手追踪 FastMCP 库源码 + 本仓库实际调用点，升级为**已确认**结论。

---

## 1. fxhoudinimcp 基准 ADR 是否已过期

### 当前状态
**已确认过期，且过期信息具体、可量化。**

### 证据
- 本仓库固定基线：`docs/adr/fxhoudinimcp-reference-baseline.md` 记录
  `healkeiser/fxhoudinimcp` release **v2.21.0**，commit
  `7405dc7bedaf9f842c0570cbdda02d47cf96c70e`，记录时间
  `2026-09-23T21:41:24Z`。
- 通过 GitHub API 直接查询 `healkeiser/fxhoudinimcp`：
  - 当前 HEAD：commit `de2c9aeb142d6ab60c0299256636e22128708c37`，
    日期 `2026-11-09T21:32:06Z`。
  - 当前最新 release：**v2.28.3**（相较固定的 v2.21.0，相差 7 个以上
    minor 版本）。
  - 间隔：约 47 天，期间有数十个 PR 合并。
  - 版本区间内存在与本仓库 Item 2（见下）直接相关的传输层变更：
    release note v2.27.0 "Streamable HTTP runs stateless on MCP SDK 2
    (SDK 1 keeps sessions)"。
- 同日早些的 `20261110-houdini-mcp-landscape-research.md:360-363` 已独立
  得出同一结论："now superseded upstream by at least commit `de2c9ae...`
  (2026-11-09) and 215 vs. the previously recorded 206 tools...this
  baseline file should be refreshed"——与本次核验结果一致，互相印证。

### 是否行动
**行动（Go）**——纯文档更新，无代码风险。

### 最小改动
更新 `docs/adr/fxhoudinimcp-reference-baseline.md`：
1. 将 pinned commit 从 `7405dc7b...` 改为 `de2c9aeb...`（或当前核验时的
   HEAD），release 从 v2.21.0 改为实际对应的新版本。
2. 重新统计工具数量（`@mcp.tool()` 装饰器出现次数），更新文档中的工具
   总数声明（旧文档声称 206，landscape 研究声称 215，均需用当前 HEAD
   重新核实后再写入，避免二次以讹传讹）。
3. 在 ADR 的 Consequences/变更记录区追加一条，注明此次刷新覆盖的版本区间
   （v2.21.0 → vX.Y.Z）及其中与本仓库架构相关的关键变更（至少应提及
   v2.27.0 的 Streamable HTTP 会话模型变化，因其影响与 Item 2 的无状态/
   有状态假设）。

### 依赖
无代码依赖；仅需确认一次新的 commit SHA 和重新跑一次工具计数（可用
`search_code` 对 `@mcp.tool()` 计数，或直接 clone 后 grep）。

### 风险
无（文档变更，不影响运行时行为）。唯一风险是“基准文档本身很快又会过期”——
这是过程性风险，而非本次变更的风险，建议在 ADR 中加一句“建议每季度复核一次”
的维护提示来缓解（文档措辞，非自动化义务）。

### 验收标准
- ADR 中的 commit SHA、release 版本、日期、工具总数四项均与核验时刻的
  `healkeiser/fxhoudinimcp` 实际状态一致。
- ADR 新增一条变更日志条目，说明本次刷新识别到的任何与本仓库架构相关的
  上游变化（至少含 Streamable HTTP 会话模型变化）。

### 优先级
**高优先级、低成本**——与 landscape 研究评级一致（"High impact, low cost"）。
应作为常规维护任务尽快执行。

---

## 2. FastMCP HTTP 层是否已有 Host/Origin/DNS-rebinding 防护

### 当前状态
**已确认缺失（不是"未知"，是"确认为否"）。** 这是本次核验中证据链最深、
结论价值最高的一项：将 landscape 研究中"review item, not confirmed absent"
的保留态度，升级为确凿的"已确认不存在"。

### 证据（完整调用链追踪，非仅 grep 名称）

**(a) 本仓库实际调用点——未传递任何防护参数**
- `houdini_agent/utils/mcp/server.py:213`：
  `mcp = FastMCP("Houdini MCP Server")  # type: ignore`
  ——构造时不带任何 `host_origin_protection`/`allowed_hosts`/
  `allowed_origins` 参数。
- `houdini_agent/utils/mcp/server.py:170`：
  `server_task = asyncio.create_task(mcp.run_async(transport=transport, host=host, port=port))`
  ——启动时同样只传 `transport`/`host`/`port`，不传任何 Origin/Host 相关
  的安全参数。
- 全仓库搜索 `host_origin_protection`/`allowed_hosts`/`allowed_origins`：
  **零命中**于 `houdini_agent/` 和 `config/` 下——证实这不是一处遗漏的
  grep 死角，而是整条调用路径都没有触达该开关。

**(b) 本仓库仅有的网络层限制是"绑定地址白名单"，不是"请求头校验"**
- `houdini_agent/utils/mcp/settings.py:49`：`host: str = "127.0.0.1"`
  （dataclass 默认值）。
- `houdini_agent/utils/mcp/settings.py:101-102`：
  ```python
  host = str(cfg_dict.get("mcp_host", "127.0.0.1")).strip().lower()
  if host not in {"127.0.0.1", "localhost", "::1"}:
  ```
  ——强制只能绑定回环地址（127.0.0.1/localhost/::1），拒绝绑定到外部
  网卡地址。
- **关键区分**：这只阻止了"进程监听在公网可达的地址上"，**不能**阻止
  DNS rebinding 攻击——恶意网页可以让浏览器把某个可控域名解析到
  `127.0.0.1`，发起带任意 `Host:`/`Origin:` 头的请求，只要端口在回环上
  监听，请求依然能到达。绑定地址限制和 Host/Origin 头校验是两条独立
  防线，本仓库目前只有前者，完全没有后者。

**(c) 上游 FastMCP 库（本仓库依赖的 MCP server 框架）的默认行为——
确认"防护能力存在，但默认关闭且从未被打开"**
- `PrefectHQ/fastmcp`（即 `jlowin/fastmcp`，GitHub 组织已迁移）
  `fastmcp_slim/fastmcp/server/http.py` 中定义了
  `HostOriginGuardMiddleware`（校验 Host 与 Origin 头，支持
  loopback-aware 的 `"auto"` 模式）与内部工厂函数
  `_host_origin_guard_middleware()`——**仅当** `host_origin_protection`
  为 `True` 或 `"auto"` 时才会构建该中间件；否则返回 `None`，即不安装
  任何中间件。
- `streamable_http_app()` / `sse_app()` 函数签名中
  `host_origin_protection: HostOriginProtection = False` 是**硬编码默认
  值**，源码注释原文："Defaults to False for compatibility."
- `fastmcp_slim/fastmcp/server/mixins/transport.py` 中
  `run_http_async(..., host_origin_protection: HostOriginProtection | None = None, ...)`
  ——当调用方（即本仓库 `server.py`）不传该参数（传 `None`）时，会继续
  下探到 `settings.http_host_origin_protection`。
- `fastmcp_slim/fastmcp/settings.py`：
  `http_host_origin_protection: bool | Literal["auto"] = False`
  ——库级全局默认值同样是 `False`。即：从 `server.py` 的调用点，一路下探
  到库的 `Settings` 类默认值，**每一层的默认值都是"关闭"**，本仓库没有
  在任何一层显式打开它。

**(d) FastMCP 会主动屏蔽官方 MCP SDK 自带的同类防护，
不存在"用了 FastMCP 但底层 SDK 仍兜底"的侥幸**
- `dev-docs/v4-notes/change-register.md`：`HostOriginGuardMiddleware` 是
  **FastMCP v4 的新特性**；原文注明 FastMCP **始终**禁用官方
  `modelcontextprotocol/python-sdk` 自带的
  `TransportSecuritySettings(enable_dns_rebinding_protection=False)`，
  无论 FastMCP 自身的防护是开是关，都会先把 SDK 层的防护关掉，以避免
  "双重拦截"。
- 对照 `modelcontextprotocol/python-sdk` 源码：其
  `TransportSecuritySettings` 的 `enable_dns_rebinding_protection`
  **默认是 `True`**——但这个默认值在使用 FastMCP（本仓库场景）时**不生效**，
  因为 FastMCP 已经把它强制关闭。

**(e) 本仓库未对 `fastmcp` 做版本钉选——进一步放大了不确定性**
- 在仓库内搜索 `requirements*.txt`、`pyproject.toml`、安装脚本等，均未
  发现对 `fastmcp` 包的版本钉选记录。`HostOriginGuardMiddleware` 是
  FastMCP **v4 时代**才引入的能力——如果实际部署环境安装的是 v3.x 或更旧
  版本，则连"默认关闭的防护开关"这一基础设施本身都可能不存在，只能回落
  到官方 SDK 层（但按 (d) 所述，FastMCP 又会主动关闭 SDK 层）。此项未做
  完全穷举式验证（原计划的 `*.ini/*.toml/*.cfg` 全仓库搜索因耗时被中断），
  应视为"大概率成立但建议复核一次"的发现，而非 100% 穷尽结论。

### 是否行动
**行动（Go）**——这是唯一一项从"疑似/待确认"被本次核验坐实为"确认缺失"
的安全相关发现，建议提升为本仓库近期的实际行动项，而非仅停留在
"re-evaluate later" 的观察清单。

### 最小改动
1. 在 `houdini_agent/utils/mcp/server.py` 构造/启动 FastMCP 实例处，显式
   传入 `host_origin_protection="auto"`（loopback-aware 模式，不会因为
   本机访问而误杀合法流量），而不是依赖任何隐式默认值。
2. 在 `houdini_agent/utils/mcp/settings.py` 的 `MCPSettings` 中新增一个
   显式字段（如 `host_origin_protection: str = "auto"`），纳入
   `read_settings()` 的配置读取/校验路径，使其与现有的 `host` 白名单机制
   并列、可被运维显式覆盖（而不是硬编码在 `server.py` 里）。
3. 在仓库中为 `fastmcp` 增加版本下限钉选（如 `fastmcp>=4.0`），确保
   `host_origin_protection` 参数确实可用，避免在旧版本上传参数却被静默
   忽略。
4. 补充一个针对真实 FastMCP 实例的集成测试（而非仅 mock），断言：
   - 带有恶意 `Origin`/`Host` 头的请求被拒绝（在非 loopback 场景或显式
     allowed_hosts 配置下）；
   - 合法 loopback 自身请求仍然放行（避免破坏现有 UI/客户端连接）。

### 依赖
- 需要先确认实际部署环境可安装/升级到的 `fastmcp` 版本（受 Houdini 内嵌
  Python 环境的包管理约束，可能不是简单的 pip 升级）。
- 若目标环境的 fastmcp 版本确实低于 v4，则需要改为直接基于官方
  `modelcontextprotocol/python-sdk` 的 `TransportSecuritySettings` 做
  防护（因为此时 FastMCP 不会使用自己的中间件，也早已关闭了 SDK 层的
  默认防护，需要显式在 SDK 层重新打开）。

### 风险
- **误杀风险**：若不使用 `"auto"`（loopback-aware）模式而直接
  `True`，可能导致合法的本机 UI 客户端因 Host/Origin 头不匹配被拒绝，
  需要先在本机验证模式选择。
- **版本钉选风险**：强制 `fastmcp>=4.0` 若与现有其它依赖冲突，需要评估
  升级影响面（可先用一个隔离的测试环境验证）。
- **不作为的风险**：当前状态下，只要攻击者能诱导受害者浏览器加载恶意
  页面并完成 DNS rebinding，就有可能绕过"仅监听回环地址"的假设，对
  本地运行的 Houdini-Agent 外部 MCP 服务发起请求——即使外部工具白名单
  本身是只读/受限的（见 `settings.py` 的 allow/deny 列表），也应补上这层
  独立防线，属于纵深防御（defense-in-depth）范畴。

### 验收标准
- `server.py` 中可见到显式传递的 `host_origin_protection` 参数（代码
  审查层面可验证，不依赖隐式默认值）。
- 新增集成测试覆盖"恶意 Origin/Host 被拒绝"与"合法本机请求仍放行"两条
  路径，且在 CI/本地测试套件中可重复通过。
- `fastmcp` 的最低版本要求在依赖声明中可见（而不是仅凭开发者记忆）。

### 优先级
**中高优先级（高于原 landscape 研究评估的"Medium impact"）**——原研究
标注为"待确认的评审项"，本次核验已将其坐实为确定性缺口，建议上调优先级，
尽快排期，但实现成本仍然可控（库已提供现成开关，无需自研校验逻辑）。

---

## 3. LOP/USD 与 PDG/TOP 只读工具当前覆盖与真实缺口

### 当前状态
**覆盖范围远超 `.copilot-tracking/plans/lops_pdg_tools_plan.md` 原计划的
假设；真实缺口比原计划设想的窄得多。** 这是本次核验避免"重复建议已完成
工作"的关键一项。

### 证据

**已实现的核心工具（非 skill，位于核心注册表，MCP 外部可见）**
- `houdini_agent/utils/usd_inspection.py`：实现 `inspect_usd_prim`、
  `inspect_usd_layer_stack` 等函数，对应 MCP 工具名
  `get_usd_prim_info`、`get_usd_layer_stack`。
- `houdini_agent/utils/pdg_inspection.py`：实现
  `inspect_top_network`、`list_work_items`、`get_top_errors`、
  `build_pdg_expression`，对应 MCP 工具名 `get_top_network_status`、
  `list_top_work_items`、`get_top_errors`。
- 以上均在 `houdini_agent/utils/mcp/client.py`（约 6130-6260 行）通过
  `HoudiniMCP._tool_get_usd_prim_info` / `_tool_get_usd_layer_stack` /
  `_tool_get_top_network_status` / `_tool_list_top_work_items` /
  `_tool_get_top_errors` 接入 `_TOOL_DISPATCH`，并在
  `houdini_agent/utils/tool_registry.py` 注册为对应工具名。
- **关键发现**：`inspect_usd_prim` 已经返回 `composition_arcs`、
  `prim_stack`，以及通过 `UsdShade.MaterialBindingAPI` 得到的材质绑定
  信息——这意味着原计划中标记为"第二批次"的 L3
  （`inspect_usd_composition`，组合弧检查）**已经基本被覆盖**，原计划
  对 L3 未实现的假设是**过时/不准确**的，不应再作为新建议提出。

**已实现的 Skill（目录 bundle 形式，非单文件）**
- `houdini_agent/skills/usd/inspect_lop_stage`：返回 layer 列表、prim
  计数、相机/灯光清单、材质绑定候选、payload/reference 信息。
- `houdini_agent/skills/materials/inspect_material_assignments`：材质库
  扫描。
- `houdini_agent/skills/performance/analyze_cook_performance`：cook 耗时
  分析（通用，非 PDG 专属，但与 TOP 性能诊断场景有重叠价值）。

**测试覆盖**
- `tests/test_usd_inspection.py`、`tests/test_pdg_inspection.py`：
  基于 mock 的契约测试，覆盖结构化错误、分页/截断、payload 上限、日志
  内容不泄露进错误输出、PDG 表达式构造器白名单校验等。
- `tests/houdini_domain_readers_smoke.py`：基于真实 Houdini（hython）
  的几何/USD/PDG reader 冒烟测试。

**与 `.copilot-tracking/plans/lops_pdg_tools_plan.md` 原计划的差异**
对照原计划提出的清单（L1-L6 为 USD 侧，P1-P7 为 PDG 侧）：

| 计划条目 | 原计划假设 | 实际现状 | 结论 |
|---|---|---|---|
| L1 `inspect_usd_prim` | 待实现 | 已实现（核心工具） | 计划已过时，勿重复提出 |
| L2 `list_usd_layers` | 待实现 | 已实现为 `inspect_usd_layer_stack` | 计划已过时 |
| L3 `inspect_usd_composition` | 待实现（第二批次） | **基本已覆盖**（随 L1 返回 composition_arcs/prim_stack） | 计划假设过时，是本次核验的重要纠正 |
| L4 `list_usd_variants` | 待实现 | **未找到任何实现痕迹** | **真实缺口** |
| L5 `inspect_usd_lighting` | 待实现 | **部分覆盖**（`inspect_lop_stage` 给出灯光清单概览，但缺少 UsdLux 详细属性：intensity/exposure/color/shadow link） | **部分缺口** |
| L6 `diff_usd_layers` | 待实现 | **未找到任何实现痕迹** | **真实缺口** |
| P1 `inspect_top_network` | 待实现 | 已实现为 `get_top_network_status` | 计划已过时 |
| P2 `list_work_items` | 待实现 | 已实现为 `list_top_work_items` | 计划已过时 |
| P3 `analyze_top_dependencies` | 待实现 | **未找到任何实现痕迹** | **真实缺口**（与 landscape 研究 "dependency graphs" 呼应，两处独立来源均指向同一缺口，可信度较高） |
| P4 `get_top_errors` | 待实现 | 已实现 | 计划已过时 |
| P7 `inspect_top_scheduler` | 待实现 | **仅部分覆盖**（`scheduler_path` 字段存在，但缺调度器类型/配置/并发度细节） | **部分缺口** |

### 是否行动
**部分行动（针对真实缺口），其余不作为（避免重复实现已覆盖功能）。**

### 最小改动（仅针对已确认的真实/部分缺口，按投入产出排序）
1. **`analyze_top_dependencies`（P3）**——优先级最高：两份独立研究
   （本次 + landscape 研究的"dependency graphs"）都指向同一缺口，且
   PDG 依赖图分析是生产诊断中高频需求。建议新增一个只读工具/skill，
   复用 `pdg_inspection.py` 中已有的 TOP 网络遍历基础设施，输出
   work-item 级或 node 级依赖边列表。
2. **`inspect_top_scheduler`（P7）细化**——在现有 `scheduler_path`
   基础上补充调度器类型、并发度上限、关键配置参数的只读读取。
3. **`inspect_usd_lighting`（L5）细化**——在 `inspect_lop_stage` 现有
   灯光清单基础上，为每个灯光 prim 补充 UsdLux 标准属性
   （intensity/exposure/color/enableShadow 等）的只读读取。
4. **`list_usd_variants`（L4）**与**`diff_usd_layers`（L6）**——
   优先级较低（原计划本就标注为"第二批次"），建议仅在有具体生产需求
   驱动时再实现，不作为本轮必须项。

### 依赖
- P3（依赖图分析）依赖对现有 `pdg_inspection.py` 内部数据结构的复用，
  无新的外部库依赖。
- L4/L5/L6 均依赖 `pxr`（USD Python 绑定）现有导入路径，技术上无新依赖，
  但 L6（跨 layer diff）在实现复杂度上高于只读单层读取，需要额外设计
  diff 输出的结构化格式（结构化文本 diff vs. 字段级对比）。

### 风险
- 新增工具若注册为 `external_mcp_visible=True`，需按现有只读工具的治理
  模式（`tool_registry.py` 的 `_READONLY_TOOLS`/`_EXTERNAL_MCP_VISIBLE_TOOLS`
  frozenset）添加，避免与治理边界（harness 风险分级、manifest 漂移检测，
  见 Item 4）脱节；新增工具必须同步更新
  `config/external_mcp_manifest.json`（通过
  `scripts/generate_external_mcp_manifest.py` 重新生成）并通过
  `tests/test_external_mcp_capabilities.py::test_committed_manifest_has_no_drift`，
  否则会在下次有人运行该测试时才被发现，造成返工。
- L6（diff_usd_layers）若实现不当（例如直接 dump 完整 layer 文本）可能
  产生超大 payload，需遵循仓库现有的分页/截断惯例
  （参见 `usd_inspection.py` 中已有的 bounded payload 模式）。

### 验收标准
- 新增工具/skill 有与 `test_usd_inspection.py`/`test_pdg_inspection.py`
  同等级别的 mock 契约测试（结构化错误、分页/截断、payload 上限）。
- 新增只读工具若对外部 MCP 可见，需通过
  `test_committed_manifest_has_no_drift` 与
  `test_schema_and_dispatch_contracts_model_internal_tools_explicitly`
  两项现有漂移检测测试（见 Item 4）。
- 不应重复实现表格中标记为"已实现"的 L1/L2/L3/P1/P2/P4 条目——任何新
  PR 若提议这些条目，应先核对本报告再决策。

### 优先级
**中优先级**——P3（依赖图分析）因双来源印证建议优先排期；其余条目按
生产需求驱动，非紧急。

---

## 4. Capability manifest / registry / runtime handler 漂移检测现状与 ADR 缺口

### 当前状态
**漂移检测机制本身已经存在且覆盖面相当完整（两套独立测试、分别覆盖
"外部 manifest vs. registry" 与 "registry vs. 运行时 dispatch handler"
两个维度），但（a）没有任何 CI/自动化强制执行，完全依赖开发者本地手动
运行 `pytest`；（b）没有一篇 ADR 把这套机制的设计意图、覆盖范围、以及
"为什么是两套独立测试而不是一套"写清楚。** 真实缺口是**流程/文档**层面，
不是**检测能力**层面。

### 证据

**(a) 漂移检测 1——外部 manifest vs. 当前 Registry+Dispatch 生成结果**
- `scripts/generate_external_mcp_manifest.py:17,23,67,76,81-82`：
  `MANIFEST_PATH = REPO_ROOT / "config" / "external_mcp_manifest.json"`；
  `generate()` 通过 AST 字面量提取 `HOUDINI_TOOLS`（`ai_client.py`）与
  `HoudiniMCP._TOOL_DISPATCH`（`client.py`），喂给 `ToolRegistry` +
  `build_external_tool_manifest`，再用 `render_external_manifest_json`
  渲染为文本；`--check` 模式下比较渲染结果与已提交文件内容
  （`MANIFEST_PATH.read_text(...) != expected` 则判定漂移）。
- `tests/test_external_mcp_capabilities.py` 第 83-87 行左右，
  `test_committed_manifest_has_no_drift`：
  ```python
  def test_committed_manifest_has_no_drift(self):
      from scripts.generate_external_mcp_manifest import generate
      committed = Path("config/external_mcp_manifest.json").read_text(encoding="utf-8")
      self.assertEqual(committed, generate())
  ```
  ——这是一个**可执行的 pytest 用例**，不是人工检查清单；只要有人运行
  `pytest`，committed manifest 与"从当前代码重新生成"的结果不一致就会
  立刻失败。

**(b) 漂移检测 2——Registry 内部核心工具 vs. 运行时 `_TOOL_DISPATCH`
  handler 是否真实可调用**
- `tests/test_tool_contracts.py`
  `test_schema_and_dispatch_contracts_model_internal_tools_explicitly`
  （约 305-322 行）：
  ```python
  core_names = set(self.registry._tools)
  dispatch_names = set(HoudiniMCP._TOOL_DISPATCH)
  ai_internal_tools = {...}          # 显式枚举，不在 dispatch 但在 registry
  non_mcp_internal_dispatch = {...}  # 显式枚举，在 dispatch 但不在 registry
  self.assertEqual(core_names - dispatch_names, ai_internal_tools)
  self.assertEqual(dispatch_names - core_names, non_mcp_internal_dispatch)
  for name, handler_name in HoudiniMCP._TOOL_DISPATCH.items():
      self.assertTrue(callable(getattr(HoudiniMCP, handler_name, None)))
  ```
  ——这不仅检测"名字对不对"，还实际 `getattr` + `callable()` 验证
  `_TOOL_DISPATCH` 里记录的每一个 handler 方法名，在 `HoudiniMCP` 类上
  确实存在且可调用，能捕获"改了方法名但忘改 dispatch 表"这类真实回归。
  两个差集都用**显式枚举集合**而非通配逻辑做断言，意味着任何未被显式
  纳入白名单的新增不一致都会导致测试失败——这是刻意设计的"fail closed"
  模式，而非宽松容错。

**(c) Skill 层的等价漂移/契约检测**
- `tests/test_skills_metadata.py::test_all_builtin_skills_satisfy_contract`
  —— 验证全部内建 skill 满足统一契约（entrypoint 格式、类别合法性等）。
- `tests/test_skills_metadata.py::test_descriptor_rejects_nonstandard_entrypoint`
  —— 验证非标准 entrypoint（如 `scripts/other.py:execute` 而非标准的
  `scripts/main.py:run`）会在 `_parse_skill_markdown` 阶段被 `ValueError`
  拒绝，属于"写入时校验"而非"运行时静默失败"。

**(d) CI/自动化强制执行现状——确认为空**
- 仓库根目录 `.github/` 下只有 `agents/`、`instructions/`、`skills/`
  三个子目录（均为 Copilot 定制文件），**没有 `workflows/` 目录**，
  即没有任何 GitHub Actions 工作流。
- 全仓库未发现 `Makefile`、`tox.ini`、或等价的"构建即测试"入口脚本。
- `pytest.ini` 中只定义了一个 marker
  （`houdini_integration: requires an explicitly enabled isolated hython
  process`），没有任何钩子（pre-commit/pre-push）文件的迹象。
- 结论：上述两套漂移检测测试**只有在开发者主动执行 `pytest`（或
  `pytest tests/test_external_mcp_capabilities.py` /
  `tests/test_tool_contracts.py` 等子集）时才会运行**，没有任何机制
  保证"每次 push/合并前必然跑一次"。考虑到这是内部 UNC 路径下的工作室
  内部扩展（非托管于公开 GitHub 的标准 CI 流水线），这一现状可能是
  有意为之的轻量级工作流，而非疏漏——但仍构成一个值得记录的流程缺口。

**(e) ADR 层面的文档缺口**
- `docs/adr/external-mcp-governance-boundary.md` 提到了 committed
  manifest 作为治理模型的一部分，但**没有**专门描述"为什么存在两套独立
  漂移测试""它们各自覆盖哪个维度""不通过 CI 强制执行的权衡是什么"。
- 同日 `20261110-houdini-mcp-landscape-research.md:413-417`
  第 4 条建议已经提出"Document the manifest/drift-detection symmetry...
  in an ADR"，评级为 "Low impact, low cost"——本次核验确认这个建议
  依然成立且尚未被执行（未发现新增的相关 ADR 文件）。

### 是否行动
**低成本文档行动（Go，低优先级）；CI 自动化为可选增强（视工作室实际
CI 基础设施可用性决定，不强制）。**

### 最小改动
1. 新增一篇简短 ADR（或扩展
   `external-mcp-governance-boundary.md` 的一个小节），记录：
   - 两套漂移检测各自的职责边界（manifest-vs-registry、
     registry-vs-dispatch-handler）；
   - 两者为何是独立测试而非合一（分别对应"外部可见的工具契约"与
     "内部 dispatch 表完整性"两个不同风险面）；
   - 当前执行方式是"随 `pytest` 手动/半自动触发"，明确说明这不是
     CI 强制门禁，属于团队约定而非系统保证。
2. （可选，视工作室是否具备可用 CI 基础设施而定）若具备，补充一个最小
   CI/钩子配置，使 `pytest tests/test_external_mcp_capabilities.py
   tests/test_tool_contracts.py` 在提交前或合并前至少跑一次；若不具备
   公开 CI，可考虑本地 pre-commit 钩子作为折中方案。

### 依赖
- ADR 撰写无技术依赖。
- CI/钩子方案依赖工作室现有的内部 CI/构建基础设施（本次核验未发现任何
  现成基础设施可直接复用，需要额外调研工作室标准，不在本报告范围内）。

### 风险
- 文档变更本身无风险。
- 若后续决定补充 CI/钩子，需确保不与现有的 hython 集成测试
  （`houdini_integration` marker，需要显式启用的隔离 hython 进程）冲突，
  避免把本应快速的 PR 检查变成需要完整 Houdini 环境的慢速门禁。

### 验收标准
- 新增/扩展的 ADR 中能找到对两套漂移检测测试的职责划分说明，并明确标注
  当前为"手动/半自动"而非"CI 强制"。
- 若采纳可选的 CI/钩子增强，验收标准为：提交一个故意制造 dispatch-registry
  不一致的试探性改动后，钩子/CI 能在合并前捕获并阻断。

### 优先级
**低优先级**——检测能力本身已经足够扎实（这是本项调查中最被低估的
"已完成工作"之一），真正的缺口只是"补文档说明现状"与"是否值得补自动化
门禁"的权衡，不构成紧急风险。

---

## 5. 请求级工具筛选与 lazy Skill loading 是否已有等效

### 当前状态
**已确认存在功能等效实现，且比一般意义上的"lazy loading"更完整**：
既有按请求（per-run）、按意图（intent）预热的 token 预算化工具 schema
筛选机制，也有真正意义上"直到被调用才 import 可执行代码"的 Skill 懒加载。
两者均有对应的行为级单元测试，而不仅是 ADR 文字描述。

### 证据

**(a) 请求级工具筛选——`ToolExposureState`**
- `houdini_agent/core/agent_request_assembly.py:40` 起的
  `class ToolExposureState`：
  - 构造函数（约第 43-61 行）接收 `registry`、`initial_tools`、`mode`、
    `use_web`、`supports_vision`、`max_schema_tokens`，并在初始化时就
    对初始工具集合做 token 预算校验
    （`if self._counter([], tools=self.snapshot()) > self.max_schema_tokens:
    raise ValueError(...)`）——即每次请求的工具 schema 集合从一开始就是
    "本次请求范围内、受 token 预算约束"的子集，而非全量工具列表。
  - `_allowed(self, name)`（约第 63-68 行）：按当前 `mode`
    （`registry.is_tool_allowed_in_mode`）、`use_web` 开关（屏蔽
    `web_search`/`fetch_webpage`）、`supports_vision` 开关（屏蔽
    `visual_review`）做三层过滤——这正是"请求级/会话级工具筛选"的具体
    实现，而非仅停留在 ADR 文字。
  - `load(self, query, tags, mode, limit)`（约第 80-101 行）：这是
    "lazy/progressive 工具加载"的核心方法——对应用户描述中的
    `search_tool_contracts(load=true)` 语义：按查询词/标签在
    `registry.search_contracts(...)` 中检索尚未加载的工具契约，若匹配
    且被当前 mode/能力许可，才把它们追加进 `self._names`（当前暴露给
    模型的工具集合），并重新计算 token 预算，超出预算时返回
    `"tool_schema_budget"` 错误而不是静默截断。方法注释原文
    `"available": "Loaded tools are callable in the next model request,
    not in this response."` 清楚说明了"懒加载"的时序语义：当前这一轮
    回复还不能用，下一轮模型请求才可用——与真正的"按需渐进式"工具暴露
    模型完全吻合。
  - `reject(self, name, ...)`（约第 102-112 行）：当模型尝试调用一个
    未被本次 `ToolExposureState` 暴露的工具时，返回结构化拒绝
    （`error_code: "tool_not_exposed"`）并记录审计事件，而不是让请求
    直接失败或报未知错误——体现这套机制有完整的失败路径设计。
- 对应测试：`tests/test_agent_tool_selection.py`
  （`self.assertLess(len(tools), len(HOUDINI_TOOLS))`，第 44、65 行）
  直接断言"按意图筛选后暴露给模型的工具数量，严格小于全量
  `HOUDINI_TOOLS`"——这是行为级断言，不是仅检查配置项存在。
- `docs/adr/prompt-tool-contract-skill-ownership.md` 的 Consequences
  一节用文字描述了同一套机制（"stable schema order, dependency
  expansion, Web/vision filtering, and the schema token budget"...
  "Intent selection prewarms a small set; `search_tool_contracts(load=true)`
  loads additional enabled, mode-compatible contracts for the next model
  request"）——与上述代码逐句对应，说明 ADR 描述与实现一致，没有
  "纸面设计未落地"的问题。

**(b) Skill 层的真正懒加载——元数据发现与可执行代码导入分离**
- `tests/test_skills_metadata.py::test_descriptor_discovery_does_not_import_entrypoint_until_run`
  （约第 284-316 行）：构造一个临时 Skill 目录（`SKILL.md` +
  `scripts/main.py`，其中 `main.py` 被执行时会写入一个 marker 文件），
  调用 `skills._load_skill_descriptors(...)` 做发现后，立即断言
  `self.assertFalse(marker.exists())`——证明"发现/注册阶段"只解析了
  `SKILL.md` 的 JSON frontmatter 元数据（name/description/category/
  risk_level/parameters/entrypoint）和纯文本 instructions，**完全没有
  import 或执行** `scripts/main.py` 里的任何代码；只有显式调用
  `skills.run_skill(...)` 之后，marker 文件才出现
  （`self.assertTrue(marker.exists())`）。这是比一般"lazy import"更严格
  的懒加载语义：不仅代码不提前执行，连模块都不会被提前导入，杜绝了
  "import 时有副作用的第三方 Skill 脚本拖慢启动或引入未预期行为"的风险。
- `tests/test_skills_metadata.py::test_descriptor_rejects_nonstandard_entrypoint`
  （约第 320-335 行）：进一步确认非标准 `entrypoint` 格式
  （如 `scripts/other.py:execute`）在元数据解析阶段就被
  `_parse_skill_markdown` 拒绝（`ValueError`，错误信息包含
  `"scripts/main.py:run"`），即契约在"发现时"就被强制校验，而不是留到
  懒加载真正执行时才暴露格式错误。

### 是否行动
**不行动（No-Go）——无需新增机制，这是本次 5 项核验中证据最充分的
"已完全覆盖"结论。** 唯一可做的是把"等效性"这件事写成一句明确的对照
说明，供未来有人看到 fxhoudinimcp/dcc-mcp 的外部研究材料时，不会误以为
这是一个尚待实现的缺口（landscape 研究第 388 行已经给出过同样的判断：
"Partial overlap - Houdini-Agent's intent classifier already achieves a
similar practical effect...no urgent gap"，本次核验用更深的代码级证据
把"partial overlap"坐实为"functional equivalence confirmed by tests"）。

### 最小改动
- 可选：在 `docs/adr/prompt-tool-contract-skill-ownership.md` 的
  Consequences 一节补充一句显式的"外部对照"说明（例如一句话引用
  `dcc-mcp-houdini` 的 `load-skill` 模型并说明本仓库的等效机制是
  `ToolExposureState.load()` + Skill 发现-执行分离），帮助未来阅读者
  不再重复提出这项建议。这是纯文档改动，非强制项。

### 依赖
无。

### 风险
不行动的风险极低——这是唯一一项"确认已完整覆盖、无需任何代码改动"的条目；
唯一的轻微风险是"未来有人不知道这一机制已存在，重复提出/重复实现"，
已通过上面的"最小改动"文档建议缓解。

### 验收标准
无需新验收标准（不新增代码）；若采纳可选文档改动，验收标准为 ADR 中
出现明确的"与外部项目等效机制对照"段落。

### 优先级
**不列入行动优先级队列**（已完成/无需行动），可选文档改动若做，归为
最低优先级的顺手维护项。

---

## 总览与优先级排序

| 项目 | 状态 | 是否行动 | 优先级 |
|---|---|---|---|
| 1. fxhoudinimcp 基准 ADR | 已确认过期 | Go（文档） | 高（低成本） |
| 2. FastMCP Host/Origin/DNS-rebinding 防护 | **已确认缺失**（非仅怀疑） | Go（代码+配置+测试） | 中高 |
| 3. LOP/USD、PDG/TOP 只读工具 | 多数已实现，仅 4 项真实缺口 | 部分 Go（仅缺口项） | 中（P3 优先） |
| 4. Manifest/Registry/Dispatch 漂移检测 | 检测能力已扎实存在，缺 ADR 说明与 CI 强制 | Go（文档为主，CI 为可选） | 低 |
| 5. 请求级工具筛选 + lazy Skill loading | **已完整实现并有行为测试** | No-Go（可选文档对照） | 不列入队列 |

## 方法论说明（避免误读本报告的证据等级）

- 所有"已确认"类结论均追溯到具体文件路径+行号，或上游仓库的具体文件/
  commit SHA，而非仅基于名称匹配的 grep 结果。
- Item 2 的结论建立在对调用链的完整追踪之上：本仓库调用点 → FastMCP
  `run_http_async` → `Settings` 默认值 → `streamable_http_app` 函数签名
  默认值 → FastMCP 对官方 MCP SDK 层防护的主动屏蔽——四层缺一不可，
  任何一层单独成立都不足以下"确认缺失"的结论，这也是为何本报告将其
  与此前"review item, not confirmed absent"的保守表述区分开来。
- Item 2 的"fastmcp 未钉选版本"这一子结论未做 100% 穷尽搜索（原搜索
  因耗时被中断），已在证据部分明确标注为"大概率成立但建议复核"，不应
  被当作与其余证据同等强度的确定性结论。
- Item 3 的"真实缺口"判定，以本仓库当前源码为准，而非仅以
  `lops_pdg_tools_plan.md` 原计划文字为准——原计划中部分条目的"待实现"
  标注已经过时，本报告据实更正。
