# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent is an AI assistant embedded in SideFX Houdini. It inspects scenes, builds and modifies node networks, runs VEX and Python, searches local documentation, plans complex work, and coordinates tools through a guarded agent loop.

Aimed at Houdini TDs, technical artists, and pipeline developers who want an interactive assistant inside Houdini rather than a separate chat window.

Current version: `1.5.3`

## Fork Origin & Adaptations

This project is a fork of [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent) (by KazamaSuichiku), based on the **v1.5.x embedded-in-Houdini line** (PySide UI, runs inside the Houdini process). It has **not** adopted upstream's v2.0 direction (standalone desktop app, QML/Qt Quick UI, Meshy 3D generation, socket bridge).

On top of the upstream v1.5.x base, this fork adds the following adaptations for team production use:

| Area | What changed |
|------|--------------|
| **Multi-user support** | Login dialog, user allowlist (`cache/.access`), per-user isolation of conversations / plans / memory / workspace / config / rules. SQLite memory DB stored on local disk (not SMB share) to avoid unreliable file locks. |
| **Harness V2 governance** | Tool execution boundary hardening — model-supplied policy flags are no longer trusted; public tool calls must pass through the policy gate. Unified input guardrails (sensitive keys, dangerous Python/Shell patterns, path traversal) and output guardrails (result normalization + secret redaction). |
| **Tool hardening** | Soft-fail → hard-fail semantics: any failure in batch operations now returns `success=False` with a full error list and did-you-mean hints. `create_node` rolls back atomically on parameter errors. New `verify_network` (one-shot network health + geometry evidence) and `get_node_card` (pre-build type inspection). `create_nodes_batch` gains Phase 1 pre-validation + `dry_run=True`. |
| **AI behavior guidance** | "Senior Artist Discipline" rules: plan the whole graph then build atomically (batch-first), never guess parameter names, verify-then-claim. Anti-patterns explicitly forbidden in schemas. |
| **Stability hardening** | Suppress Qt layout jitter during high-frequency batch node ops (avoids `QHeaderView`/`QLayout` SIGSEGV on Houdini 20.5). Skip forced cook of Volume/VDB display nodes to prevent GPU race crashes. Busy-state cursor warning reminds users not to touch the viewport while the agent runs. |
| **Rules Manager hardening** | Atomic write (`.tmp` → `fsync` → `os.replace`), corrupt-file auto-backup, mtime-based file-rule cache, token budget caps, RLock concurrency protection. |
| **Doc RAG improvements** | Multi-factor weighted scoring (title/body/coverage/source/short-fragment penalty), query-type reranking (node/vex/hom/general), diversity constraints, structured return fields. |

Detailed change history is under [changelog/](changelog).

## Quick Start

### Requirements

- SideFX Houdini 19.5+ (primary: 20.0 / 20.5)
- Windows, macOS, or Linux with Houdini's Python environment
- At least one supported AI provider key (or a local Ollama model)

No `pip install` needed — runtime dependencies are bundled in `lib/`.

### Install & Launch

Place the repository at a stable path, e.g. `C:\tools\Houdini-Agent`. Run this in Houdini's Python Shell or put it in a Shelf Tool:

```python
import sys

repo_root = r"C:\tools\Houdini-Agent"
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

import houdini_agent_launcher as launcher
launcher.show_tool()
```

For a shelf-ready snippet, see [houdini_agent/QUICK_SHELF_CODE.py](houdini_agent/QUICK_SHELF_CODE.py). Avoid moving the folder after creating a shelf button — the launch code references this path.

### Configure API Keys

Recommended: set provider keys as user environment variables before launching Houdini.

```powershell
[Environment]::SetEnvironmentVariable('DEEPSEEK_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('GLM_API_KEY', 'xxx.xxx', 'User')
[Environment]::SetEnvironmentVariable('OPENAI_API_KEY', 'sk-xxx', 'User')
[Environment]::SetEnvironmentVariable('DUOJIE_API_KEY', 'xxx', 'User')
```

