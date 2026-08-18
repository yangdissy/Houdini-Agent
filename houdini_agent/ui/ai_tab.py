# -*- coding: utf-8 -*-
"""
Houdini Agent - AI Tab
Agent loop, multi-turn tool calling, streaming UI

模块拆分结构（逐步迁移中）:
  ui/header.py          — HeaderMixin: 顶部设置栏构建
  ui/input_area.py      — InputAreaMixin: 输入区域和模式切换
  ui/chat_view.py       — ChatViewMixin: 对话显示和滚动逻辑
  core/agent_runner.py  — AgentRunnerMixin: Agent 循环和工具调度
  core/session_manager.py — SessionManagerMixin: 多会话管理和缓存
"""

import copy
import json
import math
import os
import threading
import time
import uuid
import queue
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from houdini_agent.qt_compat import QtWidgets, QtCore, QtGui, QSettings, invoke_on_main

from .i18n import tr, get_language
from ..utils.ai_client import AIClient, HOUDINI_TOOLS
from ..utils.mcp import HoudiniMCP
from ..utils.token_optimizer import TokenOptimizer, TokenBudget, CompressionStrategy
from ..utils.ultra_optimizer import UltraOptimizer
from .theme_engine import ThemeEngine
from .font_settings_dialog import FontSettingsDialog
from .cursor_analytics_widgets import TodoList
from .cursor_chat_widgets import (
    AIResponse,
    ClickableImageLabel,
    CollapsibleContent,
    StatusLine,
    UserMessage,
)
from .cursor_input_widgets import (
    ChatInput,
    NodeCompleterPopup,
    NodeContextBar,
    ToolStatusBar,
)
from .cursor_plan_widgets import (
    AskQuestionCard,
    PlanBlock,
    PlanViewer,
    StreamingPlanCard,
)
from .cursor_rich_content import (
    PythonShellWidget,
    SystemShellWidget,
)
from .cursor_theme import CursorTheme
from .cursor_utility_widgets import (
    SendButton,
    StopButton,
    UpdateNotificationBanner,
)
import re

# Mixin 模块（从 ai_tab.py 拆分出的子模块）
from .header import HeaderMixin
from .input_area import InputAreaMixin
from .chat_view import ChatViewMixin
from .history_rendering_mixin import HistoryRenderingMixin
from .image_mixin import ImageMixin
from .preferences_mixin import PreferencesMixin
from .tool_result_mixin import ToolResultMixin
from .action_commands_mixin import ActionCommandsMixin
from ..core.agent_runner import AgentRunnerMixin
from ..core.memory_mixin import MemoryMixin
from ..core.plan_mixin import PlanMixin
from ..core.session_manager import SessionManagerMixin
from ..core.streaming_parser import StreamingParserMixin
from ..core.prompt_manager import build_system_prompt
from ..core.diagnostics_mixin import DiagnosticsMixin
from ..core.runtime_state_mixin import RuntimeStateMixin
from ..core.context_manager_mixin import ContextManagerMixin
from ..core.cache_mixin import CacheMixin
from ..core.update_mixin import UpdateMixin
from ..core.tool_execution_mixin import ToolExecutionMixin
from ..core.send_orchestrator_mixin import SendOrchestratorMixin
from ..core.houdini_main_thread_executor import HoudiniMainThreadExecutor
from ..core.diagnostics_retention import (
    cleanup_diagnostics_retention,
    is_retention_cleanup_enabled,
    retention_days_from_env,
)
from ..core.harness_engine import (
    HarnessRuntimeState,
    HarnessToolPolicyEngine,
    build_tool_retry_key,
    is_harness_v2_enabled,
    sanitize_tool_result,
)

# ★ 大脑启发式长期记忆系统
from ..utils.memory_store import get_memory_store
from ..utils.reward_engine import get_reward_engine
from ..utils.reflection import get_reflection_module
from ..utils.growth_tracker import get_growth_tracker, TaskMetric

# ★ Plan 模式
from ..utils.plan_manager import get_plan_manager, PLAN_TOOL_CREATE, PLAN_TOOL_UPDATE_STEP, PLAN_TOOL_ASK_QUESTION
from shared.user_paths import UserPaths

