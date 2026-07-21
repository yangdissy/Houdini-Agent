# -*- coding: utf-8 -*-
"""Context/message/token/RAG/URL helpers for AITab."""

import re

from houdini_agent.qt_compat import QtCore
from houdini_agent.ui.i18n import tr


class ContextManagerMixin:
    """上下文管理：消息交替修复、伪造工具清理、压缩、RAG、URL 处理。"""


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
