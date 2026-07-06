# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent 是嵌入 SideFX Houdini 的 AI 助手。它可以检查场景、构建和修改节点网络、运行 VEX 与 Python、搜索本地文档、规划复杂任务，并通过受控的 Agent 循环协调工具执行。

面向 Houdini TD、技术美术和流程开发者：它不是独立聊天窗口，而是运行在 Houdini 工作流里的交互式助手。

当前版本：`1.5.3`

## Fork 来源与适配

本项目 fork 自 [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent)（作者 KazamaSuichiku），基于其 **v1.5.x 嵌入 Houdini 进程的分支**（PySide UI，运行在 Houdini 进程内）。**未采用**上游 v2.0 方向（独立桌面应用、QML/Qt Quick UI、Meshy 3D 生成、socket bridge）。

在上游 v1.5.x 基础上，本 fork 针对团队生产使用做了以下适配：

| 领域 | 改动内容 |
|------|----------|
| **多人使用** | 登录对话框、用户白名单（`cache/.access`）、按用户隔离对话/计划/记忆/工作区/配置/规则。SQLite 记忆库存本地磁盘（非 SMB 共享盘），避免文件锁不可靠。 |
| **Harness V2 治理** | 工具执行边界加固——模型传入的策略标志不再被信任；公开工具调用必须经过策略门。统一输入 guardrails（敏感 key、危险 Python/Shell 模式、路径穿越）和输出 guardrails（结果规范化 + 敏感信息脱敏）。 |
| **工具硬化** | 软失败 → 硬失败语义：批量操作中任何失败现在返回 `success=False` + 完整错误清单 + did-you-mean 提示。`create_node` 参数出错时原子回滚。新增 `verify_network`（一次性网络健康检查 + 几何证据）和 `get_node_card`（建节点前查类型说明）。`create_nodes_batch` 增加 Phase 1 预校验 + `dry_run=True`。 |
| **AI 行为引导** | “Senior Artist Discipline”规则：先规划整图再原子构建（batch 优先）、绝不猜参数名、验证后才声明成功。反模式在 schema 中明确禁止。 |
| **稳定性加固** | 批量节点操作期间抑制 Qt layout 抖动（避免 Houdini 20.5 上 `QHeaderView`/`QLayout` SIGSEGV）。跳过 Volume/VDB display 节点的强制 cook 以防 GPU 竞态崩溃。忙态光标提示用户在 Agent 运行时不要操作视口。 |
| **Rules Manager 硬化** | 原子写入（`.tmp` → `fsync` → `os.replace`）、损坏文件自动备份、mtime 文件规则缓存、token 预算上限、RLock 并发保护。 |
| **Doc RAG 改进** | 多因子加权打分（标题/正文/覆盖率/来源/短片段惩罚）、query-type 重排（node/vex/hom/general）、多样性约束、结构化返回字段。 |

详细变更历史见 [changelog/](changelog)。

## 快速开始

### 环境要求

- SideFX Houdini 19.5+（主力：20.0 / 20.5）
- Windows、macOS 或 Linux，使用 Houdini 自带 Python 环境
- 至少一个受支持的 AI Provider API Key（或本地 Ollama 模型）

无需 `pip install`——运行时依赖已内置在 `lib/`。

### 安装与启动

把仓库放到稳定路径，例如 `C:\tools\Houdini-Agent`。在 Houdini Python Shell 中运行下面代码，或放进 Shelf Tool：

```python
import sys

repo_root = r"C:\tools\Houdini-Agent"
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import houdini_agent_launcher as launcher
launcher.show_tool()
```

现成的 Shelf 代码片段见 [houdini_agent/QUICK_SHELF_CODE.py](houdini_agent/QUICK_SHELF_CODE.py)。创建 Shelf 按钮后尽量不要移动目录——启动代码会引用这个路径。

### 配置 API Key

