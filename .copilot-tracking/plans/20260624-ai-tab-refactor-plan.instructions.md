---
applyTo: ".copilot-tracking/changes/20260624-ai-tab-refactor-changes.md"
---

<!-- markdownlint-disable-file -->

# Task Checklist: ai_tab.py Refactor Split

## Overview

Split the 7073-line `houdini_agent/ui/ai_tab.py` into focused mixins while preserving `houdini_agent.ui.ai_tab.AITab` as the stable public composition root.

## Objectives

- Keep `AITab` import path, constructor signature, and Qt signals stable.
- Move remaining large implementation domains from `ai_tab.py` into focused `core/*_mixin.py` and `ui/*_mixin.py` modules.
- Preserve agent safety, diagnostics audit behavior, main-thread Houdini execution, session anchoring, cache formats, and history rendering.
- Verify the split with import smoke checks, compile checks, and targeted existing tests.

## Research Summary

### Project Files

- `houdini_agent/ui/ai_tab.py` - current 7073-line composition and implementation file.
- `houdini_agent/core/main_window.py` - public consumer constructing `AITab`.
- `tests/test_agent_tool_selection.py` - targeted test importing `AITab`.
- `tests/test_diagnostics_export.py` - targeted diagnostics test importing `AITab`.
- `houdini_agent/ui/header.py`, `houdini_agent/ui/input_area.py`, `houdini_agent/ui/chat_view.py`, `houdini_agent/ui/image_mixin.py` - existing UI mixin pattern.
- `houdini_agent/core/streaming_parser.py`, `houdini_agent/core/memory_mixin.py`, `houdini_agent/core/plan_mixin.py`, `houdini_agent/core/agent_runner.py`, `houdini_agent/core/session_manager.py` - existing core mixin pattern.

### External References

- #file:../research/20260624-ai-tab-refactor-research.md - validated workspace research for source structure, imports, split boundaries, and verification.
- #fetch:https://docs.python.org/3/tutorial/modules.html - Python module/package guidance supporting splitting larger programs into modules.

### Standards References

- #file:../../.github/instructions/agent-safety.instructions.md - safety constraints for policy gates, tool calls, and diagnostics audit behavior.
- #file:../../.github/instructions/python-mcp-server.instructions.md - Python project conventions when touching Python files.

## Implementation Checklist

### [x] Phase 1: Preserve AITab Entry Point And Extract Low-Risk Helpers

- [x] Task 1.1: Keep AITab as the public composition root

  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 11-25)

- [x] Task 1.2: Extract prompt utilities
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 27-42)

- [x] Task 1.3: Extract preferences and diagnostics mixins
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 44-62)

### [x] Phase 2: Extract Runtime And UI Action Domains

- [x] Task 2.1: Extract runtime state lifecycle mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 66-83)

- [x] Task 2.2: Extract tool result UI mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 85-102)

- [x] Task 2.3: Extract action command mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 104-120)

### [ ] Phase 3: Extract Context And Cache Domains

- [ ] Task 3.1: Extract context manager mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 124-140)

- [ ] Task 3.2: Extract cache and history rendering mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 142-159)

### [ ] Phase 4: Extract Tool Execution And Update Domains

- [ ] Task 4.1: Extract update mixin
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 163-178)

- [ ] Task 4.2: Extract tool execution mixin last
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 180-201)

### [ ] Phase 5: Verify And Clean Composition Root

- [ ] Task 5.1: Reduce ai_tab.py to composition root
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 205-219)

- [ ] Task 5.2: Run focused verification
  - Details: .copilot-tracking/details/20260624-ai-tab-refactor-details.md (Lines 221-237)

## Dependencies

- Existing mixin architecture in `houdini_agent/ui` and `houdini_agent/core`.
- Existing `AITab` public import path.
- Existing Qt compatibility layer and signal behavior.
- Existing diagnostics and agent safety behavior.
- No new third-party dependencies.

## Success Criteria

- `AITab` remains import-compatible and constructor-compatible.
- `ai_tab.py` is reduced to a smaller composition root.
- New focused mixins contain migrated behavior without rewrites.
- Agent safety, main-thread execution, diagnostics audit, session anchoring, cache formats, and history restore behavior are preserved.
- Import smoke test, compile check, and targeted tests pass or have documented unrelated failures.