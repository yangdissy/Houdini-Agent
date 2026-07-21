<!-- markdownlint-disable-file -->

# Task Details: ai_tab.py Refactor Split

## Research Reference

**Source Research**: #file:../research/20260624-ai-tab-refactor-research.md

## Phase 1: Preserve AITab Entry Point And Extract Low-Risk Helpers

### Task 1.1: Keep AITab as the public composition root

Keep `houdini_agent/ui/ai_tab.py` as the stable module exporting `AITab`. The file should continue to own class declaration, Qt signal declarations, constructor signature, and top-level composition while implementation methods move into mixins.

- **Files**:
  - `houdini_agent/ui/ai_tab.py` - keep `AITab` public class and constructor stable.
- **Success**:
  - `from houdini_agent.ui.ai_tab import AITab` still works.
  - `AITab(parent=None, workspace_dir=None, username=None)` signature is unchanged.
  - Signal declarations remain available on `AITab`.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 48-53) - external import sites.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 134-143) - behavior contracts.
- **Dependencies**:
  - Research validation complete.

### Task 1.2: Extract prompt utilities

Move module-level prompt template globals and loading helper out of `ai_tab.py` without changing `_build_system_prompt` behavior.

- **Files**:
  - `houdini_agent/core/prompt_manager.py` - `_PROMPTS_DIR`, `_PROMPT_TEMPLATE_CACHE`, `_CORE_RULES_FALLBACK`, `_load_prompt_template` or public equivalents.
  - `houdini_agent/ui/ai_tab.py` - import prompt helpers from the new module.
- **Success**:
  - Full and core system prompt fallback behavior remains unchanged.
  - Prompt template missing-file fallback still prints and returns empty text.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 59-61) - prompt responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 75-79) - prompt line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 99-99) - recommended prompt module.
- **Dependencies**:
  - Task 1.1 entry point preserved.

### Task 1.3: Extract preferences and diagnostics mixins

Move low-risk preference/statistics and diagnostics/policy UI methods into focused mixins. Keep imports and lazy exception handling intact.

- **Files**:
  - `houdini_agent/ui/preferences_mixin.py` - font zoom/settings, provider/model preference, key status, context/token stats, token stats dialog, optimize menu/manual optimization.
  - `houdini_agent/core/diagnostics_mixin.py` - policy timeline, diagnostics JSONL append/export, harness trace append, diagnostics payload, policy menu/dialog.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixins and remove moved methods.
- **Success**:
  - Token stats button and dialog still work.
  - Provider/key status and model preference restore still work.
  - Policy timeline and diagnostics export keep append-only JSONL behavior.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 63-65) - preferences and diagnostics responsibilities.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 81-82) - line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 103-107) - recommended modules.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 140-140) - diagnostics behavior contract.
- **Dependencies**:
  - Task 1.1 entry point preserved.

## Phase 2: Extract Runtime And UI Action Domains

### Task 2.1: Extract runtime state lifecycle mixin

Move running state, animation helpers, run button state, and done/error/stop lifecycle handlers into a runtime mixin.

- **Files**:
  - `houdini_agent/core/runtime_state_mixin.py` - `_set_running`, animation helpers, `_update_run_buttons`, `_on_agent_done`, `_on_agent_error`, `_on_agent_stopped`, `_ensure_history_ends_with_assistant`.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Agent session anchoring to `_agent_session_id` is preserved.
  - Running tab indicator, stop/send button visibility, thinking timer, aurora, and glow behavior remain unchanged.
  - Done/error/stopped paths still finalize responses and restore update mode.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 66-66) - runtime responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 83-84) - runtime line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 100-100) - recommended runtime module.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 138-139) - threading/session behavior contracts.
- **Dependencies**:
  - Phase 1 complete.

### Task 2.2: Extract tool result UI mixin

Move UI rendering for tool results, VEX streaming previews, node operation cards, undo/keep actions, and shell result widgets.

