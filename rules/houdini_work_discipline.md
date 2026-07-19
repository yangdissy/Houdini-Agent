# Houdini 工作纪律

本规则适用于创建、修改或调试 Houdini 内容时的决策顺序。它只约束工作方式，不扩大工具权限。

## Node-first rule

- 写 VEX、Python SOP 或调用 `execute_python` 前，先判断是否能用原生节点、现有 workflow skill 或批量节点操作完成。
- 不确定节点类型、参数名、端口或菜单值时，先用 `get_node_card`、`get_parameter_schema`、`search_houdini_help` 等只读工具查证。
- SOP 建模、散布、属性处理、拓扑、UV、体积处理默认优先使用 SOP 节点链，而不是用 wrangle 或 Python 直接造几何。

## Tool priority

工具选择优先级：

1. workflow / blueprint / guide skill
2. batch/native node operations
3. VEX wrangle
4. Python execution

`execute_python` 只作为最后手段，不能用来绕过现有 harness、安全边界、undo/cook 保护路径创建、连接或删除节点。

## Senior Houdini discipline

- 先规划整图，再执行建网；重要节点链应先确认上下文、输入、输出和验证点。
- 先 blockout、low-res、low-substep 验证，再 upres 或提高采样。
- 昂贵阶段应以 cache、checkpoint 或明确的中间输出结束。
- 可调参数优先放在 CTRL null spare parameters，避免 magic numbers 深埋在多个节点内部。
- 完成声明必须基于验证结果，例如错误节点、display flag、geometry summary、stage、viewport preview 或 cook 状态，而不是只看工具返回 success。

## Context reminders

- SOP：程序化建模、散布、属性、拓扑、UV、体积尽量用 SOP 节点完成。
- LOP/Solaris：材质属于 `materiallibrary` LOP，材质绑定通过 `assignmaterial`；lookdev 优先 viewport / Hydra preview。
- Simulation：常见模拟优先使用现代 SOP-level solver 或既有 simulation blueprint skill；手工 DOP wiring 只作 fallback。
- TOP/PDG：pipeline 优先使用 File Pattern、Wedge、ROP Fetch、Wait for All、Partition 等原生 TOP 节点。
- Debug：先定位 scene、node、parm、geometry、USD、simulation 或 performance 问题，再修改；连续尝试失败时停止盲改，回到证据收集。