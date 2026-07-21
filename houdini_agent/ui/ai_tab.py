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

import atexit
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
from .cursor_widgets import (
    CursorTheme,
    UserMessage,
    AIResponse,
    PlanBlock,
    PlanViewer,
    StreamingPlanCard,
    AskQuestionCard,
    CollapsibleContent,
    StatusLine,
    ChatInput,
    SendButton,
    StopButton,
    TodoList,
    NodeContextBar,
    PythonShellWidget,
    SystemShellWidget,
    ClickableImageLabel,
    ToolStatusBar,
    NodeCompleterPopup,
    UpdateNotificationBanner,
)
import re

# Mixin 模块（从 ai_tab.py 拆分出的子模块）
from .header import HeaderMixin
from .input_area import InputAreaMixin
from .chat_view import ChatViewMixin
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
    ImageMixin,
    PreferencesMixin,
    DiagnosticsMixin,
    RuntimeStateMixin,
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
        
        # <think> 标签流式解析状态
        self._in_think_block = False
        self._tag_parse_buf = ""
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
        
        # ★ 启动时自动恢复上次的会话（从 sessions_manifest.json）
        self._restore_all_sessions()
        
        # 定期自动保存（每 60 秒），防止 Houdini 退出时丢失会话
        self._auto_save_timer = QtCore.QTimer(self)
        self._auto_save_timer.timeout.connect(self._periodic_save_all)
        self._auto_save_timer.start(60_000)  # 60 秒
        
        # 注册 atexit 回调和 QApplication.aboutToQuit 信号
        atexit.register(self._atexit_save)
        app = QtWidgets.QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._periodic_save_all)
        
        # ★ 启动时静默检查更新（延迟 5 秒，不阻塞初始化）— 已关闭
        # QtCore.QTimer.singleShot(5000, self._silent_update_check)
        
        # ★ 插件系统初始化（延迟 3 秒，不阻塞 UI）
        QtCore.QTimer.singleShot(3000, self._init_plugin_system)
        
        # ★ 语言切换时重建系统提示词 + 重新翻译 UI
        from .i18n import language_changed
        language_changed.changed.connect(self._rebuild_system_prompts)
        language_changed.changed.connect(self._retranslateUi)

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

    def _get_current_context_limit(self) -> int:
        """获取当前模型的上下文限制"""
        model = self.model_combo.currentText()
        return self._model_context_limits.get(model, 64000)
    
    def _show_token_stats_dialog(self):
        """显示详细 Token 统计对话框（对齐 Cursor：使用 TokenAnalyticsPanel）"""
        from houdini_agent.ui.cursor_widgets import TokenAnalyticsPanel
        records = getattr(self, '_call_records', []) or []
        harness_records = getattr(self, '_harness_trace_records', []) or []
        dialog = TokenAnalyticsPanel(records, self._token_stats, harness_records, parent=self)
        dialog.exec_()
        if dialog.should_reset_stats:
            self._reset_token_stats()

    def _capture_pre_agent_update_mode(self):
        """记录本轮 Agent 启动前的 Houdini update mode。

        该快照用于区分用户/hip 原始 Manual 和 Cook Guard 临时 Manual。
        已有快照时保留原值，避免恢复失败或 Plan 执行阶段覆盖真实原始模式。
        """
        if getattr(self, '_pre_agent_update_mode', None) is not None:
            return self._pre_agent_update_mode
        try:
            import hou  # type: ignore
            self._pre_agent_update_mode = hou.updateModeSetting()
        except Exception:
            self._pre_agent_update_mode = None
        return self._pre_agent_update_mode

    def _build_manual_mode_directive(self, confirm_mode: bool = True) -> str:
        """★ 若用户/hip 自身处于 Manual 更新模式，返回一段 system prompt 硬约束。

        判断依据是 _pre_agent_update_mode（在 _on_send 时记录的用户原始模式），
        而非当前 hou.updateModeSetting()：后者在 Agent 运行期间会被 Cook Guard
        临时切为 Manual，直接读会误把「Agent 临时保护」当成「用户持久设置」。
        只有当用户原始模式就是 Manual 时才注入，避免噪声。
        """
        try:
            import hou  # type: ignore
        except Exception:
            return ""
        user_mode = getattr(self, '_pre_agent_update_mode', None)
        try:
            if user_mode is None:
                return ""
            if user_mode != hou.updateMode.Manual:
                return ""
        except Exception:
            return ""
        mode_rule = (
            "4. 不要擅自把用户的更新模式改回 Auto——这是用户有意的设置。"
            if confirm_mode
            else "4. 直接执行模式下，为验证真实几何结果可临时切 Auto；Agent 结束时框架会恢复用户原始更新模式，最终总结中说明曾临时切 Auto。"
        )
        return (
            "[Houdini 状态 — 重要] 当前 hip 文件的更新模式是 **Manual（手动）**，这是用户的持久设置。\n"
            "含义：创建/修改节点（create_node、set_node_parameter、connect_nodes、"
            "set_display_flag 等）后，Houdini 不会自动 cook，视口与下游几何不会自动刷新。\n"
            "你必须遵守：\n"
            "1. 工具返回 success 只代表操作已排队，绝不能据此宣称「已生效/视口已更新/效果已完成」。\n"
            "2. 报告完成前，必须用 verify_network / check_errors / get_network_structure 确认真实结果。\n"
            "3. 若用户期望看到结果，在总结中主动说明「当前为 Manual 模式，需手动 cook 或切回 Auto 才能看到更新」。\n"
            + mode_rule
        )

    def _cook_displayed_nodes_if_manual(self):
        """★ 在 Manual 保护模式下，对当前工作区的 display 节点做针对性 cook
        
        v1.4.4 修复：Agent 运行期间处于 Manual 模式时，修改工具不触发 cook，
        导致读取工具（get_network_structure、check_errors 等）返回 stale 数据，
        AI 误以为操作未生效。
        
        策略：只 cook 当前 /obj 下各 geo 容器中设置了 Display Flag 的节点。
        这是最小范围的 cook，只刷新 AI 关注的节点数据而不触发全场景 cook。
        """
        if getattr(self, '_pre_agent_update_mode', None) is None:
            return  # 不在 Agent cook 保护模式下，无需处理
        try:
            import hou  # type: ignore
            if hou.updateModeSetting() != hou.updateMode.Manual:
                return  # 当前不是 Manual 模式，无需处理
            
            # 收集所有需要 cook 的 display 节点
            cooked = 0
            for child in hou.node('/obj').children():
                # 只处理 geo 类型容器（SOP 网络）
                if child.type().name() not in ('geo', 'subnet'):
                    continue
                try:
                    display_node = child.displayNode()
                    if display_node is not None:
                        # ★ 跳过含体积/VDB 的 display 节点：force cook 会驱动 GPU
                        #   体积重绘，与用户视口交互叠加时易引发主线程渲染竞态崩溃
                        #   （GR_VolumeVK，见 crash 分析 2026-07）。
                        if self._display_node_has_volume(display_node):
                            continue
                        display_node.cook(force=True)
                        cooked += 1
                except Exception:
                    pass  # 单个节点 cook 失败不影响其他
            if cooked:
                print(f"[Cook Guard] Manual 模式下针对性 cook 了 {cooked} 个 display 节点")
        except Exception as e:
            print(f"[Cook Guard] 针对性 cook 失败: {e}")

    @staticmethod
    def _display_node_has_volume(display_node) -> bool:
        """判断 display 节点几何是否含 Volume/VDB primitive（用于跳过强制 cook）。

        含体积/VDB 时返回 True，让调用方跳过 cook(force=True)，避免驱动
        GPU 体积重绘与用户视口交互竞态。判断失败时保守返回 False（不跳过）。
        """
        try:
            import hou  # type: ignore
            # 节点尚未 cook 过时不强制读取几何（geometry() 可能触发 cook），
            # 直接跳过以避免竞态：未 cook 的体积节点更危险。
            if display_node.needsToCook():
                return True
            geo = display_node.geometry()
            if geo is None:
                return False
            for ptype in (hou.primType.Volume, hou.primType.VDB):
                if geo.countPrimType(ptype) > 0:
                    return True
            return False
        except Exception:
            return False

    def _on_update_todo(self, todo_id: str, text: str, status: str):
        """更新 Todo 列表（跟随对话流内联显示）
        
        使用 agent 锚定的 todo_list / chat_layout，防止切换会话后
        写入错误的窗口。
        """
        try:
            # 优先使用 agent 锚定的目标（会话 A 运行时不受会话 B 影响）
            todo = self._agent_todo_list or self.todo_list
            layout = self._agent_chat_layout or self.chat_layout
            if not todo:
                return
            # 确保 todo_list 已在对应 chat_layout 中
            self._ensure_todo_in_chat(todo, layout)
        except RuntimeError:
            return  # widget 已被 clear 销毁
        if text:
            todo.add_todo(todo_id, text, status)
        else:
            todo.update_todo(todo_id, status)

    @staticmethod
    def _geometry_validation_signal_from_result(result: dict) -> dict:
        signal = result.get('validation_signal') if isinstance(result, dict) else None
        if isinstance(signal, dict):
            return {
                'manual_mode': bool(signal.get('manual_mode_detected')),
                'is_empty_geometry': bool(signal.get('display_geometry_empty')),
                'recommended_next_action': signal.get('recommended_next_action'),
            }
        if isinstance(result, dict):
            return {
                'manual_mode': bool(result.get('manual_mode')),
                'is_empty_geometry': bool(result.get('is_empty_geometry')),
                'recommended_next_action': result.get('recommended_next_action'),
            }
        return {'manual_mode': False, 'is_empty_geometry': False, 'recommended_next_action': None}

    def _apply_geometry_validation_loop_guard(self, tool_name: str, args: dict, result: dict, mode: str) -> dict:
        if not isinstance(result, dict) or not result.get('success'):
            return result
        state = getattr(self, '_geometry_validation_loop_state', None)
        if not isinstance(state, dict):
            state = {}
            self._geometry_validation_loop_state = state

        target = args.get('node_path') or args.get('parent_path') or ''
        if tool_name == 'cook_node' and target:
            entry = state.setdefault(target, {'empty_count': 0, 'cook_after_empty': False})
            if entry.get('empty_count', 0) > 0:
                entry['cook_after_empty'] = True
            return result

        if tool_name not in {'get_geometry_summary', 'verify_network'}:
            return result

        signal = self._geometry_validation_signal_from_result(result)
        if not (signal.get('manual_mode') and signal.get('is_empty_geometry')):
            if target:
                state.pop(target, None)
            return result

        entry = state.setdefault(target, {'empty_count': 0, 'cook_after_empty': False})
        entry['empty_count'] = int(entry.get('empty_count', 0) or 0) + 1
        if entry['empty_count'] >= 2 and entry.get('cook_after_empty'):
            hint = (
                'geometry_empty_after_cook: Manual update mode still reports empty geometry. '
                'Follow recommended_next_action=temporary_auto_validate in Direct Execute mode; '
                'do not keep using ordinary cook_node, parameter schema checks, or Sphere/Box replacement as validation.'
            )
            result['recovery_hint'] = hint
            self._append_session_diagnostics_records([
                {
                    'event_type': 'geometry_validation_loop_guard',
                    'tool': tool_name,
                    'target': target,
                    'mode': mode,
                    'manual_mode': True,
                    'is_empty_geometry': True,
                    'recommended_next_action': signal.get('recommended_next_action'),
                }
            ])
        return result

    def _execute_tool_with_policy(self, tool_name: str, kwargs: dict) -> dict:
        """Harness V2 policy gate for tool execution.

        This wrapper is intentionally thin and delegates real execution to the
        existing implementation so behavior can be migrated incrementally.
        """
        mode = 'plan' if self._plan_mode else ('agent' if self._agent_mode else 'ask')
        context = {
            'mode': mode,
            'plan_phase': self._plan_phase,
            'confirm_mode': bool(getattr(self, '_confirm_mode', False)),
        }
        decision = self._tool_policy_engine.decide(tool_name, kwargs, context)
        self._append_policy_timeline(tool_name, decision.action, decision.reason)

        if self._harness_state:
            self._harness_state.add_trace(
                'tool_policy',
                tool=tool_name,
                action=decision.action,
                reason=decision.reason,
            )

        if decision.action == 'deny':
            self._addStatus.emit(f"恢复建议: {tool_name} 被策略拒绝，可切到 Plan 或启用 Confirm")
            return {
                'success': False,
                'error': decision.reason or f'Tool blocked by policy: {tool_name}',
            }

        exec_kwargs = decision.patched_args if decision.patched_args is not None else kwargs

        if decision.action == 'ask':
            confirmed = self._request_tool_confirmation(tool_name, exec_kwargs)
            if self._harness_state:
                self._harness_state.add_trace(
                    'tool_policy_ask',
                    tool=tool_name,
                    confirmed=bool(confirmed),
                )
            if not confirmed:
                self._append_policy_timeline(tool_name, 'ask_cancel', decision.reason)
                return {
                    'success': False,
                    'error': decision.reason or tr('ask.user_cancel', tool_name),
                }

            self._append_session_diagnostics_records([
                {
                    'event_type': 'tool_call',
                    'phase': 'start',
                    'tool': tool_name,
                    'action': decision.action,
                    'mode': mode,
                    'args_keys': sorted(list(exec_kwargs.keys())),
                }
            ])
            started_at = time.time()
            result = self._execute_tool_impl(
                tool_name,
                exec_kwargs,
                skip_builtin_confirm=True,
            )
            result = sanitize_tool_result(result)
            result = self._apply_geometry_validation_loop_guard(tool_name, exec_kwargs, result, mode)
            self._append_session_diagnostics_records([
                {
                    'event_type': 'tool_call',
                    'phase': 'result',
                    'tool': tool_name,
                    'action': decision.action,
                    'mode': mode,
                    'success': bool(result.get('success')),
                    'error': str(result.get('error', '')) if not result.get('success') else '',
                    'duration_ms': int(max(0.0, time.time() - started_at) * 1000),
                }
            ])
            return result

        if decision.action == 'retry':
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_kwargs)
            current_retry = self._harness_state.policy_retry_counts.get(retry_key, 0) if self._harness_state else 0
            if current_retry >= self._policy_retry_limit:
                self._append_policy_timeline(tool_name, 'retry_limit', f"limit={self._policy_retry_limit}")
                self._append_session_diagnostics_records([
                    {
                        'event_type': 'policy_retry',
                        'tool': tool_name,
                        'action': 'retry_limit',
                        'retry_key': retry_key,
                        'retry_count': current_retry,
                        'retry_limit': self._policy_retry_limit,
                    }
                ])
                self._addStatus.emit(f"恢复建议: {tool_name} 达到重试上限，建议切 Ask 排查参数")
                return {
                    'success': False,
                    'error': (
                        f"Tool retry limit reached for {tool_name} "
                        f"({self._policy_retry_limit}/{self._policy_retry_limit})."
                    ),
                }
            if self._harness_state:
                self._harness_state.policy_retry_counts[retry_key] = current_retry + 1
                self._harness_state.retries += 1
            self._append_session_diagnostics_records([
                {
                    'event_type': 'policy_retry',
                    'tool': tool_name,
                    'action': 'retry',
                    'retry_key': retry_key,
                    'retry_count': current_retry + 1,
                    'retry_limit': self._policy_retry_limit,
                    'mode': mode,
                }
            ])

        if decision.action not in {'allow', 'retry'}:
            return {
                'success': False,
                'error': f"Unsupported policy action: {decision.action}",
            }

        started_at = time.time()
        self._append_session_diagnostics_records([
            {
                'event_type': 'tool_call',
                'phase': 'start',
                'tool': tool_name,
                'action': decision.action,
                'mode': mode,
                'args_keys': sorted(list(exec_kwargs.keys())),
            }
        ])
        result = self._execute_tool_impl(tool_name, exec_kwargs)
        result = sanitize_tool_result(result)
        result = self._apply_geometry_validation_loop_guard(tool_name, exec_kwargs, result, mode)
        self._append_session_diagnostics_records([
            {
                'event_type': 'tool_call',
                'phase': 'result',
                'tool': tool_name,
                'action': decision.action,
                'mode': mode,
                'success': bool(result.get('success')),
                'error': str(result.get('error', '')) if not result.get('success') else '',
                'duration_ms': int(max(0.0, time.time() - started_at) * 1000),
            }
        ])

        if decision.action == 'retry' and self._harness_state and result.get('success'):
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_kwargs)
            self._harness_state.policy_retry_counts.pop(retry_key, None)

        if not result.get('success'):
            self._append_policy_timeline(tool_name, 'exec_fail', str(result.get('error', '')))
            self._addStatus.emit(f"恢复建议: {tool_name} 失败，可打开 Policy 时间线查看并切换 Plan/Ask")

        return result

    def _execute_tool_with_todo(self, tool_name: str, **kwargs) -> dict:
        """执行工具，包含 Todo 相关的工具
        
        注意：此方法在后台线程调用，Houdini 操作必须通过信号调度到主线程执行。
        不依赖 hou 模块的工具（execute_shell 等）直接在后台线程执行，避免阻塞 UI。
        """
        kwargs.pop('_harness_policy_checked', None)
        kwargs.pop('_harness_skip_confirm', None)
        if self._harness_v2_enabled:
            return self._execute_tool_with_policy(tool_name, kwargs)

        return self._execute_tool_impl(tool_name, kwargs)

    def _skill_risk_level(self, skill_name: str) -> str:
        """返回 skill 的 risk_level（'low'/'normal'/'high'），未知/查询失败按最保守 'normal' 处理。

        用 name->risk_level 映射缓存到实例属性，避免每次调用都遍历 skill 列表。
        risk_level 语义：'low'=只读/不改场景（规划阶段可用）；其余=会改场景/建图（规划阶段拦）。
        """
        if not skill_name:
            return 'normal'
        cache = getattr(self, '_skill_risk_cache', None)
        if cache is None:
            cache = {}
            try:
                from ..skills import list_skills
                for info in list_skills():
                    cache[info.get('name', '')] = info.get('risk_level', 'normal')
            except Exception:
                pass
            self._skill_risk_cache = cache
        return cache.get(skill_name, 'normal')

    def _execute_tool_impl(self, tool_name: str, kwargs: dict, skip_builtin_confirm: bool = False) -> dict:
        """Execute a tool after the public harness/policy boundary has run."""
        kwargs = dict(kwargs or {})

        # ★ Stop 检测：用户请求停止时立即返回，不再排队新工具
        if self.client.is_stop_requested():
            return {"success": False, "error": "用户已请求停止"}
        
        # ★ 主线程忙保护：如果上一个工具超时了且主线程仍在 cook，
        #   不再堆积新的 BlockingQueuedConnection 信号（避免死锁）
        if getattr(self, '_main_thread_busy', False):
            if tool_name not in self._BG_SAFE_TOOLS:
                return {
                    "success": False,
                    "error": "主线程正忙（可能在进行耗时计算），请等待完成后重试。"
                            "建议：按停止按钮中断当前操作。"
                }
        
        # ★ Ask 模式安全守卫：拦截任何不在白名单的工具
        if not self._agent_mode and not self._plan_mode and tool_name not in self._ASK_MODE_TOOLS:
            # 额外检查 ToolRegistry（插件/Skill 工具可能注册了 ask 模式）
            _ask_allowed = False
            try:
                from ..utils.tool_registry import get_tool_registry
                _meta = get_tool_registry()._tools.get(tool_name)
                if _meta and _meta.enabled and "ask" in _meta.modes:
                    _ask_allowed = True
            except Exception:
                pass
            if not _ask_allowed:
                return {
                    "success": False,
                    "error": tr('ask.restricted', tool_name)
                }
        
        # ★ Plan 规划阶段安全守卫
        if self._plan_mode and self._plan_phase == 'planning':
            # run_skill 在规划阶段仅允许只读 skill（risk_level == 'low'）：
            # 只读 skill（get_node_card / analyze_* / inspect_*）可分析现网、查真实参数以设计计划；
            # 会改场景/建图的 skill（setup_*，risk_level != low）留到执行阶段。
            if tool_name == 'run_skill':
                skill_name = (kwargs or {}).get('skill_name', '')
                if self._skill_risk_level(skill_name) != 'low':
                    return {
                        "success": False,
                        "error": (f"Plan 规划阶段不允许执行会改场景/建图的 skill '{skill_name}'，"
                                  f"仅可运行只读 skill（如 get_node_card、analyze_*、inspect_*）辅助设计计划")
                    }
            else:
                allowed = self._PLAN_PLANNING_TOOLS | {'create_plan'}
                if tool_name not in allowed:
                    # 额外检查 ToolRegistry（插件/Skill 工具可能注册了 plan_planning 模式）
                    _plan_allowed = False
                    try:
                        from ..utils.tool_registry import get_tool_registry
                        _meta = get_tool_registry()._tools.get(tool_name)
                        if _meta and _meta.enabled and "plan_planning" in _meta.modes:
                            _plan_allowed = True
                    except Exception:
                        pass
                    if not _plan_allowed:
                        return {
                            "success": False,
                            "error": f"Plan 规划阶段不允许执行 {tool_name}，只能使用查询工具和 create_plan"
                        }

        
        # ★ 确认模式：对关键节点操作弹出预览确认
        if (not skip_builtin_confirm) and self._confirm_mode and tool_name in self._CONFIRM_TOOLS:
            confirmed = self._request_tool_confirmation(tool_name, kwargs)
            if not confirmed:
                return {
                    "success": False,
                    "error": tr('ask.user_cancel', tool_name)
                }
        
        # ★ 显示工具执行状态
        self._showToolStatus.emit(tool_name)
        
        try:
            # ★ Plan 模式专用工具处理
            if tool_name == "create_plan":
                return self._handle_create_plan(kwargs)
            
            elif tool_name == "update_plan_step":
                return self._handle_update_plan_step(kwargs)
            
            elif tool_name == "ask_question":
                return self._handle_ask_question(kwargs)
            
            # 处理 Todo 相关工具（纯 Python 操作，线程安全）
            if tool_name == "add_todo":
                todo_id = kwargs.get("todo_id", "")
                text = kwargs.get("text", "")
                status = kwargs.get("status", "pending")
                self._updateTodo.emit(todo_id, text, status)
                return {"success": True, "result": f"Added todo: {text}"}
            
            elif tool_name == "update_todo":
                todo_id = kwargs.get("todo_id", "")
                status = kwargs.get("status", "done")
                self._updateTodo.emit(todo_id, "", status)
                return {"success": True, "result": f"Updated todo {todo_id} to {status}"}
            
            # 不依赖 hou 的工具 → 直接在后台线程执行（避免阻塞 UI）
            if tool_name in self._BG_SAFE_TOOLS:
                return self._execute_tool_in_bg(tool_name, kwargs)
            
            # 其他工具需要在主线程执行（Houdini hou 模块操作）
            return self._execute_tool_in_main_thread(tool_name, kwargs)
        finally:
            self._hideToolStatus.emit()
    
    def _execute_tool_in_bg(self, tool_name: str, kwargs: dict) -> dict:
        """在后台线程直接执行工具（不阻塞 UI 主线程）
        
        仅用于不依赖 hou 模块的工具，如 execute_shell、search_local_doc 等。
        """
        try:
            return self.mcp.execute_tool(tool_name, kwargs)
        except Exception as e:
            import traceback
            return {"success": False, "error": tr('ai.bg_exec_err', f"{e}\n{traceback.format_exc()[:300]}")}
    
    # 主线程工具执行超时（秒）
    # 修改操作可能触发 Houdini cook，需要足够的超时时间
    _TOOL_MAIN_THREAD_TIMEOUT = 120.0

    def _execute_tool_in_main_thread(self, tool_name: str, kwargs: dict) -> dict:
        """在主线程执行工具（线程安全）
        
        使用 BlockingQueuedConnection + Queue 确保：
        1. Houdini 操作在主线程执行（hou 模块非线程安全，macOS 尤其严格）
        2. 多个工具调用不会竞争
        3. 结果安全传递回调用线程
        
        ★ macOS 崩溃修复说明：
        Houdini 嵌入 Qt 时，macOS 的 Cocoa 事件循环比 Windows 更严格。
        所有 hou API 调用必须在主线程执行，否则会导致段错误或 EXC_BAD_ACCESS。
        BlockingQueuedConnection 保证信号在目标线程（主线程）的事件循环中执行，
        且 emit 会阻塞调用线程直到槽函数返回，实现了线程安全的同步调用。
        
        ★ 防卡死机制（v1.4.3）：
        当 Houdini cook 耗时导致超时后，标记 _main_thread_busy，
        阻止后续工具调用堆积 BlockingQueuedConnection 信号（避免死锁）。
        主线程槽函数执行完毕后自动清除标记。
        """
        # 使用锁确保一次只有一个工具调用（避免并发竞争）
        with self._tool_lock:
            # 清空队列（防止残留数据）
            while not self._tool_result_queue.empty():
                try:
                    self._tool_result_queue.get_nowait()
                except queue.Empty:
                    break
            
            # 发送信号到主线程执行
            # BlockingQueuedConnection 会阻塞直到槽函数执行完成
            self._executeToolRequest.emit(tool_name, kwargs)
            
            # 从队列获取结果（有超时保护）
            # ★ 超时设为 120s，因为某些 Houdini 操作（如创建复杂节点、cook 高面数模型）
            #   可能需要较长时间。超时后标记主线程忙，防止后续信号堆积。
            try:
                result = self._tool_result_queue.get(timeout=self._TOOL_MAIN_THREAD_TIMEOUT)
                # 主线程正常返回 → 清除忙标记
                self._main_thread_busy = False
                return result
            except queue.Empty:
                # ★ 超时：主线程可能仍在执行 cook，标记为忙
                self._main_thread_busy = True
                print(f"[⚠️ TIMEOUT] 工具 {tool_name} 主线程执行超时 "
                      f"({self._TOOL_MAIN_THREAD_TIMEOUT}s)，"
                      f"可能 Houdini 正在进行耗时计算。后续工具调用将被暂停。")
                return {
                    "success": False,
                    "error": f"操作超时（{int(self._TOOL_MAIN_THREAD_TIMEOUT)}秒）：Houdini 主线程可能正在进行耗时计算（如 cook/渲染）。"
                             f"操作 {tool_name} 仍在后台执行中，请等待完成或按停止按钮中断。"
                }

    def _execute_tools_batch_in_main_thread(self, batch: list) -> list:
        """在主线程批量执行只读工具（减少 N 次信号往返为 1 次）

        Args:
            batch: [(tool_name, kwargs), ...]

        Returns:
            [result_dict, ...]（与 batch 顺序一致）
        """
        with self._tool_lock:
            while not self._tool_result_queue.empty():
                try:
                    self._tool_result_queue.get_nowait()
                except queue.Empty:
                    break

            self._executeToolBatchRequest.emit(batch)

            try:
                results = self._tool_result_queue.get(timeout=60.0)
                return results if isinstance(results, list) else [results]
            except queue.Empty:
                return [{"success": False, "error": tr('ai.main_exec_timeout')}] * len(batch)

    def _on_execute_tool_batch_main_thread(self, batch: list):
        """在主线程批量执行只读工具的槽函数

        所有工具在主线程依次执行（它们是快速的只读查询），
        然后将结果列表一次性放入队列返回给调用线程。
        """
        # ★ 读取前 Cook（v1.4.4）：批量读取也需要确保数据新鲜
        needs_cook = any(tn in self._COOK_BEFORE_READ_TOOLS for tn, _ in batch)
        if needs_cook:
            self._cook_displayed_nodes_if_manual()
        
        results = []
        for tool_name, kwargs in batch:
            try:
                result = self.mcp.execute_tool(tool_name, kwargs)
            except Exception as e:
                result = {"success": False, "error": str(e)}
            results.append(result)
        self._tool_result_queue.put(results)
        # ★ 吸收 Agent 操作造成的选择变化（与单工具执行同理）
        self._refresh_selection_baseline()
    # ------------------------------------------------------------------
    # Plan 模式工具处理
    # ------------------------------------------------------------------
    # 已迁移到 core/plan_mixin.py (PlanMixin)

    # 已自带 checkpoint 追踪的工具（在 _on_add_node_operation 中有专用分支）
    _SELF_TRACKING_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'create_wrangle_node',
        'delete_node', 'set_node_parameter',
    })

    @staticmethod
    def _snapshot_network_children() -> dict:
        """快照当前网络的子节点列表 {path: {name, type, path}}"""
        try:
            import hou  # type: ignore
            network = None
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    network = editor.pwd()
            except Exception:
                pass
            if not network:
                network = hou.node('/obj/geo1') or hou.node('/obj')
            if not network:
                return {}
            return {
                node.path(): {
                    'name': node.name(),
                    'type': node.type().name(),
                    'path': node.path(),
                }
                for node in network.children()
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    #  节点路径收集：记录工具涉及的节点，用于后续去歧义
    # ------------------------------------------------------------------

    _NODE_PATH_RE = re.compile(r'/(?:obj|out|shop|stage|tasks|ch|mat|img)/[\w/]+')

    def _collect_node_paths_from_tool(self, result: dict, arguments: dict = None):
        """从工具执行的结果和参数中提取 Houdini 节点路径，累积到 _session_node_map。"""
        import re
        paths: set[str] = set()

        # 从 result 和 arguments 中用正则提取所有形如 /obj/geo1/box1 的路径
        for source in (result, arguments):
            if not source:
                continue
            raw = json.dumps(source, default=str) if isinstance(source, dict) else str(source)
            paths.update(self._NODE_PATH_RE.findall(raw))

        # 从 _node_changes 中提取
        node_changes = result.get('_node_changes') if isinstance(result, dict) else None
        if node_changes:
            for n in node_changes.get('created', []):
                if n.get('path'):
                    paths.add(n['path'])
            for n in node_changes.get('deleted', []):
                if n.get('path'):
                    paths.add(n['path'])

        # 写入 _session_node_map: name → set[path]
        for p in paths:
            name = p.rsplit('/', 1)[-1]
            if name:
                self._session_node_map.setdefault(name, set()).add(p)

    def _resolve_bare_node_names(self, text: str) -> str:
        """保留 AI 回复中的相对/短节点引用。

        数据来源：当前会话中 AI 工具调用涉及的节点路径（_session_node_map）。
        旧版本会把裸节点名自动扩写成 /obj/... 完整路径；现在用户可见回复
        优先保留相对路径/短名称，工具参数仍使用完整路径。
        """
        return text

    @staticmethod
    def _diff_network_children(before: dict, after: dict):
        """对比前后子节点快照，返回 {created: [...], deleted: [...]} 或 None"""
        before_paths = set(before.keys())
        after_paths = set(after.keys())
        created = [after[p] for p in sorted(after_paths - before_paths)]
        deleted = [before[p] for p in sorted(before_paths - after_paths)]
        if not created and not deleted:
            return None
        return {'created': created, 'deleted': deleted}

    # ★ 会触发 Houdini cook 的工具集合
    # 这些工具执行时可能导致耗时的场景计算，需要特殊保护
    # 注意：create_node/create_nodes_batch/create_wrangle_node 已使用 run_init_scripts=False
    # 不会在节点创建时触发 cook，因此不需要 Manual 模式保护
    _COOK_TRIGGERING_TOOLS = frozenset({
        'connect_nodes', 'set_display_flag', 'set_node_parameter',
        'batch_set_parameters', 'execute_python', 'run_skill',
    })

    # ★ 需要在 Manual 保护模式下做针对性 cook 的读取工具
    # 这些工具需要读取节点最新计算结果（几何体、错误状态等），
    # 如果不 cook，AI 会看到 stale 数据从而误判操作结果
    _COOK_BEFORE_READ_TOOLS = frozenset({
        'get_network_structure', 'get_node_parameters', 'list_children',
        'check_errors', 'verify_network',
        'capture_viewport',  # 截图前需确保几何体已 cook
    })

    @QtCore.Slot(str, dict)
    def _on_execute_tool_main_thread(self, tool_name: str, kwargs: dict):
        """在主线程执行工具（槽函数）
        
        注意：此方法在主线程中执行，直接操作 Houdini API 是安全的。
        所有修改操作包裹在 undo group 中，支持一键撤销整个 Agent 操作。
        ★ 对于未自带 checkpoint 的修改工具，会在执行前后快照网络子节点以检测变更。
        
        ★ macOS 线程安全说明：
        Houdini 的 hou 模块不是线程安全的。macOS 上 Cocoa/AppKit 要求 UI 和
        场景操作必须在主线程执行，否则会导致 EXC_BAD_ACCESS。
        此方法通过 BlockingQueuedConnection 信号从后台线程触发，保证在主线程执行。
        
        ★ Cook 保护（v1.4.3）：
        对可能触发 cook 的修改工具，在执行前临时切换为手动更新模式，
        执行完毕后恢复原模式。这样 setDisplayFlag/connect 等操作不会
        立即触发耗时的场景 cook，避免阻塞主线程导致死锁。
        """
        # ★ 主线程断言（调试辅助：如果在非主线程执行，输出警告）
        _app = QtWidgets.QApplication.instance()
        if _app and _app.thread() != QtCore.QThread.currentThread():
            print(f"[⚠️ THREAD SAFETY] _on_execute_tool_main_thread 不在主线程执行! "
                  f"tool={tool_name}, current_thread={QtCore.QThread.currentThread()}")
        
        result = {"success": False, "error": tr('ai.unknown_err')}
        
        # 判断是否为修改操作（需要 undo group）
        _MUTATING_TOOLS = {
            "create_node", "create_nodes_batch", "create_wrangle_node",
            "delete_node", "rename_node", "set_node_parameter", "connect_nodes",
            "copy_node", "batch_set_parameters", "set_display_flag",
            "execute_python", "save_hip", "run_skill",
        }
        use_undo_group = tool_name in _MUTATING_TOOLS
        
        # ★ Cook 保护（v1.4.3）：对可能触发 cook 的工具，
        # 在 Agent 运行期间保持 Manual 模式，防止 cook 阻塞主线程
        # 模式恢复在 Agent 结束时统一处理（_restore_update_mode）
        if tool_name in self._COOK_TRIGGERING_TOOLS:
            try:
                import hou  # type: ignore
                if hou.updateModeSetting() != hou.updateMode.Manual:
                    hou.setUpdateMode(hou.updateMode.Manual)
            except Exception:
                pass
        
        # ★ 读取前 Cook（v1.4.4）：当 Agent 处于 Manual 保护模式下，
        # 读取工具执行前先对当前显示节点做一次针对性 cook，
        # 确保 AI 能看到修改后的最新结果（而非 stale 数据）
        if tool_name in self._COOK_BEFORE_READ_TOOLS:
            self._cook_displayed_nodes_if_manual()
        
        # ★ 对不自带 checkpoint 追踪的修改工具，做 before/after 快照
        should_snapshot = (
            tool_name in _MUTATING_TOOLS
            and tool_name not in self._SELF_TRACKING_TOOLS
            and tool_name != 'save_hip'  # save 无需快照
        )
        before_children = self._snapshot_network_children() if should_snapshot else {}
        
        try:
            # 对修改操作开启 undo group
            if use_undo_group:
                try:
                    import hou  # type: ignore
                    hou.undos.beginGroup(f"AI Agent: {tool_name}")
                except Exception:
                    use_undo_group = False  # hou 不可用则跳过
            
            result = self.mcp.execute_tool(tool_name, kwargs)
        except Exception as e:
            result = {"success": False, "error": tr('ai.tool_exec_err', str(e))}
        finally:
            # ★ 执行后快照 & diff，检测节点变更
            if should_snapshot and result.get("success"):
                try:
                    after_children = self._snapshot_network_children()
                    changes = self._diff_network_children(before_children, after_children)
                    if changes:
                        result['_node_changes'] = changes
                except Exception:
                    pass  # 快照失败不影响工具结果

            # 关闭 undo group
            if use_undo_group:
                try:
                    import hou  # type: ignore
                    hou.undos.endGroup()
                except Exception:
                    pass

            # ★ Cook 保护恢复：不在单个工具 finally 中恢复更新模式
            # 而是在 Agent 结束时统一恢复（_restore_update_mode），
            # 避免中间工具恢复后触发耗时 cook 阻塞主线程

            # ★ 清除主线程忙标记
            # 无论工具执行成功或失败，主线程已经空闲
            self._main_thread_busy = False

            # ★ 吸收 Agent 操作造成的选择变化：把当前选择刷新为新基线，
            #   避免下一次 poll 把 Agent 自己改的选择误判为用户手动操作。
            self._refresh_selection_baseline()

            # ★ macOS 崩溃修复：不再在此处调用 processEvents()
            # ─────────────────────────────────────────────────────
            # 旧代码：QtWidgets.QApplication.processEvents()
            #
            # 为什么移除？
            # 1. 此槽函数通过 BlockingQueuedConnection 从后台线程触发，
            #    在 emit 返回前主线程事件循环不会处理新事件——这是设计意图。
            # 2. processEvents() 会在槽函数内部递归处理事件队列，可能导致：
            #    a) 递归触发另一个 _executeToolRequest 信号（死锁或重入）
            #    b) 触发 Houdini 场景事件、渲染回调等（与当前 hou 操作竞争）
            #    c) macOS Cocoa runloop 重入，导致 EXC_BAD_ACCESS 崩溃
            # 3. BlockingQueuedConnection 返回后，主线程事件循环自然会继续
            #    处理排队的事件——无需手动 processEvents。
            # ─────────────────────────────────────────────────────

            # 将结果放入队列（线程安全）
            self._tool_result_queue.put(result)

    # ------------------------------------------------------------------
    # 伪造工具调用检测
    # ------------------------------------------------------------------
    # 所有注册的工具名称（用于检测伪造）
    _ALL_TOOL_NAMES = (
        'create_wrangle_node|get_network_structure'
        '|get_node_parameters|get_parameter_schema|inspect_node|set_node_parameter|create_node|create_nodes_batch'
        '|connect_nodes|cook_node|get_node_connections|suggest_connection|preview_node_operation'
        '|create_named_null|validate_node_network|delete_node|search_node_types|semantic_search_nodes'
        '|list_children|find_nodes|get_geometry_summary|get_scene_snapshot|read_selection|set_display_flag'
        '|copy_node|batch_set_parameters|save_hip|undo_redo'
        '|web_search|fetch_webpage|search_local_doc|get_houdini_node_doc'
        '|execute_python|execute_shell|check_errors|add_todo|update_todo'
        '|verify_network|run_skill|list_skills'
        '|layout_nodes|preview_layout_nodes'
        '|perf_start_profile|perf_stop_and_report'
    )
    _FAKE_TOOL_PATTERNS = re.compile(
        r'^\[(?:ok|err)\]\s*(?:' + _ALL_TOOL_NAMES + r')\s*[:\uff1a]',
        re.MULTILINE | re.IGNORECASE,
    )

    @staticmethod
    def _split_and_compress_assistant(content: str, max_reply: int = 1500) -> str:
        """分离工具摘要和 AI 回复并智能压缩
        
        用于旧格式 assistant 消息（没有 _reply_content 字段），
        尝试将 [工具执行结果] 段落和后续 AI 回复分开，
        压缩工具部分、保留回复部分。
        """
        # 查找工具结果段落结尾
        if '[工具执行结果]' not in content and '[工具结果]' not in content and '[Tool Result]' not in content:
            # 没有工具摘要，直接截断
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        # 找到最后一行 [ok] 或 [err]
        last_tool_line = max(content.rfind('\n[ok]'), content.rfind('\n[err]'))
        if last_tool_line <= 0:
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        # 找到该行结束位置
        next_nl = content.find('\n', last_tool_line + 1)
        if next_nl <= 0 or next_nl >= len(content) - 5:
            return content[:max_reply] + ('...' if len(content) > max_reply else '')
        
        tool_text = content[:next_nl]
        reply_text = content[next_nl:].strip()
        
        # 压缩工具部分
        tool_lines = tool_text.strip().split('\n')
        if len(tool_lines) > 6:
            tool_text = '\n'.join(tool_lines[:1] + tool_lines[-4:]) + f'\n... {len(tool_lines)-1} calls'
        elif len(tool_text) > 500:
            tool_text = tool_text[:500] + '...'
        
        # 保留回复部分
        if reply_text:
            reply_text = reply_text[:max_reply] + ('...' if len(reply_text) > max_reply else '')
        
        return tool_text + '\n\n' + reply_text if reply_text else tool_text

    @staticmethod
    def _fix_message_alternation(messages: list) -> list:
        """修复消息交替问题：合并连续的相同角色消息
        
        Cursor 风格消息格式支持：
        - user → assistant(tool_calls) → tool → assistant → user（正常格式）
        - 只合并连续的 user 或连续的 assistant（无 tool_calls 的）
        - 不合并带 tool_calls 的 assistant 消息（它们需要对应的 tool 结果）
        - tool 消息不参与合并
        """
        if not messages:
            return messages
        
        fixed = [messages[0]]
        for msg in messages[1:]:
            role = msg.get('role', '')
            prev_role = fixed[-1].get('role', '')
            
            # tool 消息永不合并（它们通过 tool_call_id 关联到 assistant）
            if role == 'tool' or prev_role == 'tool':
                fixed.append(msg)
                continue
            
            # 带 tool_calls 的 assistant 消息不合并（API 格式要求独立）
            if role == 'assistant' and msg.get('tool_calls'):
                fixed.append(msg)
                continue
            if prev_role == 'assistant' and fixed[-1].get('tool_calls'):
                fixed.append(msg)
                continue
            
            if role == prev_role and role in ('user', 'assistant'):
                # 合并连续的相同角色消息
                prev_content = fixed[-1].get('content')
                curr_content = msg.get('content')
                
                # ★ 多模态消息（content 是 list）不能直接用 + 拼接字符串
                # 策略：如果任一 content 是 list，提取文字部分再合并
                prev_text = prev_content
                curr_text = curr_content
                if isinstance(prev_content, list):
                    prev_text = '\n'.join(
                        p.get('text', '') for p in prev_content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    ) or ''
                if isinstance(curr_content, list):
                    curr_text = '\n'.join(
                        p.get('text', '') for p in curr_content
                        if isinstance(p, dict) and p.get('type') == 'text'
                    ) or ''
                
                prev_text = prev_text or ''
                curr_text = curr_text or ''
                
                fixed[-1] = fixed[-1].copy()
                
                # 如果两边都是纯文本，直接拼接
                # 如果任一方是多模态 list，保留最后一个的图片部分 + 合并文字
                if isinstance(prev_content, list) or isinstance(curr_content, list):
                    # 合并为多模态格式：保留所有 text 和 image_url
                    merged_parts = []
                    combined_text = (prev_text + '\n\n' + curr_text).strip()
                    if combined_text:
                        merged_parts.append({'type': 'text', 'text': combined_text})
                    # 收集所有图片部分
                    for src in (prev_content, curr_content):
                        if isinstance(src, list):
                            for part in src:
                                if isinstance(part, dict) and part.get('type') == 'image_url':
                                    merged_parts.append(part)
                    fixed[-1]['content'] = merged_parts if merged_parts else combined_text
                else:
                    fixed[-1]['content'] = prev_text + '\n\n' + curr_text
                
                if 'thinking' in msg and msg['thinking']:
                    prev_thinking = fixed[-1].get('thinking', '')
                    fixed[-1]['thinking'] = (prev_thinking + '\n' + msg['thinking']).strip()
            else:
                fixed.append(msg)
        
        return fixed

    @staticmethod
    def _format_tool_args_brief(tool_name: str, args: dict) -> str:
        """格式化工具参数摘要，保留关键参数让模型能参考上一轮调用
        
        对比 ChatGPT/Cursor：它们保留完整参数，但我们需要控制 token。
        折中方案：只保留最关键的参数，限制总长度。
        """
        if not args:
            return ""
        
        # 不同工具的关键参数（按重要性排序）
        _KEY_PARAMS = {
            'create_node': ['node_type', 'parent_path', 'node_name'],
            'create_wrangle_node': ['wrangle_type', 'node_name', 'run_over'],
            'create_nodes_batch': ['nodes'],
            'connect_nodes': ['from_path', 'to_path', 'input_index'],
            'set_node_parameter': ['node_path', 'param_name', 'value'],
            'get_node_parameters': ['node_path'],
            'get_network_structure': ['network_path'],
            'set_display_flag': ['node_path', 'display', 'render'],
            'execute_python': ['code'],
            'execute_shell': ['command'],
            'search_node_types': ['keyword'],
            'web_search': ['query'],
            'fetch_webpage': ['url'],
            'check_errors': ['node_path'],
            'run_skill': ['skill_name'],
        }
        
        key_params = _KEY_PARAMS.get(tool_name, list(args.keys())[:3])
        parts = []
        for k in key_params:
            if k in args:
                v = args[k]
                v_str = str(v)
                # 代码类参数只取前 60 字符
                if k in ('code', 'vex_code', 'command') and len(v_str) > 60:
                    v_str = v_str[:60] + '...'
                elif len(v_str) > 80:
                    v_str = v_str[:80] + '...'
                parts.append(f'{k}={v_str}')
        
        brief = ', '.join(parts)
        return brief[:200] if len(brief) > 200 else brief  # 总长度限制

    def _strip_fake_tool_results(self, text: str) -> str:
        """检测并移除 AI 伪造的工具调用结果文本。
        
        AI 有时会在回复中伪装成已经调用了工具，输出类似：
          [ok] web_search: 搜索 xxx
          [ok] fetch_webpage: 网页正文 xxx
        这些不是真正的工具调用，需要清除。
        """
        if not text:
            return text
        
        # 检测 [工具执行结果] 头部（这是系统自动生成的格式，AI 不应输出）
        if text.lstrip().startswith('[工具执行结果]') or text.lstrip().startswith('[Tool Result]'):
            # 整段就是伪造的工具摘要，移除头部和 [ok]/[err] 行
            lines = text.split('\n')
            real_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped in ('[工具执行结果]', '[Tool Result]'):
                    continue
                if self._FAKE_TOOL_PATTERNS.match(stripped):
                    continue
                real_lines.append(line)
            text = '\n'.join(real_lines).strip()
        
        # 检测散布在正文中的伪造行
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            if self._FAKE_TOOL_PATTERNS.match(line.strip()):
                continue
            cleaned.append(line)
        
        return '\n'.join(cleaned).strip()

    def _manage_context(self):
        """管理上下文长度 — Cursor 风格轮次裁剪
        
        核心原则（与 _progressive_trim 一致）：
        - **永不截断 user / assistant 消息**
        - 只压缩 tool 结果（role='tool' 的 content）
        - 按「轮次」（以 user 消息为分界）裁剪，保护最近 N 轮
        - 如果仅压缩 tool 仍不够，整轮删除最早的轮次
        - 保持 assistant(tool_calls) ↔ tool 的原生链不被打破
        """
        # ★ 使用 agent 锚定的 history（避免压缩错误 session）
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        if len(history) < 6:
            return  # 太少，不需管理
        
        current_tokens = self.token_optimizer.calculate_message_tokens(history)
        context_limit = self._get_current_context_limit()
        
        # 更新预算
        self.token_optimizer.budget.max_tokens = context_limit
        should_compress, reason = self.token_optimizer.should_compress(current_tokens, context_limit)
        
        if not (should_compress and self._auto_optimize):
            if reason and ('警告' in reason or 'warning' in reason.lower()):
                self._addStatus.emit(f"Note: {reason}")
            return

        self._append_session_diagnostics_records([
            {
                'event_type': 'context_compress',
                'phase': 'start',
                'reason': reason,
                'mode': 'plan' if self._plan_mode else ('agent' if self._agent_mode else 'ask'),
                'current_tokens': int(current_tokens),
                'context_limit': int(context_limit),
            }
        ])
        
        # ★ 深度睡眠：_manage_context 压缩前整理全部上下文为长期记忆
        if self._memory_initialized and self._reflection_module and not self._sleep_in_progress:
            _params = getattr(self, '_last_agent_params', {})
            if _params:
                self._addStatus.emit("😴 深度睡眠：正在整理全部上下文为长期记忆...")
                try:
                    self._sleep_in_progress = True
                    deep_result = self._reflection_module.deep_sleep(
                        session_id=self._session_id,
                        all_messages=list(history),
                        ai_client=self.client,
                        model=_params.get('model', 'deepseek-v4-flash'),
                        provider=_params.get('provider', 'deepseek'),
                    )
                    if deep_result.get("success"):
                        n_rules = len(deep_result.get("new_rules", []))
                        n_strats = len(deep_result.get("new_strategies", []))
                        self._addStatus.emit(
                            f"😴 深度睡眠完成: {n_rules} 条经验 + {n_strats} 条策略已写入长期记忆"
                        )
                except Exception as e:
                    print(f"[Sleep] _manage_context 深度睡眠异常: {e}")
                finally:
                    self._sleep_in_progress = False
        
        old_tokens = current_tokens
        
        # --- 按 user 消息划分轮次 ---
        rounds = []       # [[msg, msg, ...], ...]
        current_round = []
        for m in history:
            if m.get('role') == 'user' and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(m)
        if current_round:
            rounds.append(current_round)
        
        if len(rounds) <= 2:
            return  # 只有 1-2 轮，不裁剪
        
        # --- 第一遍：压缩旧轮次的 tool 结果（保留最近 60%）---
        n_rounds = len(rounds)
        protect_n = max(2, int(n_rounds * 0.6))
        for r_idx in range(n_rounds - protect_n):
            for m in rounds[r_idx]:
                if m.get('role') == 'tool':
                    c = m.get('content') or ''
                    if len(c) > 200:
                        m['content'] = self.client._summarize_tool_content(c, 200) if hasattr(self.client, '_summarize_tool_content') else c[:200] + '...[summary]'
        
        # 重新计算
        compressed = [m for rnd in rounds for m in rnd]
        new_tokens = self.token_optimizer.calculate_message_tokens(compressed)
        
        if new_tokens < context_limit * self.token_optimizer.budget.compression_threshold:
            # 压缩 tool 就够了
            history.clear()
            history.extend(compressed)
            saved = old_tokens - new_tokens
            if saved > 0:
                pct = saved / old_tokens * 100 if old_tokens else 0
                self._addStatus.emit(tr('opt.auto_status', saved))
                self._append_session_diagnostics_records([
                    {
                        'event_type': 'context_compress',
                        'phase': 'result',
                        'strategy': 'tool_summary_only',
                        'saved_tokens': int(saved),
                        'saved_percent': round(pct, 2),
                        'old_tokens': int(old_tokens),
                        'new_tokens': int(new_tokens),
                    }
                ])
            return
        
        # --- 第二遍：删除最早的完整轮次，直到低于阈值 ---
        target = int(context_limit * 0.65)  # 目标降到 65%
        while len(rounds) > 2:
            # 删除最早的轮次
            removed = rounds.pop(0)
            compressed = [m for rnd in rounds for m in rnd]
            new_tokens = self.token_optimizer.calculate_message_tokens(compressed)
            if new_tokens <= target:
                break
        
        # 在头部插入摘要提示
        summary_note = {
            'role': 'system',
            'content': tr('ai.old_rounds', n_rounds - len(rounds))
        }
        
        history.clear()
        history.append(summary_note)
        history.extend([m for rnd in rounds for m in rnd])
        
        saved = old_tokens - self.token_optimizer.calculate_message_tokens(history)
        if saved > 0:
            self._addStatus.emit(tr('opt.auto_status', saved))
            # 只在聊天区顶部插一条提示，不全量重渲染（避免 UI 闪烁/重绘）
            self._insert_compression_notice(n_rounds - len(rounds))
            pct = saved / old_tokens * 100 if old_tokens else 0
            self._append_session_diagnostics_records([
                {
                    'event_type': 'context_compress',
                    'phase': 'result',
                    'strategy': 'round_prune_with_summary',
                    'saved_tokens': int(saved),
                    'saved_percent': round(pct, 2),
                    'old_tokens': int(old_tokens),
                    'new_tokens': int(self.token_optimizer.calculate_message_tokens(history)),
                    'removed_rounds': int(n_rounds - len(rounds)),
                }
            ])
    
    def _insert_compression_notice(self, removed_rounds: int):
        """在聊天区顶部（第0位）插入一条上下文压缩提示，不重建整个对话区。"""
        from .cursor_widgets import StatusLine
        text = f"🗜 已自动压缩 {removed_rounds} 轮旧对话以节省 Token"
        notice = StatusLine(text)
        notice.setStyleSheet("background:#1e293b; color:#64748b; font-size:11px; padding:4px 12px; border-radius:4px;")
        # 插到 stretch 之前的第 0 位（最顶部）
        self.chat_layout.insertWidget(0, notice)

    def _compress_context(self):
        """压缩上下文 — 智能摘要，保留关键信息

        改进策略:
        1. 按轮次（user→assistant 对）提取信息，而非简单截取
        2. 提取用户意图、工具操作、关键结果、节点路径
        3. 识别错误和纠正行为
        4. 生成结构化摘要
        """
        if len(self._conversation_history) <= 4:
            return  # 太短不需要压缩

        # 将旧对话压缩成摘要
        old_messages = self._conversation_history[:-4]  # 保留最近 4 条
        recent_messages = self._conversation_history[-4:]

        # 按轮次分组
        rounds_info = []
        current_round = {"user": "", "assistant": "", "tools": [], "errors": []}

        for msg in old_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')

            if isinstance(content, list):
                # 多模态内容 → 提取文字
                content = ' '.join(
                    p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text'
                )

            if role == 'user':
                if current_round["user"]:
                    rounds_info.append(current_round)
                    current_round = {"user": "", "assistant": "", "tools": [], "errors": []}
                current_round["user"] = content[:120].replace('\n', ' ').strip()
            elif role == 'assistant' and content:
                # 去除 think 标签
                clean = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                if clean:
                    # 提取关键句（最后两行通常是结论）
                    lines = [l.strip() for l in clean.split('\n') if l.strip()]
                    summary_lines = lines[-2:] if len(lines) > 2 else lines
                    current_round["assistant"] = ' '.join(summary_lines)[:100]
                # 提取工具调用
                tool_calls = msg.get('tool_calls', [])
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get('function', {})
                        current_round["tools"].append(fn.get('name', ''))
            elif role == 'tool':
                tool_content = content or ''
                if 'error' in tool_content.lower() or 'fail' in tool_content.lower():
                    current_round["errors"].append(tool_content[:60])

        if current_round["user"]:
            rounds_info.append(current_round)

        # 生成结构化摘要
        summary_parts = []
        for i, rnd in enumerate(rounds_info[-5:], 1):  # 最多保留最近 5 轮
            parts = []
            if rnd["user"]:
                parts.append(f"Q: {rnd['user'][:60]}")
            if rnd["assistant"]:
                parts.append(f"A: {rnd['assistant'][:60]}")
            if rnd["tools"]:
                unique_tools = list(dict.fromkeys(rnd["tools"]))[:3]
                parts.append(f"Tools: {','.join(unique_tools)}")
            if rnd["errors"]:
                parts.append(f"⚠ {rnd['errors'][0][:40]}")
            if parts:
                summary_parts.append(f"R{i}: " + " | ".join(parts))

        # 提取提到的节点路径
        all_text = ' '.join(msg.get('content', '') for msg in old_messages if isinstance(msg.get('content'), str))
        node_paths = list(set(re.findall(r'/obj/[a-zA-Z0-9_/]+', all_text)))
        if node_paths:
            summary_parts.append(f"Nodes: {', '.join(node_paths[:5])}")

        # 生成上下文摘要
        if summary_parts:
            self._context_summary = "\n".join(summary_parts)
        else:
            self._context_summary = ""

        # 更新历史（只保留最近的）
        self._conversation_history = recent_messages

        print(f"[Context] 压缩上下文: 保留 {len(recent_messages)} 条消息, "
              f"摘要 {len(self._context_summary)} 字符 ({len(rounds_info)} 轮提取)")
    
    def _get_context_reminder(self) -> str:
        """生成上下文提醒（极简，强调复用）"""
        parts = []
        
        # 添加压缩的历史摘要（极简）
        if self._context_summary:
            parts.append(f"[Context Cache] {self._context_summary}")
        
        # 添加当前 Todo 状态（极简）
        todo_summary = self._get_todo_summary_safe()
        if todo_summary:
            # 只保留未完成的 todo
            if "0/" in todo_summary or "pending" in todo_summary.lower():
                parts.append(f"[TODO] {todo_summary.split(':', 1)[-1] if ':' in todo_summary else todo_summary}")
        
        # 提醒复用上下文（极简）
        if len(self._conversation_history) > 2:
            parts.append(f"[{len(self._conversation_history)} messages in context, reuse prior info]")
        
        return " | ".join(parts) if parts else ""

    def _auto_rag_retrieve(self, user_text: str,
                           scene_context: dict = None,
                           conversation_len: int = 0) -> str:
        """自动 RAG: 从用户消息 + Houdini 场景上下文检索文档并注入

        在后台线程调用，不涉及 Qt 控件。
        
        Args:
            user_text: 用户最新消息文本
            scene_context: 主线程收集的场景上下文 (network_path, selected_types, selected_names)
            conversation_len: 当前对话历史条数（用于动态调整注入量）
        """
        try:
            from ..utils.doc_rag import get_doc_index
            index = get_doc_index()
            
            # ★ 动态调整 RAG 注入量：对话越长越精简，避免浪费 token
            if conversation_len > 20:
                max_chars = 400   # 长对话：精简注入
            elif conversation_len > 10:
                max_chars = 800   # 中等对话
            else:
                max_chars = 1200  # 短对话：充分注入
            
            # ★ 场景上下文增强：把选中节点类型也加入检索查询
            enriched_query = user_text
            if scene_context:
                selected_types = scene_context.get('selected_types', [])
                if selected_types:
                    # 把选中节点的类型名加入查询，让 RAG 检索到相关文档
                    enriched_query += ' ' + ' '.join(selected_types)
            
            return index.auto_retrieve(enriched_query, max_chars=max_chars)
        except Exception:
            return ""

    def _get_todo_summary_safe(self) -> str:
        """线程安全地获取 Todo 摘要（优先使用 agent 锚定的 TodoList）"""
        todo = self._agent_todo_list or self.todo_list
        try:
            return todo.get_todos_summary() if todo else ""
        except Exception:
            return ""

    @QtCore.Slot(result=str)
    def _invoke_get_todo_summary(self) -> str:
        todo = self._agent_todo_list or self.todo_list
        return todo.get_todos_summary() if todo else ""

    # ===== URL 识别 =====
    
    def _extract_urls(self, text: str) -> list:
        """从文本中提取 URL"""
        # URL 正则表达式
        url_pattern = r'https?://[^\s<>"\'`\]\)]+[^\s<>"\'`\]\)\.,;:!?]'
        urls = re.findall(url_pattern, text)
        return urls
    
    def _process_urls_in_text(self, text: str) -> str:
        """处理文本中的 URL，添加提示让 AI 获取网页内容"""
        urls = self._extract_urls(text)
        
        if not urls:
            return text
        
        # 如果包含 URL，添加提示
        url_list = "\n".join(f"  - {url}" for url in urls)
        hint = tr('ai.detected_url', url_list)
        
        return text + hint

    def _start_agent_run(self, agent_params_overrides: dict = None, inject_scene: bool = True):
        """启动一次 Agent/Plan 执行，共享运行前准备逻辑。

        普通 Agent 与 Plan 执行阶段都必须走这里，避免 Plan copy 一套
        update-mode 快照、UI 状态、参数收集和线程启动逻辑。
        """
        # 先记录用户/hip 原始 Update Mode。后续 Cook Guard 临时 Manual
        # 不能被误判为用户持久 Manual。
        self._capture_pre_agent_update_mode()

        if inject_scene:
            self._auto_inject_scene_read()

        self._update_context_stats()

        # 开始运行（先设置状态，再创建回复块）
        self._set_running(True)

        # 创建 AI 回复块（必须在 _set_running 之后，否则会被清除）
        self._add_ai_response()
        self._agent_response = self._current_response
        self._start_active_aurora()

        agent_params = {
            'provider': self._current_provider(),
            'model': self.model_combo.currentText(),
            'use_web': self.web_check.isChecked(),
            'use_agent': self._agent_mode,  # True=Agent(full), False=Ask(read-only)
            'use_think': self.think_check.isChecked(),
            'context_limit': self._get_current_context_limit(),
            'scene_context': self._collect_scene_context(),
            'supports_vision': self._current_model_supports_vision(),
            'plan_mode': self._plan_mode,
            'confirm_mode': bool(getattr(self, '_confirm_mode', False)),
        }
        if agent_params_overrides:
            agent_params.update(agent_params_overrides)

        self._save_model_preference()

        thread = threading.Thread(target=self._run_agent, args=(agent_params,), daemon=True)
        thread.start()

    # ===== 事件处理 =====
    
    def _on_send(self):
        text = self.input_edit.toPlainText().strip()
        # 任意 session 有 agent 在跑就阻止发送（AIClient 是共享的，不支持并行）
        if not text or self._agent_session_id is not None:
            return

        provider = self._current_provider()
        if not self.client.has_api_key(provider):
            self._on_set_key()
            return

        # ★ Hook: on_session_start
        self._fire_session_hook('on_session_start', self._session_id)

        # 收集待发送的图片（在 clear 之前）
        has_images = bool(self._pending_images) and self._current_model_supports_vision()
        pending_imgs = [img for img in self._pending_images if img is not None] if has_images else []

        # 显示用户消息（含图片缩略图）
        self._add_user_message(text, images=pending_imgs)
        self.input_edit.clear()
        self._clear_pending_images()
        
        # 自动重命名标签（首条消息时）
        self._auto_rename_tab(text)
        
        # 检测 URL 并添加提示
        processed_text = self._process_urls_in_text(text)

        # 构建消息内容（文字或多模态）
        if pending_imgs:
            msg_content = self._build_multimodal_content(processed_text, pending_imgs)
            self._conversation_history.append({'role': 'user', 'content': msg_content})
        else:
            self._conversation_history.append({'role': 'user', 'content': processed_text})

        self._start_agent_run()

    def _select_agent_tools_for_message(self, user_message: str, use_web: bool = True) -> List[dict]:
        """Select a minimal Agent-mode tool set using ToolRegistry intent groups."""
        try:
            from ..utils.tool_registry import get_tool_registry
            reg = get_tool_registry()
            selected = reg.select_tools_for_request(user_message or "", mode='agent')
        except Exception as e:
            print(f"[Tool Selection] intent selection failed, falling back to core tools: {e}")
            selected = list(HOUDINI_TOOLS)

        if not use_web:
            selected = [
                t for t in selected
                if t.get('function', {}).get('name') not in ('web_search', 'fetch_webpage')
            ]

        return UltraOptimizer.optimize_tool_definitions(selected)

    def _run_agent(self, agent_params: dict):
        """后台运行 Agent
        
        Args:
            agent_params: 从主线程获取的参数（避免在后台线程访问 Qt 控件）
                - provider: AI 提供商
                - model: 模型名称
                - use_web: 是否启用网页搜索
                - use_agent: 是否启用 Agent 模式
                - use_think: 是否启用思考模式
                - context_limit: 上下文限制
        """
        # ⚠️ 从参数获取值，不直接访问 Qt 控件（线程安全）
        provider = agent_params['provider']
        model = agent_params['model']
        use_web = agent_params['use_web']
        use_agent = agent_params['use_agent']
        use_think = agent_params.get('use_think', True)
        context_limit = agent_params['context_limit']
        scene_context = agent_params.get('scene_context', {})
        supports_vision = agent_params.get('supports_vision', True)
        plan_mode = agent_params.get('plan_mode', False)
        plan_executing = agent_params.get('plan_executing', False)
        confirm_mode = agent_params.get('confirm_mode', True)
        if self._harness_v2_enabled:
            self._harness_state = HarnessRuntimeState(session_id=self._session_id)
        
        # ★ 保存 agent_params 供反思钩子使用
        self._last_agent_params = agent_params
        
        # ★ 存储 Think 开关状态，供 _drain_tag_buffer / _on_thinking_chunk 使用
        self._think_enabled = use_think
        
        try:
            # ========================================
            # 🔥 Cache 优化：保持消息前缀稳定
            # ========================================
            # 消息结构：[系统提示] + [历史消息] + [上下文提醒+当前请求]
            # 前缀（系统提示+历史消息）保持稳定，提升 cache 命中率
            
            # 1. 系统提示词（根据思考模式和轮次选择版本）
            # 对话已有历史（续接轮）→ 用核心规则子集，节省 ~2000 tokens/轮，提升 cache 命中率
            # 首轮（无历史或全是 system 消息）→ 用完整规则，确保 AI 掌握所有约束
            _has_prior_history = bool(
                self._conversation_history
                and any(m.get('role') != 'system' for m in self._conversation_history)
            )
            if _has_prior_history:
                sys_prompt = (
                    self._cached_prompt_core_think
                    if use_think else self._cached_prompt_core_no_think
                )
            else:
                sys_prompt = self._cached_prompt_think if use_think else self._cached_prompt_no_think

            # ★ Ask 模式：追加只读约束
            if not use_agent and not plan_mode:
                sys_prompt = sys_prompt + tr('ai.ask_mode_prompt')
            
            # ★ Plan 模式：追加规划或执行阶段提示词
            if plan_mode:
                if plan_executing:
                    sys_prompt = sys_prompt + tr('ai.plan_mode_execution_prompt')
                else:
                    self._plan_phase = 'planning'
                    sys_prompt = sys_prompt + tr('ai.plan_mode_planning_prompt')
            
            # ★ Agent 模式：追加复杂任务建议切换 Plan 的提示
            if use_agent and not plan_mode:
                sys_prompt = sys_prompt + tr('ai.agent_suggest_plan_prompt')
                # ★ 直接执行模式：抑制模型主动逐步征询确认，一次性完成整条流程
                if not confirm_mode:
                    sys_prompt = sys_prompt + tr('ai.direct_execute_prompt')
            
            # ★ 个性注入：将成长系统形成的个性特征追加到 system prompt 末尾
            personality_text = self._get_personality_injection()
            if personality_text:
                sys_prompt = sys_prompt + "\n\n" + personality_text
            
            # ★ L0 核心记忆加载：全部加载到 sys_prompt（上限 5 条，按 confidence TopK）
            if self._memory_initialized and self._memory_store:
                try:
                    core_mems = self._memory_store.get_core_memories(max_count=5)
                    if core_mems:
                        core_lines = [f"- {m.rule}" for m in core_mems]
                        sys_prompt = sys_prompt + (
                            "\n\n[Core Memory — 以下为核心记忆，仅供参考，请结合当前上下文判断]\n"
                            + "\n".join(core_lines)
                        )
                except Exception as e:
                    print(f"[Memory] L0 核心记忆加载失败: {e}")
            
            # ★ 用户自定义规则注入（类似 Cursor Rules）
            rules_text = self._get_user_rules_injection()
            if rules_text:
                sys_prompt = sys_prompt + "\n\n" + rules_text
            
            # ★ Houdini 更新模式硬约束注入（放在 system prompt 末尾，AI 无法忽略）
            # 只在用户/hip 自身处于 Manual 时注入——此时 _pre_agent_update_mode 记录的是
            # 用户原始模式（Agent 尚未切换或已恢复），若它就是 Manual 说明这是用户的持久设置。
            manual_directive = self._build_manual_mode_directive(confirm_mode=confirm_mode)
            if manual_directive:
                sys_prompt = sys_prompt + "\n\n" + manual_directive
            
            messages = [{'role': 'system', 'content': sys_prompt}]
            
            # ================================================================
            # 2. Cursor 风格历史消息：原生格式直通，不预压缩
            # ================================================================
            # 核心原则：
            # - assistant 消息完整保留（包括 content 和 tool_calls）
            # - tool 消息完整保留（包括 tool_call_id 和 content）
            # - user 消息完整保留
            # - 只清理内部元数据字段（thinking, python_shells 等）
            # - 压缩只在超限时由 _progressive_trim / auto_optimize 处理
            
            # 内部元数据字段列表（不发给 API）
            _INTERNAL_FIELDS = frozenset({
                '_reply_content', '_tool_summary', 'thinking',
                'python_shells', 'system_shells',
            })
            
            # ★ Cursor 风格：只保留当前轮次（最后一条 user 消息）的图片
            # 旧轮次的 image_url 剥离为纯文本，避免 base64 膨胀上下文
            _last_user_idx = None
            for _i in range(len(self._conversation_history) - 1, -1, -1):
                if self._conversation_history[_i].get('role') == 'user':
                    _last_user_idx = _i
                    break
            
            history_to_send = []
            for msg_idx, msg in enumerate(self._conversation_history):
                role = msg.get('role', '')
                
                if role == 'tool':
                    # ★ 新格式（Cursor 风格）：保留原生 tool 消息 ★
                    # 必须有 tool_call_id 才能发给 API
                    if msg.get('tool_call_id'):
                        clean = {k: v for k, v in msg.items() if k not in _INTERNAL_FIELDS}
                        history_to_send.append(clean)
                    else:
                        # 旧格式 tool 消息（无 tool_call_id）→ 转为 assistant 文本
                        tool_name = msg.get('name', 'unknown')
                        content = msg.get('content', '')
                        history_to_send.append({
                            'role': 'assistant',
                            'content': tr('ai.tool_result', tool_name, content[:500])
                        })
                
                elif role == 'assistant':
                    # ★ 完整保留 assistant 消息 ★
                    clean = {}
                    for k, v in msg.items():
                        if k in _INTERNAL_FIELDS:
                            continue
                        clean[k] = v
                    # 如果是旧格式的 [工具执行结果] 文本，也原样保留
                    # content 完整传递，不做任何截断
                    # 同时保留 tool_calls（如果有的话 — 新格式）
                    history_to_send.append(clean)
                
                elif role == 'user':
                    # ★ Cursor 风格图片处理：
                    # - 当前轮次（最后一条 user）+ 视觉模型 → 保留图片
                    # - 旧轮次 或 非视觉模型 → 剥离 image_url，只保留文字
                    content = msg.get('content')
                    is_current_round = (msg_idx == _last_user_idx)
                    
                    if isinstance(content, list):
                        if is_current_round and supports_vision:
                            # 当前轮 + 视觉模型：完整保留图片
                            history_to_send.append(msg)
                        else:
                            # 旧轮次 或 非视觉模型：剥离图片，只留文字
                            text_parts = []
                            for part in content:
                                if isinstance(part, dict) and part.get('type') == 'text':
                                    text_parts.append(part.get('text', ''))
                            text_only = '\n'.join(t for t in text_parts if t)
                            history_to_send.append({
                                'role': 'user',
                                'content': text_only or tr('ai.image_msg')
                            })
                    else:
                        # 纯文本消息：原样保留
                        history_to_send.append(msg)
                
                elif role == 'system':
                    # 系统消息（如历史摘要）保留
                    history_to_send.append(msg)
            
            # 修复 user/assistant 交替（仅处理连续的相同角色，不影响 tool 消息）
            history_to_send = self._fix_message_alternation(history_to_send)
            
            messages.extend(history_to_send)
            
            # 3. 自动 RAG 注入（从用户最新消息中提取关键词，检索相关文档）
            user_last_msg = ""
            if self._conversation_history:
                for msg in reversed(self._conversation_history):
                    if msg.get('role') == 'user':
                        raw_content = msg.get('content', '')
                        # 多模态内容（list）中提取文字部分
                        if isinstance(raw_content, list):
                            user_last_msg = ' '.join(
                                p.get('text', '') for p in raw_content if p.get('type') == 'text'
                            )
                        else:
                            user_last_msg = raw_content
                        break
            if user_last_msg:
                rag_context = self._auto_rag_retrieve(
                    user_last_msg,
                    scene_context=scene_context,
                    conversation_len=len(self._conversation_history),
                )
                if rag_context:
                    messages.append({'role': 'system', 'content': rag_context})
            
            # 4. ★ 长期记忆激活（"我想起来了"机制）
            # 在 RAG 文档之后、上下文提醒之前注入
            if user_last_msg:
                memory_context = self._activate_long_term_memory(
                    user_last_msg, scene_context=scene_context
                )
                if memory_context:
                    messages.append({'role': 'system', 'content': memory_context})
            
            # 5. ★ Plan 上下文注入（仅在 Plan 执行阶段 + 当前 session 匹配时）
            if plan_mode and plan_executing:
                try:
                    plan_ctx = self._get_plan_manager().get_plan_for_context(self._session_id)
                    if plan_ctx:
                        messages.append({'role': 'system', 'content': plan_ctx})
                except Exception as e:
                    print(f"[Plan] Context injection error: {e}")
            
            # 6. 上下文提醒（放在最后，不破坏 cache 前缀）
            # ⚠️ Cache 优化：动态内容放在末尾，保持前缀稳定
            context_reminder = self._get_context_reminder()
            if context_reminder:
                # 将上下文提醒作为系统消息添加到末尾
                messages.append({'role': 'system', 'content': f"[Context] {context_reminder}"})
            
            # ================================================================
            # ★ 睡眠机制：浅睡眠（每 N 轮用户提问触发）
            # ================================================================
            if self._memory_initialized and self._reflection_module:
                self._sleep_msg_counter += 1
                from ..utils.reflection import LIGHT_SLEEP_INTERVAL
                if self._sleep_msg_counter % LIGHT_SLEEP_INTERVAL == 0 and not self._sleep_in_progress:
                    # 收集最近 N 轮的消息用于浅睡眠总结
                    _sleep_messages = self._collect_recent_rounds(
                        self._conversation_history, LIGHT_SLEEP_INTERVAL
                    )
                    if _sleep_messages:
                        _sleep_sid = self._session_id
                        _sleep_model = model
                        _sleep_provider = provider
                        _sleep_client = self.client
                        _sleep_reflection = self._reflection_module
                        def _do_light_sleep():
                            self._sleep_in_progress = True
                            try:
                                result = _sleep_reflection.light_sleep(
                                    session_id=_sleep_sid,
                                    recent_messages=_sleep_messages,
                                    ai_client=_sleep_client,
                                    model=_sleep_model,
                                    provider=_sleep_provider,
                                )
                                if result.get("success"):
                                    self._addStatus.emit("💤 浅睡眠完成，经验已写入长期记忆")
                            finally:
                                self._sleep_in_progress = False
                        sleep_thread = threading.Thread(target=_do_light_sleep, daemon=True)
                        sleep_thread.start()
            
            # Cursor 风格预发送压缩：只压缩 tool 结果，保留 user/assistant 完整
            if self._auto_optimize:
                current_tokens = self.token_optimizer.calculate_message_tokens(messages)
                should_compress, _ = self.token_optimizer.should_compress(current_tokens, context_limit)
                
                if should_compress:
                    # ★ 深度睡眠：压缩前将完整上下文写入长期记忆
                    if self._memory_initialized and self._reflection_module and not self._sleep_in_progress:
                        self._addStatus.emit("😴 深度睡眠：正在整理全部上下文为长期记忆...")
                        try:
                            self._sleep_in_progress = True
                            deep_result = self._reflection_module.deep_sleep(
                                session_id=self._session_id,
                                all_messages=self._conversation_history,
                                ai_client=self.client,
                                model=model,
                                provider=provider,
                            )
                            if deep_result.get("success"):
                                n_rules = len(deep_result.get("new_rules", []))
                                n_strats = len(deep_result.get("new_strategies", []))
                                self._addStatus.emit(
                                    f"😴 深度睡眠完成: {n_rules} 条经验 + {n_strats} 条策略已写入长期记忆"
                                )
                        except Exception as e:
                            print(f"[Sleep] 深度睡眠异常: {e}")
                        finally:
                            self._sleep_in_progress = False
                    
                    old_tokens = current_tokens
                    # 分离系统提示和上下文提醒
                    first_system = messages[0] if messages and messages[0].get('role') == 'system' else None
                    last_context = messages[-1] if messages and ('[上下文]' in messages[-1].get('content', '') or '[Context]' in messages[-1].get('content', '')) else None
                    start_idx = 1 if first_system else 0
                    end_idx = -1 if last_context else len(messages)
                    body = messages[start_idx:end_idx] if end_idx != len(messages) else messages[start_idx:]
                    
                    # 按 user 消息划分轮次
                    rounds = []
                    cur_rnd = []
                    for m in body:
                        if m.get('role') == 'user' and cur_rnd:
                            rounds.append(cur_rnd)
                            cur_rnd = []
                        cur_rnd.append(m)
                    if cur_rnd:
                        rounds.append(cur_rnd)
                    
                    # 第一遍：压缩旧轮次 tool 结果
                    n_rounds = len(rounds)
                    protect_n = max(2, int(n_rounds * 0.6))
                    for r_idx in range(n_rounds - protect_n):
                        for m in rounds[r_idx]:
                            if m.get('role') == 'tool':
                                c = m.get('content') or ''
                                if len(c) > 200:
                                    m['content'] = self.client._summarize_tool_content(c, 200) if hasattr(self.client, '_summarize_tool_content') else c[:200] + '...[summary]'
                    
                    compressed_body = [m for rnd in rounds for m in rnd]
                    
                    # 如果仍超限，删除最早轮次
                    target = int(context_limit * 0.7)
                    while len(rounds) > 2:
                        test_body = [m for rnd in rounds for m in rnd]
                        test_msgs = ([first_system] if first_system else []) + test_body + ([last_context] if last_context else [])
                        if self.token_optimizer.calculate_message_tokens(test_msgs) <= target:
                            break
                        rounds.pop(0)
                    
                    compressed_body = [m for rnd in rounds for m in rnd]
                    
                    # 重组
                    messages = []
                    if first_system:
                        messages.append(first_system)
                    if n_rounds - len(rounds) > 0:
                        messages.append({
                            'role': 'system',
                            'content': tr('ai.old_rounds', n_rounds - len(rounds))
                        })
                    messages.extend(compressed_body)
                    if last_context:
                        messages.append(last_context)
                    
                    new_tokens = self.token_optimizer.calculate_message_tokens(messages)
                    saved = old_tokens - new_tokens
                    if saved > 0:
                        self._addStatus.emit(tr('opt.auto_status', saved))
            
            # ⚠️ 使用从主线程传入的参数（不直接访问 Qt 控件）
            # provider, model, use_web, use_agent 已在方法开头从 agent_params 获取
            
            # 调试：显示正在请求
            self._addStatus.emit(f"Requesting {provider}/{model}...")
            
            # 推理模型兼容：清理消息格式
            is_reasoning_model = AIClient.is_reasoning_model(model)
            cleaned_messages = []
            for msg in messages:
                role = msg.get('role', 'user')
                content = msg.get('content')
                has_tool_calls = 'tool_calls' in msg
                
                clean_msg = {'role': role}
                
                # ★ Cursor 风格：assistant 有 tool_calls 时 content 可为 None ★
                # Claude/Anthropic 代理拒绝 content="" + tool_calls 共存
                if role == 'assistant' and has_tool_calls:
                    clean_msg['content'] = content  # 保留 None（不转为空字符串）
                else:
                    clean_msg['content'] = content if content is not None else ''
                
                # 推理模型：assistant 消息需要 reasoning_content 字段
                if is_reasoning_model and role == 'assistant':
                    clean_msg['reasoning_content'] = msg.get('reasoning_content', '')
                # 保留 tool_calls 字段
                if has_tool_calls:
                    clean_msg['tool_calls'] = msg['tool_calls']
                # 保留 tool_call_id 字段
                if 'tool_call_id' in msg:
                    clean_msg['tool_call_id'] = msg['tool_call_id']
                # 保留 name 字段（用于 tool 消息）
                if 'name' in msg:
                    clean_msg['name'] = msg['name']
                
                # ★ 清理 assistant content 中的 <think> 标签 ★
                # 历史中的 thinking 不需要发给 API（浪费 token）
                if role == 'assistant' and clean_msg.get('content'):
                    c = clean_msg['content']
                    if '<think>' in c:
                        c = re.sub(r'<think>[\s\S]*?</think>', '', c).strip()
                        clean_msg['content'] = c or None
                
                cleaned_messages.append(clean_msg)
            messages = cleaned_messages
            
            # 使用缓存的优化后工具定义（只计算一次）
            if plan_mode and not plan_executing:
                # ★ Plan 规划阶段：只读工具 + create_plan + ask_question
                plan_filtered = [t for t in HOUDINI_TOOLS
                                 if t['function']['name'] in self._PLAN_PLANNING_TOOLS]
                plan_filtered.append(PLAN_TOOL_CREATE)
                plan_filtered.append(PLAN_TOOL_ASK_QUESTION)
                if not use_web:
                    plan_filtered = [t for t in plan_filtered
                                     if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(plan_filtered)
            elif plan_mode and plan_executing:
                # ★ Plan 执行阶段：暴露全部 Agent 工具（user_last_msg 是 "[Plan Confirmed] ..." 拼出的
                # 占位文本，按意图筛会丢掉 create_nodes_batch 等关键工具，导致 AI 退化到逐节点单建）。
                # 计划阶段已经在 create_plan 里规划好了每个 step 该用什么工具，执行阶段不该再过滤。
                exec_tools = list(HOUDINI_TOOLS)
                exec_names = {t.get('function', {}).get('name') for t in exec_tools}
                if PLAN_TOOL_UPDATE_STEP.get('function', {}).get('name') not in exec_names:
                    exec_tools = exec_tools + [PLAN_TOOL_UPDATE_STEP]
                if PLAN_TOOL_ASK_QUESTION.get('function', {}).get('name') not in exec_names:
                    exec_tools = exec_tools + [PLAN_TOOL_ASK_QUESTION]
                if not use_web:
                    exec_tools = [t for t in exec_tools
                                  if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(exec_tools)
            elif not use_agent:
                # ★ Ask 模式：只保留只读/查询工具
                ask_filtered = [t for t in HOUDINI_TOOLS
                                if t['function']['name'] in self._ASK_MODE_TOOLS]
                if not use_web:
                    ask_filtered = [t for t in ask_filtered
                                    if t['function']['name'] not in ('web_search', 'fetch_webpage')]
                tools = UltraOptimizer.optimize_tool_definitions(ask_filtered)
            else:
                # ★ Agent 模式：按本轮用户意图选择最小工具集，避免每轮暴露全量工具。
                tools = self._select_agent_tools_for_message(user_last_msg, use_web=use_web)
            
            # ★ 合并外部工具（HookManager 插件工具；Skill 通过 list_skills/run_skill 元工具暴露）
            try:
                from ..utils.hooks import get_hook_manager as _ghm_tools
                _ext = _ghm_tools().get_external_tools()
                if _ext:
                    tools = list(tools) + _ext
            except Exception:
                pass
            try:
                from ..utils.tool_registry import get_tool_registry
                _reg = get_tool_registry()
                # 兼容旧插件/外部工具：只合并显式注册到 ToolRegistry 的 skill 来源工具。
                _existing_names = {t.get('function', {}).get('name', '') for t in tools}
                for meta in _reg._tools.values():
                    if meta.source == "skill" and meta.enabled and meta.name not in _existing_names:
                        tools = list(tools) if not isinstance(tools, list) else tools
                        tools.append(meta.schema)
            except Exception:
                pass
            
            # ★ 非视觉模型：capture_viewport 降级为仅保存文件（不注入图片）
            # 不再移除工具——AI 仍可截图保存让用户自行查看
            if not supports_vision:
                _degraded_tools = []
                for _t in tools:
                    if _t.get('function', {}).get('name') == 'capture_viewport':
                        _t_copy = copy.deepcopy(_t)
                        _t_copy['function']['description'] = (
                            "截取当前 Houdini 3D 视口快照并保存到文件。"
                            "当前模型不支持图片分析，截图将保存到 output_path 指定的路径供用户查看。"
                            "必须指定 output_path 参数。"
                        )
                        _degraded_tools.append(_t_copy)
                    else:
                        _degraded_tools.append(_t)
                tools = _degraded_tools
            
            # ★ Plan 模式的静默工具集合（不在 UI 中显示的工具）
            _silent = self._SILENT_TOOLS | self._PLAN_SILENT_TOOLS if plan_mode else self._SILENT_TOOLS
            
            # ★ 通用回调：每轮 API 迭代开始时显示 "Generating..." 状态
            # 第1轮也显示，填补 Send → 首字之间的空白
            def _on_iter(i: int) -> None:
                self._showGenerating.emit()
                if self._harness_state:
                    self._harness_state.iteration = i
            
            if plan_mode:
                # ★ Plan 模式：使用 agent loop（规划或执行阶段均走此分支）
                _max_iter = 999 if plan_executing else 20
                
                # ★ Plan 续接回调：逻辑和状态统一由 PlanMixin._check_plan_resume 管理
                _plan_resume_callback = None
                if plan_executing:
                    self._init_plan_resume_state()
                    _plan_resume_callback = self._check_plan_resume
                
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=_max_iter,
                    max_tokens=None,
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        None  # create_plan 已在 on_tool_args_delta 中处理
                        if n == 'create_plan' else
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in _silent else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in _silent else None
                    ),
                    on_tool_args_delta=lambda name, delta, acc: (
                        self._toolArgsDelta.emit(name, delta, acc)
                    ),
                    on_iteration_start=_on_iter,
                    on_plan_incomplete=_plan_resume_callback,
                )
            elif use_agent:
                # ★ Agent 模式：完整 agent loop，可创建/修改/删除节点
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=999,  # 不限制迭代次数
                    max_tokens=None,  # 不限制输出长度
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_args_delta=lambda name, delta, acc: (
                        self._toolArgsDelta.emit(name, delta, acc)
                    ),
                    on_iteration_start=_on_iter,
                )
            elif tools:
                # ★ Ask 模式：仍用 agent loop 但只提供只读工具
                result = self.client.agent_loop_auto(
                    messages=messages,
                    model=model,
                    provider=provider,
                    max_iterations=15,  # Ask 模式限制迭代（主要是查询）
                    max_tokens=None,
                    enable_thinking=use_think,
                    supports_vision=supports_vision,
                    tools_override=tools,  # ★ 只传入只读工具
                    context_limit=context_limit,
                    on_content=lambda c: self._on_content_with_limit(c),
                    on_thinking=lambda t: self._on_thinking_chunk(t),
                    on_tool_call=lambda n, a: (
                        (self._addStatus.emit(f"[tool]{n}"), self._showToolStatus.emit(n))
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_tool_result=lambda n, a, r: (
                        (self._add_tool_result(n, r, a), self._hideToolStatus.emit())
                        if n not in self._SILENT_TOOLS else None
                    ),
                    on_iteration_start=_on_iter,
                )
            else:
                # 无工具的纯对话模式（fallback）
                self._showGenerating.emit()  # ★ 显示 "Generating..." 等待首字
                result = {'ok': True, 'content': '', 'tool_calls_history': [], 'iterations': 1, 'usage': {}}
                for chunk in self.client.chat_stream(
                    messages=messages, 
                    model=model, 
                    provider=provider, 
                    tools=None,
                    max_tokens=None,
                ):
                    if self.client.is_stop_requested():
                        self._agentStopped.emit()
                        return
                    
                    ctype = chunk.get('type')
                    if ctype == 'content':
                        content = chunk.get('content', '')
                        result['content'] += content
                        # 统一走 _on_content_with_limit（内含 <think> 解析）
                        self._on_content_with_limit(content)
                    elif ctype == 'thinking':
                        # 原生 reasoning_content
                        self._on_thinking_chunk(chunk.get('content', ''))
                    elif ctype == 'done':
                        # 收集 usage 统计
                        usage = chunk.get('usage', {})
                        if usage:
                            result['usage'] = usage
                    elif ctype == 'stopped':
                        self._agentStopped.emit()
                        return
                    elif ctype == 'error':
                        result = {'ok': False, 'error': chunk.get('error')}
                        break
            
            if self.client.is_stop_requested():
                self._agentStopped.emit()
                return
            
            if result.get('ok'):
                self._agentDone.emit(result)
            else:
                error_msg = result.get('error', 'Unknown error')
                # 显示更详细的错误
                self._agentError.emit(f"API Error: {error_msg}")
                
        except Exception as e:
            import traceback
            if self.client.is_stop_requested():
                self._agentStopped.emit()
            else:
                # 显示完整错误信息
                error_detail = f"{type(e).__name__}: {str(e)}"
                print(f"[AI Tab Error] {traceback.format_exc()}")  # 控制台输出
                self._agentError.emit(error_detail)

    # ActionCommandsMixin provides stop, user switch, key, clear, slash, read, scene, wrangle, and export actions.

    def _on_cache_menu(self):
        """显示缓存菜单"""
        menu = QtWidgets.QMenu(self)
        
        # 保存存档（独立文件）
        archive_action = menu.addAction("存档当前对话")
        archive_action.triggered.connect(self._archive_cache)
        
        # 加载对话
        load_action = menu.addAction("加载对话...")
        load_action.triggered.connect(self._load_cache_dialog)
        
        menu.addSeparator()
        
        # 压缩为摘要（减少 token）
        compress_action = menu.addAction("压缩旧对话为摘要")
        compress_action.triggered.connect(self._compress_to_summary)
        
        # 列出所有缓存
        list_action = menu.addAction("查看所有缓存")
        list_action.triggered.connect(self._list_caches)
        
        menu.addSeparator()
        
        # 自动保存开关
        auto_save_action = menu.addAction("[on] 自动保存" if self._auto_save_cache else "自动保存")
        auto_save_action.setCheckable(True)
        auto_save_action.setChecked(self._auto_save_cache)
        auto_save_action.triggered.connect(lambda: setattr(self, '_auto_save_cache', not self._auto_save_cache))
        
        # 显示菜单（btn_cache 是隐藏控件，用鼠标位置避免弹到屏幕最左边）
        menu.exec_(QtGui.QCursor.pos())
    
    @staticmethod
    def _strip_images_for_cache(history: list) -> list:
        """剥离 conversation_history 中的 base64 图片数据，
        用占位文本替代，大幅减小缓存文件体积。
        返回一份深拷贝，不修改原始 history。
        """
        stripped = []
        for msg in history:
            content = msg.get('content')
            if isinstance(content, list):
                # 多模态消息：content 是 [{type:text,...}, {type:image_url,...}, ...]
                new_parts = []
                for part in content:
                    if part.get('type') == 'image_url':
                        url = part.get('image_url', {}).get('url', '')
                        if url.startswith('data:'):
                            # 替换 base64 为占位符，保留 media type 信息
                            media_type = url.split(';')[0].replace('data:', '')
                            new_parts.append({
                                'type': 'text',
                                'text': f'[Image: {media_type}]',
                            })
                        else:
                            new_parts.append(copy.copy(part))
                    else:
                        new_parts.append(copy.copy(part))
                new_msg = msg.copy()
                new_msg['content'] = new_parts
                stripped.append(new_msg)
            else:
                stripped.append(msg)  # 非多模态消息直接引用（str/None 不可变）
        return stripped
    
    def _build_cache_data(self) -> dict:
        """构建缓存数据字典"""
        todo_data = []
        if hasattr(self, 'todo_list') and self.todo_list:
            todo_data = self.todo_list.get_todos_data()
        return {
            'version': '1.0',
            'session_id': self._session_id,
            'created_at': self._session_created_at,
            'message_count': len(self._conversation_history),
            'estimated_tokens': self._calculate_context_tokens(),
            'conversation_history': self._conversation_history,
            'context_summary': self._context_summary,
            'todo_summary': self.todo_list.get_todos_summary() if hasattr(self, 'todo_list') else "",
            'todo_data': todo_data,
            'token_stats': self._token_stats.copy(),
        }

    def _periodic_save_all(self):
        """定期保存所有会话（QTimer 触发 + aboutToQuit 触发）"""
        try:
            if not self._sessions:
                return
            # 只有存在对话时才保存
            has_any = False
            for sid, sdata in self._sessions.items():
                if sdata.get('conversation_history'):
                    has_any = True
                    break
            if not has_any:
                return
            self._save_all_sessions()
        except Exception as e:
            print(f"[Cache] 定期保存失败: {e}")
    
    def _atexit_save(self):
        """Python 退出时的最后保存机会（atexit 回调）
        
        ★ 此时 Qt widget 可能已被销毁，因此：
        - 使用 _tabs_backup（纯 Python 列表）代替遍历 QTabBar
        - 使用 try/except 包裹 todo_list 访问
        """
        # ★ stale 保护：新窗口创建时旧实例被标记为 inactive，
        #   此时不再写文件，避免覆盖新窗口已保存的正确数据
        if not getattr(self, '_ai_tab_active', True):
            return
        try:
            if not hasattr(self, '_sessions') or not self._sessions:
                return
            # ★ agent 仍在运行时，先把最新 history 刷回对应 session
            try:
                agent_sid = getattr(self, '_agent_session_id', None)
                if agent_sid and agent_sid in self._sessions:
                    if getattr(self, '_agent_history', None) is not None:
                        self._sessions[agent_sid]['conversation_history'] = self._agent_history
                    if getattr(self, '_agent_token_stats', None) is not None:
                        self._sessions[agent_sid]['token_stats'] = self._agent_token_stats
            except Exception:
                pass
            # 尝试同步当前状态（Qt widget 可能已销毁）
            try:
                if getattr(self, '_agent_session_id', None) != getattr(self, '_session_id', None):
                    self._save_current_session_state()
            except (RuntimeError, AttributeError):
                pass
            
            # ★ 优先使用 _tabs_backup（纯 Python 数据，不依赖 Qt）
            tabs_info = getattr(self, '_tabs_backup', [])
            if not tabs_info:
                # 如果备份也为空，尝试从 _sessions 字典的 key 中获取
                tabs_info = [(sid, f"Chat") for sid in self._sessions]
            
            # 直接写文件，不依赖 Qt 事件循环
            manifest_tabs = []
            for sid, tab_label in tabs_info:
                if not sid or sid not in self._sessions:
                    continue
                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    continue
                # 收集 todo 数据（widget 可能已销毁）
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError, Exception):
                    pass
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'created_at': sdata.get('created_at') or datetime.now().isoformat(),
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False)
                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })
            self._write_manifest(manifest_tabs, indent=None)
        except Exception:
            pass  # atexit 中不能抛出异常

    def _save_cache(self) -> bool:
        """自动保存：覆写同 session 文件 + manifest"""
        if not self._conversation_history:
            return False
        try:
            # 同步当前会话状态到 _sessions
            self._save_current_session_state()
            # ★ 同步 tab 备份
            self._sync_tabs_backup()
            
            cache_data = self._build_cache_data()
            # ★ 剥离 base64 图片以减小缓存文件大小
            cache_data['conversation_history'] = self._strip_images_for_cache(
                cache_data.get('conversation_history', [])
            )

            # 1. 覆写固定的 session 文件（一个 session 只有一个文件）
            session_file = self._cache_dir / f"session_{self._session_id}.json"
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            # 2. 同步更新 sessions_manifest.json（确保所有 tab 信息都是最新的）
            # ★ 不再写 cache_latest.json — 恢复由 sessions_manifest + session_*.json 管理
            self._update_manifest()

            if self._workspace_dir:
                self._update_workspace_cache_info()
            return True
        except Exception as e:
            print(f"[Cache] 自动保存失败: {e}")
            return False
    
    def _update_manifest(self):
        """更新 sessions_manifest.json 以反映当前所有标签的状态"""
        try:
            manifest_tabs = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                if not sid:
                    continue
                tab_label = self.session_tabs.tabText(i)
                sdata = self._sessions.get(sid, {})
                history = sdata.get('conversation_history', [])
                if not history:
                    try:
                        session_file = self._cache_dir / f"session_{sid}.json"
                        if session_file.exists():
                            session_file.unlink()
                    except Exception:
                        pass
                    continue

                # 检查该 session 是否有对话文件存在
                session_file = self._cache_dir / f"session_{sid}.json"
                if not session_file.exists():
                    continue
                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })
            self._write_manifest(manifest_tabs)
        except Exception as e:
            print(f"[Cache] 更新 manifest 失败: {e}")

    def _write_manifest(self, manifest_tabs: list, indent: int = 2):
        manifest = {
            'version': '1.0',
            'active_session_id': self._manifest_active_session_id(manifest_tabs),
            'tabs': manifest_tabs,
        }
        manifest_file = self._cache_dir / "sessions_manifest.json"
        with open(manifest_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=indent)
        clear_marker = self._cache_dir / "sessions_cleared.json"
        if manifest_tabs:
            try:
                if clear_marker.exists():
                    clear_marker.unlink()
            except Exception:
                pass
        else:
            try:
                with open(clear_marker, 'w', encoding='utf-8') as f:
                    json.dump({
                        'version': '1.0',
                        'cleared_at': datetime.now().isoformat(),
                    }, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def _manifest_active_session_id(self, manifest_tabs: list) -> str:
        """Return an active session that is actually present in the saved manifest."""
        saved_sids = [tab.get('session_id') for tab in manifest_tabs if tab.get('session_id')]
        session_id = getattr(self, '_session_id', '')
        if session_id in saved_sids:
            return session_id
        return saved_sids[0] if saved_sids else ""

    def _save_all_sessions(self) -> bool:
        """保存所有打开的会话到磁盘（关闭软件时调用）"""
        try:
            # ★ agent 仍在运行时，先把最新 history 刷回对应 session（防止关窗口时丢最后一轮）
            agent_sid = getattr(self, '_agent_session_id', None)
            if agent_sid and agent_sid in self._sessions:
                if self._agent_history is not None:
                    self._sessions[agent_sid]['conversation_history'] = self._agent_history
                if self._agent_token_stats is not None:
                    self._sessions[agent_sid]['token_stats'] = self._agent_token_stats
            # 先保存当前活跃会话的状态到 _sessions 字典
            if agent_sid != self._session_id:
                self._save_current_session_state()
            # ★ 同步 tab 备份（确保 atexit 时也能用）
            self._sync_tabs_backup()

            manifest_tabs = []
            for i in range(self.session_tabs.count()):
                sid = self.session_tabs.tabData(i)
                tab_label = self.session_tabs.tabText(i)
                if not sid or sid not in self._sessions:
                    continue

                sdata = self._sessions[sid]
                history = sdata.get('conversation_history', [])
                if not history:
                    # ★ 空会话：清理其磁盘上的旧 session 文件（防止残留）
                    try:
                        old_file = self._cache_dir / f"session_{sid}.json"
                        if old_file.exists():
                            old_file.unlink()
                    except Exception:
                        pass
                    continue  # 空会话不保存

                # 收集 todo 数据（防御 widget 已销毁的情况）
                todo_data = []
                try:
                    todo_list_obj = sdata.get('todo_list')
                    todo_data = todo_list_obj.get_todos_data() if todo_list_obj else []
                except (RuntimeError, AttributeError):
                    pass

                # 写 session 文件（★ 剥离 base64 图片以减小文件大小）
                cache_data = {
                    'version': '1.0',
                    'session_id': sid,
                    'created_at': sdata.get('created_at') or datetime.now().isoformat(),
                    'message_count': len(history),
                    'conversation_history': self._strip_images_for_cache(history),
                    'context_summary': sdata.get('context_summary', ''),
                    'todo_data': todo_data,
                    'token_stats': sdata.get('token_stats', {}),
                }
                session_file = self._cache_dir / f"session_{sid}.json"
                with open(session_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)

                manifest_tabs.append({
                    'session_id': sid,
                    'tab_label': tab_label,
                    'file': f"session_{sid}.json",
                })

            # 写 manifest 文件
            self._write_manifest(manifest_tabs)

            # ★ 不再写 cache_latest.json — 恢复由 sessions_manifest + session_*.json 管理
            # print(f"[Cache] 已保存 {len(manifest_tabs)} 个会话到磁盘")
            return bool(manifest_tabs)
        except Exception as e:
            print(f"[Cache] 保存所有会话失败: {e}")
            import traceback; traceback.print_exc()
            return False

    def _restore_all_sessions(self) -> bool:
        """从 sessions_manifest.json 恢复所有会话标签（启动时调用，幂等）

        恢复策略（严格信任 manifest）：
                - manifest 存在 → 仅按 manifest 列出的 tab 恢复。即使 tabs 为空，
                    也表示用户上次关闭时是空工作区，不再扫描孤儿 session_*.json。
                - manifest 不存在 → 兜底扫盘，把目录下所有 session_*.json
                    作为孤儿恢复，避免误删 manifest 时丢失全部历史会话。

        可通过实例属性 `_orphan_scan_on_restore` 强制改变行为：
            True  → 即使 manifest 存在也扫盘补 tab（旧行为）
            False → 即使 manifest 不存在也不扫盘
            None / 未设置 → 按上面默认策略
        """
        # ★ 幂等保护：防止 __init__ 和 main_window 延迟回调重复恢复
        if getattr(self, '_sessions_restored', False):
            return True
        try:
            manifest_file = self._cache_dir / "sessions_manifest.json"
            clear_marker = self._cache_dir / "sessions_cleared.json"
            if clear_marker.exists():
                self._write_manifest([])
                self._sessions_restored = True
                self._sync_tabs_backup()
                self._update_context_stats()
                return True

            manifest_exists = manifest_file.exists()

            manifest = {}
            tabs_info = []
            if manifest_exists:
                with open(manifest_file, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                tabs_info = manifest.get('tabs', []) or []

            # 决定是否扫盘补孤儿 session 文件
            scan_override = getattr(self, '_orphan_scan_on_restore', None)
            if scan_override is None:
                should_scan_orphans = not manifest_exists
            else:
                should_scan_orphans = bool(scan_override)

            if should_scan_orphans:
                known_sids = {tab.get('session_id') for tab in tabs_info if tab.get('session_id')}
                for session_file in sorted(self._cache_dir.glob("session_*.json")):
                    sid = session_file.stem.replace("session_", "", 1)
                    if sid in known_sids:
                        continue
                    try:
                        with open(session_file, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                    except Exception:
                        continue
                    history = cache_data.get('conversation_history', [])
                    if not history:
                        continue
                    label = "Chat"
                    for msg in history:
                        if msg.get('role') == 'user' and msg.get('content'):
                            label = str(msg['content'])[:18].replace('\n', ' ').strip() or label
                            if len(str(msg['content'])) > 18:
                                label += "..."
                            break
                    tabs_info.append({
                        'session_id': sid,
                        'tab_label': label,
                        'file': session_file.name,
                    })
                    known_sids.add(sid)

            # manifest 不存在且扫盘也没补到任何东西 → 没什么可恢复的
            if not tabs_info:
                if manifest_exists:
                    self._sessions_restored = True
                    self._sync_tabs_backup()
                    self._update_context_stats()
                    return True
                return False

            active_sid = manifest.get('active_session_id', '')
            active_tab_index = 0
            first_tab = True

            for tab_info in tabs_info:
                sid = tab_info.get('session_id', '')
                tab_label = tab_info.get('tab_label', 'Chat')
                session_file = self._cache_dir / tab_info.get('file', '')

                if not session_file.exists():
                    continue

                with open(session_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)

                history = cache_data.get('conversation_history', [])
                if not history:
                    continue

                context_summary = cache_data.get('context_summary', '')
                created_at = cache_data.get('created_at') or datetime.now().isoformat()
                todo_data = cache_data.get('todo_data', [])
                # ★ 从缓存中恢复 token 使用统计
                saved_token_stats = cache_data.get('token_stats', {
                    'input_tokens': 0, 'output_tokens': 0,
                    'reasoning_tokens': 0,
                    'cache_read': 0, 'cache_write': 0,
                    'total_tokens': 0, 'requests': 0,
                    'estimated_cost': 0.0,
                })

                if first_tab:
                    # 第一个 tab：加载到已有的初始会话中
                    first_tab = False
                    old_id = self._session_id

                    self._session_id = sid
                    self._session_created_at = created_at
                    self._conversation_history = history
                    self._context_summary = context_summary
                    self._token_stats = saved_token_stats

                    # 更新 sessions 字典
                    if old_id in self._sessions:
                        sdata = self._sessions.pop(old_id)
                        sdata['conversation_history'] = history
                        sdata['created_at'] = created_at
                        sdata['context_summary'] = context_summary
                        sdata['token_stats'] = saved_token_stats
                        self._sessions[sid] = sdata
                    elif sid not in self._sessions:
                        self._sessions[sid] = {
                            'scroll_area': self.scroll_area,
                            'chat_container': self.chat_container,
                            'chat_layout': self.chat_layout,
                            'todo_list': self.todo_list,
                            'conversation_history': history,
                            'created_at': created_at,
                            'context_summary': context_summary,
                            'current_response': None,
                            'token_stats': saved_token_stats,
                        }

                    # 恢复 todo 数据
                    if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                        self.todo_list.restore_todos(todo_data)
                        self._ensure_todo_in_chat(self.todo_list, self.chat_layout)

                    # 更新标签
                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, sid)
                            self.session_tabs.setTabText(i, tab_label)
                            if sid == active_sid:
                                active_tab_index = i
                            break

                    self._render_conversation_history()
                else:
                    # 后续 tab：创建新标签
                    self._save_current_session_state()
                    self._session_counter += 1

                    scroll_area, chat_container, chat_layout = self._create_session_widgets()
                    self.session_stack.addWidget(scroll_area)

                    tab_index = self.session_tabs.addTab(tab_label)
                    self.session_tabs.setTabData(tab_index, sid)

                    todo = self._create_todo_list(chat_container)
                    # 恢复 todo 数据
                    if todo_data:
                        todo.restore_todos(todo_data)
                        self._ensure_todo_in_chat(todo, chat_layout)

                    self._sessions[sid] = {
                        'scroll_area': scroll_area,
                        'chat_container': chat_container,
                        'chat_layout': chat_layout,
                        'todo_list': todo,
                        'conversation_history': history,
                        'created_at': created_at,
                        'context_summary': context_summary,
                        'current_response': None,
                        'token_stats': saved_token_stats,
                    }

                    # 临时切换到该标签以渲染历史
                    old_scroll = self.scroll_area
                    old_chat_container = self.chat_container
                    old_chat_layout = self.chat_layout
                    old_todo = self.todo_list
                    old_history = self._conversation_history
                    old_summary = self._context_summary
                    old_stats = self._token_stats
                    old_sid = self._session_id
                    old_created_at = self._session_created_at

                    self._session_id = sid
                    self._session_created_at = created_at
                    self._conversation_history = history
                    self._context_summary = context_summary
                    self._token_stats = saved_token_stats
                    self.scroll_area = scroll_area
                    self.chat_container = chat_container
                    self.chat_layout = chat_layout
                    self.todo_list = todo

                    self._render_conversation_history()

                    # 恢复
                    self._session_id = old_sid
                    self._session_created_at = old_created_at
                    self._conversation_history = old_history
                    self._context_summary = old_summary
                    self._token_stats = old_stats
                    self.scroll_area = old_scroll
                    self.chat_container = old_chat_container
                    self.chat_layout = old_chat_layout
                    self.todo_list = old_todo

                    if sid == active_sid:
                        active_tab_index = tab_index

            # 切换到之前活跃的标签
            if self.session_tabs.count() > 0:
                self.session_tabs.blockSignals(True)
                self.session_tabs.setCurrentIndex(active_tab_index)
                self.session_tabs.blockSignals(False)

                target_sid = self.session_tabs.tabData(active_tab_index)
                if target_sid and target_sid in self._sessions:
                    self._load_session_state(target_sid)
                    self.session_stack.setCurrentWidget(
                        self._sessions[target_sid]['scroll_area']
                    )

            # ★ 恢复完成后同步 tab 备份并更新 UI 显示
            self._sync_tabs_backup()
            self._update_manifest()
            self._update_token_stats_display()
            self._update_context_stats()
            self._sessions_restored = True  # 标记已恢复，防止重复
            print(f"[Cache] 已恢复 {self.session_tabs.count()} 个会话标签")
            return True

        except Exception as e:
            print(f"[Cache] 恢复多会话失败: {e}")
            import traceback; traceback.print_exc()
            return False

    def _archive_cache(self) -> bool:
        """手动存档：创建带时间戳的独立文件（不会被覆写）"""
        if not self._conversation_history:
            QtWidgets.QMessageBox.information(self, "提示", "没有对话历史可存档")
            return False
        try:
            cache_data = self._build_cache_data()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"archive_{self._session_id}_{timestamp}.json"
            archive_file = self._cache_dir / filename
            with open(archive_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            est = cache_data['estimated_tokens']
            self._addStatus.emit(f"已存档: {filename} (~{est} tokens)")
            return True
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "错误", f"存档失败: {str(e)}")
            return False
    
    def _update_workspace_cache_info(self):
        """更新工作区中的缓存信息（供主窗口保存工作区时使用）"""
        # 这个方法会被主窗口调用，用于更新工作区配置
        # 实际保存由主窗口的 _save_workspace 完成
        pass
    
    def _load_cache(self, cache_file: Path, silent: bool = False) -> bool:
        """从缓存文件加载对话历史（在新标签页中打开）
        
        Args:
            cache_file: 缓存文件路径
            silent: 是否静默加载（不显示确认对话框，用于工作区自动恢复）
        """
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 验证数据格式
            if 'conversation_history' not in cache_data:
                if not silent:
                    QtWidgets.QMessageBox.warning(self, "错误", "缓存文件格式无效")
                return False
            
            # 确认加载（静默模式下跳过）
            if not silent:
                msg_count = len(cache_data.get('conversation_history', []))
                reply = QtWidgets.QMessageBox.question(
                    self, "确认加载",
                    f"将在新标签页加载 {msg_count} 条对话记录。\n是否继续？",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                
                if reply != QtWidgets.QMessageBox.Yes:
                    return False
            
            history = cache_data.get('conversation_history', [])
            context_summary = cache_data.get('context_summary', '')
            created_at = cache_data.get('created_at') or datetime.now().isoformat()
            todo_data = cache_data.get('todo_data', [])
            cached_session_id = cache_data.get('session_id', str(uuid.uuid4())[:8])
            # ★ 恢复 token 使用统计
            saved_token_stats = cache_data.get('token_stats', {
                'input_tokens': 0, 'output_tokens': 0,
                'reasoning_tokens': 0,
                'cache_read': 0, 'cache_write': 0,
                'total_tokens': 0, 'requests': 0,
                'estimated_cost': 0.0,
            })
            
            if silent and not self._conversation_history:
                # 静默恢复：当前会话为空时直接加载到当前标签
                self._conversation_history = history
                self._context_summary = context_summary
                self._last_auto_read_context = None
                self._session_id = cached_session_id
                self._session_created_at = created_at
                self._token_stats = saved_token_stats
                # 恢复 todo 数据
                if todo_data and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.restore_todos(todo_data)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
                # 更新 sessions 字典
                if self._session_id in self._sessions:
                    self._sessions[self._session_id]['conversation_history'] = self._conversation_history
                    self._sessions[self._session_id]['created_at'] = created_at
                    self._sessions[self._session_id]['context_summary'] = self._context_summary
                    self._sessions[self._session_id]['token_stats'] = saved_token_stats
                elif self._sessions:
                    # 旧 session_id 已经变了，需要重新映射
                    old_id = list(self._sessions.keys())[0]
                    sdata = self._sessions.pop(old_id)
                    sdata['conversation_history'] = self._conversation_history
                    sdata['created_at'] = created_at
                    sdata['context_summary'] = self._context_summary
                    sdata['token_stats'] = saved_token_stats
                    self._sessions[self._session_id] = sdata
                    # 更新标签数据
                    for i in range(self.session_tabs.count()):
                        if self.session_tabs.tabData(i) == old_id:
                            self.session_tabs.setTabData(i, self._session_id)
                            break
                self._render_conversation_history()
                self._update_token_stats_display()
                self._update_context_stats()
                # 自动重命名标签
                if history:
                    for msg in history:
                        if msg.get('role') == 'user' and msg.get('content'):
                            self._auto_rename_tab(msg['content'])
                            break
                print(f"[Workspace] 自动恢复上下文: {len(self._conversation_history)} 条消息")
                return True
            
            # 非静默或当前会话非空：在新标签页中打开
            self._save_current_session_state()
            
            # 创建新标签
            self._session_counter += 1
            scroll_area, chat_container, chat_layout = self._create_session_widgets()
            self.session_stack.addWidget(scroll_area)
            
            # 用缓存文件名或首条用户消息作为标签名
            label = f"Chat {self._session_counter}"
            for msg in history:
                if msg.get('role') == 'user' and msg.get('content'):
                    short = msg['content'][:18].replace('\n', ' ').strip()
                    if len(msg['content']) > 18:
                        short += "..."
                    label = short
                    break
            
            tab_index = self.session_tabs.addTab(label)
            self.session_tabs.setTabData(tab_index, cached_session_id)
            
            todo = self._create_todo_list(chat_container)
            if todo_data:
                todo.restore_todos(todo_data)
                self._ensure_todo_in_chat(todo, chat_layout)
            
            self._sessions[cached_session_id] = {
                'scroll_area': scroll_area,
                'chat_container': chat_container,
                'chat_layout': chat_layout,
                'todo_list': todo,
                'conversation_history': history,
                'created_at': created_at,
                'context_summary': context_summary,
                'current_response': None,
                'token_stats': saved_token_stats,
            }
            
            # 切换到新标签
            self._session_id = cached_session_id
            self._session_created_at = created_at
            self._conversation_history = history
            self._context_summary = context_summary
            self._last_auto_read_context = None
            self._current_response = None
            self._token_stats = saved_token_stats
            self.scroll_area = scroll_area
            self.chat_container = chat_container
            self.chat_layout = chat_layout
            self.todo_list = todo
            
            self.session_tabs.blockSignals(True)
            self.session_tabs.setCurrentIndex(tab_index)
            self.session_tabs.blockSignals(False)
            self.session_stack.setCurrentWidget(scroll_area)
            
            self._render_conversation_history()
            self._update_token_stats_display()
            self._update_context_stats()
            
            if not silent:
                self._addStatus.emit(f"缓存已加载: {cache_file.name}")
            
            return True
            
        except Exception as e:
            if not silent:
                QtWidgets.QMessageBox.warning(self, "错误", f"加载缓存失败: {str(e)}")
            else:
                print(f"[Workspace] 加载缓存失败: {str(e)}")
            return False
    
    def _load_cache_silent(self, cache_file: Path) -> bool:
        """静默加载缓存（用于工作区自动恢复）"""
        return self._load_cache(cache_file, silent=True)
    
    def _load_cache_dialog(self):
        """显示加载缓存对话框"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "提示", "没有找到缓存文件")
            return
        
        # 创建选择对话框
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("选择缓存文件")
        dialog.setMinimumWidth(500)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # 文件列表
        list_widget = QtWidgets.QListWidget()
        for cache_file in cache_files:
            # 读取文件信息
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    estimated_tokens = data.get('estimated_tokens', 0)
                    created_at = data.get('created_at', '')
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    token_info = f" | ~{estimated_tokens:,} tokens" if estimated_tokens else ""
                    item_text = f"{cache_file.name}\n  {msg_count} 条消息{token_info} | {created_at}"
            except:
                item_text = cache_file.name
            
            item = QtWidgets.QListWidgetItem(item_text)
            item.setData(QtCore.Qt.UserRole, cache_file)
            list_widget.addItem(item)
        
        layout.addWidget(QtWidgets.QLabel("选择要加载的缓存文件:"))
        layout.addWidget(list_widget)
        
        # 按钮
        btn_layout = QtWidgets.QHBoxLayout()
        btn_load = QtWidgets.QPushButton("加载")
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_layout.addWidget(btn_load)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def on_load():
            current = list_widget.currentItem()
            if current:
                cache_file = current.data(QtCore.Qt.UserRole)
                if self._load_cache(cache_file):
                    dialog.accept()
        
        btn_load.clicked.connect(on_load)
        btn_cancel.clicked.connect(dialog.reject)
        
        dialog.exec_()
    
    def _list_caches(self):
        """列出所有缓存文件"""
        cache_files = sorted(
            set(self._cache_dir.glob("session_*.json"))
            | set(self._cache_dir.glob("archive_*.json"))
            | set(self._cache_dir.glob("cache_*.json")),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        
        if not cache_files:
            QtWidgets.QMessageBox.information(self, "提示", "没有找到缓存文件")
            return
        
        # 创建信息对话框
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("缓存文件列表")
        dialog.setMinimumSize(600, 400)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        
        # 文本显示
        text_edit = QtWidgets.QTextEdit()
        text_edit.setReadOnly(True)
        
        lines = ["缓存文件列表:\n"]
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    msg_count = len(data.get('conversation_history', []))
                    created_at = data.get('created_at', '')
                    session_id = data.get('session_id', '')
                    estimated_tokens = data.get('estimated_tokens', 0)
                    
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            pass
                    
                    size_kb = cache_file.stat().st_size / 1024
                    lines.append(f"  {cache_file.name}")
                    lines.append(f"   会话ID: {session_id}")
                    lines.append(f"   消息数: {msg_count}")
                    if estimated_tokens:
                        lines.append(f"   估算Token: ~{estimated_tokens:,}")
                    lines.append(f"   创建时间: {created_at}")
                    lines.append(f"   文件大小: {size_kb:.1f} KB")
                    lines.append("")
            except Exception as e:
                lines.append(f"[err] {cache_file.name} (读取失败: {str(e)})")
                lines.append("")
        
        text_edit.setPlainText("\n".join(lines))
        layout.addWidget(text_edit)
        
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec_()
    
    def _compress_to_summary(self):
        """将旧对话压缩为摘要，减少 token 消耗"""
        if len(self._conversation_history) <= 4:
            QtWidgets.QMessageBox.information(self, "提示", "对话历史太短，无需压缩")
            return
        
        # 确认操作
        reply = QtWidgets.QMessageBox.question(
            self, "确认压缩",
            f"将把前 {len(self._conversation_history) - 4} 条对话压缩为摘要，"
            f"保留最近 4 条完整对话。\n\n"
            f"这样可以大幅减少 token 消耗。是否继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        # 执行压缩
        old_messages = self._conversation_history[:-4]
        recent_messages = self._conversation_history[-4:]
        
        # 生成详细摘要
        summary_parts = ["[历史对话摘要 - 已压缩以节省 token]"]
        
        user_requests = []
        ai_results = []
        
        for msg in old_messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'user':
                # 提取用户请求的核心（前200字符）
                user_request = content[:200].replace('\n', ' ')
                if len(content) > 200:
                    user_request += "..."
                user_requests.append(user_request)
            
            elif role == 'assistant' and content:
                # 提取 AI 回复的关键信息
                lines = [l.strip() for l in content.split('\n') if l.strip()]
                if lines:
                    # 取最后一行或前150字符
                    result_summary = lines[-1][:150].replace('\n', ' ')
                    if len(lines[-1]) > 150:
                        result_summary += "..."
                    ai_results.append(result_summary)
        
        # 合并摘要
        if user_requests:
            summary_parts.append(f"\n用户请求 ({len(user_requests)} 条):")
            for i, req in enumerate(user_requests[:10], 1):  # 最多显示10条
                summary_parts.append(f"  {i}. {req}")
            if len(user_requests) > 10:
                summary_parts.append(f"  ... 还有 {len(user_requests) - 10} 条请求")
        
        if ai_results:
            summary_parts.append(f"\nAI 完成的任务 ({len(ai_results)} 条):")
            for i, res in enumerate(ai_results[:10], 1):  # 最多显示10条
                summary_parts.append(f"  {i}. {res}")
            if len(ai_results) > 10:
                summary_parts.append(f"  ... 还有 {len(ai_results) - 10} 条结果")
        
        summary_text = "\n".join(summary_parts)
        
        # 更新历史：用摘要替换旧对话
        self._conversation_history = [
            {'role': 'system', 'content': summary_text}
        ] + recent_messages
        
        # 更新上下文摘要
        self._context_summary = summary_text
        
        # 重新渲染
        self._render_conversation_history()
        
        # 更新统计
        self._update_context_stats()
        
        # 计算节省的 token
        old_tokens = sum(self._estimate_tokens(json.dumps(msg)) for msg in old_messages)
        new_tokens = self._estimate_tokens(summary_text)
        saved_tokens = old_tokens - new_tokens
        
        QtWidgets.QMessageBox.information(
            self, "压缩完成",
            f"对话已压缩！\n\n"
            f"原始: ~{old_tokens} tokens\n"
            f"压缩后: ~{new_tokens} tokens\n"
            f"节省: ~{saved_tokens} tokens ({saved_tokens/old_tokens*100:.1f}%)"
        )
    
    # ---------- 历史渲染辅助 ----------
    _CONTEXT_HEADERS = ('[Network structure]', '[Selected nodes]',
                        '[Auto-read: Network structure]', '[Auto-read: Selected nodes]',
                        '[网络结构]', '[选中节点]')

    # ★ 分批渲染常量（借鉴 markstream-vue 的批次策略）
    _BATCH_INITIAL = 30      # 首批渲染最后 N 条消息（用户最近看到的）
    _BATCH_SIZE = 15          # 后续每批渲染 N 条
    _BATCH_BUDGET_MS = 8      # 每批时间预算（毫秒）

    def _render_conversation_history(self):
        """重新渲染对话历史到 UI

        ★ 分批渲染策略（借鉴 markstream-vue）：
        1. 首批渲染最后 _BATCH_INITIAL 条消息（用户最近看到的）
        2. 用 QTimer.singleShot(0) 模拟 idle callback，逐批渲染剩余
        3. 每批设时间预算，超出则暂停让出主线程

        处理三种数据格式：
        1. role="user" 中嵌入 [Network structure] / [Selected nodes] 等上下文
           → 用户文字正常显示，上下文数据放入可折叠区域
        2. role="assistant" 以 [工具执行结果] 开头
           → 解析每一条 [ok]/[err]/✅/❌ 行，创建折叠式 ToolCallItem
        3. role="tool"（旧缓存格式）
           → 先 add_tool_call 再 set_tool_result（折叠式）
        """
        # 清空当前显示（保留末尾 stretch）
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 取消之前的分批渲染定时器
        if hasattr(self, '_batch_render_timer') and self._batch_render_timer is not None:
            self._batch_render_timer.stop()
            self._batch_render_timer = None

        messages = self._conversation_history
        if not messages:
            return

        # ★ 预扫描：将消息分组为逻辑"轮次"（每轮 = 一组相关消息）
        groups = self._group_messages_into_turns(messages)
        total_groups = len(groups)

        if total_groups <= self._BATCH_INITIAL:
            # 消息量小，一次性渲染
            self._render_message_groups(groups, 0, total_groups)
        else:
            # ★ 分批渲染：先渲染最后 _BATCH_INITIAL 组（用户最近看到的）
            # 早期消息用占位符
            early_count = total_groups - self._BATCH_INITIAL

            # 插入占位符
            self._batch_placeholder = QtWidgets.QLabel(
                f"⏳ 加载历史消息 ({early_count} 轮)..."
            )
            self._batch_placeholder.setObjectName("batchPlaceholder")
            self._batch_placeholder.setStyleSheet(
                "color: #64748b; padding: 8px 12px; font-size: 12px; "
                "font-style: italic; background: transparent;"
            )
            self._batch_placeholder.setAlignment(QtCore.Qt.AlignCenter)
            # 插入到 stretch 之前
            self.chat_layout.insertWidget(self.chat_layout.count() - 1,
                                         self._batch_placeholder)

            # 渲染最后 _BATCH_INITIAL 组
            self._render_message_groups(groups, early_count, total_groups)

            # 用 QTimer 分批渲染早期消息
            self._batch_groups = groups
            self._batch_cursor = early_count  # 从 early_count 向 0 回退
            self._batch_insert_pos = 0  # 早期消息插入到布局头部
            self._batch_render_timer = QtCore.QTimer(self)
            self._batch_render_timer.setSingleShot(True)
            self._batch_render_timer.timeout.connect(self._render_next_batch)
            self._batch_render_timer.start(0)  # 下一帧开始

    def _group_messages_into_turns(self, messages: list) -> list:
        """将消息列表分组为逻辑轮次
        
        返回: list of (start_idx, end_idx) 元组
        """
        groups: list = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get('role', '')

            if role == 'user':
                groups.append((i, i + 1))
                i += 1
            elif role == 'assistant':
                if msg.get('tool_calls'):
                    # 收集工具交互轮次
                    j = i + 1
                    while j < len(messages):
                        m = messages[j]
                        r = m.get('role', '')
                        if r == 'tool':
                            j += 1
                        elif r == 'assistant':
                            j += 1
                            if not m.get('tool_calls'):
                                break
                        else:
                            break
                    groups.append((i, j))
                    i = j
                else:
                    # 普通 assistant + 后续 tool 消息
                    j = i + 1
                    while j < len(messages) and messages[j].get('role') == 'tool':
                        j += 1
                    groups.append((i, j))
                    i = j
            elif role == 'system':
                groups.append((i, i + 1))
                i += 1
            else:
                groups.append((i, i + 1))
                i += 1
        return groups

    def _render_message_groups(self, groups: list, start: int, end: int):
        """渲染 [start, end) 范围内的消息组"""
        messages = self._conversation_history
        for gi in range(start, end):
            si, ei = groups[gi]
            try:
                self._render_single_group(messages, si, ei)
            except Exception:
                import traceback
                traceback.print_exc()

    def _render_single_group(self, messages: list, si: int, ei: int):
        """渲染一个消息组"""
        msg = messages[si]
        role = msg.get('role', '')
        raw_content = msg.get('content', '') or ''
        if isinstance(raw_content, list):
            content = '\n'.join(
                part.get('text', '') for part in raw_content
                if isinstance(part, dict) and part.get('type') == 'text'
            )
        else:
            content = raw_content

        if role == 'user':
            self._render_user_history(content)

        elif role == 'assistant':
            if msg.get('tool_calls'):
                turn_msgs = messages[si:ei]
                self._render_native_tool_turn(turn_msgs)
            else:
                tool_msgs = [messages[j] for j in range(si + 1, ei)
                             if messages[j].get('role') == 'tool']

                if content.lstrip().startswith('[工具执行结果]'):
                    self._render_tool_summary_history(content, msg)
                else:
                    response = self._add_ai_response()
                    thinking = msg.get('thinking', '')
                    if thinking:
                        response.add_thinking(thinking)
                        response.thinking_section.finalize()
                    self._render_old_tool_msgs(response, tool_msgs)
                    self._restore_shell_widgets(response, msg)
                    response.set_content(content)
                    response.status_label.setText("历史")
                    response.finalize()
                    parts = []
                    if thinking:
                        parts.append("思考")
                    if tool_msgs:
                        parts.append(f"{len(tool_msgs)}次调用")
                    label = f"历史 | {', '.join(parts)}" if parts else "历史"
                    response.status_label.setText(label)

        elif role == 'system' and '[历史对话摘要' in content:
            response = self._add_ai_response()
            response.add_collapsible("历史对话摘要", content)
            response.status_label.setText("历史摘要")
            response.finalize()
            response.status_label.setText("历史摘要")

    def _render_next_batch(self):
        """分批渲染回调 — 渲染下一批早期消息（从后向前，插入到布局头部）"""
        if not hasattr(self, '_batch_groups') or not self._batch_groups:
            return
        if self._batch_cursor <= 0:
            # 全部渲染完毕，移除占位符
            self._finish_batch_render()
            return

        batch_start = max(0, self._batch_cursor - self._BATCH_SIZE)
        batch_end = self._batch_cursor
        start_time = time.time()

        # ★ 早期消息需要插入到占位符之前（即布局的第 0 个位置开始）
        # 我们从 batch_start 到 batch_end 按顺序渲染，每个 widget 插入到
        # 占位符位置之前（insert_pos 递增）
        messages = self._conversation_history
        insert_pos = self._batch_insert_pos  # 在此位置之前插入
        rendered_count = 0

        for gi in range(batch_start, batch_end):
            si, ei = self._batch_groups[gi]
            try:
                widgets_before = self.chat_layout.count()
                self._render_single_group(messages, si, ei)
                widgets_after = self.chat_layout.count()
                added = widgets_after - widgets_before

                # 将新添加的 widget 移动到正确位置（占位符之前）
                if added > 0:
                    for _ in range(added):
                        # 取出最后添加的 widget（在 stretch 之前）
                        from_idx = self.chat_layout.count() - 2  # -1 是 stretch, -2 是新 widget
                        item = self.chat_layout.takeAt(from_idx)
                        if item and item.widget():
                            self.chat_layout.insertWidget(insert_pos, item.widget())
                            insert_pos += 1
                    rendered_count += added
            except Exception:
                import traceback
                traceback.print_exc()

            # 时间预算检查
            elapsed_ms = (time.time() - start_time) * 1000
            if elapsed_ms > self._BATCH_BUDGET_MS and gi < batch_end - 1:
                self._batch_cursor = gi + 1
                self._batch_insert_pos = insert_pos
                remaining = gi + 1
                if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                    try:
                        self._batch_placeholder.setText(
                            f"⏳ 加载历史消息 ({remaining} 轮)..."
                        )
                    except RuntimeError:
                        pass
                self._batch_render_timer.start(0)
                return

        self._batch_cursor = batch_start
        self._batch_insert_pos = insert_pos

        if self._batch_cursor > 0:
            if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
                try:
                    self._batch_placeholder.setText(
                        f"⏳ 加载历史消息 ({self._batch_cursor} 轮)..."
                    )
                except RuntimeError:
                    pass
            self._batch_render_timer.start(0)
        else:
            self._finish_batch_render()

    def _finish_batch_render(self):
        """完成分批渲染，清理占位符"""
        if hasattr(self, '_batch_placeholder') and self._batch_placeholder:
            try:
                self._batch_placeholder.setVisible(False)
                self._batch_placeholder.deleteLater()
            except RuntimeError:
                pass
            self._batch_placeholder = None
        self._batch_groups = None
        self._batch_render_timer = None

    # ------------------------------------------------------------------
    def _replay_todo_from_tool_call(self, tool_name: str, arguments_str: str):
        """从历史工具调用中恢复 todo 项（不显示在 UI 执行列表中）
        
        注意：todo 数据现在通过 todo_data 字段在缓存中保存/恢复，
        此方法仅作为兼容旧缓存的后备方案。
        """
        try:
            if isinstance(arguments_str, str) and arguments_str:
                args = json.loads(arguments_str)
            elif isinstance(arguments_str, dict):
                args = arguments_str
            else:
                return
            if tool_name == 'add_todo':
                tid = args.get('todo_id', '')
                text = args.get('text', '')
                status = args.get('status', 'pending')
                if tid and text and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.add_todo(tid, text, status)
                    self._ensure_todo_in_chat(self.todo_list, self.chat_layout)
            elif tool_name == 'update_todo':
                tid = args.get('todo_id', '')
                status = args.get('status', 'done')
                if tid and hasattr(self, 'todo_list') and self.todo_list:
                    self.todo_list.update_todo(tid, status)
        except Exception:
            pass  # 解析失败忽略

    # ------------------------------------------------------------------
    def _render_native_tool_turn(self, turn_msgs: list):
        """渲染 Cursor 风格原生工具调用轮次
        
        turn_msgs 格式：
          assistant(tool_calls) → tool → [assistant(tool_calls) → tool →] ... → assistant(reply)
        静默工具（add_todo/update_todo）不显示在执行列表中，但会恢复 todo 数据。
        """
        response = self._add_ai_response()
        tool_count = 0
        final_content = ''
        thinking = ''
        final_msg = {}
        
        for m in turn_msgs:
            r = m.get('role', '')
            if r == 'assistant':
                tc_list = m.get('tool_calls', [])
                if tc_list:
                    # 工具调用 assistant 消息：注册每个工具调用
                    for tc in tc_list:
                        fn = tc.get('function', {})
                        name = fn.get('name', 'unknown')
                        # 静默工具：恢复 todo 但不显示在执行列表
                        if name in self._SILENT_TOOLS:
                            self._replay_todo_from_tool_call(name, fn.get('arguments', ''))
                            continue
                        response.add_status(f"[tool]{name}")
                        tool_count += 1
                else:
                    # 最终回复 assistant 消息
                    final_content = m.get('content', '') or ''
                    thinking = m.get('thinking', '')
                    final_msg = m
            elif r == 'tool':
                tc_id = m.get('tool_call_id', '')
                t_content = m.get('content', '') or ''
                # 从 tool_call_id 查找对应的工具名
                t_name = self._find_tool_name_by_id(turn_msgs, tc_id) or 'tool'
                # 静默工具的结果也不显示
                if t_name in self._SILENT_TOOLS:
                    continue
                success = not t_content.lstrip().startswith('[err]') and 'error' not in t_content[:50].lower()
                prefix = "[ok] " if success else "[err] "
                response.add_tool_result(t_name, f"{prefix}{t_content}")
        
        # 恢复 thinking
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()
        
        # 恢复 Shell 折叠面板
        self._restore_shell_widgets(response, final_msg)
        
        # AI 回复内容
        if final_content:
            response.set_content(final_content)
        
        # 状态标签
        parts = []
        if thinking:
            parts.append("思考")
        if tool_count > 0:
            parts.append(f"{tool_count}次调用")
        label = f"历史 | {', '.join(parts)}" if parts else "历史"
        response.status_label.setText(label)
        response.finalize()
        response.status_label.setText(label)

    @staticmethod
    def _find_tool_name_by_id(messages: list, tool_call_id: str) -> str:
        """从消息列表中根据 tool_call_id 查找对应的工具名"""
        if not tool_call_id:
            return ''
        for m in messages:
            if m.get('role') == 'assistant':
                for tc in m.get('tool_calls', []):
                    if tc.get('id') == tool_call_id:
                        return tc.get('function', {}).get('name', '')
        return ''

    # ------------------------------------------------------------------
    def _render_user_history(self, content: str):
        """渲染用户历史消息，长上下文自动折叠"""
        # 检查是否包含 [Network structure] 等上下文注入
        split_pos = -1
        header_tag = ''
        for tag in self._CONTEXT_HEADERS:
            pos = content.find(tag)
            if pos != -1:
                split_pos = pos
                header_tag = tag
                break

        if split_pos > 0 and len(content) > 300:
            # 用户实际输入 + 上下文注入
            user_text = content[:split_pos].strip()
            context_data = content[split_pos:]
            # 显示用户实际文字
            if user_text:
                self._add_user_message(user_text)
            # 上下文放进折叠区域
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), context_data)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        elif split_pos == 0 and len(content) > 300:
            # 纯上下文（无用户文字），整块折叠
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), content)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        else:
            self._add_user_message(content)

    # ------------------------------------------------------------------
    _TOOL_LINE_PREFIXES = ('[ok] ', '[err] ', '\u2705 ', '\u274c ')

    def _render_tool_summary_history(self, content: str, msg: dict = None):
        """渲染 [工具执行结果] 格式的 assistant 消息

        格式示例：
          [工具执行结果]
          [ok] get_network_structure: ## 网络结构: /obj
          网络类型: obj          ← 上一条的续行
          节点数量: 0            ← 上一条的续行
          [ok] create_node: /obj/geo1
        """
        if msg is None:
            msg = {}
        response = self._add_ai_response()

        # 先按行分组：以 [ok]/[err]/✅/❌ 开头的行开始新条目，
        # 其他行归到前一条目的续行
        entries = []  # [(first_line, [continuation_lines])]
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped or stripped == '[工具执行结果]':
                # 空行或标题→如果有上一条目，添加空行到续行（保留格式）
                if entries:
                    entries[-1][1].append('')
                continue
            is_new_entry = any(stripped.startswith(p) for p in self._TOOL_LINE_PREFIXES)
            if is_new_entry:
                entries.append((stripped, []))
            elif entries:
                entries[-1][1].append(stripped)
            # else: 没有前导条目的散行，忽略

        tool_count = 0
        for first_line, cont_lines in entries:
            t_name = 'unknown'
            success = True
            # 解析前缀
            rest = first_line
            for prefix in self._TOOL_LINE_PREFIXES:
                if first_line.startswith(prefix):
                    if 'err' in prefix or '\u274c' in prefix:
                        success = False
                    rest = first_line[len(prefix):]
                    break
            # 解析 tool_name: result
            if ':' in rest:
                parts = rest.split(':', 1)
                t_name = parts[0].strip()
                first_result = parts[1].strip() if len(parts) > 1 else ''
            else:
                first_result = rest

            # 合并续行
            all_parts = [first_result] + cont_lines
            t_result = '\n'.join(all_parts).strip()

            # 静默工具不显示在执行列表
            if t_name in self._SILENT_TOOLS:
                continue
            # 注册工具 + 设置结果
            response.add_status(f"[tool]{t_name}")
            tool_count += 1
            result_prefix = "[ok] " if success else "[err] "
            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

        # 恢复 Shell 折叠面板
        self._restore_shell_widgets(response, msg)

        # 恢复 thinking
        thinking = msg.get('thinking', '')
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()

        # 恢复正文（[工具执行结果]之后可能还有 AI 正式回复）
        # 找到工具摘要之后的正文部分
        text_after_tools = ''
        parts = content.split('\n\n')
        for idx_p, part in enumerate(parts):
            if not part.strip().startswith('[工具执行结果]') and not any(
                part.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES
            ):
                # 检查是否整段都是工具结果行
                is_tool_block = all(
                    any(line.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES)
                    or not line.strip()
                    or line.strip() == '[工具执行结果]'
                    for line in part.split('\n')
                )
                if not is_tool_block and part.strip():
                    text_after_tools = '\n\n'.join(parts[idx_p:])
                    break
        if text_after_tools:
            response.set_content(text_after_tools)

        label_parts = []
        if thinking:
            label_parts.append("思考")
        label_parts.append(f"{tool_count}次调用")
        response.status_label.setText(f"历史 | {', '.join(label_parts)}")
        response.finalize()
        response.status_label.setText(f"历史 | {', '.join(label_parts)}")

    # ------------------------------------------------------------------
    def _restore_shell_widgets(self, response, msg: dict):
        """从历史消息中恢复 Python Shell / System Shell 折叠面板"""
        # 恢复 Python Shell
        for ps in msg.get('python_shells', []):
            code = ps.get('code', '')
            raw_output = ps.get('output', '')
            error = ps.get('error', '')
            success = ps.get('success', True)
            # 提取执行时间（和 _on_add_python_shell 相同逻辑）
            exec_time = 0.0
            clean_parts = []
            for line in raw_output.split('\n'):
                time_match = re.match(r'^执行时间:\s*([\d.]+)s$', line.strip())
                if time_match:
                    exec_time = float(time_match.group(1))
                    continue
                if line.strip() == '输出:':
                    continue
                clean_parts.append(line)
            clean_output = '\n'.join(clean_parts).strip()
            widget = PythonShellWidget(
                code=code, output=clean_output, error=error,
                exec_time=exec_time, success=success, parent=response
            )
            response.add_shell_widget(widget)

        # 恢复 System Shell
        for ss in msg.get('system_shells', []):
            command = ss.get('command', '')
            raw_output = ss.get('output', '')
            error = ss.get('error', '')
            success = ss.get('success', True)
            cwd = ss.get('cwd', '')
            exec_time = 0.0
            exit_code = 0
            stdout_parts = []
            for line in raw_output.split('\n'):
                tm = re.search(r'耗时:\s*([\d.]+)s', line)
                cm = re.search(r'退出码:\s*(\d+)', line)
                if tm:
                    exec_time = float(tm.group(1))
                if cm:
                    exit_code = int(cm.group(1))
                if tm or cm:
                    continue
                if line.strip() in ('--- stdout ---', '--- stderr ---'):
                    continue
                stdout_parts.append(line)
            clean_output = '\n'.join(stdout_parts).strip()
            widget = SystemShellWidget(
                command=command, output=clean_output, error=error,
                exit_code=exit_code, exec_time=exec_time,
                success=success, cwd=cwd, parent=response
            )
            response.add_sys_shell_widget(widget)

    # ------------------------------------------------------------------
    def _render_old_tool_msgs(self, response, tool_msgs: list):
        """渲染旧格式 role=tool 消息到 AIResponse"""
        for tm in tool_msgs:
            t_name = tm.get('name', 'unknown')
            t_content = tm.get('content', '')
            # 解析 tool_name:result_text
            if ':' in t_content:
                parts = t_content.split(':', 1)
                t_name = parts[0].strip() or t_name
                t_result = parts[1].strip() if len(parts) > 1 else t_content
            else:
                t_result = t_content
            # 静默工具不显示在执行列表
            if t_name in self._SILENT_TOOLS:
                continue
            success = not t_result.startswith('[err]') and not t_result.startswith('\u274c')
            # 先注册工具调用
            response.add_status(f"[tool]{t_name}")
            result_prefix = "[ok] " if success else "[err] "

            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

    # ===== Token 优化管理 =====
    
    def _silent_update_check(self):
        """启动时静默检查更新（不弹窗，只在有更新时高亮按钮）"""
        try:
            self._updateCheckDone.connect(self._on_silent_check_result, QtCore.Qt.UniqueConnection)
        except RuntimeError:
            pass
        threading.Thread(target=self._bg_check_update, daemon=True).start()

    @QtCore.Slot(dict)
    def _on_silent_check_result(self, result: dict):
        """[主线程] 静默检查结果 → 如果有更新，高亮按钮 + 显示通知横幅"""
        # 断开静默回调，防止和手动点击冲突
        try:
            self._updateCheckDone.disconnect(self._on_silent_check_result)
        except RuntimeError:
            pass
        
        if result.get('has_update') and result.get('remote_version'):
            remote_ver = result['remote_version']
            local_ver = result.get('local_version', '?')
            release_name = result.get('release_name', '')
            
            # 1) 用醒目样式标记按钮
            self.btn_update.setText(tr('update.new_ver', remote_ver))
            self.btn_update.setToolTip(tr('update.new_ver_tip', remote_ver))
            self.btn_update.setProperty("state", "available")
            self.btn_update.style().unpolish(self.btn_update)
            self.btn_update.style().polish(self.btn_update)
            
            # 2) 保存检查结果，供手动点击时直接使用
            self._cached_update_result = result
            
            # 3) ★ 在输入区域上方显示更新通知横幅（含更新摘要）
            try:
                if hasattr(self, '_update_banner') and self._update_banner:
                    self._update_banner.setVisible(True)
                else:
                    release_notes = result.get('release_notes', '').strip()
                    self._update_banner = UpdateNotificationBanner(
                        remote_version=remote_ver,
                        release_name=release_name,
                        local_version=local_ver,
                        release_notes=release_notes,
                    )
                    self._update_banner.updateClicked.connect(self._on_banner_update)
                    # 插入到输入区域布局的最顶部（batch_bar 之前）
                    input_layout = self._batch_bar.parent().layout()
                    if input_layout:
                        input_layout.insertWidget(0, self._update_banner)
                    self._update_banner.setVisible(True)
            except Exception:
                pass  # 横幅创建失败不影响主流程
    
    def _on_banner_update(self):
        """通知横幅的"立即更新"按钮被点击"""
        # 隐藏横幅
        if hasattr(self, '_update_banner') and self._update_banner:
            self._update_banner.setVisible(False)
        # 触发更新流程
        cached = getattr(self, '_cached_update_result', None)
        if cached and cached.get('has_update'):
            self._on_update_check_result(cached)
            self._cached_update_result = None
        else:
            self._on_check_update()

    def _on_check_update(self):
        """点击 Update 按钮 → 后台检查更新（如果有缓存结果直接使用）"""
        # 如果启动时已检测到新版本，直接显示结果
        cached = getattr(self, '_cached_update_result', None)
        if cached and cached.get('has_update'):
            self._on_update_check_result(cached)
            self._cached_update_result = None  # 用完清除
            return
        
        self.btn_update.setEnabled(False)
        self.btn_update.setText("检查中…")
        
        # 连接信号（只连一次，用 UniqueConnection 防重复）
        try:
            self._updateCheckDone.connect(self._on_update_check_result, QtCore.Qt.UniqueConnection)
        except RuntimeError:
            pass
        
        threading.Thread(target=self._bg_check_update, daemon=True).start()

    def _bg_check_update(self):
        """[后台线程] 调用 updater.check_update"""
        try:
            from ..utils.updater import check_update
            result = check_update()
        except Exception as e:
            result = {'has_update': False, 'error': str(e), 'local_version': '?', 'remote_version': ''}
        self._updateCheckDone.emit(result)

    @QtCore.Slot(dict)
    def _on_update_check_result(self, result: dict):
        """[主线程] 处理检查结果"""
        self.btn_update.setEnabled(True)
        self.btn_update.setText("Update")
        self.btn_update.setProperty("state", "")  # 恢复默认样式
        self.btn_update.style().unpolish(self.btn_update)
        self.btn_update.style().polish(self.btn_update)
        
        if result.get('error'):
            QtWidgets.QMessageBox.warning(self, "检查更新", f"检查更新失败:\n{result['error']}")
            return
        
        local_ver = result.get('local_version', '?')
        remote_ver = result.get('remote_version', '?')
        release_name = result.get('release_name', '')
        release_notes = result.get('release_notes', '')
        
        if not result.get('has_update'):
            QtWidgets.QMessageBox.information(
                self, "检查更新",
                f"当前已是最新版本 ✓\n\n"
                f"本地版本: v{local_ver}\n"
                f"最新 Release: v{remote_ver}"
            )
            return
        
        # ---- 有新版本，弹出确认对话框 ----
        detail = f"本地版本: v{local_ver}\n最新 Release: v{remote_ver}"
        if release_name:
            detail += f"\n版本名称: {release_name}"
        if release_notes:
            detail += f"\n更新说明: {release_notes}"
        detail += "\n\n⚠️ 更新后插件窗口将自动重启。\n（config、cache、trainData 目录不会被覆盖）"
        
        reply = QtWidgets.QMessageBox.question(
            self, "发现新版本",
            f"发现新版本 v{remote_ver}，是否立即更新？\n\n{detail}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self._start_update()

    # 更新进度文案轮播（下载阶段无百分比时使用）
    _UPDATE_FUNNY_MESSAGES = [
        "文件正在赶来的路上…",
        "数据正在穿越互联网…",
        "服务器正在翻箱倒柜找数据…",
        "正在和后端同学对齐信息…",
        "正在同步相关服务…",
        "进度条正在努力工作…",
        "正在从云里把数据拽下来…",
        "服务器正在回忆文件放在哪…",
        "正在构建本次请求的最佳实践…",
        "数据已经发车，很快到站…",
    ]

    def _start_update(self):
        """开始下载并应用更新"""
        # 创建进度对话框，初始即用第一条搞怪文案 + 不确定进度条（动效）
        first_msg = self._UPDATE_FUNNY_MESSAGES[0]
        self._update_progress_dlg = QtWidgets.QProgressDialog(
            first_msg, "取消", 0, 100, self
        )
        self._update_progress_dlg.setWindowTitle("更新 Houdini Agent")
        self._update_progress_dlg.setWindowModality(QtCore.Qt.WindowModal)
        self._update_progress_dlg.setAutoClose(False)
        self._update_progress_dlg.setAutoReset(False)
        self._update_progress_dlg.setMinimumDuration(0)
        self._update_progress_dlg.setValue(0)
        # 无 Content-Length 时只动不显示百分比：用不确定进度条
        self._update_progress_dlg.setRange(0, 0)
        # 文案轮播定时器（在 _on_update_progress 收到 downloading 0 时启动）
        self._update_msg_index = 0
        self._update_msg_timer = None
        self._update_fade_anim = None
        # QProgressDialog / QProgressBar 样式由全局 QSS 控制
        
        # 连接信号
        try:
            self._updateProgress.connect(self._on_update_progress, QtCore.Qt.UniqueConnection)
            self._updateApplyDone.connect(self._on_update_apply_result, QtCore.Qt.UniqueConnection)
        except RuntimeError:
            pass
        
        threading.Thread(target=self._bg_download_and_apply, daemon=True).start()

    def _bg_download_and_apply(self):
        """[后台线程] 下载并应用更新"""
        try:
            from ..utils.updater import download_and_apply
            result = download_and_apply(progress_callback=self._update_progress_cb)
        except Exception as e:
            result = {'success': False, 'error': str(e), 'updated_files': 0}
        self._updateApplyDone.emit(result)

    def _update_progress_cb(self, stage: str, percent: int):
        """进度回调（从后台线程调用 → 通过信号到主线程）"""
        self._updateProgress.emit(stage, percent)

    def _stop_update_msg_timer(self):
        """停止更新文案轮播定时器"""
        if getattr(self, '_update_msg_timer', None) is not None:
            self._update_msg_timer.stop()
            self._update_msg_timer.deleteLater()
            self._update_msg_timer = None
        if getattr(self, '_update_fade_anim', None) is not None:
            try:
                self._update_fade_anim.stop()
            except Exception:
                pass
            self._update_fade_anim = None

    def _rotate_update_message(self):
        """轮播搞怪文案并做淡入动效"""
        if not hasattr(self, '_update_progress_dlg') or self._update_progress_dlg is None:
            return
        msgs = self._UPDATE_FUNNY_MESSAGES
        if not msgs:
            return
        self._update_msg_index = (self._update_msg_index + 1) % len(msgs)
        new_text = msgs[self._update_msg_index]
        self._update_progress_dlg.setLabelText(new_text)
        # 淡入动效：找到对话框里的 QLabel，用 QGraphicsOpacityEffect + QPropertyAnimation
        label = self._update_progress_dlg.findChild(QtWidgets.QLabel)
        if label is not None:
            effect = label.graphicsEffect()
            if effect is None:
                effect = QtWidgets.QGraphicsOpacityEffect(label)
                label.setGraphicsEffect(effect)
            effect.setOpacity(0.28)
            if getattr(self, '_update_fade_anim', None) is not None:
                try:
                    self._update_fade_anim.stop()
                except Exception:
                    pass
            anim = QtCore.QPropertyAnimation(effect, b"opacity")
            anim.setDuration(380)
            anim.setStartValue(0.28)
            anim.setEndValue(1.0)
            anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
            self._update_fade_anim = anim

    @QtCore.Slot(str, int)
    def _on_update_progress(self, stage: str, percent: int):
        """[主线程] 更新进度条（无 Content-Length 时不确定进度条 + 搞怪文案轮播）"""
        if not hasattr(self, '_update_progress_dlg') or self._update_progress_dlg is None:
            return
        
        if stage == 'downloading':
            if percent == 0:
                self._update_progress_dlg.setRange(0, 0)
                self._update_progress_dlg.setLabelText(self._UPDATE_FUNNY_MESSAGES[0])
                self._update_msg_index = 0
                if getattr(self, '_update_msg_timer', None) is None:
                    self._update_msg_timer = QtCore.QTimer(self)
                    self._update_msg_timer.timeout.connect(self._rotate_update_message)
                    self._update_msg_timer.start(2200)
            elif 1 <= percent <= 99:
                self._stop_update_msg_timer()
                self._update_progress_dlg.setRange(0, 100)
                self._update_progress_dlg.setValue(percent)
                self._update_progress_dlg.setLabelText(f"正在下载… {percent}%")
            else:
                self._stop_update_msg_timer()
                self._update_progress_dlg.setRange(0, 100)
                self._update_progress_dlg.setValue(100)
                self._update_progress_dlg.setLabelText("下载完成")
        elif stage == 'extracting':
            self._stop_update_msg_timer()
            self._update_progress_dlg.setRange(0, 0)
            self._update_progress_dlg.setLabelText("正在解压…")
            self._update_progress_dlg.setValue(0)
        elif stage == 'applying':
            self._update_progress_dlg.setRange(0, 0)
            self._update_progress_dlg.setLabelText("正在更新文件…")
        elif stage == 'done':
            self._stop_update_msg_timer()
            self._update_progress_dlg.setRange(0, 100)
            self._update_progress_dlg.setValue(100)
            self._update_progress_dlg.setLabelText("更新完成！")
        else:
            self._update_progress_dlg.setValue(percent)
            self._update_progress_dlg.setLabelText(f"{stage} ({percent}%)")

    @QtCore.Slot(dict)
    def _on_update_apply_result(self, result: dict):
        """[主线程] 更新完成后的处理"""
        self._stop_update_msg_timer()
        # 关闭进度条
        if hasattr(self, '_update_progress_dlg') and self._update_progress_dlg:
            self._update_progress_dlg.close()
            self._update_progress_dlg = None
        
        if not result.get('success'):
            QtWidgets.QMessageBox.critical(
                self, "更新失败",
                f"更新过程中出现错误:\n{result.get('error', '未知错误')}"
            )
            return
        
        updated = result.get('updated_files', 0)
        
        # 更新成功 → 提示并重启
        reply = QtWidgets.QMessageBox.information(
            self, "更新成功",
            f"已成功更新 {updated} 个文件！\n\n点击 OK 立即重启插件。",
            QtWidgets.QMessageBox.Ok,
        )
        
        # 延迟重启（让对话框关闭后再执行）
        QtCore.QTimer.singleShot(200, self._do_restart)

    def _do_restart(self):
        """执行插件重启"""
        try:
            # 先保存当前工作区
            main_win = self.window()
            if hasattr(main_win, '_save_workspace'):
                main_win._save_workspace()
            
            # 关闭当前窗口
            main_win.force_quit = True
            main_win.close()
            
            # 延迟重新打开（让窗口完全关闭后再重建）
            # 注意：使用绝对导入的函数引用，避免模块被清除后相对导入失败
            from houdini_agent.utils.updater import restart_plugin as _restart_fn
            QtCore.QTimer.singleShot(500, _restart_fn)
        except Exception as e:
            print(f"[Updater] Restart error: {e}")
            QtWidgets.QMessageBox.warning(
                self, "重启失败",
                f"自动重启失败，请手动关闭并重新打开插件。\n\n错误: {e}"
            )
    
