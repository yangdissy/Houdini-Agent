# -*- coding: utf-8 -*-
"""
PlanMixin — Plan 模式工具处理相关方法

从 ai_tab.py 拆分出的 Mixin，包含：
  - _handle_create_plan
  - _handle_update_plan_step
  - _handle_ask_question
  - _on_render_ask_question      (@QtCore.Slot())
  - _show_plan_generation_progress (@QtCore.Slot(dict))
  - _on_create_streaming_plan    (@QtCore.Slot())
  - _on_update_streaming_plan    (@QtCore.Slot(str))
  - _flush_streaming_plan
  - _on_render_plan_viewer
  - _on_update_plan_step         (@QtCore.Slot(str, str, str))
  - _on_plan_confirmed
  - _on_plan_rejected

所需 self 属性/方法（由 AITab.__init__ 或其他 Mixin 提供）：
  _plan_manager, _plan_phase, _session_id,
  _showGenerating, _renderPlanViewer, _updatePlanStep,
  _askQuestionRequest, _showPlanning,
  _ask_question_result_queue, _pending_ask_questions,
  _streaming_plan_card, _streaming_plan_acc, _streaming_plan_timer_active,
  _active_plan_viewer,
  chat_container, chat_layout,
  _scroll_to_bottom, _conversation_history,
  _set_running, _add_ai_response, _agent_response, _current_response,
  _start_active_aurora, _last_agent_params, _run_agent
"""

import queue
import threading

from houdini_agent.qt_compat import QtCore

from ..ui.i18n import tr
from ..utils.plan_manager import get_plan_manager
from ..utils.plan_runtime import PlanRuntime
from ..ui.cursor_plan_widgets import AskQuestionCard, PlanViewer, StreamingPlanCard


