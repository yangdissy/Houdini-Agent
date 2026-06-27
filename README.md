# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent is an AI assistant for SideFX Houdini. It can inspect scenes, create and modify node networks, run VEX and Python, search local Houdini documentation, plan complex work, and coordinate tools through a guarded agent loop.

The project is aimed at Houdini TDs, technical artists, pipeline developers, and maintainers who want an interactive assistant inside Houdini rather than a separate chat window.

Current version: `1.5.3`

## What It Does

Houdini Agent focuses on four daily workflows:

| Workflow | What the agent can help with |
|----------|------------------------------|
| Build node networks | Create nodes, connect them, set parameters, add Wrangles, layout nodes, group them into NetworkBoxes |
| Inspect and debug scenes | Read selected nodes, inspect parameters and flags, check cooking errors, summarize network structure |
| Write and run code | Generate VEX, run Houdini Python with `hou`, execute system shell commands when allowed |
| Plan larger tasks | Gather scene context, ask clarifying questions, create a structured plan, and execute confirmed steps |

The agent uses OpenAI-style Function Calling. Core tools, built-in skills, and plugin tools are registered through a central `ToolRegistry`, while Harness V2 adds mode checks, risk handling, retry decisions, and diagnostics.

## Quick Start

### Requirements

- SideFX Houdini 20.5 or newer
- Windows, macOS, or Linux with Houdini's Python environment
- At least one supported AI provider key, unless using a local Ollama model

No `pip install` is normally required. Runtime dependencies are bundled in `lib/`.

### Install

Place this repository somewhere stable on disk, for example:

```text
C:\tools\Houdini-Agent
```

In production, avoid moving the folder after creating a Houdini shelf button because the launch code points to this path.

### Launch in Houdini

Run this in Houdini's Python Shell, or put it in a Shelf Tool:

```python
import sys

repo_root = r"C:\tools\Houdini-Agent"
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import houdini_agent_launcher as launcher
launcher.show_tool()
```

For a shelf-ready snippet, see [houdini_agent/QUICK_SHELF_CODE.py](houdini_agent/QUICK_SHELF_CODE.py).

### Configure API Keys