推荐在启动 Houdini 前，把 API Key 设置为用户环境变量。

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('DUOJIE_API_KEY', 'xxx', 'User')
```

也可在 UI 溢出菜单中配置 Key 并保存到本地配置（`config/`）。

## Agent 模式

| 模式 | 适合场景 | 工具权限 |
|------|----------|----------|
| Ask | 读取、分析、调试建议 | 只读工具和文档工具 |
| Agent | 构建和编辑 Houdini 场景 | 完整工具权限，高风险操作会经过策略检查 |
| Plan | 需要先审查方案的多步骤任务 | 先只读规划，确认后再执行 |

如果只想解释或诊断，不希望改场景，用 Ask 模式。需要 Agent 真正操作场景时，用 Agent 模式。任务影响较大、需要先看方案时，用 Plan 模式。

## 支持的提供商

| 提供商 | 常用模型 | 说明 |
|--------|----------|------|
| DeepSeek | `deepseek-chat`、`deepseek-reasoner` | 响应快、成本低，支持工具调用 |
| GLM / 智谱 | `glm-4.7`、GLM 中转模型 | 适合国内网络环境 |
| OpenAI | 支持工具调用和视觉输入的 GPT 模型 | 通用能力强，适合工具调用和图片理解 |
| Ollama | Ollama 暴露的任意本地模型 | 本地优先；能力取决于选择的模型 |
| 拼好饭中转 | Claude、Gemini、GLM、MiniMax 等中转模型 | 通过中转接口进行模型路由 |

图片输入取决于具体模型能力。OpenAI 视觉模型、Claude 变体和 Gemini 变体在对应 Provider 暴露图片能力时可用。不支持视觉的模型会收到纯文本消息。

## 主要功能

- **节点操作**——创建/复制/删除/重命名/连接节点、设置参数（带 Diff 预览）、创建 VEX Wrangle、设置标志、保存 HIP、撤销/重做
- **场景检查**——读取选择和子节点、检查参数/标志/错误/输入/输出、搜索节点类型、NetworkBox 感知拓扑摘要、`verify_network` 健康检查
- **代码、文档和联网**——运行 Houdini Python（`hou`）、受控 Shell 命令、搜索本地 Houdini/VEX/HOM/Labs/Terrain/Copernicus/ML/MPM 文档、联网搜索和网页抓取
- **内置 Skill**——预构建 Python 分析脚本，覆盖几何属性、法线、边界信息、连通性、死节点、依赖追踪、cook 性能、材质赋值、LOP stage 等（见 [houdini_agent/skills](houdini_agent/skills)）
- **Plan 模式**——收集上下文、提出澄清问题、创建带 DAG 的结构化计划、确认后执行、自动续接
- **长期记忆**——语义/事件/流程三层存储，带奖励驱动学习和反思；按用户隔离
- **插件和规则**——`plugins/` 社区插件、通过编辑器或 `rules/*.md` 管理持久用户规则
- **UI**——多会话标签页、流式回复、可折叠区块、可点击节点路径、Token 分析、视觉模型图片粘贴/拖拽/选择、中英双语 UI、字号缩放

实际工具集由 `ToolRegistry` 在运行时注册。Harness V2 负责模式检查、风险处理、重试决策和诊断。`/diagnostics` 命令导出精简 JSON 报告（策略时间线、Harness 轨迹、调用记录——不含对话正文）。

## 项目结构

```text
Houdini-Agent/
|-- houdini_agent_launcher.py        # 顶层启动入口
|-- VERSION                          # 当前语义版本
|-- config/                          # 本地运行时配置
|-- cache/                           # 对话、计划、文档索引、诊断、users/
|-- Doc/                             # 离线 Houdini 和领域知识库
|-- plugins/                         # 社区插件目录
|-- rules/                           # 文件型用户规则
|-- shared/                          # 共享路径和配置工具（按用户隔离）
|-- houdini_agent/
|   |-- main.py                      # show_tool() 和窗口生命周期
|   |-- core/                        # 主窗口、Agent Runner、Plan、Harness
|   |-- ui/                          # Chat UI、组件、i18n、主题、登录对话框
|   |-- skills/                      # 内置分析 Skill
|   `-- utils/                       # AI 客户端、工具注册、文档、记忆、插件
`-- tests/                           # 单元测试和 smoke 测试
```

## 常见问题

- **工具无法启动**——确认 `sys.path` 指向仓库根目录；使用 `houdini_agent_launcher.py`；先在 Houdini Python Shell 中测试。
- **API Key 或 401 错误**——检查选择的 Provider；在溢出菜单重输 Key 或重设环境变量；改用户环境变量后重启 Houdini。
- **工具被拦截**——Ask 模式按设计拦截修改类工具；高风险工具可能需确认或被 Harness 策略拒绝；要修改场景时切到 Agent 模式。
- **图片没有生效**——确认模型支持视觉输入；为控制上下文长度，历史图片可能被自动剥离。
- **Plan 模式未完成全部步骤**——有自动续接机制；若仍停止，切到 Agent 模式让它从最后完成的步骤继续。

## 开发

```powershell
python -m pytest tests -q
```

涉及 Houdini 行为时，优先使用 Houdini 自带 Python 或 `hython`。开发热重载：`$env:HOUDINI_AGENT_DEV_RELOAD = "1"`。

更新器框架保留在 [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py)，但面向用户的更新 UI 已关闭——视为保留的基础设施，而非已启用的更新路径。

## 作者

KazamaSuichiku（上游）· fork 适配由 yangdi 完成

## 许可证

MIT