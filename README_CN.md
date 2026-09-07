# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent 是运行在 SideFX Houdini 进程内的 AI 助手。它直接操作场景图：读节点、建网络、改参数、跑 VEX、查文档，而不是生成一堆代码让你自己粘贴。

## 项目定位

本仓库基于上游 v1.5.x 的 Houdini 内嵌版本，保留自然语言操作场景、节点读写、VEX、文档检索及 Ask/Agent/Plan 等基础能力。上游原始功能、使用场景和通用说明请查看 [原项目](https://github.com/Kazama-Suichiku/Houdini-Agent)。本文重点记录本 fork 的安装差异、生产增强和近期改动。

## 快速开始

### 环境要求

- SideFX Houdini 19.5 或更高（主力测试：20.0 / 20.5）
- Windows、macOS 或 Linux
- 至少一个 AI Provider 的 API Key（或使用本地 Ollama）

无需 `pip install`——所有运行时依赖已打包在 `lib/` 目录。

### 安装与启动

1. 把仓库放到稳定路径，例如 `C:\tools\Houdini-Agent` 或团队共享盘固定位置。
2. 在 Houdini 中打开 Python Shell（Windows → Python Shell），运行：

```python
import sys, os, importlib.util

# 修改为你的实际路径
launcher_file = r"C:\tools\Houdini-Agent\houdini_agent_launcher.py"

spec = importlib.util.spec_from_file_location("houdini_agent_launcher", launcher_file)
mod = importlib.util.module_from_spec(spec)
sys.modules["houdini_agent_launcher"] = mod
spec.loader.exec_module(mod)
mod.show_tool()
```

3. 首次启动会出现登录对话框，输入用户名即可（用于多用户隔离配置）。
4. 验证：面板正常打开，左下角显示版本号，输入"你好"能收到回复。

**Shelf 按钮**：把上面代码保存为 Shelf Tool 方便一键启动。创建后不要移动仓库目录——启动代码引用绝对路径。现成的 Shelf 代码见 [QUICK_SHELF_CODE.py](QUICK_SHELF_CODE.py)。

### 配置 API Key

推荐在启动 Houdini 前设置用户环境变量（PowerShell）：

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
```

也可在面板右上角菜单 → 设置 → API Key 中临时输入（仅当前会话有效，除非已登录用户名）。支持的所有环境变量见下方 Provider 表格。

## 三种模式

| 模式 | 它能做什么 | 什么时候用 |
|------|-----------|-----------|
| **Ask** | 读场景、查文档、分析错误、给建议 | 只想问问题，不想让它改场景。例如："这个 foreach 为什么报错？" |
| **Agent** | 直接操作：建节点、改参数、跑代码、保存文件 | 明确知道要什么，让它动手。例如："把选中的节点都转成 polygon 并加个 subdivide" |
| **Plan** | 先出方案让你确认，再分步执行 | 复杂任务需要审查。例如："搭建一个带碰撞的 pyro 模拟流程" |

切换方式：面板底部输入框左侧的模式按钮。

**Ask 模式是只读的**——它会拒绝任何修改操作。这是安全特性，不是 bug。

## 本 Fork 的主要功能

节点操作、场景检查、VEX/Python、内置 Skills、基础 Plan 模式、Provider 能力及视觉输入等上游通用能力不在此重复展开，详情见 [原项目说明](https://github.com/Kazama-Suichiku/Houdini-Agent)。以下是本 fork 重点维护的增强功能。

### 长期记忆
三层存储（语义/事件/流程），带奖励驱动学习和反思，按用户隔离并跨 Houdini 重启保留。

- 使用 `/remember <内容>` 显式保存偏好、规则或方法；模型也可在你明确要求“记住”时调用 `remember_memory`
- 写入前展示待保存内容并要求人工确认；Ask 模式、普通问答和“你还记得吗”不会触发写入
- `/memory` 查看记忆状态，`/memories` 打开长期记忆管理器，可筛选、编辑或删除记录
- 执行过工具的回答支持“有用 / 有问题”反馈，用于强化或削弱对应任务经验
- 个人记忆数据库位于 `cache/users/<用户名>/memory/agent_memory.db`；发现历史残留库时会安全恢复或提示处理冲突

### Team Memory
成员可主动发布符合共享资格的 semantic/procedural 经验，由管理员重建团队知识库。导入过程校验文档版本、成员身份、资源上限、向量元数据和共享资格；损坏或全部无效的导出不会覆盖现有团队记忆，成员撤回全部导出后重建则会正确清空旧数据。

### 上下文压缩
在右上角菜单 → 上下文压缩中选择 `Aggressive`、`Balanced` 或 `Conservative`。所选策略同时控制手动压缩和自动裁剪：激进策略释放更多上下文，保守策略保留更多近期对话；工具调用与返回结果会按完整轮次保护，不会被拆散。

### 插件、规则与界面
支持社区插件、Markdown 持久规则及面板内规则编辑器；提供多会话、流式输出、Plan/确认卡片、节点路径跳转、Token 统计、斜杠命令补全和中英双语界面。

### 视觉审查
支持视觉的模型可在技术验证完成后，通过受治理的 `visual_review` 工具审查建模、材质、灯光、相机、构图或 USD lookdev 结果。审查会把网络/几何事实与图像观察分开，并且不会修改场景、相机或视口状态；非视觉模型不会收到此工具。

### 可靠的会话与 Plan 恢复
会话文件采用事务式提交：先写各会话，最后发布 manifest，失败时回滚旧工作区。空工作区标记可防止已清空对话重新出现；用户切换后旧窗口不能覆盖新用户数据；Plan 按会话恢复，未验证的 `running` 步骤不会被自动标记完成。

## Fork 差异说明

本项目 fork 自 [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent)，基于其 v1.5.x 嵌入 Houdini 分支。未采用上游 v2.0 的独立桌面应用方向。

本 fork 保留“直接嵌入 Houdini、操作当前场景”的产品方向，并针对多人共享环境、长时间运行和生产安全持续深化。主要差异如下：

### 多用户与数据隔离

- 登录用户名决定配置、会话、Plan、规则和个人记忆的存储边界，并支持管理员维护用户白名单。
- 用户切换后，旧面板实例会失去工作区写权限，避免 stale writer 覆盖新用户数据。
- 个人记忆权威库固定在 `cache/users/<用户名>/memory/agent_memory.db`；历史错误路径中的 SQLite 数据可在启动时安全恢复，冲突时由用户选择保留哪一份。

### 工具治理与执行安全

- Tool Registry 是工具 schema、handler、owner、启用状态、运行模式和风险元数据的唯一权威；插件和 MCP 工具不能绕过 Registry 直接执行。
- Harness 在执行前统一完成参数规范化、风险判定和 `allow` / `deny` / `ask` / `retry` 决策；batch 中每一项都独立经过同一治理链。
- 修改场景、文件或长期记忆等操作支持人工确认；确认超时、回调异常、策略歧义和授权失败均 fail closed。
- 主线程执行、Cook Guard、撤销语义、结果清洗和 append-only 审计由统一执行边界协调。

### 会话与 Plan 可靠性

- 会话工作区采用 staging、逐文件发布、manifest-last commit 和失败回滚，避免退出或共享盘写入失败留下部分更新状态。
- clear marker 防止已删除会话被旧孤儿文件恢复；Agent 结果始终写回发起请求的 session。
- Plan 的确认、拒绝、步骤状态和恢复投影均由持久化状态驱动；没有完成证据的 `running` 步骤不会自动变成 `done`。
- Plan quality gate 只允许当前 Registry 中已启用且符合 mode/runtime 的工具。

### 上下文与模型请求

- 普通发送、手动压缩和 HTTP 413 恢复共用 round-safe 裁剪，不会拆散 assistant tool call 与对应 tool result。
- `Aggressive`、`Balanced`、`Conservative` 同时控制自动裁剪目标和近期轮次保护比例，而不只是界面选项。
- 工具 schema 计入最终 token budget；当前轮图片受保护，旧轮图片可按预算剥离。
- 发送边界会捕获本轮用户消息快照，后台 Harness 不再从可变历史中误读上一轮意图。

### 个人记忆、反馈与 Team Memory

- 显式记忆提供 `/remember` 和 `remember_memory`；写入前检查用户本轮明确意图、敏感信息、重复内容和单请求调用次数，并强制人工确认。
- L0 手动核心记忆优先于自动经验；长期记忆管理器支持 semantic、episodic、procedural 记录的查看、筛选、编辑和删除。
- 执行过工具的回答提供“有用 / 有问题”反馈，直接调整对应 episodic memory 的 reward、importance 和标签。
- Team Memory 使用版本化导出文档和统一共享资格策略，校验成员身份、资源上限、向量 provenance 及条目结构。
- 全部导出无效时保留现有团队库；成员撤回所有导出时发布空库，避免旧共享经验永久残留。

### 插件、规则与文档检索

- 插件首次加载、重新启用和 reload 共用注册路径；失败时按 owner 回滚已注册的 hook、工具和按钮，防止半注册状态污染运行时。
- Rules 编辑器同时管理内置用户规则和文件规则，并显示实际来源路径。
- 离线 Houdini Help 通过统一 Help Source 读取；文档检索采用多因子评分、查询类型重排和结果多样性约束。
- 本地文档覆盖 Houdini 节点、VEX、HOM、Labs、Terrain、Copernicus、ML 和 MPM，并支持统一缓存失效。

### 宿主兼容与界面

- 保持嵌入式 Qt/PySide 面板和 Houdini 主线程执行模型，未切换到上游 v2.0 独立桌面架构。
- 针对 Houdini 宿主中的 Qt/GPU 生命周期、输入法、长 Cook、窗口销毁和热重载增加防护。
- 提供多会话、模式切换、Plan 卡片、工具状态、确认卡片、记忆管理、斜杠命令补全和中英双语 UI。

### 最近更新（2026-08）

- **08-17～18**：深化事务式会话保存、Plan 生命周期、Registry/Harness 单一执行链、Memory embedding provenance、上下文预算和插件回滚。
- **08-19～24**：加入显式核心记忆、长期记忆管理器、写入前确认、用户反馈奖惩、个人记忆数据库恢复和斜杠命令解析。
- **08-25**：强化 Team Memory 导出文档信任边界，使自动裁剪真正服从压缩策略，并修复记忆管理器布局、规则来源路径和发送边界用户消息快照。

最新更新：[2026-08-25 Team Memory、显式记忆与上下文压缩](changelog/CHANGELOG_2026-08-25.md)。详细历史见 [changelog/](changelog/)。

## 故障排查

**面板打不开，报错"模块找不到"**
- 检查 `sys.path` 是否包含仓库根目录
- 确认路径中没有中文或特殊字符
- 在 Python Shell 先测试 `import houdini_agent_launcher`

**提示"API Key 未配置"或 401 错误**
- 检查环境变量名拼写（区分大小写）
- 改环境变量后必须重启 Houdini
- 面板设置里临时输入 Key 测试，确认 Key 有效

**Ask 模式下提示"工具被拦截"**
- 这是设计如此：Ask 模式只读。切到 Agent 或 Plan 模式执行修改。

**发送图片后模型说"看不到"**
- 确认当前 Provider 支持视觉（OpenAI、多接/OpenRouter 的 Claude/Gemini）
- 检查模型是否选错（如选了 `deepseek-chat` 而非视觉模型）

**Plan 模式执行到一半停止**
- 有自动续接机制，等几秒看是否继续
- 若仍停止，切 Agent 模式说"从最后完成的步骤继续"

**批量创建节点后 Houdini 崩溃**
- 已知问题：Houdini 20.5 高频节点操作可能触发 Qt 崩溃。升级到最新版本，或分批执行。

**记忆/配置没有保存**
- 确认启动时登录了用户名
- 检查 `cache/users/<用户名>/` 目录是否存在且有写入权限
- 显式保存需使用 `/remember <内容>`，或明确要求 Agent“记住/长期保存”；写入前还需在确认卡片中批准
- 个人记忆数据库应位于 `cache/users/<用户名>/memory/agent_memory.db`

**Team Memory 重建失败**
- 检查成员导出文件是否为受支持的 schema，且文档中的用户名与扫描来源一致
- 如果发现了导出文件但全部无效，系统会保留现有团队记忆库，这是防止数据丢失的安全行为
- 重建结果对话框会显示拒绝文件、无效条目和不合共享资格条目数量

## 开发

运行测试：

```powershell
python -m pytest tests -q
```

使用 Houdini 自带 Python 或 `hython` 运行涉及 `hou` 模块的测试。

开发热重载（改代码后无需重启 Houdini）：

```powershell
$env:HOUDINI_AGENT_DEV_RELOAD = "1"
```

更新器框架保留在 [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py)，但用户界面已禁用。

## 作者

KazamaSuichiku（上游）· fork 适配由 yangdi 完成

## 许可证

MIT