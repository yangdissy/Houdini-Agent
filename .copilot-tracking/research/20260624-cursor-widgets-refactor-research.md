<!-- markdownlint-disable-file -->

# Research: cursor_widgets.py Refactor Split

## Task

Assess whether `houdini_agent/ui/cursor_widgets.py` can be split, define a low-risk module layout, and prepare implementation guidance for a later refactor.

## Research Status

Verified. Research was performed against the current workspace on 2026-06-24. No prior `.copilot-tracking/research/*cursor*research.md` or `.copilot-tracking/research/*ui*research.md` files existed, so this research file is the source of truth for the planning files.

## Tool Usage And Verified Findings

- Read `houdini_agent/ui/cursor_widgets.py` in large ranges and verified the file has 8158 lines.
- Extracted class/function structure with PowerShell `Select-String` because `rg` is unavailable in the current PowerShell environment.
- Searched Python import sites with PowerShell `Get-ChildItem` plus `Select-String`, excluding `lib`, `.git`, and large cache directories.
- Read current consumers: `houdini_agent/ui/ai_tab.py`, `houdini_agent/ui/input_area.py`, `houdini_agent/ui/chat_view.py`, and `houdini_agent/ui/header.py`.
- Fetched Python module documentation from `https://docs.python.org/3/tutorial/modules.html`; it supports splitting larger programs into modules and using packages/imports to organize definitions.
- Attempted to fetch Qt stylesheet documentation from `https://doc.qt.io/qt-6/stylesheet-reference.html` and `https://doc.qt.io/qt-6/stylesheet-syntax.html`, but extraction failed. Workspace evidence still shows extensive `setObjectName()` and dynamic property usage, so QSS object names must be preserved during moves.

## Project Structure Findings

- `houdini_agent/ui/ai_tab.py` already documents a split architecture: `ui/header.py`, `ui/input_area.py`, `ui/chat_view.py`, `core/agent_runner.py`, `core/session_manager.py`, and other mixins are gradually migrated out of `ai_tab.py`.
- `houdini_agent/ui/input_area.py` and `houdini_agent/ui/chat_view.py` are mixin modules that still import widgets from `cursor_widgets.py`.
- `houdini_agent/ui` already contains focused modules such as `image_mixin.py`, `i18n.py`, `node_links.py`, `theme_engine.py`, `font_settings_dialog.py`, and dialogs. This supports adding focused widget modules instead of creating a new package hierarchy.
- Existing style appears to favor Qt widgets in simple Python modules, with QSS selected via `setObjectName()` and dynamic properties rather than per-widget inline styles.

## cursor_widgets.py Responsibility Map

The current file mixes many unrelated UI domains:

- Shared utilities and theme: `_fmt_duration`, `CursorTheme`, `AuroraBar`, `PulseIndicator`, `CollapsibleSection`.
- Chat response flow: `ThinkingSection`, `ThinkingBar`, `ToolCallItem`, `ExecutionSection`, `UserMessage`, `AIResponse`, `StatusLine`.
- Confirm and operation UI: `VEXPreviewInline`, `NodeOperationLabel`, `StreamingCodePreview`, `ParamDiffWidget`.
- Image preview UI: `ImagePreviewDialog`, `ClickableImageLabel`.
- Plan UI: `PlanBlock`, `PlanDAGWidget`, `StreamingPlanCard`, `PlanViewer`, `AskQuestionCard`.
- Markdown/rendering/shell UI: `SimpleMarkdown`, `SyntaxHighlighter`, `_CollapsibleShellOutput`, `PythonShellWidget`, `SystemShellWidget`, `CodeBlockWidget`, `RichContentWidget`.
- Context/status UI: `NodeContextBar`, `ToolStatusBar`, `UnifiedStatusBar`.
- Input UI: `VEXPreviewDialog`, `NodeCompleterPopup`, `SlashCommandPopup`, `SLASH_COMMANDS`, `ChatInput`, `StopButton`, `SendButton`.
- Todo and diagnostics: `TodoItem`, `TodoList`, `_BarWidget`, `TokenAnalyticsPanel`.
- App management dialogs: `UpdateNotificationBanner`, `PluginManagerDialog`, `PluginSettingsPage`, `RulesEditorDialog`.

