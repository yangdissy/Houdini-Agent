# -*- coding: utf-8 -*-
"""Send/run orchestration for AITab: _on_send, tool selection, and _run_agent."""

import threading
import traceback

from typing import List

from houdini_agent.qt_compat import QtWidgets
from houdini_agent.ui.i18n import tr
from houdini_agent.core.harness_engine import HarnessRuntimeState
from houdini_agent.utils.ai_client import AIClient, HOUDINI_TOOLS
from houdini_agent.utils.ultra_optimizer import UltraOptimizer
from houdini_agent.utils.token_optimizer import (
    DynamicContextSection,
    prune_context_assembly_to_token_target,
)
from houdini_agent.core.agent_request_assembly import (
    build_context,
    finalize_context_request,
    normalize_history,
)
from houdini_agent.utils.plan_manager import (
    PLAN_TOOL_CREATE,
    PLAN_TOOL_UPDATE_STEP,
    PLAN_TOOL_ASK_QUESTION,
)


class SendOrchestratorMixin:
    def _start_agent_run(
        self,
        agent_params_overrides: dict = None,
        inject_scene: bool = True,
        user_message: str = None,
    ):
        """启动一次 Agent/Plan 执行，共享运行前准备逻辑。

        普通 Agent 与 Plan 执行阶段都必须走这里，避免 Plan copy 一套
        update-mode 快照、UI 状态、参数收集和线程启动逻辑。
        """
        # 先记录用户/hip 原始 Update Mode。后续 Cook Guard 临时 Manual
        # 不能被误判为用户持久 Manual。
        self._capture_pre_agent_update_mode()
        self._remember_memory_calls = 0

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
        current_user_message = (
            user_message if user_message is not None else self._latest_user_message()
        )
        self._current_user_message = current_user_message
        agent_params['user_message'] = current_user_message

        self._save_model_preference()

        thread = threading.Thread(target=self._run_agent, args=(agent_params,), daemon=True)
        thread.start()

    # ===== 事件处理 =====
    
    def _on_send(self):
        text = self.input_edit.toPlainText().strip()
        # 任意 session 有 agent 在跑就阻止发送（AIClient 是共享的，不支持并行）
        if not text or self._agent_session_id is not None:
            return

        parsed_command = self._parse_slash_command(text)
        if parsed_command:
            command, args = parsed_command
            if getattr(self, f'_slash_{command}', None):
                self.input_edit.clear()
                self._execute_slash_command(command, args)
                return

        provider = self._current_provider()
        if not self.client.has_api_key(provider):
            self._on_set_key()
            return

        # ★ Hook: on_session_start
        self._fire_session_hook('on_session_start', self._session_id)

        # 收集待发送的图片（在 clear 之前）
        has_images = bool(self._pending_images) and self._current_model_supports_vision()
        if has_images and len(self._pending_images) > 1:
            try:
                self._rebudget_pending_images()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "图片处理失败", str(e))
                return
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

        self._start_agent_run(user_message=text)

    def _latest_user_message(self) -> str:
        """Return the latest user text without depending on mutable state later in the worker."""
        for message in reversed(self._conversation_history):
            if message.get('role') != 'user':
                continue
            content = message.get('content', '')
            if isinstance(content, list):
                return ' '.join(
                    part.get('text', '')
                    for part in content
                    if part.get('type') == 'text'
                )
            return str(content or '')
        return ''

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
        
        # ★ 存储 Think 开关状态，供 ThinkingStreamParser 事件分发 / _on_thinking_chunk 使用
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
            
            # ★ L0 核心记忆加载：用户手动 /remember 写入，优先级高于自动记忆（上限 8 条，按 confidence TopK）
            if self._memory_initialized and self._memory_store:
                try:
                    core_mems = self._memory_store.get_core_memories(max_count=8)
                    if core_mems:
                        core_lines = [f"- {m.rule}" for m in core_mems]
                        sys_prompt = sys_prompt + (
                            "\n\n[Core Memory — 以下为用户手动设定的核心记忆，优先级高于自动积累的经验，请务必优先遵守]\n"
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
            
            prefix_messages = [{'role': 'system', 'content': sys_prompt}]
            
            # ================================================================
            # 2. Cursor 风格历史消息：原生格式直通，不预压缩
            # ================================================================
            # 核心原则：
            # - assistant 消息完整保留（包括 content 和 tool_calls）
            # - tool 消息完整保留（包括 tool_call_id 和 content）
            # - user 消息完整保留
            # - 只清理内部元数据字段（thinking, python_shells 等）
            # - 压缩只在超限时由 _progressive_trim / auto_optimize 处理
            
            history_to_send = normalize_history(
                self._conversation_history,
                supports_vision=supports_vision,
                fix_alternation=self._fix_message_alternation,
                tool_result_text=lambda name, content: tr('ai.tool_result', name, content),
                image_placeholder=tr('ai.image_msg'),
            )
            
            dynamic_sections = []
            
            # 3. 自动 RAG 注入（从用户最新消息中提取关键词，检索相关文档）
            user_last_msg = str(agent_params.get('user_message') or '')
            self._current_user_message = user_last_msg
            if user_last_msg:
                rag_context = self._auto_rag_retrieve(
                    user_last_msg,
                    scene_context=scene_context,
                    conversation_len=len(self._conversation_history),
                )
                if rag_context:
                    dynamic_sections.append(DynamicContextSection(
                        'rag', [{'role': 'system', 'content': rag_context}], 0
                    ))
            
            # 4. ★ 长期记忆激活（"我想起来了"机制）
            # 在 RAG 文档之后、上下文提醒之前注入
            if user_last_msg:
                memory_context = self._activate_long_term_memory(
                    user_last_msg, scene_context=scene_context
                )
                if memory_context:
                    dynamic_sections.append(DynamicContextSection(
                        'memory', [{'role': 'system', 'content': memory_context}], 1
                    ))
            
            # 5. ★ Plan 上下文注入（仅在 Plan 执行阶段 + 当前 session 匹配时）
            if plan_mode and plan_executing:
                try:
                    plan_ctx = self._get_plan_manager().get_plan_for_context(self._session_id)
                    if plan_ctx:
                        dynamic_sections.append(DynamicContextSection(
                            'plan', [{'role': 'system', 'content': plan_ctx}], 2
                        ))
                except Exception as e:
                    print(f"[Plan] Context injection error: {e}")
            
            # 6. 上下文提醒（放在最后，不破坏 cache 前缀）
            # ⚠️ Cache 优化：动态内容放在末尾，保持前缀稳定
            context_reminder = self._get_context_reminder()
            if context_reminder:
                dynamic_sections.append(DynamicContextSection(
                    'context_reminder',
                    [{'role': 'system', 'content': f"[Context] {context_reminder}"}],
                    3,
                ))

            context_assembly = build_context(
                prefix_messages=prefix_messages,
                history_messages=history_to_send,
                dynamic_sections=dynamic_sections,
            )
            messages = context_assembly.messages()
            
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
            
            # 工具必须先选定，messages 与实际 tools 才能共同参与预算。
            if plan_mode and not plan_executing:
                from ..utils.tool_registry import get_tool_registry
                plan_filtered = get_tool_registry().get_tools_for_mode("plan_planning")
                tools = UltraOptimizer.optimize_tool_definitions(plan_filtered)
            elif plan_mode and plan_executing:
                exec_tools = list(HOUDINI_TOOLS)
                exec_names = {t.get('function', {}).get('name') for t in exec_tools}
                for plan_tool in (PLAN_TOOL_UPDATE_STEP, PLAN_TOOL_ASK_QUESTION):
                    if plan_tool.get('function', {}).get('name') not in exec_names:
                        exec_tools.append(plan_tool)
                tools = UltraOptimizer.optimize_tool_definitions(exec_tools)
            elif not use_agent:
                from ..utils.tool_registry import get_tool_registry
                tools = UltraOptimizer.optimize_tool_definitions(
                    get_tool_registry().get_tools_for_mode("ask")
                )
            else:
                tools = self._select_agent_tools_for_message(user_last_msg, use_web=use_web)
            if not use_web:
                tools = [t for t in tools if t['function']['name'] not in ('web_search', 'fetch_webpage')]

            if self._auto_optimize:
                current_tokens = self.token_optimizer.calculate_message_tokens(messages, tools=tools)
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
                    summarize_tool_content = self.client._summarize_tool_content if hasattr(self.client, '_summarize_tool_content') else None
                    pruning_policy = self.token_optimizer.budget.automatic_pruning_policy(
                        self._optimization_strategy
                    )
                    prune_context_assembly_to_token_target(
                        context_assembly,
                        int(context_limit * pruning_policy.target_ratio),
                        self.token_optimizer.calculate_message_tokens,
                        tools=tools,
                        min_rounds=2,
                        summarize_fn=summarize_tool_content,
                        keep_current_image=supports_vision,
                    )
                    messages = context_assembly.messages()
                    new_tokens = self.token_optimizer.calculate_message_tokens(messages, tools=tools)
                    saved = old_tokens - new_tokens
                    if saved > 0:
                        self._addStatus.emit(tr('opt.auto_status', saved))
            
            # ⚠️ 使用从主线程传入的参数（不直接访问 Qt 控件）
            # provider, model, use_web, use_agent 已在方法开头从 agent_params 获取
            
            # 调试：显示正在请求
            self._addStatus.emit(f"Requesting {provider}/{model}...")
            
            # Registry is the sole authority for non-core tool exposure.
            registry_tools = []
            try:
                from ..utils.tool_registry import get_tool_registry
                _reg = get_tool_registry()
                _mode = "plan_executing" if plan_mode and plan_executing else (
                    "plan_planning" if plan_mode else ("agent" if use_agent else "ask")
                )
                registry_tools = _reg.get_tools_for_mode(_mode)
            except Exception:
                pass
            request = finalize_context_request(
                context_assembly,
                selected_tools=tools,
                registry_tools=registry_tools,
                supports_vision=supports_vision,
                is_reasoning_model=AIClient.is_reasoning_model(model),
                context_limit=context_limit,
                count_tokens=self.token_optimizer.calculate_message_tokens,
                summarize_tool_content=self.client._summarize_tool_content,
            )
            if not request.budget_result.within_budget:
                raise RuntimeError(
                    "Context cannot fit the provider budget without truncating message text or breaking a tool chain "
                    f"({request.budget_result.final_tokens}/{request.budget_result.target_tokens} tokens)."
                )
            messages = request.messages
            tools = request.tools
            
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
