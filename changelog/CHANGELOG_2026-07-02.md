# Houdini-Agent 更新记录（2026-07-02）

## 发布摘要

针对组员反馈的两次 Houdini 崩溃做了排查与加固。经调用栈分析，两次崩溃性质不同：

1. **崩溃 1**（Flipbook 体积渲染 OOM）—— Houdini 自身 GPU/内存问题，与 Agent 无关，文档化规避建议。
2. **崩溃 2**（Agent 运行期用户操作节点导致主线程 Qt/hou 竞态）—— 与 Agent 相关，本次做防御性加固（Option A）。

改动仅涉及两个文件：`houdini_agent/ui/cursor_widgets.py`、`houdini_agent/ui/ai_tab.py`。无 API / 磁盘格式变化。

---

# 崩溃排查

## 崩溃 1 — Flipbook 体积渲染 OOM（与 Agent 无关）

**来源**：`crash.tmk_r50_210_sfx_arrow.v008.fanjinjun_70136_log.txt`（H20.0.688，signal 11）

**关键调用栈**：

```
UT_NoMemHandler::classNewHandler        ← 内存分配失败
GR_VolumeVK::viewUpdate                 ← Vulkan 体积渲染
GR_VolumeCache::updateTextures
OP3D_Flipbook::captureImage
OP3D_Flipbook::writePictures
DM_PicWrite::makeFlipbook
```

**结论**：做 Flipbook（拍屏预览）时 GPU 渲染 VDB/体积遇到内存不足触发的崩溃，属 Houdini 自身 GPU/内存问题。

**规避建议**（非代码）：降低 Flipbook / 体积分辨率，关闭视口体积高质量显示，或增加显存 / 内存。

## 崩溃 2 — Agent 运行期用户操作节点竞态（与 Agent 相关）

**来源**：`crash.tmk_r50_210_sfx_arrow.v009.fanjinjun_80760_log.txt`（H20.0.688，signal 11）

**关键调用栈**：

```
QWidget::~QWidget                        ← Qt 控件树递归析构
QScrollBar::~QScrollBar
QAbstractScrollAreaPrivate::~...
PySide2/QtWidgets.pyd
python39.dll (PyEval_EvalFrameDefault)
SHLF_Tool::execute                       ← 从 Shelf 工具执行 Python
OPUI_ToolHandler::handleToolEvent
```

**组员回忆的操作场景**：Agent 还在后台运行（以为已跑完），去视口 / 网络里点选了节点。

**根因**：主线程竞态 + Qt/hou 重入。三者叠加触发：

1. 工具执行走 `BlockingQueuedConnection`（`ai_tab.py`），Agent 跑节点操作时主线程被长时间占用，组员因此误判"已结束"。
2. 读取工具前的 `_cook_displayed_nodes_if_manual` 对 `/obj` 下各 geo 的 display 节点 `cook(force=True)`，会驱动视口 GPU 重绘（即崩溃 1 里的 `GR_VolumeVK` 路径）。
3. 用户此时点选节点，触发 Houdini 自身选择 / 渲染 / UI 事件，与正在进行的 `hou` cook 在主线程交错重入，最终在 Qt widget（QScrollBar / QScrollArea）析构时段错误。

代码中早有注释记录曾因 `processEvents()` 导致同类 `EXC_BAD_ACCESS`，佐证该路径对主线程事件重入高度敏感。

---

# 修复（Option A — 防御性加固）

## 1. 忙态提示可见化

**文件**：`houdini_agent/ui/cursor_widgets.py` — `UnifiedStatusBar._paint_tool`

工具执行状态栏文案由 `Exec: <tool>` 改为带明确警示：

```
⚡ <tool> · 执行中，请勿操作 Houdini 视口/节点
```

组员在 Agent 每次执行工具时都能看到提示，减少"以为跑完了去操作节点"的误判，从源头降低竞态触发概率。

> **测试修正**：初版只改了 `tool` 模式（`_paint_tool`），但 Agent 运行期绝大部分时间处于 `thinking` / `generating` 模式，`tool` 模式只在单个工具执行的瞬间出现且随即切回 `generating`，导致提示一闪而过、组员实测看不到。修正为在 `_paint_thinking` 与 `_paint_generating` 文案也附加 `· 请勿操作 Houdini`，使警示覆盖 Agent 整个运行期（含推理、等待响应、工具间隙）。

## 2. 跳过体积 / VDB display 节点的强制 cook

**文件**：`houdini_agent/ui/ai_tab.py` — `_cook_displayed_nodes_if_manual`

在 `display_node.cook(force=True)` 前检测该节点几何是否含 Volume / VDB primitive，含则跳过，避免驱动 GPU 体积重绘（`GR_VolumeVK`）与用户视口交互竞态。

新增静态辅助方法 `_display_node_has_volume`：

- `needsToCook()` 为 True 时直接跳过（未 cook 的体积节点最危险）。
- 否则用 `geometry().countPrimType(Volume/VDB)` 判断。
- 任何异常保守返回 False，回退到原行为，不影响普通 SOP 刷新。

---

# 影响面

- 仅两个 UI 文件改动，无外部 API / 磁盘格式变化。
- 普通 SOP 的读取工具仍正常刷新（非 stale 数据），只有含 Volume / VDB 的 display 节点被跳过强制 cook。
- `get_errors` 校验两文件无错误。

# 验证建议（需组员实机）

1. 含 VDB / 体积的场景，Agent 跑操作时点选节点 → 确认不再崩溃。
2. 普通 SOP 读取工具仍返回最新数据。
3. Agent 执行期间状态栏显示忙态警示文案。

# 后续待办

- **Option B**（Agent 运行中检测用户选节点则主动提示暂停）—— 改动较大，需测事件回调在 Manual / 忙态下的行为，避免回调本身引入新竞态，暂缓。
