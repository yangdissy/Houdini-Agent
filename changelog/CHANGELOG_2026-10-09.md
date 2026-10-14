# Houdini-Agent 更新记录（2026-10-08 至 2026-10-09）

## 发布摘要

本次更新围绕本地多语言语义能力、长期记忆质量、训练数据清洗和受治理的外部进程任务展开。

默认 Embedding 模型切换为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，并将其应用范围从个人与团队记忆扩大到知识库检索、Houdini 节点发现和 Skill 发现。旧向量不会与新模型向量混用；检测到不兼容个人记忆库时暂停向量评分并提示用户备份后迁移。

记忆强化从“召回即强化”改为“任务结果获得正向 reward 后强化”，召回查询同时加入上一轮用户目标摘要。团队记忆重建会在去重前统一使用当前模型重算向量。

此外，训练数据导出增强了注入指导清理和工具调用配对校验；MCP operation 增加进度、阶段、退出码和产物信息，并新增受 allowlist、session、超时、产物声明和审计约束的外部进程作业基础设施。

---

## 一、多语言 Embedding 模型与运行环境

- 默认模型切换为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。
- 模型维度保持 384，但明确视为新的向量空间，不与旧 fallback 或 `all-MiniLM-L6-v2` 向量混用。
- 优先从共享本地模型目录加载权重，避免每个用户重复下载以及运行时依赖网络。
- Houdini 20.5 使用 Python 3.10 ABI 依赖目录，Houdini 21.0 使用 Python 3.11 ABI 依赖目录；模型权重跨版本共享，二进制 Python 依赖保持隔离。
- Launcher 按 `_embed_complete`、`_embed`、普通 ABI 目录顺序选择可用依赖目录，支持完整环境替换期间平滑切换。
- 真实模型验证中，中英文等价 Pyro 描述相似度约为 `0.838`，无关文本约为 `0.048`。

---

## 二、个人与团队记忆迁移

### 个人记忆

- 记忆库继续校验 embedding backend、model、dimension 和 format version。
- 检测到旧向量 metadata 缺失或与当前模型不兼容时，禁用向量评分，避免同维度但不同语义空间的向量混算。
- UI 在主线程提示用户执行迁移；用户选择稍后处理时，下次启动仍会提醒。
- 迁移在后台线程执行，先备份数据库，再事务性重算情景、语义和程序记忆向量。
- 成功迁移后自动轮换 `agent_memory.db.bak.<timestamp>`，仅保留最近 3 份；迁移失败时不执行清理，保留全部恢复点。
- 轮换只识别迁移备份的纯数字时间戳后缀，不删除主数据库、`pre-overwrite-backup` 或其他文件。
- 迁移成功或失败通过独立对话框反馈，不依赖当前是否存在聊天响应气泡。

### 团队记忆

- `Rebuild Team Memory` 在语义和程序记忆去重前，先使用当前模型覆盖导出文件中的旧向量及来源 metadata。
- 去重始终在同一当前模型向量空间内完成，不再因为旧模型、fallback 或缺失 metadata 而跳过本应合并的近义记录。
- 数据库替换仍保持临时文件构建和原子替换语义；文件被其他 Houdini Agent 进程占用时不会强行覆盖。

---

## 三、记忆召回与强化调整

- 移除“记忆一旦被召回就立即增加 activation”的行为。
- 每轮仅记录被实际注入上下文的个人语义记忆 ID，等待本轮反思结果。
- 只有任务获得正向 reward 后才增加对应记忆 activation；失败、负向或无 reward 的结果不会强化召回记录。
- 记忆查询由“当前用户消息 + 场景节点类型”扩展为“当前用户消息 + 上一轮用户目标摘要 + 场景节点类型”。
- 上一轮目标摘要最多取 300 字符，避免历史上下文无界进入检索 query。
- 个人和团队记忆继续共享既有候选选择器与 900 字符注入预算。

---

## 四、多语言语义能力扩展

### 知识库检索

- `HoudiniDocIndex.search_knowledge()` 从纯词法评分升级为关键词与多语言语义混合排序。
- 词法命中继续负责节点名、参数名和专业术语等精确匹配；语义分数用于跨语言补召回和近义排序。
- 文档向量在首次知识库查询时批量生成并在索引实例内缓存，不增加面板启动时延。
- 只有真实 Sentence Transformers 后端启用语义补召回；fallback 模式保持原有关键词检索。
- 模型加载或编码失败时自动回退词法路径，不阻断文档搜索。

