# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent 是面向 SideFX Houdini 的 AI 助手。它可以检查场景、创建和修改节点网络、运行 VEX 与 Python、搜索本地 Houdini 文档、规划复杂任务，并通过受控的 Agent 循环协调工具执行。

这个项目主要面向 Houdini TD、技术美术、流程开发者和项目维护者：它不是独立聊天窗口，而是一个运行在 Houdini 工作流里的交互式助手。

当前版本：`1.5.3`

## 它能做什么

Houdini Agent 聚焦四类日常工作流：

| 工作流 | Agent 可以协助的内容 |
|--------|----------------------|
| 构建节点网络 | 创建节点、连接节点、设置参数、添加 Wrangle、自动布局、用 NetworkBox 分组 |
| 检查和调试场景 | 读取选中节点、检查参数和标志、查看 cooking 错误、总结网络结构 |
| 编写和运行代码 | 生成 VEX、运行带 `hou` 模块的 Houdini Python、在允许时执行系统 Shell 命令 |
| 规划大型任务 | 收集场景上下文、提出澄清问题、创建结构化计划，并在确认后执行步骤 |

Agent 使用 OpenAI 风格的 Function Calling 协议。核心工具、内置 Skill 和插件工具都通过统一的 `ToolRegistry` 注册；Harness V2 负责模式检查、风险处理、重试决策和诊断记录。

## 快速开始

### 环境要求

- SideFX Houdini 20.5 或更高版本
- Windows、macOS 或 Linux，使用 Houdini 自带 Python 环境
- 至少一个受支持的 AI Provider API Key；如果使用本地 Ollama 模型则可以不需要云端 Key

通常不需要执行 `pip install`。运行时依赖已内置在 `lib/` 目录中。

### 安装

把仓库放到一个稳定路径，例如：

```text
C:\tools\Houdini-Agent
```

生产使用时，创建 Houdini Shelf 按钮后尽量不要移动目录，因为启动代码会引用这个路径。

### 在 Houdini 中启动

在 Houdini Python Shell 中运行下面代码，或把它放进 Shelf Tool：

```python
import sys

repo_root = r"C:\tools\Houdini-Agent"
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import houdini_agent_launcher as launcher
launcher.show_tool()
```

现成的 Shelf 代码片段见 [houdini_agent/QUICK_SHELF_CODE.py](houdini_agent/QUICK_SHELF_CODE.py)。

### 配置 API Key

