<!-- markdownlint-disable-file -->

# Research: ai_tab.py Refactor Split

## Task

Assess whether `houdini_agent/ui/ai_tab.py` can be split further, define a low-risk module layout, and prepare implementation guidance for a later refactor.

## Research Status

Verified. Research was performed against the current workspace on 2026-06-24. No prior `.copilot-tracking/research/*ai-tab*research.md` or `.copilot-tracking/research/*ai_tab*research.md` files existed, so this research file is the source of truth for the planning files.

## Tool Usage And Verified Findings

- Read the active `houdini_agent/ui/ai_tab.py` context and extracted method/class structure with PowerShell `Select-String` because `rg` is unavailable in the current PowerShell environment.
- Verified `houdini_agent/ui/ai_tab.py` has 7073 lines.
- Searched Python import sites for `AITab` and `ai_tab` references, excluding `lib`, `.git`, and large cache directories.
- Read and indexed existing split modules in `houdini_agent/ui` and `houdini_agent/core` to avoid proposing duplicate work.
- Counted related UI/core module sizes to understand existing local conventions.
- Fetched Python module documentation from `https://docs.python.org/3/tutorial/modules.html`; it supports splitting larger programs into modules and packages.

## Existing Split Architecture

`ai_tab.py` already declares an incremental split architecture in its file header and currently inherits these mixins:

- `HeaderMixin` from `houdini_agent/ui/header.py`.
- `InputAreaMixin` from `houdini_agent/ui/input_area.py`.
- `ChatViewMixin` from `houdini_agent/ui/chat_view.py`.
- `ImageMixin` from `houdini_agent/ui/image_mixin.py`.
- `StreamingParserMixin` from `houdini_agent/core/streaming_parser.py`.
- `MemoryMixin` from `houdini_agent/core/memory_mixin.py`.
- `PlanMixin` from `houdini_agent/core/plan_mixin.py`.
- `AgentRunnerMixin` from `houdini_agent/core/agent_runner.py`.
- `SessionManagerMixin` from `houdini_agent/core/session_manager.py`.

Existing module sizes show that new focused mixins are consistent with the project:

- `houdini_agent/core/agent_runner.py`: 201 lines.
- `houdini_agent/core/memory_mixin.py`: 291 lines.
- `houdini_agent/core/plan_mixin.py`: 424 lines.
- `houdini_agent/core/session_manager.py`: 337 lines.
- `houdini_agent/core/streaming_parser.py`: 342 lines.
- `houdini_agent/ui/header.py`: 719 lines.
- `houdini_agent/ui/input_area.py`: 412 lines.
- `houdini_agent/ui/chat_view.py`: 109 lines.
- `houdini_agent/ui/image_mixin.py`: 249 lines.

## External Import Sites

- `houdini_agent/core/main_window.py` imports `AITab` from `houdini_agent.ui.ai_tab` and constructs it in two places.
- `tests/test_agent_tool_selection.py` imports `AITab` from `houdini_agent.ui.ai_tab`.
- `tests/test_diagnostics_export.py` imports `AITab` from `houdini_agent.ui.ai_tab`.
- No broad external imports of internal helper functions were found. The `AITab` class and constructor signature should remain stable.

## ai_tab.py Responsibility Map

The file is already partly decomposed, but still mixes these responsibilities:

- Module-level prompt loading and core prompt fallback: `_PROMPTS_DIR`, `_PROMPT_TEMPLATE_CACHE`, `_CORE_RULES_FALLBACK`, `_load_prompt_template`.
- `AITab` composition, signal declarations, constructor state initialization, signal wiring, and top-level UI assembly.
- System prompt rebuild/retranslation and prompt construction.
- Plugin hook initialization and session hook firing.
- Theme/font/model preference and provider/key status management.
- Token and context stat UI updates.
- Policy timeline, diagnostics JSONL, diagnostics export, and harness trace persistence.
- Agent running lifecycle and UI state: `_set_running`, glow/aurora animation, run button state, done/error/stopped handling.
- Houdini main-thread tool execution, cook/update-mode guards, undo snapshots, node operation tracking, and policy gate wrapping.
- Message cleanup, message alternation, fake tool result stripping, context compression, RAG injection, URL handling, and agent send/run orchestration.
- Tool result UI rendering, VEX streaming preview, node operation undo/keep, shell result widgets, slash commands, read network/selection, and create wrangle actions.
- Cache save/load/archive/manifest, all-session save/restore, conversation history batch rendering, old tool history rendering, and optimize menu.
- Silent/manual update check, download/apply, progress messages, and restart actions.

