# Houdini-Agent 更新记录（2026-09-07）

## 发布摘要

本次更新加入受治理的视觉审查能力，并为后续 before/after 视觉对比建立安全的截图基础设施。同时修复测试与运行时 token 统计可能因 tiktoken 首次下载编码资源而长时间阻塞的问题，使默认行为保持离线且可确定结束。

本次不新增运行时依赖，不修改现有会话数据格式，也不会自动改变 Houdini 场景、相机或视口状态。

---

## 一、受治理的视觉审查

### 新增能力

- 新增 `visual_review` 工具，支持 `general`、`geometry`、`composition`、`material`、`lighting` 和 `usd` 六类视觉审查。
- 工具复用当前 Houdini Scene Viewer 截图，将图像作为当前工具结果回注给视觉模型。
- 审查结果明确区分技术验证与图像观察，不再用单张截图宣称几何已 cook、网络无错误或材质绑定正确。
- 支持传入目标节点和视觉目标，用于限定观察范围与审查意图。
- Ask、Plan、readonly、历史查询和思考提示等 Registry metadata 已同步注册。

### 能力降级

- 非视觉模型不会收到 `visual_review` 工具 schema，避免模型调用无法完成的图像能力。
- 找不到 Scene Viewer、flipbook 失败、图片未生成或图片为空时返回明确失败，不生成虚假的视觉结论。
- `visual_review` 只观察当前视口，不自动调整相机、灯光、构图或显示设置。

### 文档与提示词

- 更新中英文 README、领域词汇、系统提示规则和工具选择指南。
- 明确推荐流程为：先执行网络、参数、cook 和几何验证，再使用视觉审查判断造型、材质、灯光与构图。

---

## 二、Viewport Capture 基础设施

### 临时文件安全

- 每次 viewport capture 使用独立临时目录，不再依赖共享临时目录中的毫秒文件名。
- flipbook 追加帧号时，只在本次独立目录内查找候选图片，不会误选历史截图。
- 成功、flipbook 异常、空文件和读取失败路径均由临时目录生命周期统一清理。
- 清理仅作用于本次 capture，不删除其他截图或用户文件。

### Capture Primitive 与 Fingerprint

- 从公开 `capture_viewport` 工具中抽取内部 capture primitive，一次返回原始图片 bytes、media type 和结构化 fingerprint。
- 现有 `_viewport_image` base64 协议保持兼容，调用方无需迁移。
- 当前帧改为保留浮点值，支持 `12.5` 等 subframe，不再强制截断为整数。
- fingerprint 记录 frame、viewport、camera mode/path、实际 resolution、target path 及字段可用状态。

### 保守可比性规则

- 只有关键 fingerprint 字段完整、使用 camera view 且 before/after 全部匹配时，才标记为 `comparable`。
- 自由透视缺少稳定 view transform，默认标记为 `incomparable`。
- 帧、viewport、camera、resolution 或 target 变化，以及任何关键字段未知时，均不会误判为严格可比。

---

## 三、Capture Store 与路径隔离

- 新增纯 Python `CaptureStore`，独立于 conversation workspace 持久化协议。
- capture 路径位于 `cache/users/<用户名>/workspace/captures/<session-id>`。
- session id 仅允许 ASCII 字母、数字、下划线和连字符，拒绝空值、绝对路径、`..`、斜杠和反斜杠。
- store 自行生成 capture id、pair id 和相对文件名，调用方不能指定任意输出路径。
- baseline 发布顺序为：同目录写临时图片并 flush/fsync，`os.replace` 发布图片，最后通过 `atomic_write_json()` 发布 manifest。
- manifest 发布失败时只清理本次新图片，不修改其他 capture 或旧 manifest。
- manifest 不包含图片 bytes、base64 或完整 visual goal。

当前提交完成的是 capture store 基础和 `baseline_only` manifest；可信 user/session 上下文接线、after capture、完整 pair 生命周期及模型有序双图回注仍属于后续工作，本次不宣称已上线。

---

## 四、Token 统计默认离线

### 问题

- tiktoken 0.7.0 在本地缺少 `cl100k_base` 编码缓存时会通过 `requests.get` 下载资源。
- token 估算、上下文压缩和完整测试可能因此等待网络超时；按模型键缓存失败仍会让不同模型重复触发下载。

### 修复

- token 统计默认使用项目已有启发式估算，不初始化 tiktoken，也不产生隐式网络访问。
- 只有显式设置 `HOUDINI_AGENT_USE_TIKTOKEN=1` 时才启用 tiktoken 精确计数。
- 显式启用后若编码资源加载失败，会在当前进程禁用 tiktoken，后续模型直接降级，不重复尝试网络加载。
- 空文本、中文、代码和 JSON 等既有启发式计数行为保持不变。

### 效果

- `tests/test_token_optimizer.py` 从无本地编码缓存时约 85 秒降至约 0.38 秒。
- 完整测试不再依赖外网或 tiktoken 临时缓存，可在全新进程中稳定结束。

---

## 五、安全与隐私边界

- 视觉工具继续经过 Registry、Harness、模式限制和审计执行边界。
- 图片 bytes 和 base64 不写入 capture manifest。
- capture store 只接受受控 session 根目录，不接受模型提供的用户名、session 或输出路径。
- 单张截图不能替代几何 freshness、network health、cook 状态或材质绑定验证。
- camera/free-view 可比性采用 fail-closed 规则，缺失信息不会被解释为相等。

---

## 六、测试与验证

### 新增或更新覆盖

- `visual_review` schema、dispatch、Registry metadata、非视觉模型过滤和失败语义。
- flipbook 失败后的临时文件清理，以及外部旧截图保留。
- capture primitive 图片 bytes、media type、subframe 和 fingerprint。
- matching camera、free view、未知字段和 fingerprint 变化的可比性规则。
- per-session capture 路径校验与路径穿越拒绝。
- baseline 图片与 manifest 的原子发布及敏感字段缺失。
- 默认离线 token 计数、显式 tiktoken opt-in 和跨模型加载失败降级。

### 自动化结果

- Visual capture 聚焦回归：`22 passed`。
- Capture foundation 完整回归：`421 passed in 9.56s`。
- Token 默认离线修正完整回归：`416 passed in 11.84s`。
- 修改文件通过 workspace diagnostics，无新增 Python 诊断错误。

### 相关提交

- `36e15bc` — `Add governed visual review tool`
- `0616f87` — `test: make token counting network-independent`
- `edfef09` — `fix: keep token counting offline by default`
- `c7a9709` — `feat: add visual capture foundation`

---

## 已知范围

- Before/after pair 工具尚未完成可信运行时上下文注入，当前不能由模型创建完整持久化对比对。
- After capture、pair completion/incomparable 状态迁移和有序双图回注尚未上线。
- 自由透视暂不保存或恢复 view transform，因此不能进行严格 before/after 比较。
- 本次没有加入 perceptual diff、像素差分、OpenCV/Pillow、多视角、自动 framing 或 quick render。
- Houdini 20.0/20.5 的 camera/free view、subframe 和 flipbook 失败路径仍需在真实宿主中完成最终手工验证。