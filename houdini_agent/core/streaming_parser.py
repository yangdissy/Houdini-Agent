# -*- coding: utf-8 -*-
"""
Streaming Parser Mixin — 流式内容解析与思考区块处理

从 ai_tab.py 中拆分出的 Mixin，负责：
- <think> 标签流式解析状态机
- 自适应缓冲输出（防止 UI 卡顿）
- 思考区块 finalize/resume 线程安全调度
- Token 输出限制检查
- 原生 reasoning_content 处理（DeepSeek R1 等）
- 思考计时器与思考指示条更新
"""

import time

from houdini_agent.qt_compat import QtCore
from .thinking_stream_parser import ThinkingStreamParser
from ..ui.i18n import tr


class StreamingParserMixin:
    """<think> 标签流式解析、自适应缓冲输出、思考区块管理"""

    # ------------------------------------------------------------------
    # 信号处理入口（由 AITab 信号连接到这里）
    # ------------------------------------------------------------------

    def _on_append_content(self, text: str):
        """处理内容追加（主线程槽函数）

        注意：内容已经在 _on_content_with_limit → ThinkingStreamParser →
        _emit_normal_content 中经过了 <think> 标签过滤和伪造检测。
        这里只负责将文本交给 UI 控件显示，不做额外过滤。
        """
        resp = self._agent_response or self._current_response
        if not text or not resp:
            return
        # ★ 修复：不丢弃包含换行符的 chunk
        # 纯换行符（\n\n）是 Markdown 段落分隔的关键信号，
        # 丢弃它们会导致多段内容粘连在一起
        if not text.strip() and '\n' not in text:
            return
        try:
            # ★ 内容开始流入 → 隐藏 "Generating..." 状态（如果正在显示）
            if hasattr(self, 'thinking_bar') and getattr(self.thinking_bar, '_mode', None) == 'generating':
                self.thinking_bar.stop()
            resp.append_content(text)
            self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget 已被 clear 销毁

    def _on_content_with_limit(self, text: str):
        """处理内容追加，解析 <think> 标签，分离思考和正式内容"""
        if not text:
            return

        # 初始化输出缓冲
        if not hasattr(self, '_output_buffer'):
            self._output_buffer = ""
            self._last_flush_time = time.time()
            self._adaptive_buf_size = 80
            self._adaptive_interval = 0.15
            self._last_render_duration = 0.0
            self._flush_count = 0
            self._is_first_content_chunk = True

        if not hasattr(self, '_thinking_stream_parser'):
            self._thinking_stream_parser = ThinkingStreamParser()
        self._dispatch_thinking_stream_events(self._thinking_stream_parser.feed(text))

    # ------------------------------------------------------------------
    # <think> 标签流式解析
    # ------------------------------------------------------------------

    def _dispatch_thinking_stream_events(self, events):
        """Translate parser events to the existing Qt/UI behavior."""
        for event in events:
            if event.kind == 'content':
                self._emit_normal_content(event.text)
            elif event.kind == 'thinking_start':
                if self._think_enabled:
                    self._thinking_needs_finalize = True
                    self._resume_thinking()
            elif event.kind == 'thinking':
                if self._think_enabled and event.text:
                    self._addThinking.emit(event.text)
            elif event.kind == 'thinking_end' and self._think_enabled:
                self._finalize_thinking()

    def _finish_thinking_stream(self):
        """Flush pending parser state when a stream completes or aborts."""
        parser = getattr(self, '_thinking_stream_parser', None)
        if parser is not None:
            self._dispatch_thinking_stream_events(parser.finish())

    def _finalize_thinking(self):
        """思考阶段结束（线程安全：自动分派到主线程）"""
        self._finalizeThinkingSignal.emit()

    def _resume_thinking(self):
        """新一轮 <think> 开始（线程安全：自动分派到主线程）"""
        self._resumeThinkingSignal.emit()

    @QtCore.Slot()
    def _finalize_thinking_main_thread(self):
        """[主线程] 实际执行 finalize 思考区块并停止计时器"""
        try:
            resp = self._agent_response or self._current_response
            if resp and resp._has_thinking:
                if not resp.thinking_section._finalized:
                    resp.thinking_section.finalize()
        except RuntimeError:
            pass  # widget 已被 clear 销毁
        if self._thinking_timer:
            self._thinking_timer.stop()
            self._thinking_timer = None
        # ★ 停止输入框上方的思考指示条
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass

    @QtCore.Slot()
    def _resume_thinking_main_thread(self):
        """[主线程] 实际执行恢复思考区块并重启计时器"""
        if not getattr(self, '_is_running', False):
            return  # Agent 已停止，忽略延迟到达的信号
        try:
            resp = self._agent_response or self._current_response
            if resp and resp._has_thinking:
                ts = resp.thinking_section
                if ts._finalized:
                    ts.resume()
        except RuntimeError:
            pass  # widget 已被 clear 销毁
        # 重启计时器（如果已停止）
        if not self._thinking_timer:
            self._thinking_timer = QtCore.QTimer(self)
            # 信号-信号直连：Qt 在对象销毁时自动断开，避免 lambda 捕获已销毁的 self
            self._thinking_timer.timeout.connect(self._updateThinkingTime)
            self._thinking_timer.start(1000)
        # ★ 重新启动输入框上方的思考指示条
        try:
            self.thinking_bar.start()
        except (RuntimeError, AttributeError):
            pass

    def _emit_normal_content(self, text: str):
        """发送正式内容（带 token 限制 + 自适应缓冲刷新）

        ★ 自适应策略（借鉴 markstream-vue 的时间预算机制）：
        - 首个 chunk 立即刷新，消除首字延迟
        - 后续根据上一次渲染耗时动态调整缓冲大小：
          渲染快 → 小缓冲、多刷新（流畅感）
          渲染慢 → 大缓冲、少刷新（避免卡顿）
        - 换行始终立即刷新（段落边界及时显示）
        """
        if not text:
            return
        # 首次正式内容到达时，确保思考区块已 finalize（适配 DeepSeek 原生 reasoning_content）
        # 使用标志位避免从后台线程访问 Qt 控件属性
        parser = getattr(self, '_thinking_stream_parser', None)
        if not (parser and parser.in_thinking) and getattr(self, '_thinking_needs_finalize', True):
            self._finalize_thinking()  # 通过信号分派到主线程
            self._thinking_needs_finalize = False

        # Token 限制仅对正式内容计数
        if not self._check_output_token_limit(text):
            if self._output_buffer:
                self._appendContent.emit(self._output_buffer)
                self._output_buffer = ""
            self._appendContent.emit(tr('ai.token_limit'))
            self._addStatus.emit(tr('ai.token_limit_status'))
            self.client.request_stop()
            return

        self._output_buffer += text

        # ★ 自适应缓冲刷新策略
        should_flush = False
        current_time = time.time()

        # 初始化自适应状态（首次调用）
        if not hasattr(self, '_adaptive_buf_size'):
            self._adaptive_buf_size = 80       # 初始缓冲大小（字符）
            self._adaptive_interval = 0.15     # 初始兜底间隔（秒）
            self._last_render_duration = 0.0   # 上次渲染耗时
            self._flush_count = 0              # flush 计数（性能追踪）
            self._is_first_content_chunk = True  # 首个 chunk 标志

        # 规则 1: 首个 chunk 立即刷新（消除首字延迟）
        if self._is_first_content_chunk:
            should_flush = True
            self._is_first_content_chunk = False
        # 规则 2: 缓冲区达到自适应阈值
        elif len(self._output_buffer) >= self._adaptive_buf_size:
            should_flush = True
        # 规则 3: 换行时立即刷新（段落边界及时显示）
        elif '\n' in text:
            should_flush = True
        # 规则 4: 自适应兜底间隔
        elif current_time - self._last_flush_time > self._adaptive_interval:
            should_flush = True

        if should_flush and self._output_buffer:
            flush_start = time.time()

            # 实时过滤伪造的工具调用行
            buf = self._output_buffer
            if '[ok]' in buf or '[err]' in buf or '[工具执行结果]' in buf or '[Tool Result]' in buf:
                lines = buf.split('\n')
                filtered = []
                has_fake = False
                for ln in lines:
                    s = ln.strip()
                    if s == '[工具执行结果]' or s == '[Tool Result]' or self._FAKE_TOOL_PATTERNS.match(s):
                        has_fake = True
                        continue
                    filtered.append(ln)
                buf = '\n'.join(filtered)
                if has_fake and not getattr(self, '_fake_warned', False):
                    self._addStatus.emit(tr('ai.fake_tool'))
                    self._fake_warned = True
            if buf.strip():
                self._appendContent.emit(buf)
            self._output_buffer = ""
            self._last_flush_time = current_time
            self._flush_count += 1

            # ★ 自适应调整：根据上次渲染耗时动态调整缓冲参数
            render_dur = time.time() - flush_start
            self._last_render_duration = render_dur
            if render_dur < 0.004:
                # 渲染很快 → 减小缓冲，更频繁刷新（流畅感）
                self._adaptive_buf_size = max(40, self._adaptive_buf_size - 20)
                self._adaptive_interval = max(0.08, self._adaptive_interval - 0.02)
            elif render_dur > 0.012:
                # 渲染较慢 → 增大缓冲，减少刷新（避免卡顿）
                self._adaptive_buf_size = min(500, self._adaptive_buf_size + 40)
                self._adaptive_interval = min(0.40, self._adaptive_interval + 0.05)

    def _check_output_token_limit(self, text: str) -> bool:
        """检查正式输出 token 是否超过限制（思考内容不计入）"""
        if not text:
            return True
        new_tokens = self.token_optimizer.estimate_tokens(text)
        self._current_output_tokens += new_tokens
        if self._current_output_tokens >= self._max_output_tokens:
            return False
        if (self._current_output_tokens >= self._output_token_warning
                and self._current_output_tokens < self._max_output_tokens):
            remaining = self._max_output_tokens - self._current_output_tokens
            if remaining < 400:
                self._addStatus.emit(
                    tr('ai.approaching_limit', self._current_output_tokens, self._max_output_tokens))
        return True

    def _on_thinking_chunk(self, text: str):
        """处理原生 reasoning_content（DeepSeek R1 等模型）

        ★ 受 Think 开关控制：关闭时静默丢弃
        """
        if text and self._think_enabled:
            self._addThinking.emit(text)

    @QtCore.Slot(str)
    def _on_add_thinking(self, text: str):
        """在主线程更新思考内容（槽函数）"""
        if not getattr(self, '_is_running', False):
            return  # Agent 已停止，忽略延迟到达的信号
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_thinking(text)
                # ★ 首次思考内容 → 启动输入框上方思考指示条
                if hasattr(self, 'thinking_bar') and not self.thinking_bar.isVisible():
                    self.thinking_bar.start()
            self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget 已被 clear 销毁

    def _on_add_status(self, text: str):
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.add_status(text)
                self._scroll_agent_to_bottom(force=False)
        except RuntimeError:
            pass  # widget 已被 clear 销毁

    def _on_update_thinking(self):
        try:
            resp = self._agent_response or self._current_response
            if resp:
                resp.update_thinking_time()
                # ★ 同步更新输入框上方思考指示条的时间
                if hasattr(self, 'thinking_bar') and self.thinking_bar.isVisible():
                    if resp._has_thinking:
                        self.thinking_bar.set_elapsed(resp.thinking_section._total_elapsed())
        except RuntimeError:
            pass  # 控件可能已销毁
