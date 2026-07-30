# -*- coding: utf-8 -*-
"""
Header UI 构建 — 顶部设置栏（模型选择、Provider、Web/Think 开关等）

从 ai_tab.py 中拆分出的 Mixin，所有方法通过 self 访问 AITab 实例状态。
样式由全局 style_template.qss 通过 objectName 选择器控制。
"""

from houdini_agent.qt_compat import QtWidgets, QtCore
from .i18n import tr, get_language, set_language, language_changed
from ..utils.dev_feature_toggles import (
    DEV_FEATURE_TOGGLES,
    is_dev_reload_enabled,
    is_toggle_enabled,
    set_toggle_enabled,
)
from ..utils.team_memory_settings import is_team_export_enabled, set_team_export_enabled


class HeaderMixin:
    """顶部设置栏构建与交互逻辑"""

    def _build_header(self) -> QtWidgets.QWidget:
        """顶部设置栏 — 单行：Provider + Model + keyStatus + Web + Think + ⋯ 溢出菜单"""
        header = QtWidgets.QFrame()
        header.setObjectName("headerFrame")
        
        outer = QtWidgets.QVBoxLayout(header)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(0)
        
        # -------- 单行：Provider + Model + keyStatus + Web + Think + ⋯ --------
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        
        # 提供商
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.setObjectName("providerCombo")
        # self.provider_combo.addItem("Ollama", 'ollama')
        self.provider_combo.addItem("DeepSeek", 'deepseek')
        # self.provider_combo.addItem("GLM", 'glm')
        # self.provider_combo.addItem("OpenAI", 'openai')
        # self.provider_combo.addItem("Duojie", 'duojie')
        # self.provider_combo.addItem("OpenRouter", 'openrouter')
        self.provider_combo.addItem("Kimi Coding", 'kimi_coding')
        self.provider_combo.addItem("SiliconFlow", 'siliconflow')
        self.provider_combo.addItem("OF3D", 'of3d')
        self.provider_combo.addItem("Custom", 'custom')
        self.provider_combo.setMinimumWidth(70)
        self.provider_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        row.addWidget(self.provider_combo, 1)
        
        # Custom 配置按钮（仅在 Custom provider 时可见）
        self.btn_custom_config = QtWidgets.QPushButton("⚙")
        self.btn_custom_config.setObjectName("btnCustomConfig")
        self.btn_custom_config.setFixedSize(26, 26)
        self.btn_custom_config.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_custom_config.setToolTip("配置 Custom Model 的 URL、API Key 和模型名")
        self.btn_custom_config.setVisible(False)
        self.btn_custom_config.clicked.connect(self._open_custom_provider_dialog)
        row.addWidget(self.btn_custom_config)
        
        # 模型
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setObjectName("modelCombo")
        self._model_map = {
            'ollama': ['qwen2.5:14b', 'qwen2.5:7b', 'llama3:8b', 'mistral:7b'],
            'deepseek': ['deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat', 'deepseek-reasoner'],  # chat/reasoner 将于 2026/07/24 弃用
            'glm': ['glm-4.7'],
            'openai': ['gpt-5.2', 'gpt-5.3-codex'],
            'duojie': [
                'claude-opus-4-6-gemini',
                'claude-opus-4-6-max',
                'claude-sonnet-4-5',
                'claude-sonnet-4-6',
                'gemini-3-flash',
                'gemini-3.1-pro',
                'glm-5-turbo',
                'glm-5.1',
                'MiniMax-M2.7',
                'MiniMax-M2.7-highspeed',
            ],
            'openrouter': [
                'anthropic/claude-sonnet-4.6',
                'anthropic/claude-opus-4.6',
                'anthropic/claude-sonnet-4.5',
                'anthropic/claude-haiku-4.5',
                'openai/gpt-5.2',
                'openai/gpt-5.3-codex',
                'openai/o4-mini',
                'google/gemini-3-flash-preview',
                'google/gemini-2.5-pro',
                'google/gemini-2.5-flash',
                'deepseek/deepseek-v3.2',
                'deepseek/deepseek-r1',
                'x-ai/grok-4.1-fast',
                'meta-llama/llama-4-maverick',
                'qwen/qwen3-235b-a22b',
                'mistralai/mistral-large-2512',
            ],
            'kimi_coding': ['k3', 'kimi-for-coding', 'kimi-for-coding-highspeed'],
            'of3d': ['gpt-5.5', 'chatgpt-4o-latest'],
            'siliconflow': [
                'deepseek-ai/DeepSeek-V4-Pro',
                'deepseek-ai/DeepSeek-V4-Flash',
                'deepseek-ai/DeepSeek-V3',
                'deepseek-ai/DeepSeek-R1',
                'Pro/deepseek-ai/DeepSeek-V3',
                'Pro/deepseek-ai/DeepSeek-R1',
                'Qwen/Qwen3-235B-A22B',
                'Qwen/Qwen3-30B-A3B',
                'Qwen/Qwen3-8B',
                'THUDM/GLM-Z1-32B-0414',
            ],
            'custom': [],  # 由用户通过配置对话框动态填充
        }
        # Custom provider 的运行时配置（从持久化配置加载）
        self._custom_provider_config = {
            'api_url': '',
            'api_key': '',
            'models': [],           # 用户配置的模型名列表
            'context_limit': 128000,
            'supports_vision': False,
            'supports_fc': True,    # 是否支持 Function Calling
        }
        self._load_custom_provider_config()
        self._model_context_limits = {
            'qwen2.5:14b': 32000, 'qwen2.5:7b': 32000, 'llama3:8b': 8000, 'mistral:7b': 32000,
            'deepseek-v4-flash': 1048576, 'deepseek-v4-pro': 1048576,
            'deepseek-chat': 1048576, 'deepseek-reasoner': 1048576,
            'glm-4.7': 200000,
            'gpt-5.2': 128000,
            'gpt-5.3-codex': 200000,
            # Duojie 模型
            'claude-opus-4-6-gemini': 200000,
            'claude-opus-4-6-max': 200000,
            'claude-sonnet-4-5': 200000,
            'claude-sonnet-4-6': 200000,
            'gemini-3-flash': 1048576,
            'gemini-3.1-pro': 1048576,
            'glm-5-turbo': 200000,
            'glm-5.1': 200000,
            'MiniMax-M2.7': 128000,
            'MiniMax-M2.7-highspeed': 128000,
            # OpenRouter 模型
            'anthropic/claude-sonnet-4.6': 1000000,
            'anthropic/claude-opus-4.6': 1000000,
            'anthropic/claude-sonnet-4.5': 1000000,
            'anthropic/claude-haiku-4.5': 200000,
            'openai/gpt-5.2': 400000,
            'openai/gpt-5.3-codex': 400000,
            'openai/o4-mini': 200000,
            'google/gemini-3-flash-preview': 1048576,
            'google/gemini-2.5-pro': 1048576,
            'google/gemini-2.5-flash': 1048576,
            'deepseek/deepseek-v3.2': 163840,
            'deepseek/deepseek-r1': 64000,
            'x-ai/grok-4.1-fast': 2000000,
            'meta-llama/llama-4-maverick': 1048576,
            'qwen/qwen3-235b-a22b': 131072,
            'mistralai/mistral-large-2512': 262144,
            # Kimi Coding
            'k3': 1048576,
            'kimi-for-coding': 262144,
            'kimi-for-coding-highspeed': 262144,
            # OF3D
            'chatgpt-4o-latest': 128000,
            'gpt-5.5': 128000,
            # SiliconFlow
            'deepseek-ai/DeepSeek-V4-Pro': 1048576,
            'deepseek-ai/DeepSeek-V4-Flash': 1048576,
            'deepseek-ai/DeepSeek-V3': 65536,
            'deepseek-ai/DeepSeek-R1': 16384,
            'Pro/deepseek-ai/DeepSeek-V3': 65536,
            'Pro/deepseek-ai/DeepSeek-R1': 16384,
            'Qwen/Qwen3-235B-A22B': 131072,
            'Qwen/Qwen3-30B-A3B': 32768,
            'Qwen/Qwen3-8B': 32768,
            'THUDM/GLM-Z1-32B-0414': 32768,
        }
        # 模型特性配置
        self._model_features = {
            # Ollama
            'qwen2.5:14b':               {'supports_prompt_caching': True, 'supports_vision': False},
            'qwen2.5:7b':                {'supports_prompt_caching': True, 'supports_vision': False},
            'llama3:8b':                  {'supports_prompt_caching': True, 'supports_vision': False},
            'mistral:7b':                 {'supports_prompt_caching': True, 'supports_vision': False},
            # DeepSeek
            'deepseek-v4-flash':           {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-v4-pro':             {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-chat':              {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek-reasoner':          {'supports_prompt_caching': True, 'supports_vision': False},
            # GLM
            'glm-4.7':                    {'supports_prompt_caching': True, 'supports_vision': False},
            # OpenAI
            'gpt-5.2':                    {'supports_prompt_caching': True, 'supports_vision': True},
            'gpt-5.3-codex':              {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - Claude
            'claude-opus-4-6-gemini':    {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-opus-4-6-max':        {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-sonnet-4-5':          {'supports_prompt_caching': True, 'supports_vision': True},
            'claude-sonnet-4-6':          {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - Gemini
            'gemini-3-flash':             {'supports_prompt_caching': True, 'supports_vision': True},
            'gemini-3.1-pro':             {'supports_prompt_caching': True, 'supports_vision': True},
            # Duojie - GLM (Anthropic 协议)
            'glm-5-turbo':                {'supports_prompt_caching': True, 'supports_vision': False},
            'glm-5.1':                    {'supports_prompt_caching': True, 'supports_vision': False},
            # Duojie - MiniMax
            'MiniMax-M2.7':               {'supports_prompt_caching': True, 'supports_vision': False},
            'MiniMax-M2.7-highspeed':     {'supports_prompt_caching': True, 'supports_vision': False},
            # OpenRouter 模型
            'anthropic/claude-sonnet-4.6':        {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-opus-4.6':          {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-sonnet-4.5':        {'supports_prompt_caching': True, 'supports_vision': True},
            'anthropic/claude-haiku-4.5':         {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/gpt-5.2':                     {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/gpt-5.3-codex':               {'supports_prompt_caching': True, 'supports_vision': True},
            'openai/o4-mini':                     {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-3-flash-preview':      {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-2.5-pro':              {'supports_prompt_caching': True, 'supports_vision': True},
            'google/gemini-2.5-flash':            {'supports_prompt_caching': True, 'supports_vision': True},
            'deepseek/deepseek-v3.2':             {'supports_prompt_caching': True, 'supports_vision': False},
            'deepseek/deepseek-r1':               {'supports_prompt_caching': True, 'supports_vision': False},
            'x-ai/grok-4.1-fast':                 {'supports_prompt_caching': True, 'supports_vision': True},
            'meta-llama/llama-4-maverick':        {'supports_prompt_caching': True, 'supports_vision': True},
            'qwen/qwen3-235b-a22b':               {'supports_prompt_caching': True, 'supports_vision': False},
            'mistralai/mistral-large-2512':       {'supports_prompt_caching': True, 'supports_vision': True},
            # Kimi Coding
            'k3':                                  {'supports_prompt_caching': True, 'supports_vision': False},
            'kimi-for-coding':                    {'supports_prompt_caching': True, 'supports_vision': False},
            'kimi-for-coding-highspeed':          {'supports_prompt_caching': True, 'supports_vision': False},
            # OF3D
            'chatgpt-4o-latest':                  {'supports_prompt_caching': False, 'supports_vision': True},
            'gpt-5.5':                            {'supports_prompt_caching': False, 'supports_vision': False},
            # SiliconFlow
            'deepseek-ai/DeepSeek-V4-Pro':        {'supports_prompt_caching': False, 'supports_vision': False},
            'deepseek-ai/DeepSeek-V4-Flash':      {'supports_prompt_caching': False, 'supports_vision': False},
            'deepseek-ai/DeepSeek-V3':            {'supports_prompt_caching': False, 'supports_vision': False},
            'deepseek-ai/DeepSeek-R1':            {'supports_prompt_caching': False, 'supports_vision': False},
            'Pro/deepseek-ai/DeepSeek-V3':        {'supports_prompt_caching': False, 'supports_vision': False},
            'Pro/deepseek-ai/DeepSeek-R1':        {'supports_prompt_caching': False, 'supports_vision': False},
            'Qwen/Qwen3-235B-A22B':               {'supports_prompt_caching': False, 'supports_vision': False},
            'Qwen/Qwen3-30B-A3B':                 {'supports_prompt_caching': False, 'supports_vision': False},
            'Qwen/Qwen3-8B':                      {'supports_prompt_caching': False, 'supports_vision': False},
            'THUDM/GLM-Z1-32B-0414':              {'supports_prompt_caching': False, 'supports_vision': False},
        }
        self._refresh_models('deepseek')
        self.model_combo.setMinimumWidth(100)
        self.model_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.model_combo.setEditable(False)  # 默认不可编辑，Custom 时切换为可编辑
        row.addWidget(self.model_combo, 1)
        
        # API Key 状态 — 紧凑指示（行内，限宽 + 省略号）
        self.key_status = QtWidgets.QLabel()
        self.key_status.setObjectName("keyStatus")
        self.key_status.setMaximumWidth(90)
        self.key_status.setMinimumWidth(0)
        from houdini_agent.qt_compat import QtCore as _qc
        self.key_status.setTextInteractionFlags(_qc.Qt.NoTextInteraction)
        row.addWidget(self.key_status)

        # 当前用户
        self.user_label = QtWidgets.QLabel()
        self.user_label.setObjectName("userLabel")
        uname = getattr(self, "_username", "")
        self.user_label.setText(uname or "")
        self.user_label.setToolTip("当前用户")
        row.addWidget(self.user_label)
        
        # Web / Think 开关
        self.web_check = QtWidgets.QCheckBox("Web")
        self.web_check.setObjectName("chkWeb")
        self.web_check.setChecked(True)
        row.addWidget(self.web_check)
        
        self.think_check = QtWidgets.QCheckBox("Think")
        self.think_check.setObjectName("chkThink")
        self.think_check.setChecked(True)
        self.think_check.setToolTip(tr('header.think.tooltip'))
        row.addWidget(self.think_check)
        
        # ⋯ 溢出菜单按钮
        self.btn_overflow = QtWidgets.QPushButton("···")
        self.btn_overflow.setObjectName("btnOverflow")
        self.btn_overflow.setFixedSize(26, 26)
        self.btn_overflow.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_overflow.clicked.connect(self._show_overflow_menu)
        row.addWidget(self.btn_overflow)
        
        outer.addLayout(row)
        
        # -------- 隐藏按钮（保持 self.btn_xxx 引用兼容 _wire_events）--------
        # 这些按钮不加入布局，仅用于信号连接
        self.btn_key = QtWidgets.QPushButton("Key")
        self.btn_key.setObjectName("btnSmall")
        self.btn_key.setVisible(False)
        
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.setObjectName("btnSmall")
        self.btn_clear.setVisible(False)
        
        self.btn_cache = QtWidgets.QPushButton("Cache")
        self.btn_cache.setObjectName("btnSmall")
        self.btn_cache.setVisible(False)
        
        self.btn_optimize = QtWidgets.QPushButton("Opt")
        self.btn_optimize.setObjectName("btnOptimize")
        self.btn_optimize.setVisible(False)
        
        self.btn_update = QtWidgets.QPushButton("Update")
        self.btn_update.setObjectName("btnUpdate")
        self.btn_update.setVisible(False)
        
        self.btn_font_scale = QtWidgets.QPushButton("Aa")
        self.btn_font_scale.setObjectName("btnFontScale")
        self.btn_font_scale.setVisible(False)
        
        # 语言下拉框（隐藏，仅用于引用 + 信号）
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.setObjectName("langCombo")
        self.lang_combo.addItem("中文", "zh")
        self.lang_combo.addItem("EN", "en")
        self.lang_combo.setCurrentIndex(0 if get_language() == 'zh' else 1)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.lang_combo.setVisible(False)
        
        return header

    def _show_overflow_menu(self):
        """显示溢出菜单：低频功能集中在此"""
        menu = QtWidgets.QMenu(self)
        
        # OF3D 内置 key，不暴露 API Key 入口
        if self._current_provider() != 'of3d':
            menu.addAction("API Key", self.btn_key.click)
        menu.addAction("Clear Chat", self.btn_clear.click)
        menu.addAction("Cache", self.btn_cache.click)
        menu.addAction("Optimize", self.btn_optimize.click)
        menu.addSeparator()
        menu.addAction("Update", self.btn_update.click)
        menu.addAction("Font (Aa)", self.btn_font_scale.click)
        menu.addSeparator()
        menu.addAction(tr('rules.menu_label'), self._open_rules_editor)
        menu.addAction(tr('plugin.menu_label'), self._open_plugin_manager)
        if hasattr(self, "_request_user_switch"):
            menu.addAction("Switch User", self._request_user_switch)
        menu.addSeparator()
        self._add_team_memory_sharing_action(menu)
        if is_dev_reload_enabled():
            self._add_dev_feature_toggle_menu(menu)
            menu.addAction("Rebuild Team Memory", self._rebuild_team_memory_from_menu)
            menu.addSeparator()
        
        # 语言子菜单
        lang_menu = menu.addMenu("Language")
        act_zh = lang_menu.addAction("中文")
        act_en = lang_menu.addAction("EN")
        current_lang = get_language()
        act_zh.setCheckable(True)
        act_en.setCheckable(True)
        act_zh.setChecked(current_lang == 'zh')
        act_en.setChecked(current_lang == 'en')
        act_zh.triggered.connect(lambda: self._set_lang_from_menu('zh'))
        act_en.triggered.connect(lambda: self._set_lang_from_menu('en'))
        
        # 弹出位置：溢出按钮下方
        menu.exec_(self.btn_overflow.mapToGlobal(
            QtCore.QPoint(0, self.btn_overflow.height())
        ))

    def _add_dev_feature_toggle_menu(self, menu):
        dev_menu = menu.addMenu("Dev Feature Toggles")
        self._dev_toggle_menu_ref = dev_menu  # ★ 持久引用，排除 QAction 被提前 GC 的可能
        self._dev_toggle_action_refs = []
        for toggle in DEV_FEATURE_TOGGLES:
            action = dev_menu.addAction(toggle.label)
            self._dev_toggle_action_refs.append(action)
            action.setCheckable(True)
            action.setChecked(is_toggle_enabled(toggle))
            if toggle.description:
                try:
                    action.setToolTip(f"{toggle.env_name}: {toggle.description}")
                except Exception:
                    pass
            action.triggered.connect(
                lambda checked=False, t=toggle: self._toggle_dev_toggle(t)
            )

    def _toggle_dev_toggle(self, toggle):
        """不信任 Qt 传入的 checked 参数（实测在本机上连续两次点击都传入 False，
        导致取消后无法再次打开），改为自己重新读现持久化值并取反。
        因为整个菜单每次打开都会重建，下次打开时 checkbox 会重新从持久化值同步，
        不依赖 Qt 自己的 checked 状态追踪也能正确工作。"""
        self._set_dev_toggle(toggle, not is_toggle_enabled(toggle))

    def _set_dev_toggle(self, toggle, enabled: bool):
        """写入开发者功能开关；写入失败时弹窗提示。

        ★ 不用 self._addStatus.emit：那是挂在"当前活跃的对话消息气泡"上的，
        没有正在进行的 Agent 回复时会被静默丢弃（菜单动作常常在无活跃会话时触发）。
        """
        try:
            set_toggle_enabled(toggle, enabled)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, toggle.label, f"设置保存失败，请重试: {e}")

    def _add_team_memory_sharing_action(self, menu):
        """常驻开关：是否把本用户的技术类长期记忆同步给团队共享库（默认开启，可随时关闭）。"""
        uname = getattr(self, "_username", "")
        if not uname:
            return
        action = menu.addAction("Team Memory Sharing")
        self._team_memory_action_ref = action  # ★ 持久引用，排除 QAction 被提前 GC 的可能
        action.setCheckable(True)
        try:
            action.setChecked(is_team_export_enabled(uname))
        except Exception:
            action.setChecked(True)
        action.setToolTip(
            "睡眠维护时是否把技术类经验（不含个人偏好/身份信息）同步一份到共享盘，供团队记忆库使用。"
        )
        action.triggered.connect(
            lambda checked=False, u=uname: self._toggle_team_memory_sharing(u)
        )

    def _toggle_team_memory_sharing(self, username: str):
        """不信任 Qt 传入的 checked 参数（同样的不可靠问题），改为自己重新读现
        持久化值并取反。"""
        self._set_team_memory_sharing(username, not is_team_export_enabled(username))

    def _set_team_memory_sharing(self, username: str, enabled: bool):
        """写入开关；写入失败时弹窗提示，而不是被 Qt 静默吞掉。

        ★ 不用 self._addStatus.emit：那是挂在"当前活跃的对话消息气泡"上的，
        没有正在进行的 Agent 回复时会被静默丢弃（菜单动作常常在无活跃会话时触发）。
        """
        try:
            set_team_export_enabled(username, enabled)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Team Memory Sharing", f"设置保存失败，请重试: {e}")

    def _rebuild_team_memory_from_menu(self):
        """开发模式动作：全量扫描所有成员的 team_export.json，去重合并写入团队记忆库。

        ★ 用 QMessageBox 而不是 self._addStatus.emit：后者挂在"当前活跃的对话消息
        气泡"上，这个动作常常是在没有正在进行的 Agent 回复时点击的（刚打开面板就
        点菜单），此时 _addStatus 会被静默丢弃，看起来像"点了没反应"。
        """
        try:
            from ..utils.team_memory_store import rebuild_team_memory
            stats = rebuild_team_memory()
            QtWidgets.QMessageBox.information(
                self,
                "团队记忆库",
                "团队记忆库已重建：\n"
                f"扫描 {stats['scanned_users']} 名成员\n"
                f"合并 semantic {stats['semantic_merged']}/{stats['semantic_raw']}\n"
                f"合并 procedural {stats['procedural_merged']}/{stats['procedural_raw']}",
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "团队记忆库", f"重建失败: {e}")

    def _open_rules_editor(self):
        """打开用户自定义规则编辑器"""
        try:
            from .cursor_rules_editor_dialog import RulesEditorDialog
            # 非模态显示：模态 exec_() 在 Houdini 嵌入环境下会启动独立事件循环，
            # 导致输入法上下文无法正确附加，中文无法输入。改用 show() 并持有引用。
            dlg = RulesEditorDialog(parent=self, username=getattr(self, "_username", None))
            self._rules_editor_dlg = dlg
            dlg.setModal(False)
            dlg.setWindowModality(QtCore.Qt.NonModal)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
        except Exception as e:
            print(f"[Header] Failed to open rules editor: {e}")

    def _open_plugin_manager(self):
        """打开插件管理面板"""
        try:
            from .cursor_plugin_manager_dialog import PluginManagerDialog
            dlg = PluginManagerDialog(parent=self)
            dlg.pluginStateChanged.connect(self._on_plugin_state_changed)
            dlg.exec_()
        except Exception as e:
            print(f"[Header] Failed to open plugin manager: {e}")

    def _on_plugin_state_changed(self):
        """插件状态变化后的回调（重新挂载按钮等）"""
        try:
            from ..utils.hooks import get_hook_manager
            bridge = get_hook_manager().get_ui_bridge()
            if bridge:
                bridge.mount_buttons()
        except Exception:
            pass

    def _set_lang_from_menu(self, lang: str):
        """从溢出菜单切换语言"""
        if lang != get_language():
            set_language(lang)
            # 同步隐藏的 lang_combo（保持状态一致）
            expected_idx = 0 if lang == 'zh' else 1
            if self.lang_combo.currentIndex() != expected_idx:
                self.lang_combo.blockSignals(True)
                self.lang_combo.setCurrentIndex(expected_idx)
                self.lang_combo.blockSignals(False)

    def _on_language_changed(self, index: int):
        """语言下拉框切换"""
        lang = self.lang_combo.itemData(index)
        if lang and lang != get_language():
            set_language(lang)

    def _retranslate_header(self):
        """语言切换后更新 Header 区域所有翻译文本"""
        self.think_check.setToolTip(tr('header.think.tooltip'))
        self.btn_cache.setToolTip(tr('header.cache.tooltip'))
        self.btn_optimize.setToolTip(tr('header.optimize.tooltip'))
        self.btn_update.setToolTip(tr('header.update.tooltip'))
        self.btn_font_scale.setToolTip(tr('header.font.tooltip'))
        # 同步下拉框选中项（防止外部调用 set_language 后不同步）
        lang = get_language()
        expected_idx = 0 if lang == 'zh' else 1
        if self.lang_combo.currentIndex() != expected_idx:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(expected_idx)
            self.lang_combo.blockSignals(False)

    # ============================================================
    # Custom Provider 配置
    # ============================================================

    def _load_custom_provider_config(self):
        """从持久化配置文件加载 Custom Provider 设置"""
        try:
            from shared.common_utils import load_user_config
            cfg, _ = load_user_config(getattr(self, "_username", ""), 'ai', dcc_type='houdini')
            if cfg:
                self._custom_provider_config['api_url'] = cfg.get('custom_api_url', '')
                self._custom_provider_config['api_key'] = cfg.get('custom_api_key', '')
                models_str = cfg.get('custom_models', '')
                if models_str:
                    self._custom_provider_config['models'] = [m.strip() for m in models_str.split(',') if m.strip()]
                try:
                    self._custom_provider_config['context_limit'] = int(cfg.get('custom_context_limit', '128000'))
                except (ValueError, TypeError):
                    pass
                self._custom_provider_config['supports_vision'] = cfg.get('custom_supports_vision', 'false').lower() == 'true'
                self._custom_provider_config['supports_fc'] = cfg.get('custom_supports_fc', 'true').lower() != 'false'
                # 更新模型列表
                self._model_map['custom'] = self._custom_provider_config['models']
                # 同步到 AIClient（如果已初始化）
                self._sync_custom_to_client()
        except Exception as e:
            print(f"[Header] 加载 Custom 配置失败: {e}")

    def _save_custom_provider_config(self):
        """将 Custom Provider 设置持久化到配置文件"""
        try:
            from shared.common_utils import load_user_config, save_user_config
            cfg, _ = load_user_config(getattr(self, "_username", ""), 'ai', dcc_type='houdini')
            cfg = cfg or {}
            cc = self._custom_provider_config
            cfg['custom_api_url'] = cc['api_url']
            cfg['custom_api_key'] = cc['api_key']
            cfg['custom_models'] = ','.join(cc['models'])
            cfg['custom_context_limit'] = str(cc['context_limit'])
            cfg['custom_supports_vision'] = 'true' if cc['supports_vision'] else 'false'
            cfg['custom_supports_fc'] = 'true' if cc['supports_fc'] else 'false'
            save_user_config(getattr(self, "_username", ""), cfg, 'ai', dcc_type='houdini')
        except Exception as e:
            print(f"[Header] 保存 Custom 配置失败: {e}")

    def _sync_custom_to_client(self):
        """将 Custom 配置同步到 AIClient"""
        try:
            client = getattr(self, 'client', None)
            if client is None:
                return
            cc = self._custom_provider_config
            if cc['api_url']:
                client.set_custom_provider(
                    api_url=cc['api_url'],
                    api_key=cc['api_key'],
                    supports_fc=cc['supports_fc'],
                )
            if cc['api_key']:
                client._api_keys['custom'] = cc['api_key']
        except Exception as e:
            print(f"[Header] 同步 Custom 配置到 Client 失败: {e}")

    def _on_provider_changed_custom_visibility(self):
        """Provider 切换时更新 Custom 配置按钮可见性和模型下拉框可编辑状态"""
        provider = self._current_provider()
        is_custom = (provider == 'custom')
        self.btn_custom_config.setVisible(is_custom)
        # Custom 模式下允许用户直接在 model_combo 中输入模型名
        self.model_combo.setEditable(is_custom)
        if is_custom and not self._custom_provider_config.get('api_url'):
            # 首次选择 Custom 且未配置，自动弹出配置对话框
            QtCore.QTimer.singleShot(100, self._open_custom_provider_dialog)

    def _open_custom_provider_dialog(self):
        """打开 Custom Provider 配置对话框"""
        dlg = _CustomProviderDialog(self._custom_provider_config, parent=self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_cfg = dlg.get_config()
            self._custom_provider_config.update(new_cfg)
            # 更新模型列表
            self._model_map['custom'] = new_cfg['models']
            # 动态注册模型特性和上下文限制
            for m in new_cfg['models']:
                self._model_context_limits[m] = new_cfg['context_limit']
                self._model_features[m] = {
                    'supports_prompt_caching': True,
                    'supports_vision': new_cfg['supports_vision'],
                }
            # 同步到 AIClient
            self._sync_custom_to_client()
            # 持久化
            self._save_custom_provider_config()
            # 刷新 UI
            if self._current_provider() == 'custom':
                self._refresh_models('custom')
                self._update_key_status()


class _CustomProviderDialog(QtWidgets.QDialog):
    """Custom Provider 配置对话框 — 配置 API URL、Key、模型名等"""

    def __init__(self, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Model 配置")
        self.setMinimumWidth(460)
        self.setObjectName("customProviderDialog")
        self._build_ui(current_config)

    def _build_ui(self, cfg: dict):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 说明
        info = QtWidgets.QLabel(
            "配置任何兼容 OpenAI API 协议的服务端点。\n"
            "例如：LM Studio、vLLM、Text Generation WebUI、其他中转站等。"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(info)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # API URL
        self._url_edit = QtWidgets.QLineEdit()
        self._url_edit.setPlaceholderText("https://your-api.example.com/v1/chat/completions")
        self._url_edit.setText(cfg.get('api_url', ''))
        self._url_edit.setMinimumHeight(28)
        form.addRow("API URL:", self._url_edit)

        # API Key
        self._key_edit = QtWidgets.QLineEdit()
        self._key_edit.setPlaceholderText("sk-xxxx（留空则不发送 Authorization 头）")
        self._key_edit.setText(cfg.get('api_key', ''))
        self._key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self._key_edit.setMinimumHeight(28)
        # 显示/隐藏按钮
        key_row = QtWidgets.QHBoxLayout()
        key_row.setSpacing(4)
        key_row.addWidget(self._key_edit)
        self._btn_show_key = QtWidgets.QPushButton("👁")
        self._btn_show_key.setFixedSize(28, 28)
        self._btn_show_key.setCheckable(True)
        self._btn_show_key.toggled.connect(
            lambda checked: self._key_edit.setEchoMode(
                QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
            )
        )
        key_row.addWidget(self._btn_show_key)
        form.addRow("API Key:", key_row)

        # 模型名（支持多个，逗号分隔）
        self._models_edit = QtWidgets.QLineEdit()
        self._models_edit.setPlaceholderText("model-name-1, model-name-2（逗号分隔多个模型）")
        self._models_edit.setText(', '.join(cfg.get('models', [])))
        self._models_edit.setMinimumHeight(28)
        form.addRow("模型名:", self._models_edit)

        # 上下文长度
        self._ctx_spin = QtWidgets.QSpinBox()
        self._ctx_spin.setRange(1024, 10000000)
        self._ctx_spin.setSingleStep(1024)
        self._ctx_spin.setValue(cfg.get('context_limit', 128000))
        self._ctx_spin.setSuffix(" tokens")
        self._ctx_spin.setMinimumHeight(28)
        form.addRow("上下文长度:", self._ctx_spin)

        # 特性开关
        features_row = QtWidgets.QHBoxLayout()
        features_row.setSpacing(12)
        self._chk_vision = QtWidgets.QCheckBox("支持图片输入")
        self._chk_vision.setChecked(cfg.get('supports_vision', False))
        features_row.addWidget(self._chk_vision)
        self._chk_fc = QtWidgets.QCheckBox("支持 Function Calling")
        self._chk_fc.setChecked(cfg.get('supports_fc', True))
        features_row.addWidget(self._chk_fc)
        features_row.addStretch()
        form.addRow("特性:", features_row)

        layout.addLayout(form)

        # 测试连接按钮
        test_row = QtWidgets.QHBoxLayout()
        test_row.addStretch()
        self._btn_test = QtWidgets.QPushButton("测试连接")
        self._btn_test.setMinimumWidth(100)
        self._btn_test.setMinimumHeight(28)
        self._btn_test.clicked.connect(self._test_connection)
        test_row.addWidget(self._btn_test)
        self._test_status = QtWidgets.QLabel("")
        self._test_status.setStyleSheet("font-size: 12px;")
        test_row.addWidget(self._test_status)
        test_row.addStretch()
        layout.addLayout(test_row)

        # 按钮
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # 样式
        self.setStyleSheet("""
            QDialog#customProviderDialog {
                background: #1e1e1e;
                color: #ddd;
            }
            QLabel { color: #ccc; }
            QLineEdit, QSpinBox {
                background: #2a2a2a;
                color: #eee;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QLineEdit:focus, QSpinBox:focus {
                border-color: #6a9eff;
            }
            QCheckBox { color: #ccc; }
            QPushButton {
                background: #333;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 12px;
            }
            QPushButton:hover { background: #444; border-color: #6a9eff; }
        """)

    def _test_connection(self):
        """测试 Custom API 连接"""
        url = self._url_edit.text().strip()
        key = self._key_edit.text().strip()
        models = [m.strip() for m in self._models_edit.text().split(',') if m.strip()]
        model = models[0] if models else 'test'

        if not url:
            self._test_status.setText("⚠ 请先填写 API URL")
            self._test_status.setStyleSheet("color: #f5a623; font-size: 12px;")
            return

        self._btn_test.setEnabled(False)
        self._test_status.setText("连接中...")
        self._test_status.setStyleSheet("color: #aaa; font-size: 12px;")

        try:
            import requests
            headers = {'Content-Type': 'application/json'}
            if key:
                headers['Authorization'] = f'Bearer {key}'
            payload = {
                'model': model,
                'messages': [{'role': 'user', 'content': 'Hi'}],
                'max_tokens': 5,
                'stream': False,
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                recv_model = data.get('model', model)
                self._test_status.setText(f"✅ 连接成功（{recv_model}）")
                self._test_status.setStyleSheet("color: #4caf50; font-size: 12px;")
            else:
                err = resp.text[:120]
                self._test_status.setText(f"❌ HTTP {resp.status_code}: {err}")
                self._test_status.setStyleSheet("color: #f44336; font-size: 12px;")
        except Exception as e:
            self._test_status.setText(f"❌ {str(e)[:100]}")
            self._test_status.setStyleSheet("color: #f44336; font-size: 12px;")
        finally:
            self._btn_test.setEnabled(True)

    def _on_accept(self):
        """确认前校验必填项"""
        url = self._url_edit.text().strip()
        models_text = self._models_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, "提示", "请填写 API URL。")
            return
        if not models_text:
            QtWidgets.QMessageBox.warning(self, "提示", "请填写至少一个模型名。")
            return
        self.accept()

    def get_config(self) -> dict:
        """返回用户配置的字典"""
        models = [m.strip() for m in self._models_edit.text().split(',') if m.strip()]
        return {
            'api_url': self._url_edit.text().strip(),
            'api_key': self._key_edit.text().strip(),
            'models': models,
            'context_limit': self._ctx_spin.value(),
            'supports_vision': self._chk_vision.isChecked(),
            'supports_fc': self._chk_fc.isChecked(),
        }