### Houdini 节点发现

- `semantic_search_nodes()` 不再仅依赖硬编码中英文映射。
- 当前类别下的节点类型名和 Houdini `description()` 会被批量编码，并与自然语言查询计算相似度。
- 节点向量缓存与原有 5 分钟节点类型索引同步失效。
- 现有关键词映射继续作为精确加分和无模型回退，类别过滤仍在语义排序前执行。
- 该能力只返回节点候选，不创建节点、不扩大 Agent 工具权限。

### Skill 发现

- `list_skills()` 新增可选 `query` 和 `limit` 参数。
- 查询会综合 Skill 名称、分类、描述和参数说明进行跨语言语义排序。
- MCP 工具 schema 同步支持自然语言 Skill 查询，默认返回最多 5 个相关候选，减少将全部 Skill 元数据发送给模型的 token 开销。
- 语义发现只负责返回候选；`run_skill` 的风险级别、Plan 阶段限制和执行治理保持不变。

---

## 五、训练数据导出清洗

- 工具结果导出时移除运行时注入的指导文本，避免将内部引导语训练进模型。
- 样本上下文裁剪到第一个有效 user 消息开始，避免助手消息成为训练样本开头。
- 校验 assistant tool call 与后续 tool result 的配对关系，删除孤立或无法配对的工具消息。
- 对缺少或非法工具名的历史调用使用稳定 ASCII 函数名修复，不生成不可训练的空工具调用。
- 工具结果正文限制为 2000 字符，降低单条异常输出污染数据集的风险。

---

## 六、受治理的外部进程作业

- 新增 `ExternalProcessJobAdapter`，用于运行预注册、显式 allowlist 的外部进程任务。
- 每种作业必须提供固定 executable、参数构建器、超时、允许产物和必需产物声明；调用方不能提交任意命令行。
- 输入 payload 必须为有界 JSON 对象，超长或包含非 JSON 值时拒绝执行。
- 作业由 session 和 operation ID 共同约束，查询与取消不能跨 session。
- 明确区分 completed、failed 和 cancelled；非零退出码及超时不会被误报为用户取消。
- stdout 仅接受有界 JSON Lines 事件，未知事件、超长事件和非法 JSON 均 fail closed。
- 产物必须预先声明，且只能位于作业专属目录；拒绝路径逃逸、符号链接、缺失产物和超限文件。
- stdout、stderr 和审计记录均有界；审计不记录原始 payload 或绝对路径。
- adapter shutdown 会终止活动作业并拒绝新任务。

该模块目前提供受治理的作业生命周期基础，不等同于开放任意 shell 或 Python 执行。

---

## 七、Operation 与诊断增强

- MCP operation record 新增 `stage`、`exit_code` 和结构化 `artifacts`。
- 新增单调进度更新接口，进度必须位于 $[0, 1]$，运行中不得倒退。
- operation 产物对外只暴露名称、受控路径、大小和 media type。
- 诊断导出新增外部作业模块可用状态、runtime 配置状态、事件计数和最近 100 条作业事件。
- 诊断仅导出事件类型、时间、operation ID、kind、decision、退出码和受控产物摘要，不导出 prompt、payload 或绝对路径。

---

## 八、安全与兼容性

- 语义模型只参与检索、排序、近义去重和候选发现，不参与工具授权、安全策略或高风险操作确认。
- 精确节点名、参数名、路径和工具调用参数继续使用确定性规则处理。
- 节点语义搜索和 Skill 发现不会绕过 Tool Registry、mode、allowlist 或 Skill 风险限制。
- embedding 不兼容时 fail closed：禁用向量评分并要求迁移，不根据维度相同假设语义空间兼容。
- 外部进程任务默认不可用，只有代码注册的作业类型可以启动。
- 未开放任意 executable、shell 文本、工作目录、产物路径或跨 session 操作。

---

## 九、测试与验证

### 自动化结果

- 训练数据、团队记忆、文档检索、Skill 发现、MCP operation、外部进程作业、诊断导出和工具契约联合回归：`75 tests passed`。
- 节点跨语言语义搜索在 Houdini 21.0.596 hython 下通过：`1 test OK`。
- Skill 多语言发现聚焦测试：`3 tests passed`。
- 文档语义检索聚焦回归：`13 tests passed`。
- 工具契约聚焦回归：`20 tests passed`。
- 本次涉及的 Python 文件通过 `py_compile` 和 workspace diagnostics。