Recommended: set provider keys as user environment variables before launching Houdini.

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('DUOJIE_API_KEY', 'xxx', 'User')
```

You can also configure keys in the UI from the overflow menu and save them to local config. Local runtime settings are stored under `config/`.

## Agent Modes

| Mode | Best for | Tool access |
|------|----------|-------------|
| Ask | Reading, analysis, debugging advice | Read-only and documentation tools |
| Agent | Building and editing Houdini scenes | Full tool access, with policy checks for risky actions |
| Plan | Multi-step work that needs review | Read-only planning first, then confirmed execution |

Use Ask mode when you want an explanation or scene diagnosis without edits. Use Agent mode when you want the assistant to act. Use Plan mode when the result matters enough to review the approach before execution.

## Supported Providers

| Provider | Typical models | Notes |
|----------|----------------|-------|
| DeepSeek | `deepseek-chat`, `deepseek-reasoner` | Fast, cost-effective, supports tool calling |
| GLM / Zhipu | `glm-4.7`, GLM relay variants | Useful for China-based workflows |
| OpenAI | GPT tool-calling and vision-capable models | Strong general tool use and image understanding |
| Ollama | Any local model exposed by Ollama | Local-first; capability depends on the selected model |
| Duojie relay | Claude, Gemini, GLM, MiniMax relay models | Uses relay-specific model routing |

Vision input is model-dependent. OpenAI vision models, Claude variants, and Gemini variants are supported where the configured provider exposes image input. Non-vision models receive text-only messages.

## Main Features

### Houdini Tool Calling

- Create, copy, delete, rename, connect, and disconnect nodes
- Set parameters with diff previews and undo support where available
- Create VEX Wrangle nodes through the priority `create_wrangle_node` tool
- Set display/render/template/bypass/lock flags
- Save HIP files and run undo/redo operations

### Scene Inspection

- Read current selection and child nodes
- Inspect parameters, flags, errors, inputs, and outputs
- Search node types by keyword or natural language
- Read NetworkBox-aware topology summaries
- Verify a network and summarize warnings or cooking issues

### Code, Docs, and Web

- Run Houdini Python in-process with the `hou` module
- Run guarded system shell commands with timeout handling
- Search local Houdini, VEX, HOM, Labs, Terrain, Copernicus, ML, and MPM documentation
- Search and fetch web pages when web tools are enabled

### UI and Workflow

- Multi-session tabs
- Streaming responses and tool status display
- Collapsible thinking/tool/result blocks
- Clickable Houdini node paths in AI replies
- Token analytics and cost estimates
- Image paste, drag-drop, picker, thumbnail preview, and enlarged preview for vision models
- Bilingual Chinese/English UI through the overflow menu
- Font scaling with `Ctrl+=`, `Ctrl+-`, and `Ctrl+0`

## Tool Reference

The exact tool set is registered by `ToolRegistry` at runtime. The common groups are:

| Group | Representative tools |
|-------|----------------------|
| Node operations | `create_wrangle_node`, `create_node`, `create_nodes_batch`, `connect_nodes`, `set_node_parameter`, `delete_node`, `copy_node`, `rename_node` |
| Query and inspection | `get_network_structure`, `get_node_parameters`, `list_children`, `read_selection`, `check_errors`, `verify_and_summarize` |
| Code execution | `execute_python`, `execute_shell` |
| Documentation and web | `search_local_doc`, `get_houdini_node_doc`, `web_search`, `fetch_webpage` |
| NetworkBox and layout | `create_network_box`, `add_nodes_to_box`, `list_network_boxes`, `layout_nodes`, `get_node_positions` |
| Performance | `perf_start_profile`, `perf_stop_and_report` |
| Planning and tasks | `create_plan`, `update_plan_step`, `ask_question`, `add_todo`, `update_todo` |
| Memory and diagnostics | `search_memory`, `/diagnostics` |

## Skills

Skills are pre-built Python analysis scripts that run inside Houdini. They are preferred over ad-hoc Python for common geometry and network analysis tasks.

| Skill | Purpose |
|-------|---------|
| `analyze_geometry_attribs` | Attribute statistics for point, vertex, primitive, and detail attributes |
| `analyze_normals` | Normal quality checks, including zero length and non-normalized normals |
| `get_bounding_info` | Bounding box, center, size, diagonal, and shape metrics |
| `analyze_connectivity` | Connected component counts and piece summaries |
| `compare_attributes` | Attribute differences between two nodes |
| `find_dead_nodes` | Orphan and unused end-of-chain node detection |
| `trace_node_dependencies` | Upstream dependency or downstream impact tracing |
| `find_attribute_references` | Attribute usage search in VEX, expressions, and string parameters |
| `analyze_cook_performance` | Network-wide cook-time ranking and bottleneck analysis |
| `inspect_scene_context` | Current hip file, frame, take, selection, network, and UI pane context |
| `analyze_groups` | Point, primitive, and edge group counts, empty groups, and sample members |
| `inspect_material_assignments` | Material nodes, assignments, missing references, and unused material paths |
| `inspect_lop_stage` | USD stage layers, prim type counts, cameras, lights, references, and payloads |
| `validate_network_contract` | Network contract checks for OUT/nulls, flags, missing inputs, errors, and dead nodes |
| `cache_node_report` | Cache/export node paths, frame ranges, disk existence, and modified-time summary |

Built-in skills live in [houdini_agent/skills](houdini_agent/skills). User skills can be configured from the Plugin Manager.

## Plugins, Rules, Memory, and Diagnostics

### Plugins

Plugins live in `plugins/` and can register hooks, tools, UI buttons, and settings. The example plugin is [plugins/_example_plugin.py](plugins/_example_plugin.py), and the developer guide is [plugins/PLUGIN_DEV_GUIDE.md](plugins/PLUGIN_DEV_GUIDE.md).

### User Rules

Persistent context rules can be managed from the Rules Editor or stored as `.md` / `.txt` files under `rules/`. Enabled rules are injected into agent requests as user context.

### Long-Term Memory

The memory system stores useful interaction patterns across semantic, episodic, and procedural layers. It is designed to improve repeated workflows, not to store secrets. Do not put API keys, private paths, or personal identity data into prompts or rules.

### Diagnostics

The `/diagnostics` command exports a compact JSON report with policy timeline, Harness trace, call records, and session state. Conversation content is excluded.

## Project Structure

```text
Houdini-Agent/
|-- houdini_agent_launcher.py        # Top-level launch entry
|-- VERSION                          # Current semantic version
|-- config/                          # Local runtime configuration
|-- cache/                           # Conversations, plans, doc indexes, diagnostics
|-- Doc/                             # Offline Houdini and domain knowledge bases
|-- plugins/                         # Community plugin directory
|-- rules/                           # File-based user rules
|-- trainData/                       # Exported training data
|-- houdini_agent/
|   |-- main.py                      # show_tool() and window lifecycle
|   |-- shelf_tool.py                # Shelf integration helpers
|   |-- qt_compat.py                 # PySide2 / PySide6 compatibility
|   |-- core/                        # Main window, agent runner, plans, harness
|   |-- ui/                          # Chat UI, widgets, i18n, theme, input/header mixins
|   |-- skills/                      # Built-in analysis skills
|   `-- utils/                       # AI client, tool registry, docs, memory, plugins, updater
|-- shared/                          # Shared path/config utilities
`-- tests/                           # Unit and smoke tests
```

## Architecture Notes

The runtime is organized around a few practical boundaries:

- [houdini_agent/main.py](houdini_agent/main.py) exposes `show_tool()` and owns window startup.
- [houdini_agent/ui/ai_tab.py](houdini_agent/ui/ai_tab.py) hosts the main AI tab and combines UI, session, planning, and agent-runner mixins.
- `ToolRegistry` centralizes core tools, skill tools, and plugin tools with mode-based access checks.
- Harness V2 tracks policy decisions such as allow, deny, ask, and retry for tool execution.
- Local documentation retrieval is handled by the Doc RAG utilities and the bundled `Doc/` knowledge bases.

## Updating Status

The updater framework is present in [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py). It can check GitHub Releases, cache ETag data, download a release archive, and preserve local folders such as `config/`, `cache/`, `trainData/`, and `.git` during an update.

The user-facing update UI flow is currently kept disabled while the update system is not ready for regular use. Treat the updater as preserved infrastructure, not as an enabled production update path.

## Troubleshooting

### The tool does not launch

- Verify the path inserted into `sys.path` points to the repository root.
- Use `houdini_agent_launcher.py`, not an older launcher filename.
- Start from Houdini's Python Shell first; add a shelf button only after the manual launch works.

### I get API key or 401 errors

- Check the provider selected in the UI.
- Re-enter the key from the overflow menu and save it locally, or reset the matching environment variable.
- Restart Houdini after changing user environment variables.

### A tool is blocked

- Ask mode blocks mutating tools by design.
- Risky tools may require confirmation or be denied by Harness policy.
- Switch to Agent mode only when you want the assistant to modify the scene.

### Images are ignored

- Confirm the selected model supports vision input.
- Old images in conversation history may be stripped automatically to stay within context limits.

### Plan mode stops before all steps finish

- Plan mode has an auto-resume mechanism for incomplete plans.
- If the task still stops, switch to Agent mode and ask the agent to continue from the last completed plan step.

## Development

Run tests from the repository root with the Python interpreter that matches your environment:

```powershell
python -m pytest tests -q
```

For Houdini-specific behavior, prefer Houdini's bundled Python or `hython`.

Development hot reload can be enabled with:

```powershell
$env:HOUDINI_AGENT_DEV_RELOAD = "1"
```

## Changelog

Detailed history is kept under [changelog](changelog). The README intentionally keeps only the current usage and architecture overview.

## Author

KazamaSuichiku

## License

MIT
