---
applyTo: ".copilot-tracking/changes/20260722-cursor-widgets-diagnostic-refactor-changes.md"
---

<!-- markdownlint-disable-file -->

# Task Checklist: cursor_widgets.py Diagnostic Refactor

## Overview

Refactor the oversized `houdini_agent/ui/cursor_widgets.py` file into deeper UI modules with small, stable interfaces. The first pass must preserve behavior and existing imports; the goal is to improve locality and reduce context load before changing architecture.

## Design Diagnosis

`cursor_widgets.py` is currently a shallow module: callers learn one broad import surface, but maintainers must navigate an 8k+ line implementation that mixes chat rendering, rich content rendering, input completion, Plan UI, plugin management, rules editing, shell output, VEX previews, analytics, and tool status UI.

The desired shape is a set of deeper modules. Each module should expose a narrow interface that hides a cohesive implementation and gives callers leverage without forcing them to know unrelated widget internals.

```text
╔══════════════════════════════════════╗
║          WORKFLOW DIAGNOSTIC        ║
╠══════════════════════════════════════╣
║ Prompt Quality       ███░░  3/5     ║
║ Context Efficiency   ██░░░  2/5     ║
║ Tool Health          ███░░  3/5     ║
║ Architecture         ██░░░  2/5     ║
║ Safety & Reliability ██░░░  2/5     ║
╠══════════════════════════════════════╣
║ Overall Score:       12/25          ║
╚══════════════════════════════════════╝
```

## Objectives

- Reduce `cursor_widgets.py` from an implementation-heavy file into a compatibility facade or near-facade.
- Preserve `houdini_agent.ui.cursor_widgets` as the external seam during the first refactor pass.
- Move cohesive implementations into focused UI modules with explicit responsibility groups.
- Preserve Qt signals, object names, dynamic properties, public widget methods, styling behavior, and user-visible behavior.
- Avoid adding new dependencies, wrappers, configuration systems, or speculative extension points.
- Defer deeper core/UI seam redesign until after mechanical module extraction is stable.

## Existing Interface Contract

Treat existing imports from `houdini_agent.ui.cursor_widgets` as the compatibility interface for this phase. The first pass may move implementations behind that interface, but must not break callers.

Primary callers to protect:

- `houdini_agent/ui/ai_tab.py` - broad consumer of chat, input, Plan, todo, analytics, and status widgets.
- `houdini_agent/ui/input_area.py` - consumer of input widgets and status widgets.
- `houdini_agent/ui/action_commands_mixin.py` - adjacent consumer of slash command metadata and input behavior.
- `houdini_agent/ui/chat_view.py` - consumer of message, response, status, and image widgets.
- `houdini_agent/ui/header.py` - lazy consumer of plugin manager and rules editor dialogs.
- `houdini_agent/core/agent_runner.py` - current core-layer consumer of `VEXPreviewInline`.
- `houdini_agent/core/plan_mixin.py` - current core-layer consumer of Plan and question cards.
- `houdini_agent/core/session_manager.py` - consumer of `TodoList`.

## Target Modules And Seams

### Compatibility Facade

- Module: `houdini_agent/ui/cursor_widgets.py`
- Interface: existing exported names imported by callers.
- Implementation: re-exports from focused modules after each extraction.
- Seam decision: keep this as the external seam for compatibility until all consumers are intentionally migrated.
- Depth goal: callers keep one stable import path while implementation locality improves behind it.

### Rich Content Module

- Candidate file: `houdini_agent/ui/rich_content.py` or `houdini_agent/ui/markdown_widgets.py`
- Interface: rich content widgets and helpers used by chat response rendering.
- Implementation candidates: `SimpleMarkdown`, `SyntaxHighlighter`, `CodeBlockWidget`, `RichContentWidget`, shell/code rendering helpers that are tightly coupled to those classes.
- Depth goal: hide Markdown parsing, syntax display, copy button behavior, and shell output rendering behind a small widget interface.