## Key Line Evidence In cursor_widgets.py

- Lines 8-17 contain shared imports used by almost all classes.
- Lines 20-121 define `_fmt_duration` and `AuroraBar`.
- Lines 123-161 define `CursorTheme`.
- Lines 163-231 define `CollapsibleSection`.
- Lines 234-483 define animation and thinking widgets.
- Lines 490-738 define confirmation and tool execution widgets.
- Lines 748-839 define image preview widgets.
- Lines 844-1429 define `UserMessage` and `AIResponse`.
- Lines 1438-1878 define status, node operation, streaming code, and parameter diff widgets.
- Lines 1882-2382 define compatibility content widgets, plan block, and plan DAG drawing.
- Lines 2384-3507 define streaming/final plan cards and ask-question card.
- Lines 3519-4430 define markdown parsing, syntax highlighting, and shell/code rendering helpers.
- Lines 4428-5014 define collapsible shell output, shell widgets, code block widget, and rich content widget.
- Lines 5016-5343 define context/status bars and unified status rendering.
- Lines 5345-6170 define preview dialog, completion popups, slash commands, and `ChatInput`.
- Lines 6172-6381 define buttons and Todo widgets.
- Lines 6400-6838 define token analytics chart and dialog.
- Lines 6850-8158 define update banner, plugin manager/settings, and rules editor dialogs.

## External Import Sites

- `houdini_agent/core/agent_runner.py` imports `VEXPreviewInline`.
- `houdini_agent/core/plan_mixin.py` imports `AskQuestionCard`, `PlanViewer`, and `StreamingPlanCard`.
- `houdini_agent/core/session_manager.py` imports `TodoList`.
- `houdini_agent/ui/ai_tab.py` imports many public names from `.cursor_widgets`: `CursorTheme`, `UserMessage`, `AIResponse`, `PlanBlock`, `PlanViewer`, `StreamingPlanCard`, `AskQuestionCard`, `CollapsibleContent`, `StatusLine`, `ChatInput`, `SendButton`, `StopButton`, `TodoList`, `NodeOperationLabel`, `NodeContextBar`, `PythonShellWidget`, `SystemShellWidget`, `ClickableImageLabel`, `ToolStatusBar`, `NodeCompleterPopup`, `StreamingCodePreview`, and `UpdateNotificationBanner`.
- `houdini_agent/ui/ai_tab.py` also has late imports for `TokenAnalyticsPanel`, `StatusLine`, and `SLASH_COMMANDS`.
- `houdini_agent/ui/chat_view.py` imports `UserMessage`, `AIResponse`, `StatusLine`, and `ClickableImageLabel`.
- `houdini_agent/ui/header.py` lazily imports `RulesEditorDialog` and `PluginManagerDialog`.
- `houdini_agent/ui/image_mixin.py` imports `ClickableImageLabel`.
- `houdini_agent/ui/input_area.py` imports `CursorTheme`, `ChatInput`, `SendButton`, `StopButton`, `UnifiedStatusBar`, `NodeCompleterPopup`, and `SlashCommandPopup`.
- `houdini_agent/main.py` lists `houdini_agent.ui.cursor_widgets`, so compatibility at that module path is important.

## Recommended Module Split

Use a conservative implementation split that preserves the public import path first:

