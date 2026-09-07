# ADR-0002: Manual 逻辑批次与 scoped validation barrier

- 状态: 已接受 (Accepted)
- 日期: 2026-08-27

## 背景

Agent 在同轮工具调用中会把只读调用批量提前执行，并缓存查询结果。节点修改后读取可能因此发生在修改前，或命中旧缓存。Manual 模式验证还可能持久切到 Auto，或在 cook/read/restore 失败后错误宣称健康。

## 决策

1. Houdini 调用严格保留模型给出的相对顺序，只批处理连续 readonly 段。
2. mutation、`set_update_mode`、temporary validation 是 execution barrier；成功后立即失效查询缓存。
3. Manual 下先完成相关 mutation 批次，再临时切 Auto，只 cook/read 指定 target，最后恢复真实原模式。
4. `set_update_mode` 是独立的 persistent state change，仅用于用户明确要求；Confirm Mode 下必须确认，不归类为代码执行工具。
5. 工具继续提供字符串 `result`，并提供 `health`、`freshness`、cook/read/restore 与 mode 结构化字段。失败、Volume/VDB 安全跳过或恢复不确定时 `health=unknown`。
6. 治理异常 fail closed；审计只记录决策元数据和参数键，不记录 prompt 或参数内容。

## 后果

- 同轮 mutation→read 不再逆序。
- validation/mode barrier 后不会复用旧读取。
- 临时验证不会持久改变用户 Manual 设置；恢复失败可被模型明确识别。
- readonly batch 数量可能增加，但只发生在真实 barrier 分隔处。