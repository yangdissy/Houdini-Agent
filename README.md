# Houdini Agent

**[English](README.md)** | **[中文](README_CN.md)**

Houdini Agent is an AI assistant that runs inside the SideFX Houdini process. It operates directly on the scene graph: reading nodes, building networks, modifying parameters, running VEX, and searching documentation — instead of generating code for you to copy-paste.

Current version: `1.5.3`

## Project Scope

This repository is based on the upstream v1.5.x embedded-Houdini branch and retains its natural-language scene operations, node editing, VEX, documentation search, and Ask/Agent/Plan fundamentals. For original features, use cases, and general documentation, see the [upstream project](https://github.com/Kazama-Suichiku/Houdini-Agent). This README focuses on this fork's installation differences, production enhancements, and recent changes.

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

## Main Features of This Fork

Upstream fundamentals such as node operations, scene inspection, VEX/Python, built-in Skills, basic Plan mode, provider support, and vision input are not repeated here; see the [upstream documentation](https://github.com/Kazama-Suichiku/Houdini-Agent). The following are the enhancements actively maintained by this fork.

### Long-term Memory
Three-layer storage (semantic/episodic/procedural) with reward-driven learning and reflection, isolated per user and retained across Houdini restarts.

- Use `/remember <content>` to explicitly save a preference, rule, or method; the model may also call `remember_memory` when you clearly ask it to remember something
- The proposed content is shown for human confirmation before writing; Ask mode, ordinary Q&A, and recall questions do not trigger writes
- `/memory` shows memory status, while `/memories` opens the long-term memory manager for filtering, editing, and deleting records
- Responses that executed tools offer Good/Bad feedback to strengthen or weaken the corresponding task experience
- The authoritative personal database is `cache/users/<username>/memory/agent_memory.db`; legacy leftovers are safely restored or surfaced as conflicts

### Team Memory
Members can explicitly publish eligible semantic/procedural experience for an administrator to rebuild into the shared knowledge base. Imports validate document version, contributor identity, resource limits, embedding metadata, and sharing eligibility. Corrupt or entirely invalid exports cannot replace an existing team database, while rebuilding after all exports are withdrawn correctly clears stale shared data.

### Context Compression
Choose `Aggressive`, `Balanced`, or `Conservative` from the top-right menu → Context Compression. The selected strategy controls both manual compression and automatic pruning: aggressive mode frees more context, while conservative mode preserves more recent conversation. Tool calls and their results remain protected as complete rounds.

### Plugins, Rules, and UI
Supports community plugins, persistent Markdown rules, and an in-panel Rules editor, together with multi-session chat, streaming output, Plan/confirmation cards, clickable node paths, token statistics, slash-command completion, and bilingual CN/EN UI.

### Visual Review
Vision-capable models can use the governed `visual_review` tool after technical validation of modeling, material, lighting, camera, composition, or USD lookdev work. The review keeps network/geometry facts separate from image observations and does not modify the scene, camera, or viewport state. Non-vision models do not receive this tool.

### Reliable Session & Plan Recovery
Session files are committed transactionally with manifest-last publication and rollback on failure. Empty-workspace markers prevent stale conversations from reappearing, stale windows cannot overwrite a newly switched user, and Plan state is restored per session without auto-completing unverified steps.

## Fork Differences

This project is a fork of [Kazama-Suichiku/Houdini-Agent](https://github.com/Kazama-Suichiku/Houdini-Agent), based on its v1.5.x embedded-in-Houdini branch. It does not follow upstream's v2.0 standalone desktop app direction.

This fork retains the embedded, scene-operating product direction while deepening multi-user isolation, long-running reliability, and production safety. Key differences include:

### Multi-user Data Isolation

- The login identity determines storage boundaries for settings, sessions, Plans, rules, and personal memory, with an administrator-managed user allowlist.
- After a user switch, stale panel instances lose workspace write authority and cannot overwrite the new user's data.
- The authoritative personal memory database is `cache/users/<username>/memory/agent_memory.db`. SQLite data left in the former location can be safely restored at startup, with conflicts resolved explicitly by the user.

### Tool Governance and Execution Safety

- Tool Registry is the sole authority for schemas, handlers, owners, enabled state, modes, and risk metadata. Plugin and MCP tools cannot bypass it.
- Before execution, Harness applies argument normalization, risk evaluation, and `allow` / `deny` / `ask` / `retry` decisions. Every batch item traverses the same policy chain independently.
- Scene, file, and long-term-memory mutations support human confirmation. Confirmation timeout, callback failure, policy ambiguity, and authorization failure all fail closed.
- Main-thread execution, Cook Guard, undo semantics, result sanitization, and append-only auditing are coordinated at one governed execution boundary.

### Session and Plan Reliability

- Session workspaces use staging, per-file publication, manifest-last commit, and rollback to prevent partially updated state after exit or shared-drive failures.
- Clear markers prevent deleted sessions from returning through orphaned files, and Agent results always return to the session that initiated the request.
- Plan approval, rejection, step state, and restored UI projection are driven by persisted state. A `running` step never becomes `done` without completion evidence.
- The Plan quality gate accepts only tools currently enabled in Registry for the relevant mode and runtime.

### Context and Model Requests

- Normal send, manual compression, and HTTP 413 recovery share round-safe pruning that never splits an assistant tool call from its result.
- `Aggressive`, `Balanced`, and `Conservative` control both automatic target utilization and recent-round protection, rather than being UI-only choices.
- Tool schemas count toward the final token budget. Current-turn images are protected while older images may be removed to meet the budget.
- The current user message is captured at the send boundary, so background Harness checks cannot accidentally read stale intent from mutable history.

### Personal Memory, Feedback, and Team Memory

- Explicit memory is available through `/remember` and `remember_memory`. Writes require clear current-turn intent, sensitive-data validation, deduplication, a per-request call limit, and human confirmation.
- Manually pinned L0 memories take priority over automatically learned experience. The memory manager supports viewing, filtering, editing, and deleting semantic, episodic, and procedural records.
- Tool-using responses offer Good/Bad feedback that directly updates episodic reward, importance, and tags.
- Team Memory uses versioned export documents and one shared eligibility policy, validating contributor identity, resource limits, vector provenance, and entry structure.
- If every discovered export is invalid, the live team database is preserved. If all members withdraw their exports, rebuilding publishes an empty database so stale shared experience does not persist indefinitely.

### Plugins, Rules, and Documentation Retrieval

- Initial plugin load, re-enable, and reload share one registration path. A failed load rolls back hooks, tools, and buttons by owner instead of leaving partial registration behind.
- The Rules editor manages user and file-backed rules and displays their actual on-disk source paths.
- Offline Houdini Help is read through a shared Help Source. Retrieval uses multi-factor scoring, query-type reranking, and diversity constraints.
- Local documentation covers Houdini nodes, VEX, HOM, Labs, Terrain, Copernicus, ML, and MPM with unified cache invalidation.

### Host Compatibility and UI

- The embedded Qt/PySide panel and Houdini main-thread execution model remain intact; this fork does not adopt upstream v2.0's standalone desktop architecture.
- Additional protections cover Houdini-hosted Qt/GPU lifecycle issues, IME input, long cooks, widget destruction, and development hot reload.
- The UI provides multi-session chat, mode switching, Plan cards, tool status, confirmation cards, memory management, slash-command completion, and bilingual CN/EN presentation.

### Recent Updates (August 2026)

- **Aug 17–18:** Deepened transactional session persistence, Plan lifecycle correctness, the Registry/Harness execution chain, memory embedding provenance, context budgeting, and plugin rollback.
- **Aug 19–24:** Added explicit core memory, the long-term memory manager, pre-write confirmation, user-feedback rewards, personal database recovery, and slash-command parsing.
- **Aug 25:** Hardened the Team Memory export-document trust boundary, made automatic pruning follow the selected strategy, and fixed memory-manager layouts, rule source paths, and send-boundary user-message capture.

Latest update: [2026-08-25 Team Memory, explicit memory, and context compression](changelog/CHANGELOG_2026-08-25.md). Full change history in [changelog/](changelog/).

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
- Explicit saves require `/remember <content>` or a clear request to remember/save permanently, followed by approval in the confirmation card
- The personal memory database should be at `cache/users/<username>/memory/agent_memory.db`

**Team Memory rebuild fails**
- Check that member exports use a supported schema and that each document username matches its scanned contributor
- If export files are found but all are invalid, the existing Team Memory database is preserved by design
- The rebuild result dialog reports rejected files, invalid entries, and entries that are valid but ineligible for sharing

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
