# CONTEXT — Houdini-Agent 领域词汇

项目的领域模型与通用语言（ubiquitous language）。架构讨论与代码命名以此为准。

## Harness（工具治理层）

- **Harness**：对 LLM 工具调用做参数校验、风险评分与策略决策（allow / deny / ask / retry）的运行时层。入口 `houdini_agent/core/harness_engine.py`。
- **Tool Argument Validator**：`ToolArgumentValidator`，在策略评分前对工具参数做规范化（normalize）与结构化校验，产出 `ToolValidationResult`。
- **Tool Policy Engine**：`HarnessToolPolicyEngine`，基于 validator 结果 + 上下文（mode、confirm_mode）产出 `ToolPolicyDecision`。只做策略决策，验证逻辑一律委托 validator。
- **Node Path（节点路径）**：Houdini 场景内的节点路径，如 `/obj/geo1`。校验 traversal、null-byte，并强制落在 `_HOUDINI_ROOTS` 内。参数集合 `_NODE_PATH_KEYS`。
- **File Path（文件系统路径）**：操作系统路径，如 HIP 保存路径、渲染输出图片路径。校验 traversal、null-byte，豁免 Houdini root。参数集合 `_FILE_PATH_KEYS = {file_path, output_path}`。
- **Policy Decision**：`ToolPolicyDecision`，action ∈ `allow` / `deny` / `ask` / `retry`；`retry` 携带 `patched_args` 用于自动修补后重试。
- **Scoped Validation Transaction（目标范围验证事务）**：在捕获当前 Update Mode 后临时进入 Auto，只对指定 target 执行 cook/read，并恢复进入时模式的验证事务。operation 或 restore 失败、以及安全阻断时，健康与新鲜度均为 unknown。

## 文档检索（Doc RAG）

- **Help Source**：`houdini_agent/utils/help_source.py`，离线帮助数据源的底层 module。公开 `find_help_dir`（定位含 nodes.zip/vex.zip/hom.zip 的 help 目录）、`parse_wiki`（wiki 标记解析）、`iter_pages`（ZIP 页面遍历，统一过滤规则）。是 `HoudiniDocIndex` 与 `search_houdini_help` skill 共享的 seam。
- **Doc Index**：`HoudiniDocIndex`（`houdini_agent/utils/doc_rag.py`），dict 索引 + 知识库分段检索。ZIP 索引缓存以 help_dir 路径 + 版本 + zip mtime/size 指纹失效。

## 视觉验证（Visual Review）

- **Visual Review**：对当前 Houdini viewport 截图进行目标驱动的视觉观察。技术事实、显示状态、图像观察和目标契合度必须分开；截图不能证明网络健康、几何 freshness 或材质绑定正确。
- **Visual Goal**：用户明确提供的风格、构图、材质或灯光目标。缺少 Visual Goal 时，只允许检查通用可读性和明显视觉缺陷，不得宣称“美术正确”。

## 团队记忆（Team Memory）

- **Team Memory Export Document（团队记忆导出文档）**：成员主动发布、供团队记忆重建消费的版本化文档。扫描来源决定贡献者身份；文档必须通过 schema、资源限制及共享资格检查。
- **Team Memory Eligibility Policy（团队记忆共享资格策略）**：决定一条长期记忆是否可以进入团队共享层的统一规则。结构或安全无效与正常但不合共享资格是两种不同结果。
- **Invalid Entry（无效条目）**：违反导出文档 schema、类型、资源限制或向量一致性的条目；拒绝并产生不含记忆正文的有限诊断。
- **Ineligible Entry（不合共享资格条目）**：结构合法，但未达到 Team Memory Eligibility Policy 的条目；属于预期隐私或质量过滤，仅聚合计数。

## 工具约定

- **`save_hip`**：保存 HIP 文件，参数名为 **`file_path`**（不是 `output_path`）。harness 会为其自动补 `.hip` 扩展名。见 ADR-0001。
- **`setup_render`**：配置渲染，其 `output_path` 是**渲染输出图片路径**（文件系统路径），与 `save_hip` 的 `file_path` 不同名。

## 决策记录

- 架构决策见 `docs/adr/`。
