# LOPs / PDG 只读检查工具 — 实现计划

> 来源：借鉴 [healkeiser/fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp) 的能力域覆盖（LOPs/USD 18 工具、PDG/TOPs 10 工具）。
> 目标：补齐"让 AI **看懂** USD 舞台与 PDG 网络"这一真实只读缺口，不改嵌入式架构。
> 状态：**方案阶段，尚未改动任何代码。**
> 关联：
> - 与 [fxhoudinimcp_borrow_mvp_plan.md](fxhoudinimcp_borrow_mvp_plan.md) **互补不冲突**——那份把 LOPs/PDG *写侧* 判为"低频 YAGNI"，本计划只做 *只读检查侧*（AI 决策依赖，价值远高于写侧）。
> - 遵循 [skill_migration_plan.md](skill_migration_plan.md) 边界：**低频/组合式只读 → skill**（扔 `.py` 到 `houdini_agent/skills/` 即自动加载，不占 function-calling 名额）。

---

## 0. 前置事实核对（已确认，非猜测）

- Skill 约定：文件含 `SKILL_INFO` dict（`name`/`category`/`description`/`parameters`）+ `run(**kwargs) -> dict`，返回 dict；只读优先；错误用 `{"error": ...}` 结构化返回。**新增 skill 必须标 `category`**（本批用 `usd` / `pdg`，`list_skills` 据此分组）。参考 [inspect_lop_stage.py](../../houdini_agent/skills/inspect_lop_stage.py)。
- 现状：
  - LOPs 只读已有 `inspect_lop_stage`（stage 层/prim 计数/相机/灯光概览）、`inspect_material_assignments`。
  - PDG 仅有 `analyze_cook_performance`（性能侧），**无 work item / 网络 / 错误检查**。
- 线程安全：`run_skill` **不在** `BG_SAFE_TOOLS` 白名单 → 所有 skill 经 `run_skill` 调用时自动走主线程（`_on_execute_tool_main_thread`），在主线程 `import hou`。**新增只读 skill 天然继承此保护，无需任何线程代码。**（见 fxhoudinimcp plan「主线程安全机制核对」节。）
- 依赖防御：复用 `inspect_lop_stage` 已验证的 `_safe_call` 模式；`pxr` / `pdg` 模块用 `try import` 包裹，缺失时返回 `{"error": "..."}`，与 mock 测试兼容。

---

## 1. 范围界定

**做**：只读检查类 skill，让 AI 在 Ask/Plan 模式下看懂 USD 舞台与 PDG 网络状态。
**不做**（本计划范围外，留给未来或现有 MVP plan）：
- ❌ USD/PDG **写操作**（`set_usd_variant` / `cook_top_network` 等）——需 policy gate + 主线程 defer 写，风险高，单独立项。
- ❌ 一键 workflow 搭建——已在 fxhoudinimcp MVP plan 覆盖。

---

## 2. 第一批：核心只读检查（6 个，最高 ROI，全部可 mock 测试）

| # | skill name | 用途 | 关键 API | 复杂度 |
|---|---|---|---|---|
| L1 | `inspect_usd_prim` | 单 prim 详情：type、属性值、metadata、xform、visibility、purpose | `stage.GetPrimAtPath`, `prim.GetAttributes()` | 低 |
| L2 | `list_usd_layers` | layer stack（root/session/sublayers）+ authored/muted 状态 + 大小 | `stage.GetLayerStack()`, `layer.subLayerPaths` | 低 |
| L3 | `inspect_usd_composition` | 单 prim 的 composition arcs（reference/payload/inherit/variant）+ PrimStack | `prim.GetPrimStack()`, `Usd.PrimCompositionQuery` | 中 |
| P1 | `inspect_top_network` | TOP 网络概览：节点数、scheduler、work item 总/成功/失败计数、dirty 状态 | `node.getPDGGraphContext()`, `node.getPDGNode()` | 中 |
| P2 | `list_work_items` | 某 TOP 节点 work item 列表：index、state、attributes、输出文件 | `pdg_node.workItems`, `item.state` | 中 |
| P4 | `get_top_errors` | 汇总失败 work item 的错误、命令、日志路径 | `item.state == pdg.workItemState.CookFailed` | 中 |

