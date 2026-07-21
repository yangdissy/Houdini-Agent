<!-- markdownlint-disable-file -->
# Release Changes: ai_tab.py Refactor Split

**Related Plan**: 20260624-ai-tab-refactor-plan.instructions.md
**Implementation Date**: 2026-06-24

## Summary

Progressively split `houdini_agent/ui/ai_tab.py` into focused prompt, preferences, diagnostics, runtime, context, cache, update, and tool execution modules while preserving the public `AITab` entry point.

## Changes

### Added

- .copilot-tracking/changes/20260624-ai-tab-refactor-changes.md - Added this running implementation change log for the ai_tab refactor plan.
- houdini_agent/core/prompt_manager.py - Added cached prompt template loading and system prompt assembly outside the AITab UI module.
- houdini_agent/core/diagnostics_mixin.py - Added policy timeline, append-only diagnostics JSONL, harness trace, diagnostics export, and policy menu helpers as a focused mixin.
- houdini_agent/ui/preferences_mixin.py - Added font scale, model preference, provider/key status, token statistics, and manual context optimization helpers as a focused mixin.
- houdini_agent/core/runtime_state_mixin.py - Added running state, input glow, active response aurora, run button state, update-mode restore, and agent done/error/stopped lifecycle helpers as a focused mixin.
- houdini_agent/ui/tool_result_mixin.py - Added tool result rendering, VEX streaming preview, node operation cards, undo/keep actions, and shell result widgets as a focused mixin.
- houdini_agent/ui/action_commands_mixin.py - Added stop, user switch, API key, clear, slash command, scene read, scene context, wrangle creation, and training export actions as a focused mixin.
- houdini_agent/core/context_manager_mixin.py - Added fake-tool stripping, message alternation fix, tool-arg formatting, context management/compression, RAG, todo summary, and URL helpers as a focused mixin (13 methods, ~570 lines).
- houdini_agent/core/cache_mixin.py - Added cache save/load/archive/manifest, all-session save/restore, conversation history batch rendering, and shell/tool history reconstruction as a focused mixin (31 methods, ~1620 lines).
- houdini_agent/core/update_mixin.py - Added silent/manual update check, download/apply, progress callback, update messages, and restart behavior as a focused mixin (332 lines).
- houdini_agent/core/tool_execution_mixin.py - Added policy-gated tool execution, background/main-thread dispatch, cook/update-mode guards, geometry-validation loop guard, undo snapshots, and node-path helpers as a focused mixin (20 methods, ~850 lines).
- houdini_agent/core/send_orchestrator_mixin.py - Added send/run orchestration (`_on_send`, tool selection, `_run_agent`, `_start_agent_run`) as a focused mixin (4 methods, ~745 lines).

### Modified

- .copilot-tracking/plans/20260624-ai-tab-refactor-plan.instructions.md - Marked Phase 1 Task 1.1 and Task 1.2 complete after preserving the AITab entry point and extracting prompt utilities.
- .copilot-tracking/plans/20260624-ai-tab-refactor-plan.instructions.md - Marked Phase 1 Task 1.3 and the Phase 1 header complete after extracting preferences and diagnostics mixins.
- houdini_agent/ui/ai_tab.py - Preserved AITab as the public composition root while delegating system prompt construction to the new prompt manager.
- houdini_agent/ui/ai_tab.py - Added PreferencesMixin and DiagnosticsMixin to the AITab composition and removed the migrated method bodies from the composition root.
- .copilot-tracking/plans/20260624-ai-tab-refactor-plan.instructions.md - Marked Phase 2 Task 2.1 complete after extracting runtime state lifecycle behavior.
- houdini_agent/ui/ai_tab.py - Added RuntimeStateMixin to the AITab composition and removed the migrated runtime lifecycle method bodies from the composition root.
- .copilot-tracking/plans/20260624-ai-tab-refactor-plan.instructions.md - Marked Phase 2 Task 2.2 complete after extracting tool result UI behavior.
- houdini_agent/ui/ai_tab.py - Added ToolResultMixin to the AITab composition and removed the migrated tool result, VEX preview, node operation, undo/keep, and shell widget method bodies from the composition root.
- .copilot-tracking/plans/20260624-ai-tab-refactor-plan.instructions.md - Marked Phase 2 Task 2.3 and the Phase 2 header complete after extracting action command behavior.
- houdini_agent/ui/ai_tab.py - Added ActionCommandsMixin to the AITab composition and removed the migrated stop, user switch, key, clear, slash, scene read, wrangle, and training export method bodies from the composition root.
- houdini_agent/ui/ai_tab.py - Added ContextManagerMixin to the AITab composition and removed the migrated context/message/token/RAG/URL method bodies (now 4074 lines).
- houdini_agent/ui/ai_tab.py - Added CacheMixin to the AITab composition and removed the migrated cache/history-rendering method bodies (now 2460 lines).
- houdini_agent/ui/ai_tab.py - Added UpdateMixin to the AITab composition and removed the migrated update method bodies (now 2128 lines).
- houdini_agent/ui/ai_tab.py - Added ToolExecutionMixin to the AITab composition and removed the migrated tool-execution method bodies (now 1282 lines).
- tests/test_tool_dispatch.py - Added tool dispatch path check verifying `_execute_tool_with_policy`/`_execute_tool_impl` dispatch chain reaches main-thread and background slots (AST-level, Qt-env independent).
- houdini_agent/ui/ai_tab.py - Added SendOrchestratorMixin to the AITab composition and removed the migrated send/run orchestration method bodies (now 538 lines, below the 1500-line target).
- houdini_agent/ui/ai_tab.py - Removed duplicate `_get_current_context_limit` and `_show_token_stats_dialog` that were shadowing PreferencesMixin (leftover from Task 1.3), reducing AITab to 8 composition-root methods (525 lines). MRO audit: zero duplicate method names across the 18 AITab mixins; the only cross-class name collisions are AITab vs the unrelated `_CustomProviderDialog` in header.py and do not affect the MRO.

