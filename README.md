# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent is an AI assistant that runs inside the SideFX Houdini process. It operates directly on the scene graph: reading nodes, building networks, modifying parameters, running VEX, and searching documentation — instead of generating code for you to copy-paste.

Current version: `1.5.3`

## What It Is

An interactive agent embedded in Houdini, not a standalone chat window. You open a panel inside Houdini, describe what you need in natural language, and the agent will:

- Inspect the current scene state (selected nodes, network topology, parameter values, error messages)
- Plan and execute node operations (create, connect, parameter setup, VEX writing)
- Search the local documentation library to answer "how do I do X in Houdini" questions
- For complex tasks, present a plan for your approval before executing step by step

Good use cases: batch node operations, parameter tuning, scene diagnosis, writing Wrangles, documentation lookup, multi-step workflow setup. Not a substitute for: artistic judgment, unverified production renders, or operating node types you don't understand.

## Quick Start

### Requirements

- SideFX Houdini 19.5 or later (primary tested: 20.0 / 20.5)
- Windows, macOS, or Linux
- At least one AI provider API key (or a local Ollama instance)

No `pip install` needed — all runtime dependencies are bundled in `lib/`.

### Install & Launch

1. Place the repository at a stable path, e.g. `C:\tools\Houdini-Agent` or a fixed team share location.
2. In Houdini, open the Python Shell (Windows → Python Shell) and run:

```python
import sys, os, importlib.util

# Change to your actual path
launcher_file = r"C:\tools\Houdini-Agent\houdini_agent_launcher.py"

spec = importlib.util.spec_from_file_location("houdini_agent_launcher", launcher_file)
mod = importlib.util.module_from_spec(spec)
sys.modules["houdini_agent_launcher"] = mod
spec.loader.exec_module(mod)
mod.show_tool()
```

3. On first launch, a login dialog appears — enter a username (used for per-user config isolation).
4. Verify: the panel opens, the version number shows in the bottom-left, and typing "hello" gets a response.

**Shelf button**: Save the snippet above as a Shelf Tool for one-click launch. Do not move the repo folder after creating the button — the launch code references the absolute path. A ready-made snippet is in [QUICK_SHELF_CODE.py](QUICK_SHELF_CODE.py).

### Configure API Keys

Set user environment variables before launching Houdini (PowerShell):

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
```

You can also enter keys temporarily in the panel menu → Settings → API Key (session-only unless a username is logged in). See the Provider table below for all supported environment variables.

## Agent Modes

| Mode | What it does | When to use |
|------|-------------|-------------|
| **Ask** | Reads scenes, searches docs, analyzes errors, gives advice | You only want answers, not scene changes. E.g., "Why is this foreach erroring?" |
| **Agent** | Direct action: create nodes, modify parameters, run code, save files | You know what you want and want it done. E.g., "Convert selected nodes to polygons and add a subdivide" |
| **Plan** | Presents a plan for approval, then executes step by step | Complex tasks that need review. E.g., "Set up a pyro sim with collision" |

Switch via the mode button on the left side of the input bar.

**Ask mode is read-only** — it will refuse any mutating operation. This is a safety feature, not a bug.

## Provider Configuration

| Provider | Environment Variable | Typical Models | Notes |
|----------|---------------------|----------------|-------|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat`, `deepseek-reasoner` | Fast, cost-effective |
| GLM (Zhipu) | `GLM_API_KEY` or `ZHIPU_API_KEY` | `glm-4.7` etc. | Stable for China-based networks |
| OpenAI | `OPENAI_API_KEY` | GPT-4o, GPT-4 Turbo, etc. | Strong tool calling and vision |
| Ollama | No key needed | Any locally deployed model | Offline-capable; capability varies by model |
| Duojie | `DUOJIE_API_KEY` | Claude, Gemini, GLM relay | Aggregated relay, unified API |
| OpenRouter | `OPENROUTER_API_KEY` | 200+ model routing | Pay-per-token, wide selection |
| Kimi Coding | `KIMI_CODING_API_KEY` | `kimi-coding` series | Moonshot code-specialized |
| SiliconFlow | `SILICONFLOW_API_KEY` | Chinese open-source model aggregation | Fast domestic access |
| OF3D | Built-in key, no config needed | `of3d` series | Ready to use out of the box |
| Custom | `CUSTOM_API_KEY` (optional) | Self-hosted OpenAI-compatible API | Also set `CUSTOM_API_URL` |

All providers also support the `DCC_AI_` prefix (e.g. `DCC_AI_DEEPSEEK_API_KEY`) to avoid conflicts with other tools.

**Vision input**: OpenAI, Claude (via Duojie/OpenRouter), and Gemini (via Duojie/OpenRouter) support image paste/drag-drop. Other providers receive text-only messages.