### 真实运行时验证

- Houdini 20.5.684 / Python 3.10.10 成功加载本地多语言模型并生成 384 维向量。
- Houdini 21.0.596 / Python 3.11.7 成功加载独立 ABI 依赖目录和共享模型权重。
- 两个版本均使用 `sentence-transformers` 后端，而非 fallback。

---

## 已知范围

- 首次执行知识库、节点或 Skill 语义查询时需要加载模型并生成对应缓存，首次查询延迟高于后续查询。
- 知识库和节点向量当前为进程内缓存，Agent 重启后会重新编码；尚未增加持久化向量索引。
- 各用户的个人记忆迁移需要在自己的 Houdini Agent 面板中确认执行。
- 团队记忆数据库被其他 Houdini Agent 进程占用时，需关闭占用进程后再次执行 Rebuild。
- 外部进程作业基础设施尚未注册通用用户作业，也不会接受任意命令。
- 工具意图分类仍以确定性中英文关键词为主；多语言模型尚未进入每次消息发送的关键路径。

---

## 十、结构化 Docs Skills

### 新增能力

- 新增 `lookup_vex_reference`，联合 Houdini 自带 VEX 离线手册和随项目分发的 snippets 参考，返回函数、概念及错误信息对应的结构化证据。
- 新增 `explain_node_parameters`，按节点类型和用户目标筛选相关参数文档，避免将整页参数说明直接交给 Agent。
- 新增 `find_node_for_task`，根据任务描述从节点文档反查候选节点，并支持 SOP、LOP、DOP、COP 等上下文过滤。
- 新增 `compare_houdini_nodes`，并列返回多个节点的用途、上下文、输入、参数、示例和注意事项；未找到的节点会被明确标记，不伪造比较结果。
- 新增 `explain_houdini_error`，从 Houdini、VEX、USD、Karma 和 Python 相关离线文档中查找错误证据，并保留实际使用的检索词。
- 新增 `lookup_attribute_semantics`，查询 `P`、`N`、`orient`、`pscale`、`name` 等属性的类型、用途、优先级和常见陷阱。
- 新增 `lookup_expression_reference`，查询 HScript 表达式、通道引用、局部变量和 VEX snippet 语法，并返回对应上下文及来源。
- 新增 `check_example_compatibility`，提取 VEX 或 Houdini 示例中的标识符，并逐项检查当前随附文档是否存在对应条目。

### 文档检索基础

- 新增共享只读模块 `_doc_support.py`，统一封装帮助目录发现、ZIP 页面遍历、关键词排序、Markdown 章节提取和结果裁剪。
- 复用现有 `houdini_agent.utils.help_source`，不再实现第二套 Houdini 帮助目录发现或 wiki 解析逻辑。
- 数据来源包括 Houdini 离线帮助中的 `nodes.zip`、`vex.zip`、`hom.zip`，以及 `Doc/vex_attributes_reference.txt` 和 `Doc/vex_snippets_reference.txt`。
- 搜索结果保留标题、文档路径、节点上下文、内部类型名和匹配章节，便于 Agent 引用来源并继续深查。
- 新能力负责结构化解释、比较和核对，不替代已有 `search_local_doc`、`get_houdini_node_doc` 或 `search_houdini_help`。

### 安全与行为边界

- 全部 Docs Skill 为 `low` 风险、只读能力，不导入 `hou`，也不读取或修改当前 HIP 场景。
- 示例兼容性检查不会执行用户代码、Cook 节点或调用 shell，仅核对标识符是否存在于随附文档。
- 文档没有命中时返回空证据或 `found: false`，不根据模型常识补写不存在的参数、节点或函数。
- `check_example_compatibility` 只证明文档中存在相关标识符，不代表示例已通过运行时、类型或语义验证；返回结果中会明确提示此限制。
- 单次检索限制扫描页数、页面大小和返回条数，避免离线手册查询无界消耗资源。

### 测试与验证

