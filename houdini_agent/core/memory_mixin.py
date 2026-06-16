# -*- coding: utf-8 -*-
"""
MemoryMixin — 长期记忆系统相关方法

从 ai_tab.py 拆分出的 Mixin，包含：
  - _init_memory_system
  - _activate_long_term_memory
  - _collect_recent_rounds  (staticmethod)
  - _reflect_after_task
  - _get_personality_injection
  - _get_user_rules_injection

所需 self 属性（由 AITab.__init__ 初始化）：
  _username, _memory_store, _reward_engine, _reflection_module,
  _growth_tracker, _memory_initialized, _agent_history,
  _conversation_history, _agent_session_id, _session_id, client
"""

import threading

from ..utils.memory_store import get_memory_store
from ..utils.reward_engine import get_reward_engine
from ..utils.reflection import get_reflection_module
from ..utils.growth_tracker import get_growth_tracker, TaskMetric


class MemoryMixin:
    """长期记忆系统 Mixin：分层检索、任务后反思、个性注入"""

    # ==========================================================
    # ★ 大脑启发式长期记忆系统
    # ==========================================================

    def _init_memory_system(self):
        """初始化长期记忆系统（后台线程，不阻塞 UI）"""
        def _init():
            try:
                self._memory_store = get_memory_store(self._username)
                self._reward_engine = get_reward_engine(self._username)
                self._reflection_module = get_reflection_module(self._username)
                self._growth_tracker = get_growth_tracker(self._username)
                self._memory_initialized = True
                print(f"[Memory] 长期记忆系统已初始化: {self._memory_store.get_stats()}")
            except Exception as e:
                print(f"[Memory] 初始化失败 (非致命): {e}")
                self._memory_initialized = False

        thread = threading.Thread(target=_init, daemon=True)
        thread.start()

    def _activate_long_term_memory(self, user_message: str, scene_context: dict = None) -> str:
        """动态记忆激活 — 分层 chunk 检索

        6 层抽象层级体系：
        - L0 (核心身份): 已在 sys_prompt 中加载，此处跳过
        - L1 (核心偏好): embedding 检索, top_k=3, threshold=0.15
        - L2 (经验规则): embedding 检索, top_k=3, threshold=0.25
        - L3 (工作流模式): embedding 检索, top_k=2, threshold=0.35
        - L4-L5: 不自动注入，仅通过 search_memory 工具检索

        每层独立取 TopK chunk，互不挤占。
        每条 chunk 附带置信度标注，明确标注"仅供参考"。

        ★ 注意: fallback embedding (n-gram hash) 的 cosine similarity 值域约 0~0.4，
        远低于 sentence-transformers 的 0~1.0。threshold 会在 search_by_level 内部
        自动缩放以适配不同后端。Episodic / Procedural 的 score 阈值也需同样处理。
        """
        if not self._memory_initialized or not self._memory_store:
            return ""

        try:
            store = self._memory_store

            # 构建查询（用户消息 + 场景关键词）
            query = user_message
            if scene_context:
                selected_types = scene_context.get('selected_types', [])
                if selected_types:
                    query += ' ' + ' '.join(selected_types)

            # ★ fallback 模式下 cosine similarity 值域很低，缩放 score 阈值
            _is_semantic = store.embedder.is_semantic
            _ep_threshold = 0.3 if _is_semantic else 0.05
            _proc_threshold = 0.25 if _is_semantic else 0.04

            parts = []

            # ── L1: 核心偏好 (top_k=3, threshold=0.15) ──
            l1_results = store.search_by_level(query, level=1, top_k=3, threshold=0.15)
            for rec, score in l1_results:
                parts.append(f"[L1 Preference] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── L2: 经验规则 (top_k=3, threshold=0.25) ──
            l2_results = store.search_by_level(query, level=2, top_k=3, threshold=0.25)
            for rec, score in l2_results:
                parts.append(f"[L2 Rule] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── L3: 工作流模式 (top_k=2, threshold=0.35) ──
            l3_results = store.search_by_level(query, level=3, top_k=2, threshold=0.35)
            for rec, score in l3_results:
                parts.append(f"[L3 Workflow] (conf={rec.confidence:.2f}) {rec.rule[:120]}")
                store.increment_semantic_activation(rec.id)

            # ── Episodic: 相关经历 (top_k=2) ──
            episodes = store.search_episodic(query, top_k=2, min_importance=0.3)
            for ep, score in episodes:
                if score > _ep_threshold:
                    status = "✅" if ep.success else "❌"
                    parts.append(
                        f"[Past Experience] {status} {ep.task_description[:80]} "
                        f"→ {ep.result_summary[:60]}"
                    )
                    try:
                        new_imp = min(5.0, ep.importance * 1.05)
                        store.update_episodic_importance(ep.id, new_imp)
                    except Exception:
                        pass

            # ── Procedural: 适用策略 (top_k=2) ──
            strategies = store.search_procedural(query, top_k=2)
            for strat, score in strategies:
                if score > _proc_threshold:
                    parts.append(f"[Strategy] {strat.description[:80]}")

            if not parts:
                return ""

            header = "[Long-Term Memory — 历史经验仅供参考，请结合当前上下文判断]"
            result = header + "\n" + "\n".join(parts)
            return result

        except Exception as e:
            print(f"[Memory] 记忆激活失败: {e}")
            return ""

    @staticmethod
    def _collect_recent_rounds(history: list, n_rounds: int) -> list:
        """从对话历史中收集最近 N 轮（以 user 消息为分界）的消息

        Args:
            history: 完整对话历史
            n_rounds: 要收集的轮数

        Returns:
            最近 N 轮的消息副本列表
        """
        if not history:
            return []

        # 按 user 消息划分轮次
        rounds = []
        current_round = []
        for m in history:
            if m.get('role') == 'user' and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(m)
        if current_round:
            rounds.append(current_round)

        # 取最近 n_rounds 轮
        recent = rounds[-n_rounds:] if len(rounds) >= n_rounds else rounds
        # 展平为消息列表（深拷贝避免修改原始数据）
        import copy
        return [copy.copy(m) for rnd in recent for m in rnd]

    def _reflect_after_task(self, result: dict, agent_params: dict):
        """任务完成后的反思钩子 — 在后台线程执行

        从 agent result 中提取信号，创建 episodic 记忆，
        计算 reward，触发规则/LLM 反思。
        """
        if not self._memory_initialized or not self._reflection_module:
            return

        try:
            # 提取任务信息
            tool_calls_history = result.get('tool_calls_history', [])
            final_content = result.get('final_content', '') or result.get('content', '')
            new_messages = result.get('new_messages', [])

            # 构建工具调用序列
            tool_calls = []
            error_count = 0
            retry_count = 0
            for tc in tool_calls_history:
                tc_result = tc.get('result', {})
                success = bool(tc_result.get('success', True))
                has_error = bool(tc_result.get('error', ''))
                tool_calls.append({
                    "name": tc.get('tool_name', ''),
                    "success": success and not has_error,
                    "error": tc_result.get('error', ''),
                })
                if has_error or not success:
                    error_count += 1

            # 检测重试（连续相同工具调用）
            for i in range(1, len(tool_calls)):
                if (tool_calls[i]["name"] == tool_calls[i-1]["name"]
                        and not tool_calls[i-1]["success"]):
                    retry_count += 1

            # 提取用户请求
            history = self._agent_history if self._agent_history is not None else self._conversation_history
            task_description = ""
            for msg in reversed(history):
                if msg.get('role') == 'user':
                    content = msg.get('content', '')
                    if isinstance(content, list):
                        task_description = ' '.join(
                            p.get('text', '') for p in content if p.get('type') == 'text'
                        )
                    else:
                        task_description = content
                    task_description = task_description[:200]
                    break

            # 判断成功 / 失败
            success = result.get('ok', True) and error_count < len(tool_calls) * 0.5

            # 结果摘要
            result_summary = ""
            if final_content:
                # 去除 think 标签
                import re as _re
                clean = _re.sub(r'<think>[\s\S]*?</think>', '', final_content).strip()
                result_summary = clean[:150]

            session_id = self._agent_session_id or self._session_id

            # 执行反思
            reflect_result = self._reflection_module.reflect_on_task(
                session_id=session_id,
                task_description=task_description,
                result_summary=result_summary,
                success=success,
                error_count=error_count,
                retry_count=retry_count,
                tool_calls=tool_calls,
                ai_client=self.client,
                model=agent_params.get('model', 'deepseek-v4-flash'),
                provider=agent_params.get('provider', 'deepseek'),
            )

            # 更新 Growth Tracker
            if self._growth_tracker:
                metric = TaskMetric(
                    success=success,
                    error_count=error_count,
                    retry_count=retry_count,
                    tool_call_count=len(tool_calls),
                    reward=reflect_result.get('reward', 0.0),
                    tags=reflect_result.get('tags', []),
                )
                self._growth_tracker.record_task(metric)

                # 如果 LLM 反思返回了技能置信度更新
                if reflect_result.get('deep_reflected') and 'skill_confidence' in reflect_result:
                    self._growth_tracker.update_skill_confidence_batch(
                        reflect_result.get('skill_confidence', {})
                    )

            if reflect_result.get('reward', 0) > 0:
                print(f"[Memory] 反思完成: reward={reflect_result['reward']:.2f}, "
                      f"tags={reflect_result.get('tags', [])}, "
                      f"deep_reflected={reflect_result.get('deep_reflected', False)}")

        except Exception as e:
            import traceback
            print(f"[Memory] 反思钩子异常: {e}")
            traceback.print_exc()

    def _get_personality_injection(self) -> str:
        """获取个性注入文本（附加到 system prompt 末尾）"""
        if not self._memory_initialized or not self._growth_tracker:
            return ""
        try:
            return self._growth_tracker.get_personality_description()
        except Exception:
            return ""

    def _get_user_rules_injection(self) -> str:
        """获取用户自定义规则文本（附加到 system prompt 末尾）"""
        try:
            from ..utils.rules_manager import get_rules_for_prompt
            return get_rules_for_prompt(username=self._username)
        except Exception:
            return ""
