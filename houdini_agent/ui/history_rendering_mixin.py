# -*- coding: utf-8 -*-
"""History conversation rendering helpers for AITab."""

import json
import re
import time

from houdini_agent.qt_compat import QtCore, QtWidgets
from houdini_agent.ui.cursor_rich_content import PythonShellWidget, SystemShellWidget


class HistoryRenderingMixin:
    """Render cached conversation history back into chat widgets."""

    _CONTEXT_HEADERS = ('[Network structure]', '[Selected nodes]',
                        '[Auto-read: Network structure]', '[Auto-read: Selected nodes]',
                        '[网络结构]', '[选中节点]')

    _BATCH_INITIAL = 30
    _BATCH_SIZE = 15
    _BATCH_BUDGET_MS = 8

    def _render_conversation_history(self):
        """重新渲染对话历史到 UI"""
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if hasattr(self, '_batch_render_timer') and self._batch_render_timer is not None:
            self._batch_render_timer.stop()
            self._batch_render_timer = None

        messages = self._conversation_history
        if not messages:
            return

        groups = self._group_messages_into_turns(messages)
        total_groups = len(groups)

        if total_groups <= self._BATCH_INITIAL:
            self._render_message_groups(groups, 0, total_groups)
        else:
            early_count = total_groups - self._BATCH_INITIAL

            self._batch_placeholder = QtWidgets.QLabel(
                f"⏳ 加载历史消息 ({early_count} 轮)..."
            )
            self._batch_placeholder.setObjectName("batchPlaceholder")
            self._batch_placeholder.setStyleSheet(
                "color: #64748b; padding: 8px 12px; font-size: 12px; "
                "font-style: italic; background: transparent;"
            )
            self._batch_placeholder.setAlignment(QtCore.Qt.AlignCenter)
            self.chat_layout.insertWidget(self.chat_layout.count() - 1,
                                         self._batch_placeholder)

            self._render_message_groups(groups, early_count, total_groups)

            self._batch_groups = groups
            self._batch_cursor = early_count
            self._batch_insert_pos = 0
            self._batch_render_timer = QtCore.QTimer(self)
            self._batch_render_timer.setSingleShot(True)
            self._batch_render_timer.timeout.connect(self._render_next_batch)
            self._batch_render_timer.start(0)

    def _group_messages_into_turns(self, messages: list) -> list:
        """将消息列表分组为逻辑轮次"""
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
        """分批渲染回调 — 渲染下一批早期消息。"""
        if not hasattr(self, '_batch_groups') or not self._batch_groups:
            return
        if self._batch_cursor <= 0:
            self._finish_batch_render()
            return

        batch_start = max(0, self._batch_cursor - self._BATCH_SIZE)
        batch_end = self._batch_cursor
        start_time = time.time()
        messages = self._conversation_history
        insert_pos = self._batch_insert_pos

        for gi in range(batch_start, batch_end):
            si, ei = self._batch_groups[gi]
            try:
                widgets_before = self.chat_layout.count()
                self._render_single_group(messages, si, ei)
                widgets_after = self.chat_layout.count()
                added = widgets_after - widgets_before

                if added > 0:
                    for _ in range(added):
                        from_idx = self.chat_layout.count() - 2
                        item = self.chat_layout.takeAt(from_idx)
                        if item and item.widget():
                            self.chat_layout.insertWidget(insert_pos, item.widget())
                            insert_pos += 1
            except Exception:
                import traceback
                traceback.print_exc()

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

    def _replay_todo_from_tool_call(self, tool_name: str, arguments_str: str):
        """从历史工具调用中恢复 todo 项（不显示在 UI 执行列表中）"""
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
            pass

    def _render_native_tool_turn(self, turn_msgs: list):
        """渲染 Cursor 风格原生工具调用轮次"""
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
                    for tc in tc_list:
                        fn = tc.get('function', {})
                        name = fn.get('name', 'unknown')
                        if name in self._SILENT_TOOLS:
                            self._replay_todo_from_tool_call(name, fn.get('arguments', ''))
                            continue
                        response.add_status(f"[tool]{name}")
                        tool_count += 1
                else:
                    final_content = m.get('content', '') or ''
                    thinking = m.get('thinking', '')
                    final_msg = m
            elif r == 'tool':
                tc_id = m.get('tool_call_id', '')
                t_content = m.get('content', '') or ''
                t_name = self._find_tool_name_by_id(turn_msgs, tc_id) or 'tool'
                if t_name in self._SILENT_TOOLS:
                    continue
                success = not t_content.lstrip().startswith('[err]') and 'error' not in t_content[:50].lower()
                prefix = "[ok] " if success else "[err] "
                response.add_tool_result(t_name, f"{prefix}{t_content}")

        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()

        self._restore_shell_widgets(response, final_msg)

        if final_content:
            response.set_content(final_content)

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

    def _render_user_history(self, content: str):
        """渲染用户历史消息，长上下文自动折叠"""
        split_pos = -1
        header_tag = ''
        for tag in self._CONTEXT_HEADERS:
            pos = content.find(tag)
            if pos != -1:
                split_pos = pos
                header_tag = tag
                break

        if split_pos > 0 and len(content) > 300:
            user_text = content[:split_pos].strip()
            context_data = content[split_pos:]
            if user_text:
                self._add_user_message(user_text)
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), context_data)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        elif split_pos == 0 and len(content) > 300:
            resp = self._add_ai_response()
            resp.add_collapsible(header_tag.strip('[]'), content)
            resp.status_label.setText("上下文")
            resp.finalize()
            resp.status_label.setText("上下文")
        else:
            self._add_user_message(content)

    _TOOL_LINE_PREFIXES = ('[ok] ', '[err] ', '\u2705 ', '\u274c ')

    def _render_tool_summary_history(self, content: str, msg: dict = None):
        """渲染 [工具执行结果] 格式的 assistant 消息"""
        if msg is None:
            msg = {}
        response = self._add_ai_response()

        entries = []
        for line in content.split('\n'):
            stripped = line.strip()
            if not stripped or stripped == '[工具执行结果]':
                if entries:
                    entries[-1][1].append('')
                continue
            is_new_entry = any(stripped.startswith(p) for p in self._TOOL_LINE_PREFIXES)
            if is_new_entry:
                entries.append((stripped, []))
            elif entries:
                entries[-1][1].append(stripped)

        tool_count = 0
        for first_line, cont_lines in entries:
            t_name = 'unknown'
            success = True
            rest = first_line
            for prefix in self._TOOL_LINE_PREFIXES:
                if first_line.startswith(prefix):
                    if 'err' in prefix or '\u274c' in prefix:
                        success = False
                    rest = first_line[len(prefix):]
                    break
            if ':' in rest:
                parts = rest.split(':', 1)
                t_name = parts[0].strip()
                first_result = parts[1].strip() if len(parts) > 1 else ''
            else:
                first_result = rest

            all_parts = [first_result] + cont_lines
            t_result = '\n'.join(all_parts).strip()

            if t_name in self._SILENT_TOOLS:
                continue
            response.add_status(f"[tool]{t_name}")
            tool_count += 1
            result_prefix = "[ok] " if success else "[err] "
            response.add_tool_result(t_name, f"{result_prefix}{t_result}")

        self._restore_shell_widgets(response, msg)

        thinking = msg.get('thinking', '')
        if thinking:
            response.add_thinking(thinking)
            response.thinking_section.finalize()

        text_after_tools = ''
        parts = content.split('\n\n')
        for idx_p, part in enumerate(parts):
            if not part.strip().startswith('[工具执行结果]') and not any(
                part.strip().startswith(p) for p in self._TOOL_LINE_PREFIXES
            ):
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

    def _restore_shell_widgets(self, response, msg: dict):
        """从历史消息中恢复 Python Shell / System Shell 折叠面板"""
        for ps in msg.get('python_shells', []):
            code = ps.get('code', '')
            raw_output = ps.get('output', '')
            error = ps.get('error', '')
            success = ps.get('success', True)
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

    def _render_old_tool_msgs(self, response, tool_msgs: list):
        """渲染旧格式 role=tool 消息到 AIResponse"""
        for tm in tool_msgs:
            t_name = tm.get('name', 'unknown')
            t_content = tm.get('content', '')
            if ':' in t_content:
                parts = t_content.split(':', 1)
                t_name = parts[0].strip() or t_name
                t_result = parts[1].strip() if len(parts) > 1 else t_content
            else:
                t_result = t_content
            if t_name in self._SILENT_TOOLS:
                continue
            success = not t_result.startswith('[err]') and not t_result.startswith('\u274c')
            response.add_status(f"[tool]{t_name}")
            result_prefix = "[ok] " if success else "[err] "

            response.add_tool_result(t_name, f"{result_prefix}{t_result}")