推荐在启动 Houdini 前，把 API Key 设置为用户环境变量。

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('DUOJIE_API_KEY', 'xxx', 'User')
```

也可以在 UI 的溢出菜单中配置 Key，并保存到本地配置。运行时配置保存在 `config/` 目录下。

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

### Houdini 工具调用

- 创建、复制、删除、重命名、连接和断开节点
- 设置参数，并在可用时显示 Diff 预览和撤销入口
- 通过优先工具 `create_wrangle_node` 创建 VEX Wrangle 节点
- 设置显示、渲染、模板、绕过、锁定等节点标志
- 保存 HIP 文件，执行撤销和重做操作

### 场景检查

- 读取当前选中节点和子节点
- 检查参数、标志、错误、输入和输出
- 按关键词或自然语言搜索节点类型
- 读取 NetworkBox 感知的网络拓扑摘要
- 验证网络并总结警告或 cooking 问题

### 代码、文档和联网

- 在 Houdini 进程内运行带 `hou` 模块的 Python
- 执行带超时处理和安全限制的系统 Shell 命令
- 搜索本地 Houdini、VEX、HOM、Labs、Terrain、Copernicus、ML 和 MPM 文档
- 在 Web 工具启用时进行搜索和网页正文抓取

### UI 和工作流

- 多会话标签页
- 流式回复和工具状态显示
- 可折叠的思考、工具调用和结果区块
- AI 回复中的 Houdini 节点路径可点击跳转
- Token 分析和费用估算
- 对支持视觉的模型提供图片粘贴、拖拽、选择、缩略图和放大预览
- 通过溢出菜单切换中文/英文 UI
- 通过 `Ctrl+=`、`Ctrl+-` 和 `Ctrl+0` 调整字号

## 工具参考

实际工具集由 `ToolRegistry` 在运行时注册。常见分组如下：

| 分组 | 代表性工具 |
|------|------------|
| 节点操作 | `create_wrangle_node`、`create_node`、`create_nodes_batch`、`connect_nodes`、`set_node_parameter`、`delete_node`、`copy_node`、`rename_node` |
| 查询和检查 | `get_network_structure`、`get_node_parameters`、`list_children`、`read_selection`、`check_errors`、`verify_and_summarize` |
| 代码执行 | `execute_python`、`execute_shell` |
| 文档和联网 | `search_local_doc`、`get_houdini_node_doc`、`web_search`、`fetch_webpage` |
| NetworkBox 和布局 | `create_network_box`、`add_nodes_to_box`、`list_network_boxes`、`layout_nodes`、`get_node_positions` |
| 性能分析 | `perf_start_profile`、`perf_stop_and_report` |
| 规划和任务 | `create_plan`、`update_plan_step`、`ask_question`、`add_todo`、`update_todo` |
| 记忆和诊断 | `search_memory`、`/diagnostics` |

## Skill

Skill 是运行在 Houdini 环境中的预构建 Python 分析脚本。常见几何和网络分析任务应优先使用 Skill，而不是临时手写 Python。

| Skill | 用途 |
|-------|------|
| `analyze_geometry_attribs` | point、vertex、primitive、detail 属性统计 |
| `analyze_normals` | 法线质量检查，包括零长度和未归一化法线 |
| `get_bounding_info` | 边界盒、中心、尺寸、对角线和形状指标 |
| `analyze_connectivity` | 连通区域数量和 piece 摘要 |
| `compare_attributes` | 比较两个节点之间的属性差异 |
| `find_dead_nodes` | 查找孤立节点和未使用的链末端节点 |
| `trace_node_dependencies` | 追踪上游依赖或下游影响范围 |
| `find_attribute_references` | 搜索 VEX、表达式和字符串参数中的属性引用 |
| `analyze_cook_performance` | 全网络 cook 时间排名和瓶颈分析 |
| `inspect_scene_context` | 当前 hip、帧、take、选择、网络和 UI pane 上下文 |
| `analyze_groups` | point、primitive、edge 组数量、空组和成员采样 |
| `inspect_material_assignments` | 材质节点、赋值、丢失引用和未使用材质路径 |
| `inspect_lop_stage` | USD stage 图层、prim 类型统计、相机、灯光、引用和 payload |
| `validate_network_contract` | 检查 OUT/null、显示/渲染标志、缺失输入、错误和死节点 |
| `cache_node_report` | 缓存/导出节点路径、帧范围、磁盘存在性和修改时间摘要 |

内置 Skill 位于 [houdini_agent/skills](houdini_agent/skills)。用户 Skill 目录可在插件管理器中配置。

## 插件、规则、记忆和诊断

### 插件

插件位于 `plugins/`，可以注册 Hook、工具、UI 按钮和设置。示例插件是 [plugins/_example_plugin.py](plugins/_example_plugin.py)，开发指南见 [plugins/PLUGIN_DEV_GUIDE.md](plugins/PLUGIN_DEV_GUIDE.md)。

### 用户规则

持久上下文规则可以通过 Rules Editor 管理，也可以把 `.md` / `.txt` 文件放在 `rules/` 目录中。启用的规则会作为用户上下文注入到 Agent 请求中。

### 长期记忆

记忆系统会在语义、事件和流程三层保存有用的交互模式，用于改进重复工作流。它不应该存储密钥。不要把 API Key、私有路径或个人身份信息写进提示词或规则。

### 诊断

`/diagnostics` 命令会导出精简 JSON 报告，包含策略时间线、Harness 轨迹、调用记录和会话状态，不包含对话正文。

## 项目结构

```text
Houdini-Agent/
|-- houdini_agent_launcher.py        # 顶层启动入口
|-- VERSION                          # 当前语义版本
|-- config/                          # 本地运行时配置
|-- cache/                           # 对话、计划、文档索引和诊断
|-- Doc/                             # 离线 Houdini 和领域知识库
|-- plugins/                         # 社区插件目录
|-- rules/                           # 文件型用户规则
|-- trainData/                       # 导出的训练数据
|-- houdini_agent/
|   |-- main.py                      # show_tool() 和窗口生命周期
|   |-- shelf_tool.py                # Shelf 集成辅助
|   |-- qt_compat.py                 # PySide2 / PySide6 兼容层
|   |-- core/                        # 主窗口、Agent Runner、Plan、Harness
|   |-- ui/                          # Chat UI、组件、i18n、主题、输入区和头部 mixin
|   |-- skills/                      # 内置分析 Skill
|   `-- utils/                       # AI 客户端、工具注册、文档、记忆、插件、更新器
|-- shared/                          # 共享路径和配置工具
`-- tests/                           # 单元测试和 smoke 测试
```

## 架构说明

运行时主要边界如下：

- [houdini_agent/main.py](houdini_agent/main.py) 暴露 `show_tool()`，负责窗口启动。
- [houdini_agent/ui/ai_tab.py](houdini_agent/ui/ai_tab.py) 承载主 AI 标签页，并组合 UI、会话、规划和 Agent Runner mixin。
- `ToolRegistry` 集中管理核心工具、Skill 工具和插件工具，并执行基于模式的访问检查。
- Harness V2 记录 allow、deny、ask、retry 等工具执行策略决策。
- 本地文档检索由 Doc RAG 工具和内置 `Doc/` 知识库提供。

## 更新状态

更新器框架保留在 [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py)。它可以检查 GitHub Releases、缓存 ETag 数据、下载 Release 压缩包，并在更新时保留 `config/`、`cache/`、`trainData/`、`.git` 等本地目录。

当前面向用户的更新 UI 流程保持关闭，因为更新系统还没有准备作为常规入口使用。请把更新器视为保留的基础设施，而不是已启用的生产更新路径。

## 常见问题

### 工具无法启动

- 确认插入 `sys.path` 的路径指向仓库根目录。
- 使用 `houdini_agent_launcher.py`，不要使用旧版启动文件名。
- 先在 Houdini Python Shell 中手动启动；确认可用后再创建 Shelf 按钮。

### API Key 或 401 错误

- 检查 UI 中选择的 Provider。
- 在溢出菜单中重新输入 Key 并保存到本地，或重设对应环境变量。
- 修改用户环境变量后重启 Houdini。

### 工具被拦截

- Ask 模式会按设计拦截修改类工具。
- 高风险工具可能需要确认，或被 Harness 策略拒绝。
- 只有在希望 Agent 修改场景时，才切换到 Agent 模式。

### 图片没有生效

- 确认当前模型支持视觉输入。
- 为控制上下文长度，历史图片可能会被自动剥离。

### Plan 模式未完成全部步骤

- Plan 模式有未完成计划的自动续接机制。
- 如果任务仍然停止，可以切换到 Agent 模式，并要求它从最后完成的计划步骤继续。

## 开发

在仓库根目录使用匹配环境的 Python 运行测试：

```powershell
python -m pytest tests -q
```

涉及 Houdini 行为时，优先使用 Houdini 自带 Python 或 `hython`。

开发热重载可以通过以下环境变量开启：

```powershell
$env:HOUDINI_AGENT_DEV_RELOAD = "1"
```

## 更新日志

详细历史记录保存在 [changelog](changelog)。README 只保留当前使用方式和架构概览。