class AITab(
    HeaderMixin,
    InputAreaMixin,
    ChatViewMixin,
    HistoryRenderingMixin,
    ImageMixin,
    PreferencesMixin,
    DiagnosticsMixin,
    RuntimeStateMixin,
    ContextManagerMixin,
    CacheMixin,
    UpdateMixin,
    ToolExecutionMixin,
    SendOrchestratorMixin,
    ToolResultMixin,
    ActionCommandsMixin,
    StreamingParserMixin,
    MemoryMixin,
    PlanMixin,
    AgentRunnerMixin,
    SessionManagerMixin,
    QtWidgets.QWidget,
):
    """AI 助手 - 极简侧边栏风格（Mixin 架构）"""
    
    # 信号（用于线程安全的 UI 更新）
    _appendContent = QtCore.Signal(str)
    _addStatus = QtCore.Signal(str)
    _updateThinkingTime = QtCore.Signal()
    _agentDone = QtCore.Signal(dict)
    _agentError = QtCore.Signal(str)
    _agentStopped = QtCore.Signal()
    _updateTodo = QtCore.Signal(str, str, str)  # (todo_id, text, status)
    _addNodeOperation = QtCore.Signal(str, object)  # (name, result_dict) ★ 直接传 dict，避免 JSON 序列化/反序列化开销
    _addPythonShell = QtCore.Signal(str, str)  # (code, result_json)
    _addSystemShell = QtCore.Signal(str, str)  # (command, result_json)
    _executeToolRequest = QtCore.Signal(str, dict)  # 工具执行请求信号（线程安全）
    _executeToolBatchRequest = QtCore.Signal(list)   # 批量工具执行请求：[(tool_name, kwargs), ...]
    _addThinking = QtCore.Signal(str)  # 思考内容更新信号（线程安全）
    _finalizeThinkingSignal = QtCore.Signal()  # 结束思考区块（线程安全）
    _resumeThinkingSignal = QtCore.Signal()    # 恢复思考区块（线程安全）
    _showToolStatus = QtCore.Signal(str)       # 显示工具执行状态（线程安全）
    _hideToolStatus = QtCore.Signal()          # 隐藏工具执行状态
    _showGenerating = QtCore.Signal()          # 显示 "Generating..." 状态（线程安全）
    _autoTitleDone = QtCore.Signal(str, str)   # 自动标题生成完成: (session_id, title)
    _confirmToolRequest = QtCore.Signal()  # 确认模式：请求确认（参数通过属性传递，避免 QueuedConnection dict 问题）
    _confirmToolResult = QtCore.Signal(bool)        # 确认模式：结果 (True=执行, False=取消)
    _toolArgsDelta = QtCore.Signal(str, str, str)   # 流式 VEX 预览: (tool_name, delta, accumulated)
    _showPlanning = QtCore.Signal(str)              # 显示 "Planning..." 进度 (progress_text)
    _createStreamingPlan = QtCore.Signal()           # 创建流式 Plan 预览卡片
    _updateStreamingPlan = QtCore.Signal(str)        # 更新流式 Plan 预览卡片内容 (accumulated_json)
    _renderPlanViewer = QtCore.Signal(dict)          # Plan 模式：在主线程渲染 PlanViewer 卡片
    _updatePlanStep = QtCore.Signal(str, str, str)   # Plan 模式：更新步骤状态 (step_id, status, result_summary)
    _askQuestionRequest = QtCore.Signal()             # Plan 模式：ask_question 请求（参数通过属性传递）
    
    def __init__(self, parent=None, workspace_dir: Optional[Path] = None, username: Optional[str] = None):
        super().__init__(parent)

        self._username = (username or "").strip().lower() or "default"
        user_paths = UserPaths(self._username)
        self._user_paths = user_paths
        user_paths.ensure_dirs()

        try:
            self.client = AIClient(username=self._username)
        except TypeError:
            # Backward-compatible fallback for older AIClient versions
            self.client = AIClient()
        self.mcp = HoudiniMCP()
        if hasattr(self.mcp, "set_user"):
            self.mcp.set_user(self._username)
        self.mcp.set_stop_event(self.client._stop_event)  # 共享停止事件，使 shell/python 命令可被中断
        self.client.set_tool_executor(self._execute_tool_with_todo)
        self.client.set_batch_tool_executor(self._execute_tools_batch_in_main_thread)
        
        # 状态
        self._conversation_history: List[Dict[str, Any]] = []
        self._pending_ops: list = []  # 追踪未决操作: [(label, op_type, paths, snapshot), ...]
        self._current_response: Optional[AIResponse] = None
        self._is_running = False
        self._thinking_timer: Optional[QtCore.QTimer] = None
        
        # Agent 运行锚点：记录发起请求的 session，保证回调写入正确的会话
        self._agent_session_id: Optional[str] = None
        self._agent_response: Optional[AIResponse] = None
        self._agent_scroll_area = None  # 运行中 session 的 scroll_area
        self._agent_history: Optional[List[Dict[str, Any]]] = None
        self._agent_token_stats: Optional[Dict] = None
        self._agent_todo_list = None       # 运行中 session 的 TodoList
        self._agent_chat_layout = None     # 运行中 session 的 chat_layout
        
        # 上下文管理
        self._max_context_messages = 20
        self._context_summary = ""
        self._last_auto_read_context = None
        
        # 缓存管理
        self._session_id = str(uuid.uuid4())[:8]  # 当前会话 ID
        self._session_created_at = datetime.now().isoformat()
        self._cache_dir = user_paths.conversations_dir()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._auto_save_cache = True  # 自动保存缓存
        self._workspace_dir = workspace_dir  # 工作区目录
        
        # 多会话管理
        self._sessions: Dict[str, dict] = {}   # session_id -> session state
        self._session_counter = 0               # 用于生成 tab 标签
        # ★ 纯 Python 备份：tab 顺序和标签名（atexit 时 Qt widget 可能已销毁）
        self._tabs_backup: list = []  # [(session_id, tab_label), ...]
        self._ai_tab_active = True
        
        # 静态内容缓存（只计算一次，节省 token 和计算时间）
        self._cached_optimized_system_prompt: Optional[str] = None
        self._cached_optimized_tools: Optional[List[dict]] = None
        self._cached_optimized_tools_no_web: Optional[List[dict]] = None
        
        # Token 优化器
        self.token_optimizer = TokenOptimizer()
        self._auto_optimize = True  # 自动优化
        self._optimization_strategy = CompressionStrategy.BALANCED
        
        # ★ Plan 模式状态
        self._plan_phase = 'idle'          # idle | planning | awaiting_confirmation | executing | completed
        self._active_plan_viewer = None    # 当前活跃的 PlanViewer 组件引用
        self._streaming_plan_card = None   # 流式 Plan 预览卡片（生成中临时使用）
        self._plan_manager = None          # PlanManager 实例（延迟初始化）
        
        # ★ 大脑启发式长期记忆系统（延迟初始化，避免阻塞 UI）
        self._memory_store = None
        self._reward_engine = None
        self._reflection_module = None
        self._growth_tracker = None
        self._memory_initialized = False
        
        # ★ 睡眠机制计数器
        self._sleep_msg_counter = 0       # 当前 session 累计用户消息数
        self._sleep_in_progress = False   # 防止并发睡眠

        # 用户切换请求（在停止后执行）
        self._pending_user_switch: Optional[str] = None
        
        self._init_memory_system()
        
        # 思考长度限制（已禁用，允许完整思考）
        self._max_thinking_length = float('inf')  # 不限制思考长度
        self._thinking_length_warning = float('inf')  # 不警告
        
        # 输出 Token 限制（不限制）
        self._max_output_tokens = float('inf')
        self._output_token_warning = float('inf')
        self._current_output_tokens = 0
        
        # <think> 标签流式解析状态（运行开始时创建纯 Python parser）
        self._thinking_needs_finalize = False  # 标记是否需要 finalize 思考区块
        self._think_enabled = True  # 当前会话是否启用思考显示（由 Think 开关控制）
        
        # 会话级节点路径映射：name → set[path]，用于节点引用去歧义
        self._session_node_map: dict[str, set[str]] = {}
        
        # Token 使用统计（累积值，每轮对话叠加）—— 对齐 Cursor
        self._token_stats = self._empty_token_stats()
        self._call_records: list = []  # 每次 API 调用的详细记录（对齐 Cursor）
        self._harness_trace_records: list = []  # Harness 调度追踪记录（V2）
        self._policy_timeline_records: list = []  # 最近策略决策时间线
        self._policy_failure_count: int = 0
        
        # 工具执行线程安全机制（使用队列和锁避免竞争）
        self._tool_result_queue: queue.Queue = queue.Queue()
        self._tool_lock = threading.Lock()  # 确保一次只有一个工具调用
        self._main_thread_busy = False  # ★ 主线程忙标记（防止超时后堆积信号死锁）
        self._houdini_main_thread_executor = None
        self._harness_v2_enabled = is_harness_v2_enabled(default=True)
        self._harness_state = HarnessRuntimeState(session_id=self._session_id)
        self._tool_policy_engine = HarnessToolPolicyEngine()
        try:
            self._policy_retry_limit = max(1, int(os.getenv("HOUDINI_AGENT_POLICY_MAX_RETRIES", "2")))
        except Exception:
            self._policy_retry_limit = 2
        
        # 连接信号
        self._appendContent.connect(self._on_append_content)
        self._addStatus.connect(self._on_add_status)
        self._updateThinkingTime.connect(self._on_update_thinking)
        self._agentDone.connect(self._on_agent_done)
        self._agentError.connect(self._on_agent_error)
        self._agentStopped.connect(self._on_agent_stopped)
        self._updateTodo.connect(self._on_update_todo)
        self._addNodeOperation.connect(self._on_add_node_operation)
        self._addPythonShell.connect(self._on_add_python_shell)
        self._addSystemShell.connect(self._on_add_system_shell)
        self._executeToolRequest.connect(self._on_execute_tool_main_thread, QtCore.Qt.BlockingQueuedConnection)
        self._executeToolBatchRequest.connect(self._on_execute_tool_batch_main_thread, QtCore.Qt.BlockingQueuedConnection)
        self._houdini_main_thread_executor = HoudiniMainThreadExecutor(
            emit_tool_request=self._executeToolRequest.emit,
            emit_batch_request=self._executeToolBatchRequest.emit,
            result_queue=self._tool_result_queue,
            main_timeout=self._TOOL_MAIN_THREAD_TIMEOUT,
            batch_timeout=60.0,
            record_event=lambda event: self._append_session_diagnostics_records([event]),
        )
        self._addThinking.connect(self._on_add_thinking)
        self._finalizeThinkingSignal.connect(self._finalize_thinking_main_thread)
        self._resumeThinkingSignal.connect(self._resume_thinking_main_thread)
        self._showToolStatus.connect(self._on_show_tool_status)
        self._hideToolStatus.connect(self._on_hide_tool_status)
        self._showGenerating.connect(self._on_show_generating)
        self._autoTitleDone.connect(self._on_auto_title_done)
        self._confirmToolRequest.connect(self._on_confirm_tool_request, QtCore.Qt.QueuedConnection)
        self._toolArgsDelta.connect(self._on_tool_args_delta)
        self._showPlanning.connect(self._on_show_planning)
        self._createStreamingPlan.connect(self._on_create_streaming_plan, QtCore.Qt.QueuedConnection)
        self._updateStreamingPlan.connect(self._on_update_streaming_plan)
        self._renderPlanViewer.connect(self._on_render_plan_viewer, QtCore.Qt.QueuedConnection)
        self._updatePlanStep.connect(self._on_update_plan_step, QtCore.Qt.QueuedConnection)
        self._askQuestionRequest.connect(self._on_render_ask_question, QtCore.Qt.QueuedConnection)
        
        # ── 流式 VEX 预览状态 ──
        self._streaming_preview = None          # 当前的 StreamingCodePreview widget
        self._streaming_preview_tool = ""       # 正在流式预览的工具名
        self._streaming_last_code = ""          # 上次解析出的完整代码（用于增量 diff）
        
        # 构建并缓存系统提示词（完整版：首轮；核心版：续接轮）
        self._system_prompt_think = self._build_system_prompt(with_thinking=True)
        self._system_prompt_no_think = self._build_system_prompt(with_thinking=False)
        self._cached_prompt_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_think, max_length=1800
        )
        self._cached_prompt_no_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_no_think, max_length=1500
        )
        # 核心规则子集版（续接轮使用，节省 ~2000 tokens/轮）
        self._cached_prompt_core_think = self.token_optimizer.optimize_system_prompt(
            self._build_system_prompt(with_thinking=True, full_rules=False), max_length=1200
        )
        self._cached_prompt_core_no_think = self.token_optimizer.optimize_system_prompt(
            self._build_system_prompt(with_thinking=False, full_rules=False), max_length=1000
        )
        # 兼容旧引用
        self._system_prompt = self._system_prompt_think
        self._cached_optimized_system_prompt = self._cached_prompt_think
        self._build_ui()
        self._wire_events()
        self._load_model_preference(restore_provider=True)  # 恢复上次使用的提供商和模型
        self._update_key_status()
        self._update_context_stats()
        self._refresh_mode_guard_ui()
        
        QtCore.QTimer.singleShot(5000, self._run_diagnostics_retention_cleanup)
        
        # 定期自动保存（每 60 秒），防止 Houdini 退出时丢失会话
        self._auto_save_timer = QtCore.QTimer(self)
        self._auto_save_timer.timeout.connect(self._periodic_save_all)
        self._auto_save_timer.start(60_000)  # 60 秒
        
        # ★ 启动时静默检查更新（延迟 5 秒，不阻塞初始化）— 已关闭
        # QtCore.QTimer.singleShot(5000, self._silent_update_check)
        
        # ★ 插件系统初始化（延迟 3 秒，不阻塞 UI）
        QtCore.QTimer.singleShot(3000, self._init_plugin_system)
        
        # ★ 语言切换时重建系统提示词 + 重新翻译 UI
        from .i18n import language_changed
        language_changed.changed.connect(self._rebuild_system_prompts)
        language_changed.changed.connect(self._retranslateUi)

    def _run_diagnostics_retention_cleanup(self):
        if not is_retention_cleanup_enabled():
            return
        try:
            summary = cleanup_diagnostics_retention(
                self._cache_dir,
                retention_days=retention_days_from_env(),
                current_session_id=self._session_id,
            )
            if summary.get('deleted') or summary.get('errors'):
                print(
                    "[Diagnostics Retention] "
                    f"deleted={summary.get('deleted', 0)} "
                    f"errors={summary.get('errors', 0)}"
                )
        except Exception as exc:
            print(f"[Diagnostics Retention] cleanup failed: {exc}")

    def _rebuild_system_prompts(self, _lang: str = ''):
        """语言切换后重建系统提示词（含 Ask/Agent 模式强制语言规则）"""
        self._system_prompt_think = self._build_system_prompt(with_thinking=True)
        self._system_prompt_no_think = self._build_system_prompt(with_thinking=False)
        self._cached_prompt_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_think, max_length=1800
        )
        self._cached_prompt_no_think = self.token_optimizer.optimize_system_prompt(
            self._system_prompt_no_think, max_length=1800
        )
        # 核心规则子集版同步重建
        self._cached_prompt_core_think = self.token_optimizer.optimize_system_prompt(
            self._build_system_prompt(with_thinking=True, full_rules=False), max_length=1200
        )
        self._cached_prompt_core_no_think = self.token_optimizer.optimize_system_prompt(
            self._build_system_prompt(with_thinking=False, full_rules=False), max_length=1000
        )
        self._system_prompt = self._system_prompt_think
        self._cached_optimized_system_prompt = self._cached_prompt_think
        print(f"[i18n] System prompts rebuilt for language: {_lang or get_language()}")

    def _retranslateUi(self, _lang: str = ''):
        """语言切换后重新翻译所有静态 UI 文本"""
        # Header 区域
        self._retranslate_header()
        # 输入区域
        self._retranslate_input_area()
        # 会话标签栏
        self._retranslate_session_tabs()
        print(f"[i18n] UI retranslated for language: {_lang or get_language()}")

    # ==========================================================
    # ★ 大脑启发式长期记忆系统
    # ==========================================================
    # 已迁移到 core/memory_mixin.py (MemoryMixin)

    # ==========================================================
    # ★ 插件系统 (Hook / Plugin System)
    # ==========================================================

    def _init_plugin_system(self):
        """初始化插件系统：加载插件、设置 UI Bridge、挂载按钮"""
        try:
            from ..utils.hooks import get_hook_manager, PluginUIBridge, load_all_plugins

            manager = get_hook_manager()

            # 创建 UI Bridge 并关联到 HookManager
            bridge = PluginUIBridge()
            # 设置按钮容器引用
            if hasattr(self, '_plugin_button_container'):
                bridge.set_button_container(self._plugin_button_container)
            # 设置聊天区域布局（供 insert_chat_card 使用）
            if hasattr(self, 'chat_layout') and self.chat_layout:
                bridge.set_chat_layout(self.chat_layout)
            bridge.set_ai_tab(self)
            manager.set_ui_bridge(bridge)

            # 加载所有插件
            load_all_plugins()

            # 挂载插件按钮
            bridge.mount_buttons()

            print("[Hook] 插件系统初始化完成")
        except Exception as e:
            print(f"[Hook] 插件系统初始化失败 (非致命): {e}")

    def _fire_session_hook(self, event: str, session_id: str):
        """触发会话相关的 Hook 事件"""
        try:
            from ..utils.hooks import get_hook_manager
            get_hook_manager().fire(event, session_id=session_id)
        except Exception:
            pass

    def _build_system_prompt(self, with_thinking: bool = True, full_rules: bool = True) -> str:
        return build_system_prompt(with_thinking=with_thinking, full_rules=full_rules)

    def _build_ui(self):
        # ---- 全局 QSS（由 ThemeEngine 从模板渲染） ----
        self.setObjectName("aiTab")
        self._theme = ThemeEngine()
        self._theme.load_template(Path(__file__).parent / "style_template.qss")
        self._theme.load_preference()
        self.setStyleSheet(self._theme.render())

        self.setMinimumWidth(320)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部设置栏
        header = self._build_header()
        layout.addWidget(header)
        
        # 会话标签栏（多会话切换）
        session_tabs_bar = self._build_session_tabs()
        layout.addWidget(session_tabs_bar)
        
        # 节点上下文栏
        self.node_context_bar = NodeContextBar()
        self.node_context_bar.refreshRequested.connect(self._refresh_node_context)
        layout.addWidget(self.node_context_bar)
        
        # 对话区域（多会话 - 使用 QStackedWidget）
        self.session_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.session_stack, 1)
        
        # 创建第一个会话
        self._create_initial_session()

        # 输入区域
        input_area = self._build_input_area()
        layout.addWidget(input_area)

    # ===================================================================
    # 以下方法已迁移到 Mixin 模块（通过继承自动可用）:
    #   HeaderMixin       → _build_header, _combo_style, _small_btn_style
    #   InputAreaMixin    → _build_input_area, mode toggles, @mention, tool status
    #   ChatViewMixin     → _add_user_message, _add_ai_response, scroll, toast
    #   AgentRunnerMixin  → title gen, confirm mode, tool constants
    #   SessionManagerMixin → session tabs, create/switch/close session
    # ===================================================================

    def _wire_events(self):
        self.btn_send.clicked.connect(self._on_send)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_key.clicked.connect(self._on_set_key)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_cache.clicked.connect(self._on_cache_menu)
        self.btn_optimize.clicked.connect(self._on_optimize_menu)
        self.btn_network.clicked.connect(self._on_read_network)
        self.btn_selection.clicked.connect(self._on_read_selection)
        self.btn_export_train.clicked.connect(self._on_export_training_data)
        self.btn_attach_image.clicked.connect(self._on_attach_image)
        # self.btn_update.clicked.connect(self._on_check_update)  # 已关闭
        self.btn_font_scale.clicked.connect(self._on_font_settings)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.model_combo.currentIndexChanged.connect(self._update_context_stats)
        
        # 字号缩放快捷键
        # QShortcut 在 PySide6 中位于 QtGui，PySide2 中位于 QtWidgets
        _QShortcut = getattr(QtWidgets, 'QShortcut', None) or QtGui.QShortcut
        _QShortcut(QtGui.QKeySequence("Ctrl+="), self, self._zoom_in)
        _QShortcut(QtGui.QKeySequence("Ctrl++"), self, self._zoom_in)
        _QShortcut(QtGui.QKeySequence("Ctrl+-"), self, self._zoom_out)
        _QShortcut(QtGui.QKeySequence("Ctrl+0"), self, self._zoom_reset)
        # 切换提供商或模型或 Think 时自动保存偏好
        self.provider_combo.currentIndexChanged.connect(self._save_model_preference)
        self.model_combo.currentIndexChanged.connect(self._save_model_preference)
        self.think_check.stateChanged.connect(self._save_model_preference)
        self.mode_combo.currentIndexChanged.connect(self._save_model_preference)
        self.read_combo.currentIndexChanged.connect(self._save_model_preference)
        self.input_edit.sendRequested.connect(self._on_send)
        
        # 多会话标签
        self.session_tabs.currentChanged.connect(self._switch_session)
        self.btn_new_session.clicked.connect(self._new_session)

    # ===== 字号缩放 =====

    


    # ActionCommandsMixin provides stop, user switch, key, clear, slash, read, scene, wrangle, and export actions.


    # ===== Token 优化管理 =====
    
    
