# Houdini-Agent 更新记录（2026-10-14）

## 发布摘要

本次更新完成内置 Skill 的标准 bundle 迁移，新增面向 Houdini 工作流的方法层 Skill，并强化 Skill 发现、执行路由与循环治理。

内置 Skill 现在统一使用 `SKILL.md` 描述元数据和使用说明；可执行 Skill 使用固定入口 `scripts/main.py:run`，instructions-only Skill 仅提供按需方法指导。Skill 发现不再导入可执行代码，非法 metadata、路径逃逸、符号链接、重复名称和非标准入口继续 fail closed。

此外，`list_skills` 的中文查询改用轻量双语词法检索，不再为 Skill 发现探测完整 Sentence Transformers 依赖。首次中文查询实测由约 8.4 秒降至约 1.1 秒，并增加专用循环预算，避免模型持续更换参数反复调用同一发现工具。

---

## 一、标准 Skill Bundle 迁移

- 61 个内置可执行 Skill 已迁移为标准目录 bundle：`<category>/<name>/SKILL.md` 与 `scripts/main.py:run`。
- `SKILL.md` 使用严格 JSON-compatible frontmatter，声明名称、描述、分类、风险级别、参数和可选入口。
- 可执行入口固定为 `scripts/main.py:run`，不接受自定义模块路径或任意函数名。
- Skill 发现阶段只解析 metadata 和 instructions，不导入可执行 Python 代码。
- 入口仅在 `run_skill` 实际执行对应 Skill 时延迟加载，并校验函数签名与参数合同。
- 内置 Skill 缺少分类、使用未知字段、名称与目录不一致、入口逃逸、符号链接或文件缺失时拒绝加载。
- 重复 Skill 名称采用 fail-closed 处理：冲突候选均不进入 registry，并记录结构化诊断。
- 用户目录继续兼容旧式 `SKILL_INFO` / `run()` 单文件 Skill，但新建 Skill 应使用标准 bundle。

---

## 二、方法层 Instructions-only Skills

新增三个只读、不可执行的方法 Skill：

- `decompose_houdini_task`：定义跨领域模块边界、依赖关系、局部反馈和集成顺序。
- `design_houdini_parameter_ui`：定义面向艺术家的参数语义、控件选择、布局、绑定和兼容性建议。
- `handoff_houdini_network`：定义网络编辑入口、输出、Network Box 职责、注释和交付布局。

instructions-only Skill 没有 Python entrypoint：

- 通过 `get_skill_instructions` 按需读取内容。
- 通过 `run_skill` 执行时明确拒绝，不把 Markdown 当作代码运行。
- 不注册为独立工具，不扩大 Tool Registry 权限或 Houdini 场景修改能力。

当前内置库存为 65 个 Skill，其中 61 个可执行、4 个 instructions-only。

---

## 三、Workflow Skill 协作边界

以下现有 workflow Skill 增加结构化模块边界和方法 Skill 路由，同时保持原节点、连接、参数及 blueprint 执行合同不变：

- `procedural_modeling_guide`
- `setup_copernicus_pipeline`
- `setup_kinefx_pipeline`
- `setup_material_lookdev`
- `usd_scene_assembly_guide`

具体行为：

- 复杂任务可推荐 `decompose_houdini_task`、`design_houdini_parameter_ui` 和 `handoff_houdini_network`。
- 简单 procedural modeling 不附加复杂分解流程，避免为小任务引入额外仪式。
- Workflow 输出增加 `module_boundaries` 或 `recommended_existing_skills`，供 Agent 规划与交付使用。
- 可执行领域 Skill 继续拥有节点配方、版本相关实现和结果验证职责；方法 Skill 不复制工具 schema 或业务构建逻辑。
- 自动化测试校验所有结构化推荐名称均存在于当前 Skill registry。

---

## 四、Skill 发现性能与中文召回

- `list_skills(query=..., limit=...)` 继续按名称、分类、描述和参数说明进行相关性排序。
- Skill 发现改用独立的 lightweight 双语词法 embedder，不再初始化完整 Sentence Transformers backend。
- `LocalEmbedder` 新增 `load_semantic_model=False` 轻量构造方式；文档 RAG、记忆和其他语义消费者仍使用原有全局语义模型路径。
- 无语义模型时不再退回无法处理中文整句的空格分词，而是使用已有 CJK n-gram、中英文领域别名和哈希向量。
- 增加“性能”“拖慢”“运算”等领域别名；查询“检查哪些节点拖慢了运算”会优先返回 `analyze_cook_performance`。
- 实测首次中文 Skill 查询从约 8.4 秒降至约 1.1 秒，热查询约 0.0007 秒。
- 剩余首次延迟主要来自内置 bundle 扫描及基础数值依赖导入，不再来自重模型探测。

---

## 五、Agent 工具循环治理

- 修复 Agent 持续更换参数调用 `list_skills`、软提示后仍继续循环的问题。
- `list_skills` 连续调用达到 8 次时中止当前 agent loop，并要求根据已有结果调用 `run_skill` 或直接说明没有合适 Skill。
- Streaming tool-call 模式与 JSON tool-call 模式共用同一循环判定，避免治理行为漂移。
- 完全相同参数的重复调用继续使用通用签名检测和缓存机制。
- `set_node_parameter` 等正常批量操作不受 Skill 发现专用预算影响。
- 循环终止发生在 AIClient 治理层，不修改 Skill loader、风险级别或 MCP 工具授权。

---

## 六、文档与所有权

- 新增 ADR，明确 system prompt、工具合同、Skill instructions 和可执行 Skill 之间的职责边界。
- 工具 schema 继续拥有参数名、类型、必填项、默认值和枚举。
- Tool Registry 与 MCP dispatch 继续拥有授权、确认、执行和审计语义。
- 方法 Skill 只负责工作方法和交付结构，不定义第二套工具参数合同。
- Loader 模块说明已更新为标准 bundle、延迟导入和 instructions-only 模式。

---

## 七、测试与验证

- Skill metadata 与 workflow 定向测试：`28 passed`。
- 11 个 Skill 测试模块完整回归：`80 passed`。
- Agent loop、streaming executor 与工具分发邻近测试：`37 passed`。
- Skill 搜索、AI loop、语义节点搜索和帮助源相关回归：`60 passed`，另有 1 项既有库存检查被单独记录。
- Python compileall、VS Code diagnostics 和本次文件的 `git diff --check` 通过。
- Houdini 21.0.596 hython smoke 验证：65 个 Skill、61 个可执行、4 个 instructions-only、0 条 discovery diagnostics。

---

## 已知范围

- 当前工作树中存在 `authoring/draft_houdini_skill.py` 和 `authoring/install_houdini_skill.py` 两个旧式分类目录文件，因此“内置分类目录无 legacy `.py`”库存测试仍会失败；本次未擅自删除这些文件。
- Skill 发现的轻量双语排序用于候选检索，不参与工具授权、安全决策或高风险操作确认。
- 词法 fallback 为确定性近似检索，不等同于完整多语言语义模型；未覆盖的表达仍可能需要补充领域别名。
- `list_skills` 的 8 次预算限制单轮连续发现循环；新用户请求会重新开始计数。