## Key Line Evidence In ai_tab.py

- Lines 14-87 contain broad imports for UI, core, memory, plan, user paths, threading, cache, JSON, and diagnostics concerns.
- Lines 90-124 define prompt template globals, core-rule fallback, and `_load_prompt_template`.
- Lines 127-169 define `AITab` inheritance and Qt signals.
- Lines 171-376 define constructor setup, runtime state, signal wiring, prompt cache building, UI construction, session restore, timers, plugin init, and language hooks.
- Lines 378-500 define prompt rebuild, UI retranslation, plugin hooks, session hook helper, and system prompt construction.
- Lines 502-615 define UI assembly, event wiring, font zoom, and font settings.
- Lines 619-842 define token estimation, context statistics, model preferences, provider/key status, token stats, and token dialog.
- Lines 845-1085 define policy timeline, diagnostics JSONL/path/export, harness trace persistence, diagnostics payload, and token reset.
- Lines 1096-1299 define provider helpers, running state, animation helpers, and run button state.
- Lines 1310-1729 define Houdini cook/update-mode guards and agent done/error/stopped lifecycle.
- Lines 1735-2433 define Todo updates, policy-gated tool execution, background/main-thread tool execution, undo/snapshot helpers, node path collection, and main-thread execution slot.
- Lines 2436-2996 define fake-tool detection, message alternation, tool-arg formatting, context management, compression, RAG, todo summary, URL extraction, and URL processing.
- Lines 3001-3724 define send handling, tool selection, and `_run_agent`; this is the largest remaining mixed block.
- Lines 3725-4524 define tool result UI, VEX preview, node operation UI, navigation, undo/keep, and shell widget insertion.
- Lines 4528-5055 define stop/user switch/key/clear/slash commands/read network/read selection/scene context/create wrangle actions.
- Lines 5070-6057 define training export, cache menus, cache data, save/load/restore/archive/session cache handling, and compression-to-summary.
- Lines 6061-6658 define batched history rendering and historical tool/shell reconstruction.
- Lines 6661-6734 define optimize menu and manual optimization.
- Lines 6737-7051 define update check/download/apply/progress/restart behavior.

## Recommended Module Split

Keep `AITab` in `houdini_agent/ui/ai_tab.py` as the composition root and public import target. Move remaining implementations into focused mixins/helpers:

- `houdini_agent/core/prompt_manager.py`: `_PROMPTS_DIR`, `_PROMPT_TEMPLATE_CACHE`, `_CORE_RULES_FALLBACK`, `_load_prompt_template`, and a small prompt-building helper if it can be done without pulling UI state.
- `houdini_agent/core/runtime_state_mixin.py`: `_set_running`, `_update_run_buttons`, `_start_input_glow`, `_stop_input_glow`, `_update_input_glow`, `_start_active_aurora`, `_stop_active_aurora`, `_on_agent_done`, `_on_agent_error`, `_on_agent_stopped`, `_ensure_history_ends_with_assistant`.
- `houdini_agent/core/tool_execution_mixin.py`: `_execute_tool_with_policy`, `_execute_tool_with_todo`, `_execute_tool_in_bg`, `_execute_tool_in_main_thread`, `_execute_tools_batch_in_main_thread`, `_on_execute_tool_batch_main_thread`, `_on_execute_tool_main_thread`, cook/update-mode helpers, snapshot/diff/node-path helpers, tool constants.
- `houdini_agent/core/context_manager_mixin.py`: `_estimate_tokens`, `_calculate_context_tokens`, `_fix_message_alternation`, `_strip_fake_tool_results`, `_split_and_compress_assistant`, `_format_tool_args_brief`, `_manage_context`, `_compress_context`, `_get_context_reminder`, `_auto_rag_retrieve`, URL helpers, todo summary helper.
- `houdini_agent/core/diagnostics_mixin.py`: policy timeline, diagnostics JSONL append/export, harness trace append, diagnostics payload, policy menu/dialog.
- `houdini_agent/core/cache_mixin.py`: cache data building, periodic save, atexit save, save/load/archive/list/manifest/all-session restore, history render helpers, shell/tool history reconstruction.
- `houdini_agent/ui/tool_result_mixin.py`: `_add_tool_result`, `_add_tool_result_ui`, `_add_collapsible_result`, VEX preview methods, node operation UI, navigation, undo/keep all, shell widget insertion.
- `houdini_agent/ui/action_commands_mixin.py`: stop, user switch, set key, clear, slash commands, read network/selection, scene context collection, create wrangle, export training data.
- `houdini_agent/ui/preferences_mixin.py`: font zoom/settings, provider/model preference, key status, context/token stats, token stats dialog, optimize menu/manual optimization.
- `houdini_agent/core/update_mixin.py`: silent/manual update check, update download/apply/progress callback, update status messages, restart.

