# houdini_progressive_template_builder

Version: 1.0 (Simplified)
Scope: Houdini SOP/DOP/VOP 节点网络生成
Constraint: 强制执行，不可绕过

## 1. 核心原则（必须遵守）
- 禁止“跨阶段顶层设计后一次性实现”。
- 必须采用分层渐进式构建（Layered Progressive Construction）。
- 每一层必须先独立 Cook 通过，再进入下一层。
- 渐进式构建指“按阶段/批次验证”，不是把一个小型连通网络拆成多个 `create_node` + `connect_nodes`。
- 同一阶段内若需要创建 2 个及以上相互关联节点，优先用 `create_nodes_batch` 一次声明 `nodes` 和 `connections`，让系统原子创建、连接并整理本批布局。

## 2. 五阶段锁定协议（5-Stage Lock Protocol）

| 阶段 | 名称 | 允许节点类型 | 禁止节点类型 | 退出验证条件 |
|---|---|---|---|---|
| S1 | GEO 几何结构 | File, Null, Group, Merge, Blast, Rename | Solver, DOP, Vellum, FEM, Wire | 1) 组命名符合 `[SYS]_[NAME]_[TYPE]`；2) Cook < 0.1s；3) 无红错节点 |
| S2 | ATTR 属性准备 | Attribute Create, Attribute Wrangle, Measure, Clean | Deform, Solver | 1) 目标属性存在；2) 类型前缀正确（f@/v@/i@/s@/u@）；3) 属性范围合理 |
| S3 | CONN 拓扑连接 | 连接 S1-S2 已存在节点；或在同一个 `create_nodes_batch` 批次内声明本批节点之间的连接 | 任何跨阶段新增功能节点 | 1) Output/Input 数据类型一致；2) 无悬空输入；3) 无循环依赖 |
| S4 | SIM 模拟解算 | DOP Network, Solver, Vellum Solver, FEM Solid, Wire Solver, RBD | 修改 S1-S3 已冻结结构 | 1) DOP Cook 全绿；2) 帧1无报错；3) 碰撞体/约束路径有效 |
| S5 | TUNE 调优细化 | 参数调整、优化节点、可视化节点 | 新增改变拓扑结构的节点 | 1) 每调 3 个参数 Cook 一次；2) 最终全帧 Cook 通过 |

### 阶段转换规则（Transition Rule）
- 当前阶段验证条件必须全部为 True，才能进入下一阶段。
- 任一条件失败，必须执行 Rollback Protocol，禁止继续生成。

## 3. 节点生成限制（Generation Limits）

### 3.1 批次限制（Batch Limit）
- 单次响应最多生成 5 个相互连接的节点。
- 超出时必须分多轮生成，且每轮之间必须 Cook 验证。
- “最多 5 个”是单个批次的安全上限，不是要求逐个节点创建。
- 当本轮需要生成 2-5 个相互连接节点时，应使用 `create_nodes_batch`，不要拆成多个 `create_node` 后再逐个 `connect_nodes`。
- `connect_nodes` 仅用于连接已经存在的节点、补连漏连、或修改现有网络连接；不应用作新建小网络的默认流程。
- 每个 `create_nodes_batch` 批次必须包含完整 `connections` 契约，并在批次结束后 Cook/verify，再进入下一批或下一阶段。

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
