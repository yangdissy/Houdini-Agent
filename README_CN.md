# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent 是运行在 SideFX Houdini 进程内的 AI 助手。它直接操作场景图：读节点、建网络、改参数、跑 VEX、查文档，而不是生成一堆代码让你自己粘贴。

当前版本：`1.5.3`

## 它是什么

这是一个嵌入 Houdini 的交互式 Agent，不是独立聊天窗口。你在 Houdini 里打开一个面板，用自然语言描述需求，Agent 会：

- 检查当前场景状态（选了什么节点、网络拓扑、参数值、错误信息）
- 规划并执行节点操作（创建、连接、参数设置、VEX 编写）
- 调用本地文档库回答"Houdini 怎么做"类问题
- 对复杂任务先出方案让你确认，再分步执行

它适合的场景：批量节点操作、参数调优、场景诊断、写 Wrangle、查文档、多步骤流程搭建。它不适合的场景：替代你的艺术判断、处理未验证的生产渲染任务、操作你不了解的陌生节点类型。

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

## Provider 配置

| Provider | 环境变量 | 常用模型 | 说明 |
|----------|---------|---------|------|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat`、`deepseek-reasoner` | 响应快，成本低 |
| GLM（智谱） | `GLM_API_KEY` 或 `ZHIPU_API_KEY` | `glm-4.7` 等 | 国内网络稳定 |
| OpenAI | `OPENAI_API_KEY` | GPT-4o、GPT-4 Turbo 等 | 工具调用和视觉能力强 |
| Ollama | 无需 Key | 本地部署的任意模型 | 离线可用，能力取决于模型 |
| 多接（Duojie） | `DUOJIE_API_KEY` | Claude、Gemini、GLM 中转 | 聚合多家，统一接口 |
| OpenRouter | `OPENROUTER_API_KEY` | 200+ 模型路由 | 按 token 计费，选择多 |
| Kimi Coding | `KIMI_CODING_API_KEY` | `kimi-coding` 系列 | 月之暗面代码专用 |
| SiliconFlow | `SILICONFLOW_API_KEY` | 国产开源模型聚合 | 国内访问快 |
| OF3D | 内置 Key，无需配置 | `of3d` 系列 | 内置可用 |
| Custom | `CUSTOM_API_KEY`（可选） | 自建 OpenAI 兼容接口 | 需同时配置 `CUSTOM_API_URL` |

所有 Provider 也支持 `DCC_AI_` 前缀的环境变量（如 `DCC_AI_DEEPSEEK_API_KEY`），避免与其他工具冲突。

**视觉输入**：OpenAI、Claude（通过多接/OpenRouter）、Gemini（通过多接/OpenRouter）支持图片粘贴/拖拽。其他 Provider 收到纯文本。

## 核心功能

### 节点操作
创建/复制/删除/重命名/连接节点，批量设置参数（带 Diff 预览），创建 VEX Wrangle，设置 Display/Render 标志，保存 HIP，撤销/重做。

### 场景检查
读取选择集和子网络，检查参数/标志/错误/输入/输出，搜索节点类型，NetworkBox 拓扑摘要，`verify_network` 一键健康检查。

### 代码与文档
执行 Houdini Python（`hou` 模块），运行受控 Shell 命令，搜索本地文档库（Houdini 节点、VEX、HOM、Labs、Terrain、Copernicus、ML、MPM），联网搜索。

### 内置 Skills（24 个）
预置 Python 分析脚本，覆盖：几何属性分析、法线检查、包围盒、连通性、死节点清理、依赖追踪、Cook 性能、材质赋值、LOP Stage 检查、Pyro/动力学搭建向导、USD 装配等。完整列表见 [houdini_agent/skills/](houdini_agent/skills/)。

### Plan 模式
收集上下文 → 提出澄清问题 → 生成带 DAG 依赖图的计划 → 你确认后执行 → 自动续接中断的步骤。

### 长期记忆
三层存储（语义/事件/流程），带奖励驱动学习和反思。按用户隔离，重启 Houdini 后保留。

### 插件与规则
- `plugins/`：社区插件，扩展工具集
- `rules/`：Markdown 文件定义持久规则，影响 Agent 行为
- 面板内规则编辑器：图形化管理

### UI 特性
多会话标签页、流式输出、代码块折叠、节点路径可点击跳转、Token 用量统计、图片粘贴/拖拽（视觉模型）、中英双语界面、字号缩放。

## 项目结构

```text
Houdini-Agent/
|-- houdini_agent_launcher.py   # 启动入口
|-- VERSION                     # 版本号
|-- config/                     # 用户配置（API Key、界面设置）
|-- cache/                      # 对话记录、计划、记忆、用户隔离数据
|-- Doc/                        # 离线文档库
|-- plugins/                    # 插件目录
|-- rules/                      # 用户规则文件
|-- houdini_agent/
|   |-- main.py                 # 窗口生命周期
|   |-- core/                   # Agent 循环、工具执行、Harness 治理
|   |-- ui/                     # 聊天界面、组件、登录对话框
|   |-- skills/                 # 内置分析脚本
|   `-- utils/                  # AI 客户端、工具注册、文档检索
`-- tests/                      # 单元测试
```

## Fork 差异说明

本项目 fork 自 [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent)，基于其 v1.5.x 嵌入 Houdini 分支。未采用上游 v2.0 的独立桌面应用方向。

主要适配：

| 领域 | 差异 |
|------|------|
| 多用户支持 | 登录隔离、用户白名单、按用户分离配置/记忆/对话 |
| 工具治理 | Harness V2 策略门、输入输出 guardrails、批量操作硬失败语义 |
| 稳定性 | Qt 布局抖动抑制、GPU 竞态防护、原子写入 |
| 文档检索 | 多因子加权、查询类型重排、多样性约束 |

详细变更见 [changelog/](changelog/)。

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