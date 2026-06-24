<!-- markdownlint-disable-file -->

# Task Details: cursor_widgets.py Refactor Split

## Research Reference

**Source Research**: #file:../research/20260624-cursor-widgets-refactor-research.md

## Phase 1: Establish Compatibility Boundary

### Task 1.1: Preserve public cursor_widgets import contract

Keep `houdini_agent/ui/cursor_widgets.py` available as the public compatibility module while moving implementations into focused sibling modules. The first implementation pass should not require consumer files to change imports.

- **Files**:
  - `houdini_agent/ui/cursor_widgets.py` - convert to explicit compatibility facade after implementation modules are created.
  - `houdini_agent/ui/cursor_theme.py` - new home for `CursorTheme`.
  - `houdini_agent/ui/cursor_common.py` - new home for shared helpers/widgets.
- **Success**:
  - All existing imports from `.cursor_widgets` still resolve.
  - `houdini_agent/main.py` can still load `houdini_agent.ui.cursor_widgets`.
  - `cursor_widgets.py` exports the same public names through explicit imports and `__all__`.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 65-76) - external import sites and compatibility requirement.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 105-113) - staged migration strategy.
  - #fetch:https://docs.python.org/3/tutorial/modules.html - Python modules and packages support splitting larger programs into files.
- **Dependencies**:
  - Research validation complete.
  - No consumer import migration is required in this phase.

### Task 1.2: Move leaf shared modules first

Create low-dependency modules before moving larger widgets. Start with theme/common/images/todo because these groups are either foundational or leaf-like.

- **Files**:
  - `houdini_agent/ui/cursor_theme.py` - `CursorTheme`.
  - `houdini_agent/ui/cursor_common.py` - `_fmt_duration`, `AuroraBar`, `PulseIndicator`, `CollapsibleSection`, `StatusLine`.
  - `houdini_agent/ui/cursor_images.py` - `ImagePreviewDialog`, `ClickableImageLabel`.
  - `houdini_agent/ui/cursor_todo.py` - `TodoItem`, `TodoList`.
- **Success**:
  - These modules import only required Qt/i18n/theme helpers.
  - QSS object names and widget behavior remain unchanged.
  - Compatibility facade re-exports the moved names.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 33-42) - responsibility map.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 46-63) - class line evidence in the source file.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 82-94) - recommended module split.
- **Dependencies**:
  - Task 1.1 compatibility boundary.

## Phase 2: Move Rendering And Chat Domains

### Task 2.1: Move markdown, code, and shell rendering widgets

Move the rendering stack before chat because `AIResponse` depends on Markdown parsing and code block rendering.

- **Files**:
  - `houdini_agent/ui/cursor_markdown.py` - `SimpleMarkdown`, `SyntaxHighlighter`, `_CollapsibleShellOutput`, `PythonShellWidget`, `SystemShellWidget`, `CodeBlockWidget`, `RichContentWidget`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export moved rendering names.
- **Success**:
  - `SimpleMarkdown.parse_segments()` and syntax highlighter APIs remain unchanged.
  - `CodeBlockWidget.createWrangleRequested` behavior remains available.
  - Shell widgets still render output/error with the same object names.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 57-58) - rendering line ranges.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 96-103) - dependency guidance.
- **Dependencies**:
  - Phase 1 complete.

### Task 2.2: Move operation widgets used by chat/core

Move confirmation, node operation, streaming code preview, and parameter diff widgets to a separate operations module.

- **Files**:
  - `houdini_agent/ui/cursor_operations.py` - `VEXPreviewInline`, `NodeOperationLabel`, `StreamingCodePreview`, `ParamDiffWidget`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export moved operation names.
- **Success**:
  - `houdini_agent/core/agent_runner.py` can still import `VEXPreviewInline` from `.cursor_widgets`.
  - Operation label signals and diff collapse behavior are unchanged.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 35-35) - operation UI responsibility.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 67-70) - external imports and consumers.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 115-121) - behavior contracts.
- **Dependencies**:
  - Task 1.2 complete.

### Task 2.3: Move chat response widgets

Move the core chat display widgets after rendering and operations modules exist.

- **Files**:
  - `houdini_agent/ui/cursor_chat.py` - `ThinkingSection`, `ThinkingBar`, `ToolCallItem`, `ExecutionSection`, `UserMessage`, `AIResponse`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export chat names.
- **Success**:
  - `AIResponse` public API and signals remain unchanged.
  - `chat_view.py` and `ai_tab.py` continue to work through `.cursor_widgets` imports.
  - Node link activation still routes through `nodePathClicked`.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 34-34) - chat responsibility.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 53-54) - `UserMessage` and `AIResponse` line evidence.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 117-120) - behavior contracts.
- **Dependencies**:
  - Task 2.1 complete.
  - Task 2.2 complete.

## Phase 3: Move Plan, Input, Status, Analytics, And Management Widgets

### Task 3.1: Move plan widgets

Create a dedicated plan module for the legacy and streaming plan UI.