### Chat And Status Module

- Candidate file: `houdini_agent/ui/chat_widgets.py`
- Interface: chat message/status widgets used by chat view and AI tab.
- Implementation candidates: `UserMessage`, `AIResponse`, `StatusLine`, `CollapsibleSection`, `AuroraBar`, `ThinkingSection`, `ThinkingBar`, `UnifiedStatusBar`, `ToolStatusBar`, `ToolCallItem`, `ExecutionSection`.
- Depth goal: keep message rendering and status transitions local instead of distributed through the monolith.

### Operation Preview Module

- Candidate file: `houdini_agent/ui/operation_widgets.py`
- Interface: widgets for displaying tool/node/VEX/image operation previews.
- Implementation candidates: `VEXPreviewInline`, `VEXPreviewDialog`, `NodeOperationLabel`, `ParamDiffWidget`, `ImagePreviewDialog`, `ClickableImageLabel`, and closely related preview helpers.
- Depth goal: isolate tool-confirmation-adjacent UI and make safety review more local.

### Plan Workflow Module

- Candidate file: `houdini_agent/ui/plan_widgets.py`
- Interface: Plan display and interactive question widgets.
- Implementation candidates: `PlanBlock`, `PlanDAGWidget`, `StreamingPlanCard`, `PlanViewer`, `AskQuestionCard`.
- Depth goal: keep Plan rendering, streaming updates, DAG display, and answer payload behavior in one module.

### Input Module

- Candidate file: `houdini_agent/ui/input_widgets.py`
- Interface: chat input widget, node completion popup, slash command popup, and command metadata.
- Implementation candidates: `ChatInput`, `NodeCompleterPopup`, `SlashCommandPopup`, `NodeContextBar`, `SLASH_COMMANDS`.
- Depth goal: hide IME handling, paste/drag behavior, slash filtering, and node completion behind the input widget interface.

### Analytics And Management Modules

- Candidate files: `houdini_agent/ui/analytics_widgets.py`, `houdini_agent/ui/plugin_manager_dialog.py`, `houdini_agent/ui/rules_editor_dialog.py`
- Interface: focused dialogs/widgets opened by current UI code.
- Implementation candidates: `TodoList`, `TokenAnalyticsPanel`, `PluginManagerDialog`, `PluginSettingsPage`, `RulesEditorDialog`, `IMELineEdit`, `IMEPlainTextEdit`.
- Depth goal: keep high-impact management behavior auditable and testable without scanning unrelated chat/input code.

## Implementation Checklist

### [x] Phase 1: Preserve Compatibility Interface

- [x] Task 1.1: Inventory public names imported from `cursor_widgets.py`.
  - Use current caller imports as the interface contract.
  - Record any symbol whose behavior depends on Qt signals, object names, dynamic properties, or callback ordering.

- [x] Task 1.2: Keep `cursor_widgets.py` import-compatible.
  - Move implementations behind the current interface one group at a time.
  - Re-export moved names explicitly from the facade.
  - Do not use broad wildcard imports unless the repo already uses that style for compatibility facades.

### [x] Phase 2: Extract Rich Content First

- [x] Task 2.1: Move rich content implementation into a focused module.
  - Move only the classes/helpers needed for Markdown, code block, syntax, rich text, and shell/code presentation.
  - Keep behavior identical; do not redesign parsing or rendering in this pass.

- [x] Task 2.2: Verify the facade exposes all moved rich content names.
  - Compile touched modules.
  - Import `houdini_agent.ui.cursor_widgets` and assert moved names are still available.

### [x] Phase 3: Extract Chat, Status, And Operation Preview Widgets

- [x] Task 3.1: Move chat/status widgets after rich content dependencies are stable.
  - Preserve message layout, streaming update behavior, status text, animation setup, and public methods.

