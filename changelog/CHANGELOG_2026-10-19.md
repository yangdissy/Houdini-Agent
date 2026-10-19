# Houdini-Agent 更新记录（2026-10-19）

## 发布摘要

本次更新新增由本地知识资产驱动的 Houdini Workflow Guide 体系，覆盖 31 类常见工作流，并为 Houdini 20.0.688、20.5.684 和 21.0.596 提供版本化节点事实校验。

同时修复了同一 Plan 在创建、步骤更新和会话恢复期间被重复插入聊天流的问题，并调整任务反思评分：复杂建图即使经历错误与重试，只要最终成功纠正并完成，就不再被记录为低质量任务。深度反思 JSON 解析失败现在也会输出可诊断但不泄露内容的结构化原因。

---

## 一、Workflow Guide 知识体系

- 新增 `get_workflow_guide` 可执行 Skill，按主题加载本地工作流指导。
- 新增 31 篇 Workflow Guide，覆盖动画、资产、角色、合成、Copernicus、复制、Crowds、破碎、粒子、动力学、羽毛、有限元、流体、毛发、颗粒、HeightField、I/O、机器学习、建模、MPM、肌肉、海洋、道具、Pyro、渲染、材质、Solaris、TOPs、故障排查和 Vellum 等主题。
- Guide 正文统一归属 `Doc/workflow_guides/`；Skill 只负责路由、渲染、版本信息和审计，不复制知识正文。
- 新增迁移矩阵 `Doc/workflow_guide_migration_matrix.md`，记录主题状态、来源、许可证、能力映射和安全适配。
- 支持主题别名，同时保持精确主题优先；未知主题和路径逃逸请求采用 fail-closed 处理。
- Guide 返回稳定 `guide_id`、revision、证据策略、来源、帮助页、节点要求和工具引用元数据。

---

## 二、证据策略与知识审计

每篇 Guide 显式声明其事实来源策略：

- `local-knowledge`：使用仓库内知识资产。
- `packaged-help`：使用随项目发布的 Houdini 帮助页。
- `runtime-search`：要求运行时查询当前 Houdini 环境。

审计行为包括：

- 校验 Guide 声明的工具是否已注册。
- 校验 packaged-help 页面是否存在。
- 校验 local-knowledge 来源是否位于 `Doc/`，并拒绝绝对路径和 `..` 路径逃逸。
- 校验 Guide 目录与迁移矩阵保持 31 对 31 一致。
- 对读取失败、编码失败、渲染失败和缺少证据采用结构化失败结果，不静默降级为无依据指导。
- 增加 Git 跟踪交付门，防止源码工作区中存在但发布包未包含知识资产。

---

## 三、三版本节点事实资产

新增三份版本化节点目录：

- Houdini 20.0.688
- Houdini 20.5.684
- Houdini 21.0.596

节点声明支持：

- 所有支持版本共有节点，例如 `sop/commonnode`。
- 最低版本约束，例如 `sop/newnode [20.5.684+]`。
- 精确版本约束，例如 `sop/legacy [20.0.688]`。

运行时资产审计会逐版本检查节点声明，只在约束适用的版本中要求节点存在。目录缺失、空目录、非法版本约束和不存在的节点都会使审计失败。

---

## 四、Plan 卡片重复投影修复

- 修复 `_restore_plan_projection()` 每次调用都清空 active viewer 并重新发射渲染信号的问题。
- 使用 `(session_id, plan_id)` 作为 Plan UI 投影幂等键。
- 同一会话、同一 Plan 已存在活动 viewer 时，只恢复阶段状态，不再新增相同卡片。
- 创建新 Plan或切换到其他会话时仍会正常投影对应 Plan。
- Plan 被拒绝时清除投影键和活动 viewer 状态。
- 保留流式 Plan 卡片原地升级为完整 PlanViewer 的现有行为。
- 不改变 Plan 保存、确认、步骤更新和执行上下文注入语义。

---

## 五、任务反思评分修正

- 明确区分规则评分与 LLM 深度反思：reward 在深度反思之前计算，深度反思 JSON 解析失败不会直接降低 reward。
- 修复复杂建图任务最终成功并完成错误纠正后，仍可能落入低 reward 区间的问题。
- 最终成功且带有 `error_correction` 标签的任务，reward 现在至少达到记忆强化阈值 `0.6`。
- 工具调用数量、错误数和重试数仍参与效率排序；只有确认发生错误后成功纠正的任务获得该下限。
- 失败任务和未解决错误不会获得成功纠错下限。

---

## 六、深度反思解析诊断

- 深度反思继续要求模型返回 JSON object。
- JSON 解析失败时返回结构化原因：
  - `invalid_json`
  - `json_object_not_found`
  - `json_root_not_object`
- 日志增加响应字符数、是否以对象括号开始/结束以及 JSON 错误位置，便于区分截断和格式污染。
- 解析诊断不输出反思原文，避免将会话内容写入日志。
- 深度反思失败原因会传播到任务反思结果，并由 Memory 日志明确显示，例如：

```text
[Memory] 深度反思未写入: reason=invalid_json
```

- 深度反思失败不会删除已写入的 episodic 记录，也不会否定 Houdini 节点树的实际执行结果。

---

## 七、安全与职责边界

- Workflow Guide 只提供决策依据、步骤和验证方法，不直接执行场景写操作。
- Guide blueprint 不等于执行；节点创建和参数修改继续经过 Tool Registry、Harness、确认策略、审计和 Houdini 主线程执行器。
- 节点事实来自版本化本地目录或显式运行时查询，不把上游工作流文本当作当前 Houdini 版本的节点事实。
- 深度反思解析日志仅记录结构元数据，不记录模型原始响应或用户内容。
- Plan 投影去重只作用于 UI 展示，不改变 Plan 数据文件或执行状态机。

---

## 八、测试与验证

- Workflow Guide 定向测试：`22 passed`。
- Houdini 帮助源测试：`13 passed`。
- Plan 生命周期与执行提示测试：`20 passed`。
- Session manifest 与缓存恢复测试：`17 passed`。
- 反思、成长追踪和用户反馈测试：`25 passed`。
- 修改文件的 VS Code diagnostics 无错误。
- `git diff --check` 通过；仅保留 Git 对现有 LF/CRLF 工作区策略的提示。
- 测试解释器：`C:\rez\rez_2.112.0\Scripts\python.exe`。

---

## 已知范围

- 深度反思解析失败的历史响应未落盘，因此无法还原 2026-10-19 既有会话中模型返回的原始非法 JSON；新增诊断会从后续任务开始提供错误位置和结构信息。
- 当前解析器不会自动修复截断 JSON 或任意语法错误，避免把不确定内容误写入长期记忆。
- Reward 下限依赖任务被识别为最终成功并带有 `error_correction`；用户仍可通过回复块上的反馈操作修正具体 episodic 记录。
- Workflow Guide 的节点事实审计覆盖显式节点声明，不将正文中的每个自然语言术语自动解释为节点类型。
- 本次更新未修改高风险工具授权、用户确认要求或未知执行状态的 fail-closed 行为。
