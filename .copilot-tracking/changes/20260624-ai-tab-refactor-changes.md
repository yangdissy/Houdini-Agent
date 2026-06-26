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

### Removed