- **Files**:
  - `houdini_agent/ui/cursor_plan.py` - `CollapsibleContent`, `PlanBlock`, `PlanDAGWidget`, `StreamingPlanCard`, `PlanViewer`, `AskQuestionCard`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export plan names.
- **Success**:
  - `houdini_agent/core/plan_mixin.py` imports continue working from `.cursor_widgets`.
  - Plan confirm/reject signals and step update APIs remain unchanged.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 37-37) - plan responsibility.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 55-56) - plan line evidence.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 68-68) - plan consumer import.
- **Dependencies**:
  - Phase 2 complete.

### Task 3.2: Move input and status widgets

Split input-specific widgets from status indicators while preserving imports used by `input_area.py` and `ai_tab.py`.

- **Files**:
  - `houdini_agent/ui/cursor_input.py` - `VEXPreviewDialog`, `NodeCompleterPopup`, `SlashCommandPopup`, `SLASH_COMMANDS`, `ChatInput`, `StopButton`, `SendButton`.
  - `houdini_agent/ui/cursor_status.py` - `NodeContextBar`, `ToolStatusBar`, `UnifiedStatusBar`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export input/status names.
- **Success**:
  - `input_area.py` can still import `ChatInput`, buttons, popups, and `UnifiedStatusBar` through `.cursor_widgets`.
  - Slash command completion and IME handling behavior are unchanged.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 39-40) - status and input responsibility.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 59-60) - status/input line evidence.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 75-75) - input consumer imports.
- **Dependencies**:
  - Phase 2 complete.

### Task 3.3: Move analytics and management dialogs

Move token analytics and app management dialogs into focused modules. Preserve lazy imports inside management dialogs where present.

- **Files**:
  - `houdini_agent/ui/cursor_analytics.py` - `_BarWidget`, `TokenAnalyticsPanel`.
  - `houdini_agent/ui/cursor_management.py` - `UpdateNotificationBanner`, `PluginManagerDialog`, `PluginSettingsPage`, `RulesEditorDialog`.
  - `houdini_agent/ui/cursor_widgets.py` - re-export analytics and management names.
- **Success**:
  - `ai_tab.py` late import of `TokenAnalyticsPanel` still works.
  - `header.py` lazy imports for `RulesEditorDialog` and `PluginManagerDialog` still work.
  - Plugin/rules dialogs preserve lazy imports and avoid new startup side effects.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 41-42) - analytics and management responsibility.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 62-63) - analytics/management line evidence.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 71-73) - late/lazy consumer imports.
- **Dependencies**:
  - Phase 2 complete.

## Phase 4: Verify And Optionally Migrate Consumers

### Task 4.1: Verify compatibility facade and imports

Run smoke and compile checks after all implementation moves.

- **Files**:
  - `houdini_agent/ui/cursor_widgets.py` - final facade verification.
  - `houdini_agent/ui/cursor_*.py` - compile/import verification.
- **Success**:
  - Python import smoke test can import `houdini_agent.ui.cursor_widgets` and all public names listed in the facade.
  - `compileall` succeeds for affected UI modules.
  - Existing tests that touch imports/core UI continue passing or fail only for unrelated pre-existing issues.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 123-128) - verification guidance.
- **Dependencies**:
  - Phase 3 complete.

### Task 4.2: Defer consumer import cleanup unless needed

Consumer files can continue importing from `cursor_widgets.py`; migrating them to focused modules is optional and should be a later cleanup if there is no behavior need.

- **Files**:
  - `houdini_agent/ui/ai_tab.py` - optional later focused imports.
  - `houdini_agent/ui/input_area.py` - optional later focused imports.
  - `houdini_agent/ui/chat_view.py` - optional later focused imports.
  - `houdini_agent/ui/header.py` - optional later focused imports.
  - `houdini_agent/core/agent_runner.py`, `houdini_agent/core/plan_mixin.py`, `houdini_agent/core/session_manager.py` - optional later focused imports.
- **Success**:
  - No unnecessary consumer churn in the initial refactor.
  - Any later cleanup is mechanical and independently testable.
- **Research References**:
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 105-113) - staged migration and optional cleanup guidance.
  - #file:../research/20260624-cursor-widgets-refactor-research.md (Lines 130-132) - final decision.
- **Dependencies**:
  - Task 4.1 complete.

## Dependencies

- Existing Python/Qt compatibility layer: `houdini_agent.qt_compat`.
- Existing i18n helper: `houdini_agent/ui/i18n.py`.
- Existing node link helpers: `houdini_agent/ui/node_links.py`.
- No new third-party dependencies.

## Success Criteria

- `cursor_widgets.py` is reduced to a compatibility facade or near-facade.
- Focused `cursor_*.py` modules contain the moved implementations.
- Existing imports from `.cursor_widgets` continue to resolve.
- Object names, dynamic properties, signals, and public widget methods are preserved.
- Import smoke test, compile check, and relevant existing tests pass or have documented unrelated failures.