After the split, `AITab` should become a composition root that mainly declares signals, initializes state that truly belongs at the whole-tab level, calls mixin setup methods, and keeps `_build_ui` / `_wire_events` if those remain small.

## Dependency Guidance

- Preserve `houdini_agent.ui.ai_tab.AITab` as the public import path and constructor API.
- Prefer mixins over service objects for the first refactor because the code already uses mixins and many methods access `self` state directly.
- Move leaf domains before the large `_run_agent` block. Do not attempt to rewrite `_run_agent` and tool execution in one pass.
- Tool execution and diagnostics are high-risk because they touch agent safety, policy decisions, audit records, Houdini main thread execution, and undo semantics. Move them with minimal edits only.
- Cache/history rendering can move as a later phase because it has many UI dependencies and restores old message formats.
- Keep lazy imports and `try/except` behavior intact, especially around Houdini `hou`, plugin hooks, diagnostics, and update operations.
- Avoid new dependencies; use current Python modules and project helpers only.

## Migration Strategy

Use staged extraction with no behavior rewrites:

1. Extract module-level prompt utilities to `prompt_manager.py`, leaving `AITab._build_system_prompt` behavior unchanged except import source.
2. Extract low-risk UI preferences and diagnostics mixins.
3. Extract runtime-state lifecycle mixin.
4. Extract tool-result/action command UI mixins.
5. Extract context-management helpers and cache/history mixins.
6. Extract tool execution mixin last, or split it into two smaller passes: policy/background dispatch first, Houdini main-thread slot second.
7. Keep `AITab` as the only public class in `ai_tab.py`; update inheritance order deliberately and run tests after each phase.

## Behavior Contracts To Preserve

- `AITab(parent=None, workspace_dir: Optional[Path] = None, username: Optional[str] = None)` constructor signature.
- All Qt signals currently declared on `AITab`, including tool execution, streaming, planning, update, and diagnostics-related signals.
- Main-thread Houdini execution via `BlockingQueuedConnection` and result queue semantics.
- `_agent_session_id` anchoring so background callbacks write to the correct session.
- Append-only diagnostics JSONL behavior and no logging of full prompt/message content in audit records.
- Ask/Agent/Plan mode safety gates and confirm-mode behavior.
- Cache save/load formats and historical conversation rendering behavior.
- Existing tests importing `AITab` from `houdini_agent.ui.ai_tab`.

## Verification Guidance

- Run a Python import smoke test for `from houdini_agent.ui.ai_tab import AITab`.
- Run targeted tests: `tests/test_agent_tool_selection.py` and `tests/test_diagnostics_export.py`.
- Compile affected modules with Python `compileall`.
- If Houdini/Qt runtime is available, manually verify: create/open tab, send Ask message, Agent tool call, Plan card, diagnostics export, session save/restore, history restore, policy menu, token stats, slash commands, and update menu.

## Decision

Yes, `ai_tab.py` can and should be split further. It is already using the correct mixin direction; the next safest step is to keep `AITab` as the stable public composition root and extract remaining domains into focused mixins without changing behavior.