- 新增 `tests/test_docs_skills.py`，覆盖必填参数、VEX 多来源证据、节点参数目标筛选、上下文过滤、缺失节点、错误关键词清理、属性规范化、表达式多来源结果和未记录函数检查。
- 8 个 Docs Skill 已纳入统一 Skill 元数据、分类目录和无 `hou` 导入契约测试。
- Docs Skills、Skill loader 和帮助源联合回归：`32 tests passed`。
- Python 运行时能够正常导入共享模块，并可通过动态 Skill loader 发现新增能力。

### 已知范围

- 当前参数筛选基于帮助页 `@parameters` 章节中的文本段落，不解析 Houdini 参数模板或菜单 token schema。
- 节点比较返回文档证据，不主动生成主观性能结论；只有手册明确记录的性能信息才会出现在结果中。
- 错误解释是文档检索入口，不读取报错节点、场景状态或 cook 日志；需要场景级诊断时仍应使用对应检查工具。
- 示例兼容性检查当前以函数调用标识符为主要核对单位，不进行 VEX AST、重载匹配、参数类型检查或 Houdini 版本差异分析。
- VS Code/Pylance 对新共享模块仍显示一条无法解析导入的索引诊断；同一解释器下的实际导入、动态发现和全部自动化测试均已通过。

---

## 十一、Houdini Skill Creator 第一阶段

### `draft_houdini_skill`

- 新增 `authoring` Skill 分类，用于 Skill 草案生成、契约校验和后续评估能力。
- 新增只读 Skill `draft_houdini_skill`，将名称、意图、分类、参数、示例、Houdini 依赖和风险信息转换为可审核的 Python Skill 草案与聚焦测试草案。
- 草案遵循当前运行时协议：`SKILL_INFO`、现有分类目录、参数元数据以及 `run(**kwargs) -> dict`。
- 返回建议模块路径、测试路径、相邻 Skill、最多 3 个评估案例、兼容性信息和人工审查清单。
- Workflow 草案会明确要求只返回 blueprint，并在后续执行前通过 `create_nodes_batch(dry_run=True)` 审核。
- 需要 `hou` 的草案会提示 Houdini runtime 和主线程边界；场景修改草案会提示确认、Undo、审计和缓存失效链路。

### 治理边界

- 第一阶段不会写入任何 Skill 或测试文件，结果固定返回 `written: false`。
- 不导入、不编译、不执行生成的代码，结果固定返回 `executed: false`。
- 不允许未知分类、非法 Python 标识符、重复参数或不支持的参数类型。
- 场景修改能力不能声明为 `low` 风险，避免生成具有误导性治理元数据的草案。
- 生成结果中的实现体保持显式失败状态，必须由开发者补充实现和行为断言后才能安装。
- 相邻能力通过现有 `list_skills` 发现，用于提醒重复职责，不自动覆盖或修改已有 Skill。

### 测试与验证

- 新增 `tests/test_draft_houdini_skill.py`，覆盖无写入/无执行、代码模板、测试模板、非法分类、低风险场景修改拒绝和 Workflow blueprint 提示。
- `draft_houdini_skill` 已纳入统一 Skill 导入、分类和元数据契约。
- 工具选择指南新增 Skill 创建与适配路由，要求先生成草案，再通过独立实现步骤写入和验证。

### 已知范围

- 第一阶段只生成草案，不提供文件安装、覆盖、回滚或用户 Skill 目录写入。
- 草案器不会根据自然语言自动实现 Houdini 业务逻辑；生成的 `run()` 会保持 `status: draft` 并返回明确错误。
- 评估案例当前来自调用者提供的示例，不运行基线对比、子代理评分、token benchmark 或 Anthropic eval viewer。

---

## 十二、Houdini Skill Creator 第二阶段

### `install_houdini_skill`

- 新增受治理的用户 Skill 安装器，接收经过实现和审核的完整 Python 源码。
- 默认 `mode='preview'`，只执行语法、元数据、目标目录、重名和 draft 占位检查，不写入文件。
- `mode='install'` 只允许写入 `config/houdini_ai.ini` 中 `[skills] user_skill_dir` 指向的有效目录；未配置时 fail closed，不回退到内置 Skill 目录。
- 目标文件名完全由经验证的 `SKILL_INFO.name` 推导，不接受调用方提供任意相对或绝对路径。
- 安装前拒绝内置或用户 registry 中的同名 Skill、现存目标文件、目录符号链接、目标符号链接和路径逃逸。
- 源码使用 AST 校验，要求字面量 `SKILL_INFO`、同步 `run()`、已知分类、有效风险级别和完整参数元数据。
- 第一阶段生成的 `status: draft` 或 `Implementation required...` 占位实现不能安装。