- **Files**:
  - `houdini_agent/ui/tool_result_mixin.py` - tool result UI, VEX preview, node operation UI, navigation, undo/keep actions, shell widget insertion.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Tool result cards still update the active `AIResponse`.
  - VEX streaming preview still appears and finalizes.
  - Node operation undo/keep and batch bar behavior remain unchanged.
  - Python/System shell widgets still attach to the active response.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 69-69) - tool result UI responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 88-88) - line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 105-105) - recommended module.
- **Dependencies**:
  - Phase 1 complete.

### Task 2.3: Extract action command mixin

Move UI actions that are not part of startup composition: stop, user switching, API key, clear, slash commands, scene read actions, scene context collection, create wrangle, and training export.

- **Files**:
  - `houdini_agent/ui/action_commands_mixin.py` - stop/user switch/key/clear/slash/read/scene/wrangle/export actions.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Slash commands keep existing command behavior.
  - Read network/selection and auto scene context still inject the same content.
  - User switch behavior still waits for running agent stop when needed.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 69-69) - action/UI responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 89-89) - action line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 106-106) - recommended action module.
- **Dependencies**:
  - Phase 1 complete.

## Phase 3: Extract Context And Cache Domains

### Task 3.1: Extract context manager mixin

Move token estimation, message cleanup, fake tool stripping, context compression, RAG, URL handling, and todo summary helpers into a context manager mixin.

- **Files**:
  - `houdini_agent/core/context_manager_mixin.py` - context/message/token/RAG/URL helpers.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Message alternation and fake tool result cleanup are unchanged.
  - Context compression still only compresses/removes the intended rounds/tool outputs.
  - RAG and URL processing still inject the same helper content.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 68-68) - context responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 86-87) - context/run line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 102-102) - recommended module.
- **Dependencies**:
  - Phase 2 complete.

### Task 3.2: Extract cache and history rendering mixin

Move cache save/load/archive/manifest restore and batched history rendering into a cache/history mixin.

- **Files**:
  - `houdini_agent/core/cache_mixin.py` - cache persistence, manifest, session restore, history rendering, shell/tool history reconstruction.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Session save/load compatibility is preserved.
  - Existing cache files still restore conversation history, todo state, shell widgets, and tool summaries.
  - Batched rendering still respects batch sizes and final scroll behavior.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 70-70) - cache/history responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 90-91) - cache/history line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 104-104) - recommended module.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 142-142) - cache/history behavior contract.
- **Dependencies**:
  - Task 3.1 complete.

## Phase 4: Extract Tool Execution And Update Domains

### Task 4.1: Extract update mixin

Move update check, download/apply, progress callback, update messages, and restart behavior into an update mixin.

- **Files**:
  - `houdini_agent/core/update_mixin.py` - update check/download/apply/progress/restart methods and update signals if signal placement remains compatible.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - Silent update check remains disabled unless currently enabled by caller.
  - Manual update check, progress updates, and restart behavior remain unchanged.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 71-71) - update responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 93-93) - update line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 108-108) - recommended module.
- **Dependencies**:
  - Phase 1 complete.

### Task 4.2: Extract tool execution mixin last

Move policy-gated tool execution, background/main-thread dispatch, cook/update-mode guards, undo snapshots, node path collection, and main-thread execution slot after lower-risk modules are stable.

- **Files**:
  - `houdini_agent/core/tool_execution_mixin.py` - tool execution policy, dispatch, thread queue, cook guards, undo snapshots, node path helpers, main-thread slots, tool constants.
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Success**:
  - `BlockingQueuedConnection` result queue semantics are unchanged.
  - Ask/Agent/Plan guard behavior and confirm mode are unchanged.
  - Houdini update-mode restoration, cook guards, undo groups, and snapshot diff behavior are unchanged.
  - Diagnostics for tool policy and tool results continue to append records.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 67-67) - tool execution responsibility.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 84-85) - tool execution line evidence.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 101-101) - recommended module.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 117-120) - risk and dependency guidance.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 138-141) - thread/safety behavior contracts.
