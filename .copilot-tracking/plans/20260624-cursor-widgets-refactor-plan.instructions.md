---
applyTo: ".copilot-tracking/changes/20260624-cursor-widgets-refactor-changes.md"
---

<!-- markdownlint-disable-file -->

# Task Checklist: cursor_widgets.py Refactor Split

## Overview

Split the 8158-line `houdini_agent/ui/cursor_widgets.py` into focused UI modules while preserving existing `.cursor_widgets` imports through a compatibility facade.

## Objectives

- Reduce `cursor_widgets.py` from a monolithic implementation file to a compatibility facade or near-facade.
- Move widget implementations into focused `houdini_agent/ui/cursor_*.py` modules by responsibility.
- Preserve all existing public imports, Qt signals, object names, dynamic properties, and widget APIs.
- Verify the refactor with import smoke checks, compile checks, and relevant existing tests.

## Research Summary

### Project Files

- `houdini_agent/ui/cursor_widgets.py` - monolithic 8158-line source file to split.
- `houdini_agent/ui/ai_tab.py` - primary consumer of chat, plan, input, status, and analytics widgets.
- `houdini_agent/ui/input_area.py` - consumer of input widgets, buttons, popups, and unified status bar.
- `houdini_agent/ui/chat_view.py` - consumer of message, response, status, and image widgets.
- `houdini_agent/ui/header.py` - lazy consumer of plugin manager and rules editor dialogs.
- `houdini_agent/core/agent_runner.py` - consumer of `VEXPreviewInline`.
- `houdini_agent/core/plan_mixin.py` - consumer of plan and question cards.
- `houdini_agent/core/session_manager.py` - consumer of `TodoList`.

### External References

- #file:../research/20260624-cursor-widgets-refactor-research.md - validated workspace research for source structure, imports, split boundaries, and verification.
- #fetch:https://docs.python.org/3/tutorial/modules.html - Python module/package guidance supporting splitting larger programs into modules.

### Standards References

- #file:../../.github/instructions/agent-safety.instructions.md - safety constraints for agent-related code; relevant if touching agent confirmation UI boundaries.
- #file:../../.github/instructions/python-mcp-server.instructions.md - Python project conventions when touching Python files.

## Implementation Checklist

### [ ] Phase 1: Establish Compatibility Boundary

- [ ] Task 1.1: Preserve public `cursor_widgets` import contract

  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 11-29)

- [ ] Task 1.2: Move leaf shared modules first
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 31-49)

### [ ] Phase 2: Move Rendering And Chat Domains

- [ ] Task 2.1: Move markdown, code, and shell rendering widgets
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 53-68)

- [ ] Task 2.2: Move operation widgets used by chat/core
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 70-85)

- [ ] Task 2.3: Move chat response widgets
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 87-104)

### [ ] Phase 3: Move Plan, Input, Status, Analytics, And Management Widgets

- [ ] Task 3.1: Move plan widgets
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 108-123)

- [ ] Task 3.2: Move input and status widgets
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 125-141)

- [ ] Task 3.3: Move analytics and management dialogs
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 143-160)

### [ ] Phase 4: Verify And Optionally Migrate Consumers

- [ ] Task 4.1: Verify compatibility facade and imports
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 164-178)

- [ ] Task 4.2: Defer consumer import cleanup unless needed
  - Details: .copilot-tracking/details/20260624-cursor-widgets-refactor-details.md (Lines 180-197)

## Dependencies

- Existing `houdini_agent.qt_compat` Qt compatibility layer.
- Existing `houdini_agent/ui/i18n.py` translation helper.
- Existing `houdini_agent/ui/node_links.py` node link helpers.
- No new third-party dependencies.

## Success Criteria

- `cursor_widgets.py` remains import-compatible and re-exports existing public names.
- Focused `cursor_*.py` modules contain the moved widget implementations.
- Existing consumer imports from `.cursor_widgets` continue to resolve.
- Qt object names, dynamic properties, signals, and public widget methods remain unchanged.
- Import smoke test, compile check, and relevant tests complete successfully or document unrelated failures.