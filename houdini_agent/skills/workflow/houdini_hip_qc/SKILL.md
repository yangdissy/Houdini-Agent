---
{"name":"houdini_hip_qc","category":"workflow","description":"对当前已打开的 Houdini HIP 工程执行可分范围的只读流程规范 QC。启动时先确认检查全部，还是仅检查基础设置、节点命名、缓存/VDB 路径、HIP 文件命名、外部引用、OF/SFX 工作流规则中的一部分；按所选范围分步执行，减少大型场景扫描耗时。适用于“检查工程规不规范”“QC 这个 Houdini 文件”“过一遍流程规范”。","risk_level":"low","parameters":{"checks":{"type":"array","items":{"type":"string","enum":["scene_settings","node_naming","cache_paths","file_naming","external_references","workflow_rules","all"]},"description":"要执行的检查范围，可多选。all 表示全部；未提供时不得直接运行，应先询问用户。","required":false,"default":null},"project_fps":{"type":"number","description":"项目要求的帧率；不提供时只报告当前帧率并标为存疑。","required":false,"default":null},"max_nodes":{"type":"integer","description":"节点相关检查最多扫描的节点数，默认 10000。","required":false,"default":10000}},"entrypoint":"scripts/main.py:run"}
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
- `all`：以上全部，并列出无法从场景自动证明的人工流程项

用户选择后再调用一次 Skill。不得把缺省 `checks` 当作 `all`；入口会返回 `selection_required`，不会开始扫描。

## 分步执行

每次只执行用户选择的范围。多个范围按上述顺序处理，并在结果中分别报告；节点扫描只在 `node_naming`、`cache_paths` 或 `workflow_rules` 被选中时发生，外部引用枚举只在 `external_references` 被选中时发生。

保持只读：不加载、烹饪、保存或修改 HIP。只有 `all` 才附带 ChooseTask、Daily、SubmitTool、Publish 等人工确认项，避免局部检查被无关存疑结果淹没。

`scene_settings` 会在未提供项目 FPS 时先检查当前值是否为清单允许的 24fps；合法时仍因缺少项目标准而标为存疑，其他值直接失败。艺术表现、最终 velocity、渲染器、色彩空间、合成和交付质量需要观察最终结果或读取已烹饪几何，因此仅在 `all` 中列为人工确认，不做猜测性自动判定。
