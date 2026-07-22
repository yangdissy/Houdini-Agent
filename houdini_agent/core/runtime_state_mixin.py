# -*- coding: utf-8 -*-
"""Runtime state and agent lifecycle helpers for AITab."""

import math
import re
import threading
import time
from datetime import datetime

from houdini_agent.qt_compat import QtCore
from houdini_agent.ui.i18n import tr
from ..utils.dev_feature_toggles import DEV_FEATURE_TOGGLES, is_toggle_enabled


class RuntimeStateMixin:
    _TAB_RUNNING_PREFIX = "\u25cf "

    @staticmethod
    def _selection_watch_enabled() -> bool:
        toggle = next(t for t in DEV_FEATURE_TOGGLES if t.env_name == "HOUDINI_AGENT_SELECTION_WATCH")
        return is_toggle_enabled(toggle)

    def _set_running(self, running: bool):
        self._is_running = running

        if running:
            self._agent_session_id = self._session_id
            self._agent_response = self._current_response
            self._agent_scroll_area = self.scroll_area
            self._agent_history = self._conversation_history
            self._agent_token_stats = self._token_stats
            self._agent_todo_list = self.todo_list
            self._agent_chat_layout = self.chat_layout

            self._thinking_buffer = ""
            self._content_buffer = ""
            self._current_output_tokens = 0
            self._in_think_block = False
            self._tag_parse_buf = ""
            self._fake_warned = False
            self._output_buffer = ""
            self._last_flush_time = time.time()
            self._adaptive_buf_size = 80
            self._adaptive_interval = 0.15
            self._last_render_duration = 0.0
            self._flush_count = 0
            self._is_first_content_chunk = True

            self.client.reset_stop()
            self._thinking_timer = QtCore.QTimer(self)
            # 信号-信号直连：Qt 在对象销毁时自动断开，避免 lambda 捕获已销毁的 self
            self._thinking_timer.timeout.connect(self._updateThinkingTime)
            self._thinking_timer.start(1000)
            self._start_input_glow()
            self._selection_stop_triggered = False
            self._start_selection_watch()
        else:
            self._stop_selection_watch()
            if self._thinking_timer:
                self._thinking_timer.stop()
                self._thinking_timer = None
            self._stop_input_glow()
            self._stop_active_aurora()
            try:
                self.thinking_bar.stop()
            except (RuntimeError, AttributeError):
                pass

            if self._agent_session_id and self._agent_session_id in self._sessions:
                session_state = self._sessions[self._agent_session_id]
                session_state['current_response'] = self._agent_response
                if self._agent_history is not None:
                    session_state['conversation_history'] = self._agent_history
                if self._agent_token_stats is not None:
                    session_state['token_stats'] = self._agent_token_stats
                if self._agent_todo_list is not None:
                    session_state['todo_list'] = self._agent_todo_list

            self._agent_session_id = None
            self._agent_response = None
            self._agent_scroll_area = None
            self._agent_history = None
            self._agent_token_stats = None
            self._agent_todo_list = None
            self._agent_chat_layout = None

        self._update_run_buttons()

    def _start_selection_watch(self):
        """★ 启动用户选择监视：Agent 运行期间轮询 Houdini 选择集。

        目的：Agent 运行时若用户在视口/网络里点选节点（手动交互），会与
        主线程正在进行的 hou 操作/cook 交错重入，触发 Qt/hou 段错误崩溃
        （crash 分析 2026-07）。检测到用户改变选择即自动停止 Agent。

        用 hou.ui.addEventLoopCallback 在主线程事件循环轮询，回调天然线程
        安全；request_stop 只 set 线程事件、不触碰 hou 场景，不引入新竞态。
        以启动时的选择为基线，只有之后发生变化才判定为用户操作。
        """
        self._selection_watch_cb = None
        self._agent_selection_baseline = None
        if not self._selection_watch_enabled():
            return
        # 启动瞬间给一个短抑制期，吸收 Agent 首个工具执行前的选择抖动
        self._selection_settle_until = time.time() + 1.0
        try:
            import hou  # type: ignore
            self._agent_selection_baseline = {n.path() for n in hou.selectedNodes()}
            hou.ui.addEventLoopCallback(self._on_selection_poll)
            self._selection_watch_cb = self._on_selection_poll
        except Exception:
            # 无 UI 环境 / hou 不可用 / 无 addEventLoopCallback：静默跳过，不影响运行
            self._selection_watch_cb = None

    def _refresh_selection_baseline(self):
        """★ 把当前选择集刷新为新基线（Agent 每次工具执行后调用）。

        Agent 自身操作（如 create_node、delete_node）会改变节点选择，若不
        更新基线，下一次 poll 会把 Agent 造成的选择变化误判为用户手动操作
        而误触发停止。工具在主线程执行完毕后调用此方法吸收该变化。

        同时记录时间戳建立"抑制窗口"：工具执行可能触发嵌套事件循环
        （cook/UI 刷新），使 poll 在基线刷新前插入、读到 Agent 改后的选择
        而误报。抑制窗口内 poll 只刷新基线、不触发停止，消除该时序竞态。
        仅在监视处于激活状态时更新，避免无谓开销。
        """
        if getattr(self, '_selection_watch_cb', None) is None:
            return
        self._selection_settle_until = time.time() + 2.0
        try:
            import hou  # type: ignore
            self._agent_selection_baseline = {n.path() for n in hou.selectedNodes()}
        except Exception:
            pass  # 读取失败时保留旧基线，不影响运行

    def _stop_selection_watch(self):
        """注销选择监视回调（Agent 结束/停止/AITab 销毁时调用）。"""
        cb = getattr(self, '_selection_watch_cb', None)
        if cb is not None:
            try:
                import hou  # type: ignore
                hou.ui.removeEventLoopCallback(cb)
            except Exception:
                pass
            self._selection_watch_cb = None
        self._agent_selection_baseline = None

    def _on_selection_poll(self):
        """事件循环回调（主线程）：检测到用户改变选择则自动停止 Agent。"""
        if not getattr(self, '_is_running', False):
            return
        if getattr(self, '_selection_stop_triggered', False):
            return
        try:
            import hou  # type: ignore
            current = {n.path() for n in hou.selectedNodes()}
        except Exception:
            return  # 读取失败时保守不触发，避免误停
        # ★ 抑制窗口：工具执行前后（含其触发的 cook/UI 刷新导致的选择抖动）
        #   期间，把当前选择持续吸收为基线、不触发停止，消除 Agent 自身操作
        #   与 poll 之间的时序竞态误报。
        if time.time() < getattr(self, '_selection_settle_until', 0.0):
            self._agent_selection_baseline = current
            return
        baseline = getattr(self, '_agent_selection_baseline', None)
        if baseline is None or current == baseline:
            return
        # 用户改变了选择 → 停止一次（原因提示在 _on_agent_stopped 里写入正文，
        # 避免这里 emit 的状态被后续停止流程覆盖或一闪而过）
        self._selection_stop_triggered = True
        try:
            self.client.request_stop()
        except (RuntimeError, AttributeError):
            pass

    def cleanup(self):
        """销毁前清理：停止所有定时器并请求停止 agent，避免悬空回调。

        当 AITab 被销毁（如切换用户）时，若 agent 仍在运行，运行中的
        QTimer 会在 C++ 对象销毁后继续触发，导致 RuntimeError。
        """
        try:
            self.client.request_stop()
        except (RuntimeError, AttributeError):
            pass
        executor = getattr(self, '_houdini_main_thread_executor', None)
        if executor is not None:
            executor.shutdown()
        self._stop_selection_watch()
        for attr in ("_thinking_timer", "_glow_timer"):
            timer = getattr(self, attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
                setattr(self, attr, None)

    def _start_input_glow(self):
        """启动输入框边框呼吸光晕（AI 运行期间）"""
        self._glow_phase = 0.0
        if not hasattr(self, '_glow_timer') or self._glow_timer is None:
            self._glow_timer = QtCore.QTimer(self)
            self._glow_timer.setInterval(50)
            self._glow_timer.timeout.connect(self._update_input_glow)
        self._glow_timer.start()

    def _stop_input_glow(self):
        """停止输入框呼吸光晕，恢复默认边框"""
        if hasattr(self, '_glow_timer') and self._glow_timer is not None:
            self._glow_timer.stop()
        try:
            self.input_edit.setStyleSheet("")
        except RuntimeError:
            pass

    def _update_input_glow(self):
        """定时器回调：正弦波驱动边框亮度在银灰/亮白之间柔和呼吸"""
        self._glow_phase += 0.04
        t = (math.sin(self._glow_phase) + 1.0) / 2.0
        r = int(100 + (200 - 100) * t)
        g = int(116 + (210 - 116) * t)
        b = int(139 + (220 - 139) * t)
        a = int(60 + 70 * t)
        try:
            self.input_edit.setStyleSheet(
                f"QPlainTextEdit#chatInput {{ border: 1.5px solid rgba({r},{g},{b},{a}); }}"
            )
        except RuntimeError:
            pass

    def _start_active_aurora(self):
        """启动当前活跃 AIResponse 的流光边框"""
        try:
            response = self._agent_response or self._current_response
            if response and hasattr(response, 'aurora_bar'):
                response.start_aurora()
        except RuntimeError:
            pass

    def _stop_active_aurora(self):
        """停止当前活跃 AIResponse 的流光边框"""
        try:
            response = self._agent_response or self._current_response
            if response and hasattr(response, 'aurora_bar'):
                response.stop_aurora()
        except RuntimeError:
            pass

    def _update_run_buttons(self):
        """根据当前显示的 session 是否正在运行，更新 send/stop 按钮和 tab 指示器"""
        current_is_running = (
            self._agent_session_id is not None
            and self._agent_session_id == self._session_id
        )
        any_running = self._agent_session_id is not None
        self.btn_stop.setVisible(current_is_running)
        self.btn_send.setVisible(not current_is_running)
        self.btn_send.setEnabled(not any_running)

        for i in range(self.session_tabs.count()):
            sid = self.session_tabs.tabData(i)
            label = self.session_tabs.tabText(i)
            is_agent_tab = sid == self._agent_session_id and self._agent_session_id is not None
            has_prefix = label.startswith(self._TAB_RUNNING_PREFIX)
            if is_agent_tab and not has_prefix:
                self.session_tabs.setTabText(i, self._TAB_RUNNING_PREFIX + label)
            elif not is_agent_tab and has_prefix:
                self.session_tabs.setTabText(i, label[len(self._TAB_RUNNING_PREFIX):])

    def _restore_update_mode(self):
        """恢复 Houdini 更新模式（Agent 结束/错误/停止时调用）

        无论恢复成功与否都清空 _pre_agent_update_mode，避免下一轮把
        Agent 留下的 Manual 误当成"用户原模式"记录。
        """
        user_mode = getattr(self, '_pre_agent_update_mode', None)
        if user_mode is None:
            return
        try:
            import hou  # type: ignore
            if hou.updateModeSetting() != user_mode:
                hou.setUpdateMode(user_mode)
        except Exception as e:
            print(f"[Cook Guard] 恢复 update mode 失败: {e}")
        finally:
            self._pre_agent_update_mode = None

    def _on_agent_done(self, result: dict):
        self._fire_session_hook('on_session_end', self._agent_session_id or self._session_id)

        self._main_thread_busy = False
        self._restore_update_mode()
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass

        response = self._agent_response or self._current_response
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        stats = self._agent_token_stats or self._token_stats

        if self._tag_parse_buf:
            if self._in_think_block:
                if self._think_enabled:
                    self._addThinking.emit(self._tag_parse_buf)
            else:
                self._emit_normal_content(self._tag_parse_buf)
            self._tag_parse_buf = ""
            self._in_think_block = False

        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""

        try:
            if response:
                response.finalize()
        except RuntimeError:
            response = None

        tool_calls_history = result.get('tool_calls_history', [])
        new_messages = result.get('new_messages', [])
        if new_messages:
            for message in new_messages:
                clean = message.copy()
                clean.pop('reasoning_content', None)
                if message is new_messages[-1] and message.get('role') == 'assistant' and not message.get('tool_calls'):
                    continue
                history.append(clean)

        final_content = result.get('final_content', '')
        if not final_content or not final_content.strip():
            for message in reversed(new_messages):
                if message.get('role') == 'assistant' and message.get('content'):
                    content = message['content']
                    stripped = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
                    if stripped:
                        final_content = content
                        break
            if not final_content or not final_content.strip():
                final_content = result.get('content', '')

        thinking_text = ""
        clean_content = ""
        if final_content:
            thinking_parts = re.findall(r'<think>([\s\S]*?)</think>', final_content)
            thinking_text = '\n'.join(thinking_parts).strip() if thinking_parts else ''
            clean_content = re.sub(r'<think>[\s\S]*?</think>', '', final_content).strip()
            clean_content = self._strip_fake_tool_results(clean_content)

        need_final = bool(clean_content) or bool(new_messages) or not history or history[-1].get('role') != 'assistant'
        if need_final:
            final_msg = {'role': 'assistant', 'content': clean_content or tr('ai.no_content')}
            if thinking_text:
                final_msg['thinking'] = thinking_text
            py_shells = []
            sys_shells = []
            for tool_call in tool_calls_history:
                tool_name = tool_call.get('tool_name', '')
                tool_args = tool_call.get('arguments', {})
                tool_result = tool_call.get('result', {})
                if tool_name == 'execute_python' and tool_args.get('code'):
                    py_shells.append({
                        'code': tool_args['code'],
                        'output': tool_result.get('result', ''),
                        'error': tool_result.get('error', ''),
                        'success': bool(tool_result.get('success')),
                    })
                elif tool_name == 'execute_shell' and tool_args.get('command'):
                    sys_shells.append({
                        'command': tool_args['command'],
                        'output': tool_result.get('result', ''),
                        'error': tool_result.get('error', ''),
                        'success': bool(tool_result.get('success')),
                        'cwd': tool_args.get('cwd', ''),
                    })
            if py_shells:
                final_msg['python_shells'] = py_shells
            if sys_shells:
                final_msg['system_shells'] = sys_shells
            history.append(final_msg)

        self._manage_context()

        usage = result.get('usage', {})
        new_call_records = result.get('call_records', [])
        if usage:
            stats['input_tokens'] += usage.get('prompt_tokens', 0)
            stats['output_tokens'] += usage.get('completion_tokens', 0)
            stats['reasoning_tokens'] = stats.get('reasoning_tokens', 0) + usage.get('reasoning_tokens', 0)
            stats['cache_read'] += usage.get('cache_hit_tokens', 0)
            stats['cache_write'] += usage.get('cache_miss_tokens', 0)
            stats['total_tokens'] += usage.get('total_tokens', 0)
            stats['requests'] += 1

            from houdini_agent.utils.token_optimizer import calculate_cost
            model_name = self.model_combo.currentText()
            this_cost = calculate_cost(
                model=model_name,
                input_tokens=usage.get('prompt_tokens', 0),
                output_tokens=usage.get('completion_tokens', 0),
                cache_hit=usage.get('cache_hit_tokens', 0),
                cache_miss=usage.get('cache_miss_tokens', 0),
                reasoning_tokens=usage.get('reasoning_tokens', 0),
            )
            stats['estimated_cost'] = stats.get('estimated_cost', 0.0) + this_cost

        if new_call_records:
            if not hasattr(self, '_call_records'):
                self._call_records = []
            self._call_records.extend(new_call_records)
            call_rows = []
            for record in new_call_records:
                if not isinstance(record, dict):
                    continue
                call_rows.append({
                    'event_type': 'api_call_record',
                    'model': record.get('model'),
                    'iteration': record.get('iteration'),
                    'latency': record.get('latency'),
                    'input_tokens': record.get('input_tokens'),
                    'output_tokens': record.get('output_tokens'),
                    'reasoning_tokens': record.get('reasoning_tokens'),
                    'cache_hit': record.get('cache_hit'),
                    'cache_miss': record.get('cache_miss'),
                    'total_tokens': record.get('total_tokens'),
                    'estimated_cost': record.get('estimated_cost'),
                    'has_tool_calls': bool(record.get('has_tool_calls')),
                })
            self._append_session_diagnostics_records(
                call_rows,
                session_id=self._agent_session_id or self._session_id,
            )

        if usage:
            if not self._agent_session_id or self._agent_session_id == self._session_id:
                self._update_token_stats_display()

            cache_hit = usage.get('cache_hit_tokens', 0)
            cache_miss = usage.get('cache_miss_tokens', 0)
            cache_rate = usage.get('cache_hit_rate', 0)
            harness_trace = usage.get('harness_trace', [])

            if cache_hit > 0 or cache_miss > 0:
                rate_percent = cache_rate * 100
                self._addStatus.emit(f"Cache: {cache_hit}/{cache_hit+cache_miss} ({rate_percent:.0f}%)")

            if harness_trace:
                if not hasattr(self, '_harness_trace_records'):
                    self._harness_trace_records = []
                now_ts = datetime.now().strftime('%H:%M:%S')
                model_name = self.model_combo.currentText()
                persisted_rows = []
                for record in harness_trace:
                    item = dict(record or {})
                    item.setdefault('time', now_ts)
                    item.setdefault('model', model_name)
                    self._harness_trace_records.append(item)
                    persisted_rows.append(item)
                if len(self._harness_trace_records) > 2000:
                    self._harness_trace_records = self._harness_trace_records[-2000:]

                self._append_harness_trace_records(
                    persisted_rows,
                    session_id=self._agent_session_id or self._session_id,
                )
                session_rows = []
                for item in persisted_rows:
                    compress_stats = {
                        'compressed_messages': item.get('compressed_messages'),
                        'removed_messages': item.get('removed_messages'),
                        'compression_ratio': item.get('compression_ratio'),
                    }
                    compress_stats = {key: value for key, value in compress_stats.items() if value is not None}
                    session_rows.append({
                        'event_type': 'harness_round',
                        'source': 'ai_client',
                        'iteration': item.get('iteration'),
                        'tool_count': item.get('tool_count'),
                        'dedup_hits': item.get('dedup_hits'),
                        'early_skips': item.get('early_skips'),
                        'failed_tools': item.get('failed_tools'),
                        'retry_count': item.get('retries'),
                        'compress_stats': compress_stats or None,
                    })
                self._append_session_diagnostics_records(
                    session_rows,
                    session_id=self._agent_session_id or self._session_id,
                )

                total_tools = sum(int(item.get('tool_count', 0) or 0) for item in harness_trace)
                dedup_hits = sum(int(item.get('dedup_hits', 0) or 0) for item in harness_trace)
                early_skips = sum(int(item.get('early_skips', 0) or 0) for item in harness_trace)
                failed_tools = sum(int(item.get('failed_tools', 0) or 0) for item in harness_trace)
                self._addStatus.emit(
                    f"Harness: tools={total_tools}, dedup={dedup_hits}, skip={early_skips}, failed={failed_tools}"
                )

        if self._memory_initialized and tool_calls_history:
            reflect_params = getattr(self, '_last_agent_params', {})
            def do_reflect():
                self._reflect_after_task(result, reflect_params)
            reflect_thread = threading.Thread(target=do_reflect, daemon=True)
            reflect_thread.start()

        agent_sid = self._agent_session_id
        if self._auto_save_cache and len(history) > 0 and agent_sid:
            if agent_sid in self._sessions:
                self._sessions[agent_sid]['conversation_history'] = history
                self._sessions[agent_sid]['token_stats'] = stats
            if agent_sid == self._session_id:
                self._save_cache()

        self._set_running(False)
        self._hideToolStatus.emit()
        self._update_context_stats()
        self._maybe_generate_title(agent_sid, history)

    def _on_agent_error(self, error: str):
        self._main_thread_busy = False
        self._restore_update_mode()
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass
        if self._tag_parse_buf:
            if self._in_think_block and self._think_enabled:
                self._addThinking.emit(self._tag_parse_buf)
            elif not self._in_think_block:
                self._emit_normal_content(self._tag_parse_buf)
            self._tag_parse_buf = ""
        if self._in_think_block:
            self._in_think_block = False
            self._finalizeThinkingSignal.emit()
        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""

        response = self._agent_response or self._current_response
        try:
            if response:
                response.finalize()
                response.add_status(f"Error: {error}")
        except RuntimeError:
            pass

        self._ensure_history_ends_with_assistant(f"[Error] {error}")
        self._set_running(False)

    def _on_agent_stopped(self):
        self._main_thread_busy = False
        self._restore_update_mode()
        try:
            self.thinking_bar.stop()
        except (RuntimeError, AttributeError):
            pass
        if self._tag_parse_buf:
            if self._in_think_block and self._think_enabled:
                self._addThinking.emit(self._tag_parse_buf)
            elif not self._in_think_block:
                self._emit_normal_content(self._tag_parse_buf)
            self._tag_parse_buf = ""
        if self._in_think_block:
            self._in_think_block = False
            self._finalizeThinkingSignal.emit()
        if hasattr(self, '_output_buffer') and self._output_buffer:
            self._on_append_content(self._output_buffer)
            self._output_buffer = ""

        # ★ 若因用户手动操作 Houdini 而自动停止，用独立警示横幅显示原因，
        #   与 status_label("Stopped")/正文完全解耦，避免 finalize 时被
        #   "执行完成/no_reply" 覆盖吞掉（见 crash 分析 2026-07）。
        stopped_by_selection = getattr(self, '_selection_stop_triggered', False)

        response = self._agent_response or self._current_response
        try:
            if response:
                response.finalize()
                response.add_status("Stopped")
                if stopped_by_selection and hasattr(response, 'show_warning'):
                    response.show_warning(
                        "⚠ 检测到你手动操作了 Houdini（选择了节点）。"
                        "为防止与 Agent 操作冲突导致崩溃，已自动停止本次任务。"
                    )
        except RuntimeError:
            pass

        self._ensure_history_ends_with_assistant(
            "[因用户手动操作 Houdini 自动停止]" if stopped_by_selection
            else "[Stopped by user]"
        )
        self._set_running(False)
        self._hideToolStatus.emit()

        if self._pending_user_switch:
            target_user = self._pending_user_switch
            self._pending_user_switch = None
            self._perform_user_switch(target_user)

    def _ensure_history_ends_with_assistant(self, fallback_content: str):
        """确保 conversation_history 以 assistant 消息结尾。"""
        history = self._agent_history if self._agent_history is not None else self._conversation_history
        if history and history[-1].get('role') == 'user':
            history.append({'role': 'assistant', 'content': fallback_content})