- [x] Task 3.2: Move operation preview widgets into their own module.
  - Preserve VEX preview confirmation behavior, image preview behavior, node operation display, and parameter diff display.
  - Keep current core imports working through the `cursor_widgets.py` facade.

### [x] Phase 4: Extract Plan Workflow Widgets

- [x] Task 4.1: Move Plan widgets to `plan_widgets.py`.
  - Preserve streaming Plan card updates, Plan viewer behavior, DAG rendering, button callbacks, and ask-question answer payloads.

- [x] Task 4.2: Verify `plan_mixin.py` call sites.
  - Keep existing import paths compatible unless performing a separate consumer migration.
  - Do not redesign Plan orchestration or handoff protocols in this phase.

### [x] Phase 5: Extract Input Widgets

- [x] Task 5.1: Move input and completion widgets.
  - Preserve IME behavior, paste behavior, drag/drop image behavior, slash command filtering, and node completion behavior.

- [x] Task 5.2: Verify `input_area.py` and `action_commands_mixin.py`.
  - Compile/import check both consumers.
  - Manually validate slash command popup and text/image input when a Qt runtime is available.

### [x] Phase 6: Extract Analytics And Management Dialogs

- [x] Task 6.1: Move analytics widgets.
  - Preserve data display behavior and any assumptions used by diagnostics/history UI.

- [x] Task 6.2: Move plugin manager dialog.
  - Preserve plugin enable/disable, reload, settings rendering, and tool registry display behavior.
  - Keep agent-safety-related checks and user confirmations intact.

- [x] Task 6.3: Move rules editor dialog and IME edit controls.
  - Preserve autosave, delete confirmation, validation display, and error handling behavior.

### [x] Phase 7: Review Module Depth And Deferred Seams

- [x] Task 7.1: Review `cursor_widgets.py` as a compatibility facade.
  - Confirm it no longer owns unrelated implementations after extraction.
  - Confirm moved modules each have a small interface and cohesive implementation.

- [x] Task 7.2: Record deferred core/UI seam work.
  - Current issue: core modules import concrete Qt widgets.
  - Deferred direction: core should ask the UI layer to present operation/Plan interactions through a narrow seam instead of constructing widgets directly.
  - Do not perform this redesign during the mechanical split unless explicitly approved.

## Verification Strategy

After each phase:

- Run a compile check for touched Python modules.
- Run an import smoke check for `houdini_agent.ui.cursor_widgets` and the moved symbols.
- Check for circular import failures before continuing to the next group.
- Run targeted tests touching `AITab`, diagnostics, tool selection, Plan, or session restore when available.
- When a Qt runtime is available, manually validate chat rendering, code blocks, slash commands, node completion, Plan cards, VEX preview, plugin manager, and rules editor.

Suggested smoke check shape:

```python
from houdini_agent.ui import cursor_widgets

for name in [
    "SimpleMarkdown",
    "CodeBlockWidget",
    "AIResponse",
    "ChatInput",
    "StreamingPlanCard",
    "PluginManagerDialog",
    "RulesEditorDialog",
]:
    assert hasattr(cursor_widgets, name), name
```

## Success Criteria

- `houdini_agent.ui.cursor_widgets` remains import-compatible for existing consumers.
- `cursor_widgets.py` is reduced to a compatibility facade or near-facade.
- New modules have clear interfaces and cohesive implementations.
- No user-visible behavior changes are introduced during the split.
- No new dependencies are added.
- Compile/import checks pass after each phase, or unrelated failures are documented with exact commands and outputs.
- Deferred core/UI seam work is explicitly recorded instead of hidden in this refactor.

## Out Of Scope

- Rewriting Markdown parsing behavior.
- Redesigning Plan workflows, tool confirmation flows, plugin registry behavior, or rules storage.
- Removing compatibility imports from `cursor_widgets.py` in the same pass.
- Broad style-only formatting changes unrelated to moved code.
- Introducing new UI frameworks or dependencies.