### 预览确认协议

- 每次成功预览返回一个随机一次性 `confirmation_token`。
- token 与预览源码的 SHA-256 摘要绑定；预览后源码发生任何变化，安装都会被拒绝。
- 安装调用必须同时提供精确相同的源码和 token；跳过预览、重复使用 token 或进程重启后使用旧 token均会 fail closed。
- 新预览会使旧 token 失效，避免多个待安装草案共用模糊确认状态。

### 写入与回滚

- 安装采用同目录 `.partial` 文件、flush、`fsync` 和 `os.replace` 原子替换流程。
- 安装器绝不覆盖已有文件，原子替换只发生在预先确认不存在的目标路径上。
- 写入后调用现有 Skill loader 重载并验证新名称可发现，但不会调用新 Skill 的 `run()`。
- loader 发现失败或安装异常时删除新目标和临时文件，避免留下不可用的半安装 Skill。
- 安装结果始终包含 `executed: false`，明确区分“被 loader 发现”和“业务代码已执行”。

### 测试与验证

- 新增 `tests/test_install_houdini_skill.py`，覆盖预览无写入、原子安装、未配置目录拒绝、draft 拒绝、重名拒绝、loader 失败回滚、缺失 token 拒绝和源码变更令牌失效。
- `install_houdini_skill` 已加入统一 Skill 导入、分类和元数据契约。

### 已知范围

- 当前配置文件默认未包含 `[skills] user_skill_dir`；使用安装能力前需先在插件管理界面选择用户 Skill 目录。
- 安装器不开放覆盖、升级或卸载已有 Skill；这些操作需要独立的版本、备份和回滚协议。
- AST 校验验证结构和治理元数据，不证明实现逻辑正确；安装前仍需人工审查和聚焦行为测试。
- 安装后仅验证 loader 可发现，不执行新 Skill，避免安装动作触发场景修改、文件写入或其他业务副作用。

---

## 十三、每用户 Skill 目录与创建入口

### 用户目录与配置

- 每个用户默认使用 `cache/users/<username>/skills` 作为个人 Skill 目录。
- 初始化用户时自动创建 Skill 目录，并在该用户的 `config.ini` 中补齐 `[skills] user_skill_dir`。
- 兼容用户配置中已有的旧式 `key:value` 内容，不要求整体改写配置文件。
- Skill loader 按当前用户读取配置和发现个人 Skill，避免不同用户之间互相加载私有能力。
- MCP 客户端切换用户时同步更新 Skill registry；执行 `run_skill` 前再次绑定当前用户，避免长生命周期客户端使用过期用户上下文。

### 运行时与交互入口

- 本地 `list_skills` 不再硬编码 Houdini runtime，而是使用工具注册表中的运行时元数据进行分派。
- 对话框 `/` 命令列表新增 `/create_skill`，用于向 Agent 提交仅生成草案的 Skill 创建请求。
- `/create_skill` 不直接写入或执行 Skill；实际安装仍经过预览、人工审核和独立安装步骤。
- `install_houdini_skill` 预览时会初始化当前用户目录和配置，因此新用户无需先手工创建 Skill 目录。

### 确认协议回退

- 曾尝试将安装参数 `confirmation_token` 改名为 `approval_code`，以绕过通用敏感参数检测和输出脱敏。
- 该方案会让一次性确认凭据继续经过模型可见的通用 `run_skill` 参数通道，因此不作为最终设计保留。
- 已完整撤销 `approval_code` schema、实现和护栏特例测试，恢复原有 `confirmation_token` 预览与安装契约。
- 通用 harness 的敏感参数拒绝和输出脱敏规则保持严格，未为安装器增加例外。
- 后续确认机制将重新设计；候选方向是由服务端保存待确认预览状态，并通过独立人工确认动作消费，不在通用工具参数中传递凭据。

### 测试与验证

- 用户路径、Skill 安装、harness policy 和工具运行时相关聚焦回归均已通过。
- 本次确认参数回退联合回归：`55 tests passed`。
- 涉及的安装器、harness 和测试文件通过 workspace diagnostics，无新增错误。