- **Dependencies**:
  - Phases 1-3 complete.
  - Diagnostics mixin available.
  - Runtime state mixin available.

### Task 4.3: Extract send orchestration mixin

Move the send/run orchestration block — `_on_send`, tool selection, and `_run_agent` (originally lines 3001-3724, the largest remaining mixed block) — into a dedicated mixin. This block is NOT covered by Tasks 3.1 (context helpers only) or 4.2 (policy/dispatch only); it must not be left behind or absorbed silently.

- **Files**:
  - `houdini_agent/core/send_orchestrator_mixin.py` - `_on_send`, tool selection, `_run_agent` and its direct private helpers. (Alternative: merge into existing `houdini_agent/core/agent_runner.py` if the added size stays under ~800 lines — decide before starting, not during.)
  - `houdini_agent/ui/ai_tab.py` - inherit the new mixin and remove moved methods.
- **Expected budget**: ~700 lines moved out of `ai_tab.py`.
- **Success**:
  - `_on_send` / `_run_agent` no longer exist in `ai_tab.py`.
  - `_agent_session_id` anchoring still routes background callbacks to the correct session.
  - Streaming, tool calls, and Plan-mode paths through `_run_agent` are unchanged.
  - Import smoke test and `compileall` pass immediately after this task.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md - Key Line Evidence: lines 3001-3724 send/tool-selection/`_run_agent` block.
  - #file:../research/20260624-ai-tab-refactor-research.md - Migration Strategy: move leaf domains before the large `_run_agent` block.
- **Dependencies**:
  - Task 3.1 (context manager mixin) complete — `_run_agent` depends on context helpers.
  - Task 4.2 (tool execution mixin) complete — `_run_agent` calls tool dispatch.

## Phase 5: Verify And Clean Composition Root

### Task 5.1: Reduce ai_tab.py to composition root

After extraction, keep `ai_tab.py` focused on imports, signal declarations, constructor state setup, `_build_system_prompt` if not moved, `_build_ui`, `_wire_events`, and inheritance composition.

- **Files**:
  - `houdini_agent/ui/ai_tab.py` - remove moved method bodies and update inheritance/imports.
- **Success**:
  - `ai_tab.py` is substantially smaller and only coordinates mixins.
  - Inheritance order is deliberate and no method resolution conflicts occur.
  - Existing tests import `AITab` unchanged.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 110-110) - composition root target.
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 122-132) - staged migration strategy.
- **Dependencies**:
  - Phase 4 complete.

### Task 5.2: Run focused verification

Run import, compile, and targeted existing tests after the split.

- **Files**:
  - `houdini_agent/ui/ai_tab.py` - final import smoke test.
  - `houdini_agent/core/*_mixin.py` and `houdini_agent/ui/*_mixin.py` - compile targets.
  - `tests/test_agent_tool_selection.py` - targeted behavior test.
  - `tests/test_diagnostics_export.py` - diagnostics behavior test.
- **Success**:
  - Import smoke test for `AITab` passes.
  - `compileall` passes for affected modules.
  - Targeted tests pass or report only unrelated pre-existing failures.
- **Research References**:
  - #file:../research/20260624-ai-tab-refactor-research.md (Lines 145-150) - verification guidance.
- **Dependencies**:
  - Task 5.1 complete.

## Dependencies

- Existing mixin architecture in `houdini_agent/ui` and `houdini_agent/core`.
- Existing `AITab` public import path.
- Existing Qt compatibility layer and signal behavior.
- Existing diagnostics and agent safety behavior.
- No new third-party dependencies.

## Success Criteria

- `AITab` remains import-compatible and constructor-compatible.
- `ai_tab.py` becomes a smaller composition root rather than a 7000-line mixed implementation file.
- New focused mixins contain migrated behavior without rewrites.
- Agent safety, main-thread execution, diagnostics audit, session anchoring, cache formats, and history restore behavior are preserved.
- Import smoke test, compile check, and targeted tests pass or have documented unrelated failures.