# houdini_progressive_template_builder

Version: 1.0 (Simplified)
Scope: Houdini SOP/DOP/VOP 节点网络生成
Constraint: 强制执行，不可绕过

## 1. 核心原则（必须遵守）
- **批量优先**：创建节点的默认方式是 `create_nodes_batch`，一次原子声明本批 `nodes` 与 `connections`，由系统统一创建、连接并整理布局。
- **验证单元是「阶段」，不是「单个节点」**：同一阶段内的关联节点应尽量在一个批次里一次建好；每个阶段（而非每个节点）完成后 Cook 验证通过，再进入下一阶段。
- 禁止“跨阶段顶层设计后一次性把 S1–S5 全部塞进一个批次”——批量的边界是**单个阶段**。
- 禁止把一个本可一次声明的小型连通网络拆成多个 `create_node` + `connect_nodes` 逐个手搓。
- 渐进式构建 = **按阶段分批验证**，不是逐节点验证。

## 2. 五阶段锁定协议（5-Stage Lock Protocol）

| 阶段 | 名称 | 允许节点类型 | 禁止节点类型 | 退出验证条件 |
|---|---|---|---|---|
| S1 | GEO 几何结构 | File, Null, Group, Merge, Blast, Rename | Solver, DOP, Vellum, FEM, Wire | 1) 组命名符合 `[SYS]_[NAME]_[TYPE]`；2) Cook < 0.1s；3) 无红错节点 |
| S2 | ATTR 属性准备 | Attribute Create, Attribute Wrangle, Measure, Clean | Deform, Solver | 1) 目标属性存在；2) 类型前缀正确（f@/v@/i@/s@/u@）；3) 属性范围合理 |
| S3 | CONN 拓扑连接 | 两种合法路径：(a) 用 `connect_nodes` 连接 S1-S2 已存在节点；(b) 在 `create_nodes_batch` 批次内一并声明本批（本阶段）节点及其相互连接 | 引入属于其他阶段的功能节点（如 S4 的 Solver/DOP） | 1) Output/Input 数据类型一致；2) 无悬空输入；3) 无循环依赖 |
| S4 | SIM 模拟解算 | DOP Network, Solver, Vellum Solver, FEM Solid, Wire Solver, RBD | 修改 S1-S3 已冻结结构 | 1) DOP Cook 全绿；2) 帧1无报错；3) 碰撞体/约束路径有效 |
| S5 | TUNE 调优细化 | 参数调整、优化节点、可视化节点 | 新增改变拓扑结构的节点 | 1) 每调 3 个参数 Cook 一次；2) 最终全帧 Cook 通过 |

### 阶段转换规则（Transition Rule）
- 当前阶段验证条件必须全部为 True，才能进入下一阶段。
- 任一条件失败，必须执行 Rollback Protocol，禁止继续生成。

## 3. 节点生成限制（Generation Limits）

### 3.1 批次规则（Batch Rule）
- **默认用 `create_nodes_batch` 批量生成**：本阶段需要的多个关联节点，在一个批次里一次声明 `nodes` + `connections`，原子创建。
- 单个批次最多 8 个相互连接的节点（安全上限，防止一次性错误扩散）。需要更多时按逻辑子结构拆成多批，每批之间 Cook 验证。
- “最多 8 个”是批次上限，**不是**要求逐个 `create_node`；能合批就合批。
- `create_node`（单个）仅在阶段内只需 1 个孤立节点时使用。
- `connect_nodes` 仅用于连接已存在节点、补连漏连、或修改现有网络连接；**不作为新建小网络的默认流程**（新建走 `create_nodes_batch`）。
- 每个批次必须包含完整 `connections` 契约，批次结束后 Cook/verify，再进入下一批或下一阶段。

### 3.2 连接契约（Connection Contract）
任何连接必须使用以下结构化格式，禁止模糊自然语言：

```text
CONNECT:
  Source: [节点路径] | Output Port: [端口名/索引] | DataType: [具体类型]
  Target: [节点路径] | Input Port: [端口名/索引] | DataType: [具体类型]
  Contract Check: [Compatible / Incompatible]
  Action: [EXECUTE / ABORT]
```

## 4. Rollback Protocol（回滚协议）
验证失败时必须执行：
1. 立即停止当前阶段后续生成。
2. 回退到“最近一次 Cook 通过”的状态（禁止跨阶段推进）。
3. 输出失败原因与最小修复步骤。
4. 修复后仅重试当前阶段，验证通过后再继续。