class PlanMixin:
    """Plan 模式 Mixin：Plan 工具处理、交互卡片渲染与执行流程"""

    def _get_plan_manager(self):
        if self._plan_manager is None:
            user_paths = getattr(self, '_user_paths', None)
            cache_root = getattr(user_paths, 'user_root', None)
            self._plan_manager = get_plan_manager(cache_root)
        return self._plan_manager

    # ------------------------------------------------------------------
    # Plan 模式工具处理
    # ------------------------------------------------------------------

    def _handle_create_plan(self, kwargs: dict) -> dict:
        """处理 create_plan 工具调用（后台线程）"""
        try:
            plan_data = self._get_plan_manager().create_plan(self._session_id, kwargs)
            self._plan_phase = 'awaiting_confirmation'
            # 切换状态：Planning → Generating（Plan 已完成构建）
            self._showGenerating.emit()
            # 通过信号在主线程渲染 PlanViewer 卡片
            self._renderPlanViewer.emit(plan_data)
            return {
                "success": True,
                "result": f"Plan '{plan_data.get('title', '')}' created with {len(plan_data.get('steps', []))} steps. Waiting for user confirmation."
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create plan: {e}"}

    def _handle_update_plan_step(self, kwargs: dict) -> dict:
        """处理 update_plan_step 工具调用（后台线程）"""
        try:
            step_id = kwargs.get('step_id', '')
            status = kwargs.get('status', 'done')
            result_summary = kwargs.get('result_summary', '')
            plan = self._get_plan_manager().update_step(
                self._session_id, step_id, status, result_summary
            )
            if not plan:
                return {"success": False, "error": f"No active plan found for session {self._session_id}"}
            # 通过信号在主线程更新 PlanViewer 步骤状态
            self._updatePlanStep.emit(step_id, status, result_summary or '')
            # 检查是否全部完成
            all_steps = plan.get('steps', [])
            done_count = sum(1 for s in all_steps if s.get('status') == 'done')
            error_count = sum(1 for s in all_steps if s.get('status') == 'error')
            total = len(all_steps)

            if plan.get('status') == 'completed':
                self._plan_phase = 'completed'
                return {
                    "success": True,
                    "result": f"Step {step_id} updated to '{status}'. Plan complete! ({done_count}/{total} done, {error_count} errors)"
                }

            # 返回进度信息，让 AI 知道还有多少步骤要做
            ready_steps = PlanRuntime().next_ready_steps(plan)
            next_step_info = ""
            if ready_steps:
                ns = ready_steps[0]
                next_step_info = f" Next: {ns['id']} \"{ns.get('title', ns.get('description', ns['id']))}\""

            return {
                "success": True,
                "result": f"Step {step_id} updated to '{status}'. Progress: {done_count}/{total} done.{next_step_info}"
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to update plan step: {e}"}

    def _handle_ask_question(self, kwargs: dict) -> dict:
        """处理 ask_question 工具调用（后台线程）

        复用 _request_tool_confirmation 的阻塞模式：
        1. 设置 pending 属性 → 发射信号 → 主线程渲染 AskQuestionCard
        2. 后台线程在 queue 上阻塞等待用户回答
        3. 用户提交后 queue.put(answers) → 后台线程继续
        """
        questions = kwargs.get('questions', [])
        if not questions:
            return {"success": False, "error": "No questions provided"}

        self._ask_question_result_queue = queue.Queue()
        self._pending_ask_questions = questions
        self._askQuestionRequest.emit()

        try:
            result = self._ask_question_result_queue.get(timeout=300.0)  # 5 分钟超时
            if result is None:
                return {"success": True, "result": "User skipped the questions."}
            # 格式化答案为可读文本
            answer_lines = []
            for q_id, selections in result.items():
                readable = []
                for sel in selections:
                    if sel.startswith("__free_text__:"):
                        readable.append(sel.replace("__free_text__:", ""))
                    else:
                        readable.append(sel)
                answer_lines.append(f"{q_id}: {', '.join(readable)}")
            return {
                "success": True,
                "result": f"User answered:\n" + "\n".join(answer_lines)
            }
        except queue.Empty:
            return {"success": True, "result": "User did not answer within the time limit."}

    @QtCore.Slot()
    def _on_render_ask_question(self):
        """主线程：在聊天流中插入 AskQuestionCard"""
        q = getattr(self, '_ask_question_result_queue', None)
        questions = getattr(self, '_pending_ask_questions', [])

        if not q:
            print("[AskQuestion] ⚠ _ask_question_result_queue 不存在")
            return

        try:
            card = AskQuestionCard(questions, parent=self.chat_container)
        except Exception as e:
            print(f"[AskQuestion] ✖ AskQuestionCard 创建失败: {e}")
            q.put(None)
            return

        def _on_answered(answers: dict):
            q.put(answers)

        def _on_cancelled():
            q.put(None)

        card.answered.connect(_on_answered)
        card.cancelled.connect(_on_cancelled)

        # 插入到对话流
        try:
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, card)
        except Exception as e:
            print(f"[AskQuestion] ⚠ 插入失败: {e}")
            q.put(None)
            return

        card.setVisible(True)
        try:
            self._scroll_to_bottom(force=True)
        except Exception:
            pass

    @QtCore.Slot(dict)
    def _show_plan_generation_progress(self, accumulated: str):
        """从 create_plan 的流式参数中提取进度信息并显示 Planning... 状态"""
        import re as _re
        # 统计已出现的 step id
        step_ids = _re.findall(r'"id"\s*:\s*"(step-\d+)"', accumulated)
        # 尝试提取 title
        title_match = _re.search(r'"title"\s*:\s*"([^"]{1,30})', accumulated)
        title_part = title_match.group(1) if title_match else ""

        # 检查是否已进入 architecture 部分
        has_arch = '"architecture"' in accumulated
        arch_nodes = _re.findall(r'"id"\s*:\s*"(?!step-)([^"]+)"', accumulated)

        if has_arch and arch_nodes:
            progress = f"architecture ({len(arch_nodes)} nodes)"
        elif step_ids:
            progress = f"step {len(step_ids)}"
            if title_part:
                progress = f"「{title_part}」 {progress}"
        elif title_part:
            progress = f"「{title_part}」"
        else:
            progress = ""

        self._showPlanning.emit(progress)

    @QtCore.Slot()
    def _on_create_streaming_plan(self):
        """主线程：创建流式 Plan 预览卡片并插入聊天流"""
        try:
            # 如果已有旧的流式卡片则先移除
            if self._streaming_plan_card is not None:
                self._streaming_plan_card.setParent(None)
                self._streaming_plan_card.deleteLater()

            card = StreamingPlanCard(parent=self.chat_container)
            self._streaming_plan_card = card
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, card)
            self._scroll_to_bottom(force=True)
        except Exception as e:
            print(f"[Plan] Create streaming card error: {e}")

    @QtCore.Slot(str)
    def _on_update_streaming_plan(self, accumulated: str):
        """主线程：将流式 JSON 碎片增量渲染到流式 Plan 卡片

        使用简单的节流策略：缓存最新数据，通过 singleShot 延迟处理，
        避免每个 token 都触发正则解析和 UI 更新。
        """
        self._streaming_plan_acc = accumulated
        if not getattr(self, '_streaming_plan_timer_active', False):
            self._streaming_plan_timer_active = True
            QtCore.QTimer.singleShot(150, self._flush_streaming_plan)

    def _flush_streaming_plan(self):
        """实际执行流式 Plan 卡片更新"""
        self._streaming_plan_timer_active = False
        if self._streaming_plan_card is None:
            return
        acc = getattr(self, '_streaming_plan_acc', '')
        if not acc:
            return
        try:
            old_count = self._streaming_plan_card._rendered_step_count
            self._streaming_plan_card.update_from_accumulated(acc)
            new_count = self._streaming_plan_card._rendered_step_count
            if new_count > old_count:
                self._scroll_to_bottom()
        except Exception as e:
            print(f"[Plan] Update streaming card error: {e}")

    def _on_render_plan_viewer(self, plan_data: dict):
        """主线程：将流式 Plan 卡片原地升级为完整交互卡片。

        如果流式卡片已存在 → finalize_with_data 原地补充完整数据。
        如果不存在（边缘情况）→ 创建新卡片。
        """
        try:
            if self._streaming_plan_card is not None:
                # ★ 原地升级：在流式骨架上补充 DAG + 按钮
                card = self._streaming_plan_card
                card.finalize_with_data(plan_data)
                card.planConfirmed.connect(self._on_plan_confirmed)
                card.planRejected.connect(self._on_plan_rejected)
                self._active_plan_viewer = card
                self._streaming_plan_card = None  # 不再追踪为流式卡片
            else:
                # 边缘情况：没有流式卡片时直接创建 PlanViewer
                viewer = PlanViewer(plan_data, parent=self.chat_container)
                viewer.planConfirmed.connect(self._on_plan_confirmed)
                viewer.planRejected.connect(self._on_plan_rejected)
                self._active_plan_viewer = viewer
                self.chat_layout.insertWidget(self.chat_layout.count() - 1, viewer)
            self._scroll_to_bottom(force=True)
        except Exception as e:
            print(f"[Plan] Render PlanViewer error: {e}")

    @QtCore.Slot(str, str, str)
    def _on_update_plan_step(self, step_id: str, status: str, result_summary: str):
        """主线程：更新 PlanViewer 卡片中的步骤状态"""
        if self._active_plan_viewer:
            try:
                self._active_plan_viewer.update_step_status(step_id, status, result_summary)
            except Exception as e:
                print(f"[Plan] Update step UI error: {e}")

    def _on_plan_confirmed(self, plan_data: dict):
        """用户点击 Confirm 按钮 → 启动执行阶段"""
        self._plan_phase = 'executing'
        # 禁用 PlanViewer 按钮（防止重复点击）
        if self._active_plan_viewer:
            self._active_plan_viewer.set_confirmed()

        # 构造执行提示消息
        exec_msg = tr('ai.plan_confirmed_msg', plan_data.get('title', 'Plan'))
        self._conversation_history.append({
            'role': 'user', 'content': exec_msg
        })

        self._start_agent_run({
            'use_agent': True,          # 执行阶段用完整工具
            'plan_mode': True,
            'plan_executing': True,     # 标记为 Plan 执行阶段
            'plan_data': plan_data,
        })

    def _on_plan_rejected(self):
        """用户点击 Reject 按钮 → 丢弃 Plan"""
        self._plan_phase = 'idle'
        try:
            self._get_plan_manager().delete_plan(self._session_id)
        except Exception:
            pass
        if self._active_plan_viewer:
            self._active_plan_viewer.set_rejected()
        self._active_plan_viewer = None

    # ------------------------------------------------------------------
    # Plan 续接：检测 AI 提前终止但 Plan 未完成
    # ------------------------------------------------------------------

    #: 最多续接次数上限（类常量，改这里即可调整全局行为）
    _MAX_PLAN_RESUMES: int = 5

    def _init_plan_resume_state(self) -> None:
        """每次 Plan 执行开始前调用，重置续接计数器。"""
        self._plan_resume_count: int = 0
        self._last_resume_done_count: int = -1

    def _check_plan_resume(self):
        """检查 Plan 是否有未完成步骤，返回续接消息字符串或 None。

        由 agent_loop_stream 的 on_plan_incomplete 回调调用（每轮 AI 输出
        纯文本时触发）。提取自 _run_agent 的内联闭包，逻辑和状态均在此方法
        内管理，便于单独测试和审计。

        退出条件（返回 None，不再续接）：
          - 续接次数已达 _MAX_PLAN_RESUMES
          - 所有步骤已完成（done_count >= total）
          - done_count 未增长（AI 卡死，防死循环）
          - 无 pending/running 步骤

        副作用：
          - 自动将 running 状态步骤推进为 done（AI 忘调
            update_plan_step 时代劳），并重新加载 plan
        """
        if self._plan_resume_count >= self._MAX_PLAN_RESUMES:
            print(f"[Plan] 续接次数已达上限 ({self._MAX_PLAN_RESUMES})，停止续接")
            return None
        try:
            plan_manager = self._get_plan_manager()
            plan = plan_manager.load_plan(self._session_id)
            if not plan:
                return None
            steps = plan.get('steps', [])
            if not steps:
                return None

            # 自动推进 running → done（AI 执行完但忘调 update_plan_step）
            running_steps = [s for s in steps if s.get('status') == 'running']
            if running_steps:
                for s in running_steps:
                    print(f"[Plan] 自动标记 running 步骤为 done: {s['id']}")
                    plan_manager.update_step(
                        self._session_id, s['id'], 'done',
                        '(auto-completed: AI finished but did not call update_plan_step)'
                    )
                plan = plan_manager.load_plan(self._session_id)
                steps = plan.get('steps', [])

            done_count = sum(1 for s in steps if s.get('status') == 'done')
            total = len(steps)

            if done_count >= total:
                return None  # 全部完成，正常结束

            # done_count 未增长 → AI 卡死，停止防死循环
            if done_count == self._last_resume_done_count:
                print(f"[Plan] done_count 没有增长 ({done_count}/{total})，停止续接防止死循环")
                return None
            self._last_resume_done_count = done_count

            runtime = PlanRuntime()
            ready_steps = runtime.next_ready_steps(plan)
            running_steps = [s for s in steps if s.get('status') == 'running']
            pending_steps = running_steps or ready_steps
            if not pending_steps:
                return None

            self._plan_resume_count += 1
            pending_names = ', '.join(
                f'"{s.get("title", s.get("description", s["id"]))}"'
                for s in pending_steps[:5]
            )
            plan_ctx = plan_manager.get_plan_for_context(self._session_id)
            resume_msg = (
                f"[Plan Incomplete] 计划尚未完成！已完成 {done_count}/{total} 步。\n"
                f"未完成步骤: {pending_names}\n"
                f"请立即继续执行下一个未完成的步骤。不要停止，不要总结，继续调用工具执行。\n"
            )
            if plan_ctx:
                resume_msg += f"\n{plan_ctx}"
            return resume_msg
        except Exception as e:
            print(f"[Plan] _check_plan_resume error: {e}")
            return None
