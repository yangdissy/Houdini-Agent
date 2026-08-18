# ADR-0001: Harness 路径参数分类与 save_hip 参数名

- 状态: 已接受 (Accepted)
- 日期: 2026-07-31
- 决策域: `houdini_agent/core/harness_engine.py` 的 `ToolArgumentValidator` / `HarnessToolPolicyEngine`

## 背景 (Context)

`ToolArgumentValidator` 此前用单一白名单 `_NORMALIZE_KEYS` 枚举了 10 个路径参数名，`_check_path_args` 遍历这个固定集合去 `args.get(key)` 做校验。这带来两个问题：

1. **静默漏校验**：`_REQUIRED_ARG_KEYS` 与工具实现里出现了不在白名单中的路径参数（如 `hou_core.connect_nodes` 的 `input_path`），它们不会被 traversal / null-byte / Houdini-root 校验。新增工具时若用了未枚举的路径参数名，同样静默跳过。
2. **语义混杂**：`output_path` 实际是**文件系统路径**（渲染输出图片、HIP 保存路径），而非 Houdini 节点路径，却被混在同一个集合里，靠 `_validate_path_arg` 中 `if key == "output_path": return ""` 的特例豁免 root 校验。

同时发现一个独立 bug：harness 对 `save_hip` 的 `.hip` 扩展名自动补全逻辑读的是 `output_path`，但工具 schema（`utils/ai_client.py`）与 MCP client 实现（`utils/mcp/client.py`）读的参数名都是 `file_path`。参数名不一致导致该补全逻辑**从未真正生效**。

## 决策 (Decision)

1. **将路径参数显式分为两类**：
   - `_NODE_PATH_KEYS`：Houdini 节点路径（`node_path`、`from_path`、`input_path` 等）。校验 traversal、null-byte，并强制落在 `_HOUDINI_ROOTS` 之内。
   - `_FILE_PATH_KEYS = {file_path, output_path}`：文件系统路径。校验 traversal、null-byte，但**豁免 Houdini root 校验**（它们是 OS 路径而非节点路径）。

2. **遍历方式从「固定白名单」改为「按实际参数」**：`_check_path_args` 遍历 `args` 中真实出现的键，由 `_validate_path_arg` 判断该键属于哪个分类（或不属于任何分类则跳过）。新增工具只要参数名落在分类集合内即自动纳入校验，消除白名单漂移。

3. **`save_hip` 参数名以 `file_path` 为准**：harness 的 `.hip` 补全逻辑从 `output_path` 改为 `file_path`，与工具 schema 及 MCP client 实现对齐。

## 理由 (Rationale)

- **Locality**：路径校验语义收敛为「节点路径 vs 文件系统路径」两个明确分类，集中在一处，不再有特例散落在 `_validate_path_arg` 内部。
- **Leverage**：按实际参数遍历让分类集合成为唯一的扩展点——新增路径参数时只需加入对应集合，无需修改遍历逻辑。
- **消除静默分叉**：白名单遍历与按实际参数遍历在参数名漂移时行为不同；后者杜绝了「加了工具忘了加白名单」导致的漏校验。

## 后果 (Consequences)

- `save_hip` 的 `.hip` 自动补全现在真正生效；LLM 传 `file_path`（无扩展名）时会被重写为 `<name>.hip` 并经 retry 重新决策。
- `setup_render` 的 `output_path` 现在会被 traversal / null-byte 校验（此前完全豁免）。若 LLM 传含 `..` 的渲染路径将被 deny——这是预期收紧。
- `input_path` 等新纳入的节点路径参数现在做 Houdini-root 校验，传 `/etc/...` 等会被 deny——同样是预期收紧。
- 新增文件系统路径参数时，需加入 `_FILE_PATH_KEYS` 以获得 root 豁免；否则若落在节点路径集合会被强制 root 校验。

## 备选方案 (Alternatives considered)

- **保留固定白名单**：被否，因为无法消除参数名漂移导致的静默漏校验。
- **`output_path` 完全豁免（维持现状）**：被否，traversal/null-byte 对文件系统路径同样是有效威胁。
