# -*- coding: utf-8 -*-
"""Preferences, model selection, and token statistics helpers for AITab."""

import json

from houdini_agent.qt_compat import QtWidgets, QtGui, QSettings
from houdini_agent.ui.cursor_theme import CursorTheme
from houdini_agent.ui.font_settings_dialog import FontSettingsDialog
from houdini_agent.ui.i18n import tr
from houdini_agent.utils.token_optimizer import CompressionStrategy


class PreferencesMixin:
    def _apply_font_scale(self):
        """重新渲染 QSS 并应用到界面"""
        self.setStyleSheet(self._theme.render())
        self._theme.save_preference()

    def _zoom_in(self):
        self._theme.zoom_in()
        self._apply_font_scale()

    def _zoom_out(self):
        self._theme.zoom_out()
        self._apply_font_scale()

    def _zoom_reset(self):
        self._theme.zoom_reset()
        self._apply_font_scale()

    def _on_font_settings(self):
        """打开字号设置面板"""
        dlg = FontSettingsDialog(current_scale=self._theme.scale, parent=self)
        dlg.scaleChanged.connect(self._on_font_scale_preview)
        dlg.exec_()
        self._theme.set_scale(dlg.scale)
        self._apply_font_scale()

    def _on_font_scale_preview(self, scale: float):
        """实时预览字号缩放"""
        self._theme.set_scale(scale)
        self.setStyleSheet(self._theme.render())

    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数量（粗略估算）"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        tokens = chinese_chars / 1.5 + other_chars / 4
        return int(tokens)

    def _calculate_context_tokens(self) -> int:
        """计算当前上下文的总 token 数（含工具定义）"""
        if not hasattr(self, '_tools_token_cache'):
            from houdini_agent.utils.ai_client import HOUDINI_TOOLS
            tools_json = json.dumps(HOUDINI_TOOLS, ensure_ascii=False)
            self._tools_token_cache = self.token_optimizer.estimate_tokens(tools_json)

        total = self._tools_token_cache
        total += self.token_optimizer.estimate_tokens(self._system_prompt)
        if self._context_summary:
            total += self.token_optimizer.estimate_tokens(self._context_summary)
        total += self.token_optimizer.calculate_message_tokens(self._conversation_history)
        return total

    def _save_model_preference(self):
        """保存模型选择偏好"""
        settings = QSettings("HoudiniAI", "Assistant")
        provider = self._current_provider()
        model = self.model_combo.currentText()
        settings.setValue("last_provider", provider)
        settings.setValue("last_model", model)
        settings.setValue("use_think", self.think_check.isChecked())
        settings.setValue("last_mode_index", self.mode_combo.currentIndex())
        settings.setValue("last_read_mode_index", self.read_combo.currentIndex())

    def _load_model_preference(self, restore_provider: bool = False):
        """加载模型选择偏好"""
        settings = QSettings("HoudiniAI", "Assistant")
        last_provider = settings.value("last_provider", "")
        last_model = settings.value("last_model", "")

        use_think = settings.value("use_think", True)
        if isinstance(use_think, str):
            use_think = use_think.lower() == 'true'
        self.think_check.setChecked(bool(use_think))

        mode_index = settings.value("last_mode_index", 1)
        try:
            mode_index = int(mode_index)
        except (TypeError, ValueError):
            mode_index = 1
        mode_index = max(0, min(mode_index, self.mode_combo.count() - 1))
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(mode_index)
        self.mode_combo.blockSignals(False)
        self._on_mode_changed(mode_index)

        read_index = settings.value("last_read_mode_index", 1)
        try:
            read_index = int(read_index)
        except (TypeError, ValueError):
            read_index = 1
        read_index = max(0, min(read_index, self.read_combo.count() - 1))
        self.read_combo.blockSignals(True)
        self.read_combo.setCurrentIndex(read_index)
        self.read_combo.blockSignals(False)
        self._on_auto_read_changed(read_index)

        if not last_provider:
            return

        if restore_provider and last_provider != self._current_provider():
            for i in range(self.provider_combo.count()):
                if self.provider_combo.itemData(i) == last_provider:
                    self.provider_combo.blockSignals(True)
                    self.provider_combo.setCurrentIndex(i)
                    self.provider_combo.blockSignals(False)
                    self._refresh_models(last_provider)
                    self._update_key_status()
                    break

        current_provider = self._current_provider()
        if last_provider == current_provider and last_model:
            available_models = [self.model_combo.itemText(i) for i in range(self.model_combo.count())]
            if last_model in available_models:
                index = self.model_combo.findText(last_model)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)

    def _get_current_context_limit(self) -> int:
        """获取当前模型的上下文限制"""
        model = self.model_combo.currentText()
        return self._model_context_limits.get(model, 64000)

    def _update_context_stats(self):
        """更新上下文统计显示（包含优化状态）"""
        used = self._calculate_context_tokens()
        limit = self._get_current_context_limit()

        if used >= 1000:
            used_str = f"{used / 1000:.1f}K"
        else:
            used_str = str(used)
        limit_str = f"{limit // 1000}K"
        percent = (used / limit) * 100 if limit > 0 else 0

        optimize_indicator = ""
        if self._auto_optimize:
            should_compress, _ = self.token_optimizer.should_compress(used, limit)
            if should_compress:
                optimize_indicator = " *"

        if percent < 50:
            ctx_state = ""
        elif percent < 80:
            ctx_state = "warning"
        else:
            ctx_state = "critical"

        self.context_label.setText(f"{percent:.1f}% {used_str}/{limit_str}{optimize_indicator}")
        self.context_label.setProperty("state", ctx_state)
        self.context_label.style().unpolish(self.context_label)
        self.context_label.style().polish(self.context_label)

        opt_state = "warning" if percent >= 80 else ""
        self.btn_optimize.setProperty("state", opt_state)
        self.btn_optimize.style().unpolish(self.btn_optimize)
        self.btn_optimize.style().polish(self.btn_optimize)

    def _update_token_stats_display(self):
        """更新 Token 统计按钮显示（对齐 Cursor：显示费用）"""
        total = self._token_stats['total_tokens']
        cost = self._token_stats.get('estimated_cost', 0.0)

        if total >= 1000000:
            tok_display = f"{total / 1000000:.1f}M"
        elif total >= 1000:
            tok_display = f"{total / 1000:.1f}K"
        else:
            tok_display = str(total)

        if cost >= 1.0:
            cost_display = f"${cost:.2f}"
        elif cost >= 0.01:
            cost_display = f"${cost:.2f}"
        elif cost > 0:
            cost_display = f"${cost:.4f}"
        else:
            cost_display = ""

        if cost_display:
            self.token_stats_btn.setText(f"{tok_display} | {cost_display}")
        else:
            self.token_stats_btn.setText(tok_display)

        cache_read = self._token_stats['cache_read']
        cache_write = self._token_stats['cache_write']
        cache_total = cache_read + cache_write
        hit_rate_display = f"{(cache_read / cache_total * 100):.1f}%" if cache_total > 0 else "N/A"

        reasoning = self._token_stats.get('reasoning_tokens', 0)
        reasoning_line = tr('token.reasoning_line', reasoning) if reasoning > 0 else ""

        self.token_stats_btn.setToolTip(
            tr('token.summary',
               self._token_stats['requests'],
               self._token_stats['input_tokens'],
               self._token_stats['output_tokens'],
               reasoning_line,
               cache_read, cache_write, hit_rate_display,
               total, cost_display or '$0.00')
        )

    def _show_token_stats_dialog(self):
        """显示详细 Token 统计对话框（对齐 Cursor：使用 TokenAnalyticsPanel）"""
        from houdini_agent.ui.cursor_analytics_widgets import TokenAnalyticsPanel
        records = getattr(self, '_call_records', []) or []
        harness_records = getattr(self, '_harness_trace_records', []) or []
        dialog = TokenAnalyticsPanel(records, self._token_stats, harness_records, parent=self)
        dialog.exec_()
        if dialog.should_reset_stats:
            self._reset_token_stats()

    def _reset_token_stats(self):
        """重置 Token 统计"""
        self._token_stats = self._empty_token_stats()
        self._call_records = []
        self._harness_trace_records = []
        self._update_token_stats_display()

        if self._current_response:
            self._current_response.add_status(tr('status.stats_reset'))

    @staticmethod
    def _empty_token_stats() -> dict:
        return {
            'input_tokens': 0,
            'output_tokens': 0,
            'reasoning_tokens': 0,
            'cache_read': 0,
            'cache_write': 0,
            'total_tokens': 0,
            'requests': 0,
            'estimated_cost': 0.0,
        }

    def _current_provider(self) -> str:
        return self.provider_combo.currentData() or 'deepseek'

    def _refresh_models(self, provider: str):
        self.model_combo.clear()

        if provider == 'ollama':
            try:
                models = self.client.get_ollama_models()
                if models:
                    self.model_combo.addItems(models)
                    return
            except Exception:
                pass

        self.model_combo.addItems(self._model_map.get(provider, []))

    def _update_key_status(self):
        provider = self._current_provider()

        if provider == 'ollama':
            result = self.client.test_connection('ollama')
            if result.get('ok'):
                self.key_status.setText("Local")
                self.key_status.setProperty("state", "ok")
            else:
                self.key_status.setText("Offline")
                self.key_status.setProperty("state", "error")
        elif self.client.has_api_key(provider):
            masked = self.client.get_masked_key(provider)
            self.key_status.setText(masked)
            self.key_status.setProperty("state", "ok")
        else:
            self.key_status.setText("No Key")
            self.key_status.setProperty("state", "warning")
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)

    def _on_provider_changed(self):
        provider = self._current_provider()
        self._refresh_models(provider)
        self._load_model_preference()
        self._update_key_status()
        self._on_provider_changed_custom_visibility()

    def _on_optimize_menu(self):
        """显示 Token 优化菜单"""
        menu = QtWidgets.QMenu(self)

        optimize_now_action = menu.addAction("立即压缩对话")
        optimize_now_action.triggered.connect(self._optimize_now)

        menu.addSeparator()

        auto_label = "自动压缩 [on]" if self._auto_optimize else "自动压缩"
        auto_opt_action = menu.addAction(auto_label)
        auto_opt_action.setCheckable(True)
        auto_opt_action.setChecked(self._auto_optimize)
        auto_opt_action.triggered.connect(lambda: setattr(self, '_auto_optimize', not self._auto_optimize))

        menu.addSeparator()

        strategy_menu = menu.addMenu("压缩策略")
        for label, strat in [
            ("激进 (最大节省)", CompressionStrategy.AGGRESSIVE),
            ("平衡 (推荐)", CompressionStrategy.BALANCED),
            ("保守 (保留细节)", CompressionStrategy.CONSERVATIVE),
        ]:
            action = strategy_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._optimization_strategy == strat)
            action.triggered.connect(lambda _, s=strat: setattr(self, '_optimization_strategy', s))

        menu.exec_(QtGui.QCursor.pos())

    def _optimize_now(self):
        """立即优化当前对话"""
        if len(self._conversation_history) <= 4:
            QtWidgets.QMessageBox.information(self, "提示", "对话历史太短，无需优化")
            return

        before_tokens = self._calculate_context_tokens()
        compressed_messages, stats = self.token_optimizer.compress_messages(
            self._conversation_history,
            strategy=self._optimization_strategy
        )

        if stats['saved_tokens'] > 0:
            self._conversation_history = compressed_messages
            self._context_summary = compressed_messages[0].get('content', '') if compressed_messages and compressed_messages[0].get('role') == 'system' else self._context_summary
            self._render_conversation_history()
            self._update_context_stats()
            saved_percent = stats.get('saved_percent', 0)
            QtWidgets.QMessageBox.information(
                self, "优化完成",
                f"对话已优化！\n\n"
                f"原始: ~{before_tokens:,} tokens\n"
                f"优化后: ~{stats['compressed_tokens']:,} tokens\n"
                f"节省: ~{stats['saved_tokens']:,} tokens ({saved_percent:.1f}%)\n\n"
                f"压缩了 {stats['compressed']} 条消息，保留 {stats['kept']} 条"
            )
        else:
            QtWidgets.QMessageBox.information(self, "提示", "无需优化，对话历史已经很精简")
