# Houdini-Agent 更新记录（2026-10-15）

## 发布摘要

本次更新强化了工具执行结果管理、操作恢复、工具契约自省、Python 执行治理和 Spare Parameter 管理能力。

大型工具结果现在可以归档为会话隔离的 `result_ref`，并通过 JSON Pointer 与字符分页按需读取；操作 receipt 升级为正式恢复协议，记录稳定请求引用、工具合同版本、参数摘要、场景身份和执行端身份。Tool Registry 同时成为可查询的工具合同权威来源，并新增独立的只读 Python 检查入口和受治理的 Spare Parameter 写入工具。

---

## 一、通用 Result Reference 与分页读取

- 新增通用 Tool Result Store，对超过约 16 KB 的已脱敏工具结果进行归档。
- 大结果返回稳定 `result_ref`，避免将完整载荷持续写入模型上下文。
- 新增 `read_tool_result`，支持按 `result_ref` 读取归档结果。
- 支持 JSON Pointer 选择结果子树，减少无关数据传输。
- 支持基于字符偏移量和上限的分页读取，并返回后续分页所需元数据。
- Result Store 按会话隔离；其他会话不能读取不属于自己的引用。
- 归档发生在结果脱敏之后，避免通过结果存储绕过现有敏感信息处理边界。

---

## 二、Operation Receipt 正式恢复协议

- receipt 增加稳定 `request_ref`，当前与对应 `operation_id` 对齐，用于查询和恢复关联。
- 增加协议版本、参数摘要和工具 `contract_version`，便于判断恢复请求与原执行上下文是否一致。
- `get_operation_status` 和 receipt 列表继续作为操作状态真相源。
- 未知传输状态与已知执行状态明确分离；无法确认结果时不会自动重放可能产生副作用的操作。
- 工具执行完成后可将最终结果信息附加到原 receipt，保持操作身份连续。

---

## 三、Registry 驱动的工具契约查询

- Tool Registry 新增单工具契约查询 `inspect_tool_contract`。
- 新增 `search_tool_contracts`，支持按名称、描述、标签和模式查找工具合同。
- 查询结果来自已注册 `ToolMeta`，不暴露可执行 handler。
- 公共合同包括 schema、owner、标签、模式、runtime、风险级别、确认要求以及 Undo/Cook 等执行语义。
- 每份合同使用确定性的 SHA-256 摘要生成 `contract_version`；合同内容变化时版本随之变化。
- 合同序列化采用稳定键排序，避免字典顺序导致无意义版本漂移。

---

## 四、独立只读 Python 检查入口

- 新增 `inspect_python`，用于执行经过静态分类的只读 Python 代码。
- AST 分类器位于独立纯 Python 模块，不依赖 Houdini、Qt 或 MCP client 导入链，可单独测试。
- 分类采用 fail-closed 策略：写操作、导入、赋值及无法确认安全性的调用默认拒绝。
- 仅允许小范围纯内建查询和输出函数，包括只读计算与 `print()`。
- `inspect_python` 与现有高风险 `execute_python` 分离，不扩大任意 Python 执行权限。
- 工具可用于 Agent、Ask 和 Plan 规划阶段的只读检查。

---

## 五、场景与执行端身份

- operation receipt 增加稳定 `executor_id`，用于区分不同面板或执行器实例。
- 增加 `scene_id`，用于标识操作发生时的 Houdini 场景上下文。
- UI 初始化时为每个面板建立稳定执行端身份，并向主线程执行器注入场景身份提供器。
- 状态查询可同时核对请求、合同、场景和执行端身份，降低跨场景或跨执行器误恢复风险。

---

## 六、Spare Parameter 管理

- 新增 `upsert_spare_parameter`，用于创建或显式替换受支持的标量 Spare Parameter。
- 工具作为正式场景写操作进入 Registry、Harness 策略、Undo、Cook 和缓存失效语义。
- 参数意图过滤和依赖展开会同时提供 `inspect_node` 与 `get_parameter_schema`，便于写入前检查目标节点和参数合同。
- Agent Direct Execute 模式可直接完成受治理写入；Confirm Mode 仍由 Harness/UI 请求用户确认。
- 对专用工具尚不支持的模板类型或复杂布局，允许回退至受治理的 `execute_python`，但仍经过危险代码过滤和审计。

---

## 七、安全与执行边界

- 新增查询工具通过 Registry 注册并参与模式、runtime、风险和确认策略判定。
- `inspect_tool_contract`、`search_tool_contracts` 和 `read_tool_result` 使用本地 runtime。
- `inspect_python` 作为只读工具进入只读、Ask 和 Plan 规划白名单。
- `execute_python` 从“一律确认”调整为 Agent Direct Execute 模式可直接调用，Confirm Mode 下仍按界面策略确认。
- `execute_python` 继续经过模式限制、危险代码过滤、参数摘要和仅记录代码哈希的审计；模型不能通过参数跳过确认。
- 高风险 Shell、保存场景及其他高影响操作未降低授权或确认要求。
- receipt 恢复继续遵循 fail-closed 原则，不把超时或断连等同于执行失败。

---

## 八、测试与验证

- Tool Registry 定向测试：`66 passed`。
- 工具合同测试：`25 passed`。
- Result Store 测试：`3 passed`。
- 只读 Python、Registry 与合同组合回归：`94 passed`。
- receipt、结果存储、只读 Python、合同和诊断组合验证：`115 passed`。
- 最终聚焦复验：`49 passed`。
- Harness 策略覆盖 Direct Execute、Confirm Mode、危险 Python 拒绝和模型伪造跳过确认参数。
- Spare Parameter 定向测试覆盖创建、替换、校验和治理边界。
- 测试解释器为 Python 3.8.10：`C:\rez\rez_2.112.0\Scripts\python.exe`。

---

## 已知范围

- Raw HOM AST Gate 尚未纳入本次更新；`execute_python` 仍依赖现有危险代码过滤、Harness 策略和审计边界，而非完整 HOM AST 能力分类。
- Result Store 当前针对大型文本化工具结果提供字符分页，不是通用二进制对象存储。
- receipt 用于查询与恢复判断，不承诺自动重放未知状态的写操作。
- 合同版本使用 Python 标准库 `hashlib` 生成，不需要额外依赖或复制到项目 `lib/`。
- 工作区中既有的 `bs4` 静态导入诊断与本次变更无关。