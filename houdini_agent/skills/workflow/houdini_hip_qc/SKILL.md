---
{"name":"houdini_hip_qc","category":"workflow","description":"对当前已打开的 Houdini HIP 工程执行只读 QC。既可检查基础设置、命名、路径和 OF/SFX 规则，也可先识别全部节点，再强制分组并逐组分析节点用途、组合目的与采用原因，最后分层汇总整个工程。适用于“检查工程规不规范”“QC 这个 Houdini 文件”“分析这个节点网络”。","risk_level":"low","parameters":{"checks":{"type":"array","items":{"type":"string","enum":["scene_settings","node_naming","cache_paths","file_naming","external_references","workflow_rules","network_analysis","all"]},"description":"要执行的检查范围，可多选。network_analysis 执行节点识别和分组分析；all 表示全部；未提供时不得直接运行，应先询问用户。","required":false,"default":null},"project_fps":{"type":"number","description":"项目要求的帧率；不提供时只报告当前帧率并标为存疑。","required":false,"default":null},"max_nodes":{"type":"integer","description":"节点相关检查最多扫描的节点数，默认 10000。","required":false,"default":10000}},"entrypoint":"scripts/main.py:run"}
---
# Houdini Hip Qc

## 启动门

调用前先确认检查范围。若用户没有明确范围，只询问一次并给出以下可多选项：

- `scene_settings`：Houdini 版本、FPS 和帧范围
- `node_naming`：集成节点默认命名
- `cache_paths`：File Cache 与 VDB 发布路径
- `file_naming`：HIP 文件命名
- `external_references`：外部引用是否缺失
- `workflow_rules`：OF/SFX 路径变量、节点版本命名、File Cache 类型和 ABC 直连缓存规则
- `network_analysis`：识别全部节点，形成小组，再逐组分析用途、组合目的和采用原因，最后分层汇总
- `all`：以上全部，并列出无法从场景自动证明的人工流程项

用户选择后再调用一次 Skill。不得把缺省 `checks` 当作 `all`；入口会返回 `selection_required`，不会开始扫描。

## 分步执行

每次只执行用户选择的范围。多个范围按上述顺序处理，并在结果中分别报告；节点扫描只在 `node_naming`、`cache_paths`、`workflow_rules` 或 `network_analysis` 被选中时发生，外部引用枚举只在 `external_references` 被选中时发生。

保持只读：不加载、烹饪、保存或修改 HIP。只有 `all` 才附带 ChooseTask、Daily、SubmitTool、Publish 等人工确认项，避免局部检查被无关存疑结果淹没。

`scene_settings` 会在未提供项目 FPS 时先检查当前值是否为清单允许的 24/25fps；合法时仍因缺少项目标准而标为存疑，其他值直接失败。艺术表现、最终 velocity、渲染器、色彩空间、合成和交付质量需要观察最终结果或读取已烹饪几何，因此仅在 `all` 中列为人工确认，不做猜测性自动判定。

## 节点网络分析协议

选择 `network_analysis` 或 `all` 时，必须按以下顺序完成，不能跳过分组后直接做全局概述：

本协议是**纯只读报告**。不得调用节点注释、NetworkBox、颜色、布局、重命名或其他写入工具；不得给每个节点写用途注释，也不得为了呈现 QC 结果在工程中创建或调整分组框。所有说明只输出在 QC 报告中。只有用户在 QC 结束后另行明确要求整理网络时，才进入独立的修改任务。

1. **节点识别与递归覆盖**：覆盖返回的每一个节点，并按 `depth` 和 `parent_path` 逐层检查。遇到 `is_network_container=true` 的 GEO、Subnet、DOP Network、Solver、For-Each、LOP、COP、VOP 等容器，必须继续分析其直接子网络，直到 `network_containers` 全部有对应分析；不能只描述容器节点本身。对每个节点记录路径、类型、节点在当前连接和关键参数下的实际角色。节点类型的一般用途不等于它在本场景中的实际角色；不熟悉的类型先用 `get_node_card` 或 Houdini 文档查询，不得仅凭名称猜测。
2. **强制分组**：以入口返回的 `group_tasks` 为准，每个任务最多 8 个节点，独立分析。现有 NetworkBox 只是节点上的弱证据，**不定义报告组**；忽略其误导性的大边界。根据组内数据依赖、输入输出和职责复核任务边界，必要时进一步细分，但不得合并成全局大组。跨组连接保留为依赖，孤立节点也必须有独立任务。报告分组只用于分析，不写回 HIP。
3. **组级重新评估**：每次只处理一个 `group_task`，重新读取其 `nodes` 和 `internal_edges`，说明这组节点组合后完成什么事情、输入是什么、输出给谁、哪个节点是主要结果或继续编辑入口。结论必须来自组内拓扑、`key_parameters`、注释和文档证据，而不是节点用途的简单拼接。
4. **组合原因**：解释为什么这些节点要这样组合，分别指出必要的数据转换、属性准备、分支/汇合、缓存或交付边界。区分“有证据的设计原因”和“可能原因”；无法从只读场景证明的内容标为 `uncertain`，不得补写作者意图。
5. **分层汇总**：按 `container_tasks` 为每个 GEO 或其他网络容器写专属用途摘要，回答“这个容器具体在当前工程中完成什么”，摘要必须引用其 `internal_group_ids`、输入和输出；空容器明确写“当前为空”，不得套用模板。然后再按组间依赖顺序综合工程目标、主数据流、关键输出、风险与存疑项。不得用最终汇总代替逐组报告。

每组报告固定包含 `group_id`、`node_paths`、`node_roles`、`group_purpose`、`inputs`、`outputs`、`composition_reasons`、`evidence`、`confidence` 和 `uncertainties`，与入口的 `required_output` 一致。完成前四步和分层汇总后才结束网络分析。

入口 `network_analysis` 直接携带本协议、逐组任务和覆盖审计，因为可执行 Skill 的 Markdown 正文不会随 `run_skill` 自动返回。完成前必须满足 `coverage_audit`：所有扫描节点恰好出现一次且都有角色，每个任务都有组级用途与组合原因，所有 `container_paths` 都有专属摘要和内部组分析，尤其不能漏掉 Subnet 和 DOP 内部节点。若 `scan_truncated=true`，不得声称已经识别所有节点或给出完整工程汇总，应提高 `max_nodes` 后重跑。

## 故障排查 Handoff

本 Skill 只负责确定性检查，不在内部调用其他 Skill，也不根据自然语言建议自动修改场景。

当结果包含 `fail` 或需要继续调查的 `uncertain` 时：

1. 保留对应 finding 的 `module`、`item`、`problem`、`evidence` 和原始 `checks` 范围。
2. 调用 `get_workflow_guide`，传入 `topic="troubleshooting"`，并在 `description` 中描述失败项及证据。
3. 按 Guide 建议使用 `debug_scene_workflow` 做局部检查；所有场景修改仍通过现有受治理工具执行。
4. 修复后只重新运行原失败项对应的 `checks`，不要无条件重跑 `all`。

若同一症状连续两次修复仍未通过，停止继续猜测性修改，补充 Houdini 官方帮助或运行时证据后再形成新假设。QC 的工具调用成功不等于场景、视觉结果或模拟结果已通过；最终结论仍以原检查项复验结果为准。
