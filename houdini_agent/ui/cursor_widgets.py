# -*- coding: utf-8 -*-
"""
Cursor 风格 UI 组件 — 兼容 facade。

各 widget 实现已迁移到独立的 focused module（chat_widgets / plan_widgets /
rich_content / input_widgets / analytics_widgets / plugin_manager_dialog /
rules_editor_dialog / utility_widgets / cursor_theme）。
本文件仅做显式 re-export，保持 `from .cursor_widgets import X` 的旧调用不破。
"""

from .cursor_theme import CursorTheme

from .cursor_chat_widgets import (
    AIResponse,
    AuroraBar,
    ClickableImageLabel,
    CollapsibleContent,
    CollapsibleSection,
    ExecutionSection,
    ImagePreviewDialog,
    NodeOperationLabel,
    ParamDiffWidget,
    PulseIndicator,
    StatusLine,
    StreamingCodePreview,
    ThinkingBar,
    ThinkingSection,
    ToolCallItem,
    UserMessage,
    VEXPreviewInline,
    _fmt_duration,
)
from .cursor_plan_widgets import (
    AskQuestionCard,
    PlanBlock,
    PlanDAGWidget,
    PlanViewer,
    StreamingPlanCard,
)
from .cursor_rich_content import (
    CodeBlockWidget,
    PythonShellWidget,
    RichContentWidget,
    SimpleMarkdown,
    SyntaxHighlighter,
    SystemShellWidget,
)
from .cursor_input_widgets import (
    ChatInput,
    NodeCompleterPopup,
    NodeContextBar,
    SLASH_COMMANDS,
    SlashCommandPopup,
    ToolStatusBar,
    UnifiedStatusBar,
    VEXPreviewDialog,
)
from .cursor_utility_widgets import (
    SendButton,
    StopButton,
    UpdateNotificationBanner,
)
from .cursor_analytics_widgets import (
    TokenAnalyticsPanel,
    TodoItem,
    TodoList,
    _BarWidget,
)
from .cursor_plugin_manager_dialog import (
    PluginManagerDialog,
    PluginSettingsPage,
)
from .cursor_rules_editor_dialog import (
    IMELineEdit,
    IMEPlainTextEdit,
    RulesEditorDialog,
)