> 6 个覆盖约 80% 的"AI 看懂 USD/PDG 场景"需求，全部只读、可在无 `hou` 环境 mock 测试。

---

## 3. 第二批：分析增强（按需，非阻塞）

| # | skill name | 用途 | 复杂度 |
|---|---|---|---|
| L4 | `list_usd_variants` | prim 上的 variantSet + 各 selection | 低 |
| L5 | `inspect_usd_lighting` | 场景灯光清单：类型、强度、曝光、color、shadow link（`UsdLux`） | 中 |
| L6 | `diff_usd_layers` | 对比两个 LOP 节点的 prim 差异（新增/删除/改属性） | 高 |
| P3 | `analyze_top_dependencies` | work item 依赖图 / 上下游、瓶颈节点 | 高 |
| P7 | `inspect_top_scheduler` | scheduler 类型与配置（local/HQueue/Deadline）、并发、临时目录 | 低 |

---

## 4. 每个 skill 的实现骨架（统一约定）

```python
# -*- coding: utf-8 -*-
"""<one-line purpose>. Read-only."""

SKILL_INFO = {
    "name": "<skill_name>",
    "description": "<what it inspects>. Read-only.",
    "parameters": {
        "node_path": {"type": "string", "description": "...", "required": True},
        # + max_* 截断参数，默认值与 inspect_lop_stage 一致
    },
}

def _safe_call(func, default=None):
    try:
        return func()
    except Exception:
        return default

def run(node_path, **kwargs):
    import hou  # type: ignore
    node = hou.node(node_path)
    if not node:
        return {"error": f"Node does not exist: {node_path}"}
    # USD skill: 校验 hasattr(node, "stage") + try import pxr
    # PDG skill: 校验 node.getPDGGraphContext 存在 + try import pdg
    ...
    return {"...": ...}  # 结构化 dict，含 truncated 标志
```

**强约束**：
1. 全部只读，绝不 `stage.OverridePrim()` / 建节点 / cook 写。
2. `pxr`（USD）、`pdg`（PDG）用 `try import` 包裹，缺失返回 `{"error": "pxr USD not available"}` / `{"error": "pdg not available"}`。
3. 遍历带 `max_*` 截断 + `truncated: bool`，防大场景卡死（照抄 `inspect_lop_stage` 的 `max_prims`）。
4. PDG work item state 用 `pdg.workItemState` 枚举名映射为可读字符串，不返回裸整数。

---

## 5. 测试策略（借鉴 fxhoudinimcp 的 hython 集成思路）

| 层级 | 方式 | 覆盖 |
|---|---|---|
| 单元（无 hou） | mock `hou` / `pxr` / `pdg`，验证参数校验、`{"error":...}` 分支、返回结构 | 所有 skill |
| 加载 | `list_skills()` 断言新 skill 已注册；空/错误 `node_path` 走 error 分支 | 所有 skill |
| 集成（可选） | `hou` 可用时对真实 `/stage` 与 TOP 网络跑一遍，`hou` 不可用自动 skip | 有条件 |

> 参照仓库现有测试命令模式（见会话历史 `run_skill('explain_node_error', ...)` 的 NO_HOU 断言写法），每个新 skill 至少覆盖：EMPTY node_path、NO_HOU（缺 hou 时结构化 error）、正常返回结构。

---

## 6. 落地顺序

1. **L1 `inspect_usd_prim`** — 作为 USD 只读模板，跑通 `list_skills` 注册 + mock 测试。
2. **P1 `inspect_top_network`** — 作为 PDG 只读模板（含 `try import pdg` 与 state 枚举映射）。
3. 补齐第一批其余 4 个（L2/L3/P2/P4），复用前两个的模板。
4. 第二批按团队实际 USD/PDG pipeline 使用情况按需实现。

---

## 7. 验收标准

- [ ] 第一批 6 个 skill 文件落在 `houdini_agent/skills/`，`list_skills()` 全部可见。
- [ ] 每个 skill 在无 `hou`/`pxr`/`pdg` 环境返回结构化 `{"error": ...}`，不抛异常。
- [ ] 大场景遍历带截断 + `truncated` 标志。
- [ ] 单元测试全绿；`hou` 可用时集成测试通过或正确 skip。
- [ ] 不引入任何写操作、不新增线程代码、不改 core 工具列表。