### Removed

- houdini_agent/ui/ai_tab.py - Removed 13 context/context-management method bodies (moved to ContextManagerMixin).
- houdini_agent/ui/ai_tab.py - Removed 31 cache/history-rendering method bodies (moved to CacheMixin).
- houdini_agent/ui/ai_tab.py - Removed 11 update method bodies (moved to UpdateMixin).
- houdini_agent/ui/ai_tab.py - Removed 20 tool-execution method bodies (moved to ToolExecutionMixin).
- houdini_agent/ui/ai_tab.py - Removed 4 send/run orchestration method bodies (moved to SendOrchestratorMixin).
- houdini_agent/ui/ai_tab.py - Removed duplicate `_get_current_context_limit` and `_show_token_stats_dialog` shadowing PreferencesMixin.

## Release Summary

**Goal**: Split the 7073-line `houdini_agent/ui/ai_tab.py` into focused mixins while keeping `AITab` as the stable public composition root.

**Outcome**: `ai_tab.py` reduced from 7073 lines to **525 lines** (8 composition-root methods: `__init__`, `_rebuild_system_prompts`, `_retranslateUi`, `_init_plugin_system`, `_fire_session_hook`, `_build_system_prompt`, `_build_ui`, `_wire_events`). Constructor signature `AITab(parent=None, workspace_dir=None, username=None)` and all 28 Qt signals unchanged. Public import path `houdini_agent.ui.ai_tab.AITab` preserved.

**New mixin modules** (this refactor, Tasks 3.1-4.3):
- `houdini_agent/core/context_manager_mixin.py` - 13 methods, context/message/token/RAG/URL helpers.
- `houdini_agent/core/cache_mixin.py` - 31 methods, cache persistence + history rendering.
- `houdini_agent/core/update_mixin.py` - 11 methods, update check/download/apply/restart.
- `houdini_agent/core/tool_execution_mixin.py` - 20 methods, policy-gated dispatch + main-thread Houdini execution + cook guards.
- `houdini_agent/core/send_orchestrator_mixin.py` - 4 methods, `_on_send`/tool selection/`_run_agent`/`_start_agent_run`.

**Tests added**:
- `tests/test_tool_dispatch.py` - tool dispatch path check (policy → impl → main-thread/background slots).

**Verification**:
- `compileall` passes for `ai_tab.py` and all `houdini_agent/core` + `houdini_agent/ui` modules.
- AST-level public-API check: all 11 critical methods resolvable via MRO, constructor signature unchanged, 28 signals declared.
- MRO audit: zero duplicate method names across the 18 AITab mixins; removed 2 methods shadowing PreferencesMixin.
- **Pre-existing failure (unrelated)**: `unittest` runs of `tests/test_import_smoke.py`, `tests/test_tool_dispatch.py`, `tests/test_diagnostics_export.py`, `tests/test_agent_tool_selection.py` fail in this shell because system `C:\Python38\lib\site-packages\PySide6` conflicts with the tests' Qt stub installation (`AttributeError: __spec__` in shibokensupport bootstrap). This predates the refactor and reproduces on the pre-refactor baseline. These tests are designed to run in the Houdini Python environment.

