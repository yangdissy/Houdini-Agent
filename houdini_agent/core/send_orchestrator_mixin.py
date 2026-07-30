# -*- coding: utf-8 -*-
"""Send/run orchestration for AITab: _on_send, tool selection, and _run_agent."""

import copy
import re
import threading
import traceback

from typing import List

from houdini_agent.ui.i18n import tr
from houdini_agent.core.harness_engine import HarnessRuntimeState
from houdini_agent.utils.ai_client import AIClient, HOUDINI_TOOLS
from houdini_agent.utils.ultra_optimizer import UltraOptimizer
from houdini_agent.utils.token_optimizer import (
    assemble_context_messages,
    compress_old_round_tool_results,
    plan_context_rounds,
    prune_context_rounds_to_token_target,
)
from houdini_agent.utils.plan_manager import (
    PLAN_TOOL_CREATE,
    PLAN_TOOL_UPDATE_STEP,
    PLAN_TOOL_ASK_QUESTION,
)


class SendOrchestratorMixin:
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
                                    try:
                                        from ..utils.team_memory_export import maybe_export_team_memory
                                        maybe_export_team_memory(self._username, self._memory_store)
                                    except Exception:
                                        pass
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
                                try:
                                    from ..utils.team_memory_export import maybe_export_team_memory
                                    maybe_export_team_memory(self._username, self._memory_store)
                                except Exception:
                                    pass
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
                    rounds = plan_context_rounds(body, protect_recent_rounds=0).rounds
                    
                    # 第一遍：压缩旧轮次 tool 结果
                    n_rounds = len(rounds)
                    protect_n = max(2, int(n_rounds * 0.6))
                    summarize_tool_content = self.client._summarize_tool_content if hasattr(self.client, '_summarize_tool_content') else None
                    compress_old_round_tool_results(rounds, protect_n, summarize_fn=summarize_tool_content)
                    
                    # 如果仍超限，删除最早轮次
                    target = int(context_limit * 0.7)
                    prune_context_rounds_to_token_target(
                        rounds,
                        target,
                        self.token_optimizer.calculate_message_tokens,
                        prefix_messages=[first_system] if first_system else [],
                        suffix_messages=[last_context] if last_context else [],
                        min_rounds=2,
                        check_before_pop=True,
                    )
                    
                    # 重组
                    summary_message = None
                    if n_rounds - len(rounds) > 0:
                        summary_message = {
                            'role': 'system',
                            'content': tr('ai.old_rounds', n_rounds - len(rounds))
                        }
                    messages = assemble_context_messages(
                        rounds,
                        prefix_messages=[first_system] if first_system else [],
                        summary_message=summary_message,
                        suffix_messages=[last_context] if last_context else [],
                    )
                    
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