- `houdini_agent/ui/cursor_theme.py`: `CursorTheme` and small shared UI constants if needed.
- `houdini_agent/ui/cursor_common.py`: `_fmt_duration`, `AuroraBar`, `PulseIndicator`, `CollapsibleSection`, and `StatusLine`.
- `houdini_agent/ui/cursor_images.py`: `ImagePreviewDialog`, `ClickableImageLabel`.
- `houdini_agent/ui/cursor_markdown.py`: `SimpleMarkdown`, `SyntaxHighlighter`, `CodeBlockWidget`, `RichContentWidget`, `_CollapsibleShellOutput`, `PythonShellWidget`, `SystemShellWidget`.
- `houdini_agent/ui/cursor_chat.py`: `ThinkingSection`, `ThinkingBar`, `ToolCallItem`, `ExecutionSection`, `UserMessage`, `AIResponse`.
- `houdini_agent/ui/cursor_operations.py`: `VEXPreviewInline`, `NodeOperationLabel`, `StreamingCodePreview`, `ParamDiffWidget`.
- `houdini_agent/ui/cursor_plan.py`: `CollapsibleContent`, `PlanBlock`, `PlanDAGWidget`, `StreamingPlanCard`, `PlanViewer`, `AskQuestionCard`.
- `houdini_agent/ui/cursor_input.py`: `VEXPreviewDialog`, `NodeCompleterPopup`, `SlashCommandPopup`, `SLASH_COMMANDS`, `ChatInput`, `StopButton`, `SendButton`.
- `houdini_agent/ui/cursor_status.py`: `NodeContextBar`, `ToolStatusBar`, `UnifiedStatusBar`.
- `houdini_agent/ui/cursor_todo.py`: `TodoItem`, `TodoList`.
- `houdini_agent/ui/cursor_analytics.py`: `_BarWidget`, `TokenAnalyticsPanel`.
- `houdini_agent/ui/cursor_management.py`: `UpdateNotificationBanner`, `PluginManagerDialog`, `PluginSettingsPage`, `RulesEditorDialog`.
- `houdini_agent/ui/cursor_widgets.py`: compatibility facade that imports and re-exports the same public names. This should remain until consumers are migrated.

## Dependency Guidance

- Keep `CursorTheme` in its own module to avoid circular imports. Almost every split module depends on it.
- Keep `cursor_common.py` below other widgets in the dependency graph; it can depend on `CursorTheme`, `qt_compat`, `i18n`, and `node_links` only if needed.
- `cursor_chat.py` can depend on `cursor_common`, `cursor_markdown`, `cursor_images`, and `cursor_operations`; avoid reverse dependencies from those modules back into chat.
- `cursor_markdown.py` may need `CursorTheme`, `_linkify_node_paths`, `tr`, `html`, `re`, and Qt imports. It should not import `AIResponse`.
- `cursor_input.py` may need `SLASH_COMMANDS`, completer popups, send/stop buttons, and `ChatInput`. It should not import `AIResponse`.
- `cursor_management.py` likely has imports nested inside methods; preserve those lazy imports to avoid startup/plugin side effects.

## Migration Strategy

Use a staged move to reduce risk:

1. Add new modules by moving independent leaf groups first: theme/common/images/todo.
2. Move markdown/shell/code rendering next because `AIResponse` depends on it.
3. Move chat, operations, plan, input, status, analytics, and management modules.
4. Replace `cursor_widgets.py` with explicit re-export imports and an `__all__` list matching the public names used by consumers.
5. Optionally migrate consumers to the focused modules in a later cleanup. This is not required for behavior parity.

## Behavior Contracts To Preserve

- Every existing `setObjectName()` string and dynamic property name must remain unchanged to keep QSS styling intact.
- Existing Qt signals must keep their names and payloads, including `AIResponse.createWrangleRequested`, `AIResponse.nodePathClicked`, `VEXPreviewInline.confirmed`, `VEXPreviewInline.cancelled`, `NodeOperationLabel.nodeClicked`, `undoRequested`, and `decided`.
- Public methods called by consumers must remain available, especially `AIResponse.add_thinking`, `append_content`, `finalize`, `start_aurora`, `stop_aurora`, `add_tool_result`, `add_shell_widget`, and `add_sys_shell_widget`.
- Compatibility imports from `.cursor_widgets` must continue working throughout the refactor.
- Do not introduce new dependencies; use Python modules and existing Qt compatibility imports only.

## Verification Guidance

- Run a Python import smoke test for `houdini_agent.ui.cursor_widgets` and all public re-exported names.
- Compile the affected UI modules with Python's `compileall` or project test command.
- Run existing tests that touch UI/core imports, such as `tests/test_agent_tool_selection.py`, `tests/test_diagnostics_export.py`, and the closest available import/session tests.
- If Houdini/Qt runtime is available, open the AI tab and verify chat response rendering, input completion, plan card display, plugin manager, rules editor, and token analytics dialog.

## Decision

Yes, the file can and should be split. The safest split is not to immediately update every consumer; instead, move implementations into focused modules and leave `cursor_widgets.py` as a compatibility facade. This reduces blast radius while making future UI work much easier.