## Core Features

### Node Operations
Create/copy/delete/rename/connect nodes, batch parameter setup with diff preview, VEX Wrangle creation, Display/Render flag control, HIP save, undo/redo.

### Scene Inspection
Read selection and subnetworks, inspect parameters/flags/errors/inputs/outputs, search node types, NetworkBox topology summaries, `verify_network` one-shot health checks.

### Code & Documentation
Execute Houdini Python (`hou` module), run guarded shell commands, search local doc library (Houdini nodes, VEX, HOM, Labs, Terrain, Copernicus, ML, MPM), web search.

### Built-in Skills (24)
Pre-built Python analysis scripts covering: geometry attribute analysis, normals inspection, bounding boxes, connectivity, dead node cleanup, dependency tracing, cook performance, material assignments, LOP stage inspection, Pyro/dynamics setup wizards, USD assembly, and more. Full list in [houdini_agent/skills/](houdini_agent/skills/).

### Plan Mode
Gather context → ask clarifying questions → generate a plan with DAG dependencies → you approve → execute → auto-resume interrupted steps.

### Long-term Memory
Three-layer store (semantic/episodic/procedural) with reward-driven learning and reflection. Per-user isolated, persists across Houdini restarts.

### Plugins & Rules
- `plugins/`: Community plugins that extend the tool set
- `rules/`: Markdown files defining persistent rules that shape agent behavior
- Built-in rules editor: GUI-based management

### UI Features
Multi-session tabs, streaming output, collapsible code blocks, clickable node paths, token usage stats, image paste/drag-drop (vision models), bilingual CN/EN UI, font scaling.

## Project Structure

```text
Houdini-Agent/
|-- houdini_agent_launcher.py   # Launch entry point
|-- VERSION                     # Version number
|-- config/                     # User config (API keys, UI settings)
|-- cache/                      # Conversations, plans, memory, per-user data
|-- Doc/                        # Offline documentation library
|-- plugins/                    # Plugin directory
|-- rules/                      # User rule files
|-- houdini_agent/
|   |-- main.py                 # Window lifecycle
|   |-- core/                   # Agent loop, tool execution, Harness governance
|   |-- ui/                     # Chat interface, widgets, login dialog
|   |-- skills/                 # Built-in analysis scripts
|   `-- utils/                  # AI client, tool registry, doc retrieval
`-- tests/                      # Unit tests
```

## Fork Differences

This project is a fork of [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent), based on its v1.5.x embedded-in-Houdini branch. It does not follow upstream's v2.0 standalone desktop app direction.

Key adaptations:

| Area | Difference |
|------|-----------|
| Multi-user support | Login isolation, user allowlist, per-user config/memory/conversations |
| Tool governance | Harness V2 policy gate, input/output guardrails, hard-fail batch semantics |
| Stability | Qt layout jitter suppression, GPU race protection, atomic writes |
| Doc retrieval | Multi-factor weighted scoring, query-type reranking, diversity constraints |

Full change history in [changelog/](changelog/).

## Troubleshooting

**Panel won't open, "module not found" error**
- Verify `sys.path` includes the repo root
- Check the path contains no Chinese or special characters
- Test `import houdini_agent_launcher` in the Python Shell first

**"API Key not configured" or 401 errors**
- Check environment variable spelling (case-sensitive)
- Restart Houdini after changing env vars
- Test the key temporarily in panel Settings to confirm it's valid

**"Tool blocked" in Ask mode**
- By design: Ask mode is read-only. Switch to Agent or Plan mode for modifications.

**Model says "I can't see the image" after pasting**
- Confirm the current provider supports vision (OpenAI, Claude/Gemini via Duojie/OpenRouter)
- Check the model selection (e.g., `deepseek-chat` is not a vision model)

**Plan mode stops mid-execution**
- Auto-resume usually kicks in — wait a few seconds
- If still stuck, switch to Agent mode and say "continue from the last completed step"

**Houdini crashes after batch node creation**
- Known issue: high-frequency node ops on Houdini 20.5 can trigger Qt crashes. Update to the latest version or split into smaller batches.

**Memory/config not persisting**
- Confirm you logged in with a username at startup
- Check that `cache/users/<username>/` exists and is writable

## Development

Run tests:

```powershell
python -m pytest tests -q
```

Use Houdini's bundled Python or `hython` for tests involving the `hou` module.

Dev hot reload (no Houdini restart needed after code changes):

```powershell
$env:HOUDINI_AGENT_DEV_RELOAD = "1"
```

The updater framework is preserved in [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py), but the user-facing update UI is disabled.

## Author

KazamaSuichiku (upstream) · fork adaptations by yangdi

## License

MIT
