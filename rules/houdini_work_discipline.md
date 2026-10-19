# Houdini 工作纪律

本规则约束创建、修改和调试 Houdini 内容的工作顺序，不扩大工具权限。

## 工具顺序

- 优先级：workflow/blueprint/guide skill > 原生或批量节点操作 > VEX wrangle > Python。
- 写 VEX、Python SOP 或调用 `execute_python` 前，先判断原生节点或现有 skill 是否能完整完成；若缺少必要能力（例如写入 Spare Parameter / `ParmTemplateGroup`），应直接调用注册的 `execute_python` 工具作为 fallback。注册工具调用会经过 Harness、安全边界和审计，不属于绕过治理；不得在工具之外执行 Python 或规避 Undo/Cook 保护。
- 不确定节点类型、参数名、端口或菜单值时，先用 `get_node_card`、`get_parameter_schema`、`search_houdini_help` 等只读工具查证。
- SOP 建模、散布、属性处理、拓扑、UV、体积处理默认优先使用 SOP 节点链，而不是用 wrangle 或 Python 直接造几何。

## 工作纪律

- 先规划整图，再执行建网；重要节点链应先确认上下文、输入、输出和验证点。
- 先 blockout、low-res、low-substep 验证，再 upres 或提高采样。
- 昂贵阶段应以 cache、checkpoint 或明确的中间输出结束。
- 可调参数优先放在 CTRL null spare parameters，避免 magic numbers 深埋在多个节点内部。
- 完成声明必须基于错误节点、display flag、geometry summary、stage、viewport 或 cook 状态等验证结果，不能只看工具返回 success。

## 上下文约定

- LOP/Solaris：材质属于 `materiallibrary` LOP，材质绑定通过 `assignmaterial`；lookdev 优先 viewport / Hydra preview。
- Simulation：优先现代 SOP-level solver 或既有 simulation blueprint skill；手工 DOP wiring 只作 fallback。
- TOP/PDG：pipeline 优先使用 File Pattern、Wedge、ROP Fetch、Wait for All、Partition 等原生 TOP 节点。
- Debug：先定位 scene、node、parm、geometry、USD、simulation 或 performance 问题，再修改；连续尝试失败时停止盲改，回到证据收集。