Keys can also be configured in the UI overflow menu and saved to local config (`config/`).

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

- **Node operations** — create/copy/delete/rename/connect nodes, set parameters with diff previews, create VEX Wrangles, set flags, save HIP, undo/redo
- **Scene inspection** — read selection and children, inspect parameters/flags/errors/inputs/outputs, search node types, NetworkBox-aware topology summaries, `verify_network` health checks
- **Code, docs, and web** — run Houdini Python (`hou`), guarded shell commands, search local Houdini/VEX/HOM/Labs/Terrain/Copernicus/ML/MPM docs, web search and page fetch
- **Built-in skills** — pre-built Python analysis scripts for geometry attributes, normals, bounding info, connectivity, dead nodes, dependency tracing, cook performance, material assignments, LOP stage, etc. (see [houdini_agent/skills](houdini_agent/skills))
- **Plan mode** — gather context, ask clarifying questions, create a structured plan with DAG, execute confirmed steps with auto-resume
- **Long-term memory** — three-layer (semantic/episodic/procedural) store with reward-driven learning and reflection; per-user isolated
- **Plugins & rules** — community plugins in `plugins/`, persistent user rules via editor or `rules/*.md`
- **UI** — multi-session tabs, streaming responses, collapsible blocks, clickable node paths, token analytics, image paste/drag-drop/picker for vision models, bilingual CN/EN UI, font scaling

The exact tool set is registered by `ToolRegistry` at runtime. Harness V2 adds mode checks, risk handling, retry decisions, and diagnostics. The `/diagnostics` command exports a compact JSON report (policy timeline, Harness trace, call records — no conversation content).

## Project Structure

```text
Houdini-Agent/
|-- houdini_agent_launcher.py        # Top-level launch entry
|-- VERSION                          # Current semantic version
|-- config/                          # Local runtime configuration
|-- cache/                           # Conversations, plans, doc indexes, diagnostics, users/
|-- Doc/                             # Offline Houdini and domain knowledge bases
|-- plugins/                         # Community plugin directory
|-- rules/                           # File-based user rules
|-- shared/                          # Shared path/config utilities (per-user isolation)
|-- houdini_agent/
|   |-- main.py                      # show_tool() and window lifecycle
|   |-- core/                        # Main window, agent runner, plans, harness
|   |-- ui/                          # Chat UI, widgets, i18n, theme, login dialog
|   |-- skills/                      # Built-in analysis skills
|   `-- utils/                       # AI client, tool registry, docs, memory, plugins
`-- tests/                           # Unit and smoke tests
```

## Troubleshooting

- **Tool does not launch** — verify `sys.path` points to the repo root; use `houdini_agent_launcher.py`; test in Houdini Python Shell first.
- **API key / 401 errors** — check the selected provider; re-enter the key from the overflow menu or reset the env var; restart Houdini after changing user env vars.
- **Tool blocked** — Ask mode blocks mutating tools by design; risky tools may require confirmation or be denied by Harness policy; switch to Agent mode to modify the scene.
- **Images ignored** — confirm the model supports vision; old images in history may be auto-stripped for context limits.
- **Plan mode stops early** — auto-resume handles incomplete plans; if it still stops, switch to Agent mode and ask it to continue from the last completed step.

## Development

```powershell
python -m pytest tests -q
```

For Houdini-specific behavior, prefer Houdini's bundled Python or `hython`. Dev hot reload: `$env:HOUDINI_AGENT_DEV_RELOAD = "1"`.

The updater framework is preserved in [houdini_agent/utils/updater.py](houdini_agent/utils/updater.py) but the user-facing update UI is disabled — treat it as infrastructure, not an enabled update path.

## Author

KazamaSuichiku (upstream) · fork adaptations by yangdi

## License

MIT
