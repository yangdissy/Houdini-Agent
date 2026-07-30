# -*- coding: utf-8 -*-
"""Tool execution policy, dispatch, main-thread Houdini execution, cook guards, and snapshot helpers for AITab."""

import json
import queue
import re
import time
import traceback

from houdini_agent.qt_compat import QtCore, QtWidgets
from houdini_agent.ui.i18n import tr
from houdini_agent.core.harness_engine import build_tool_retry_key, sanitize_tool_result
from houdini_agent.core.houdini_main_thread_executor import OPERATION_ID_KEY


class ToolExecutionMixin:
    def _capture_pre_agent_update_mode(self):
        """记录本轮 Agent 启动前的 Houdini update mode。

        该快照用于区分用户/hip 原始 Manual 和 Cook Guard 临时 Manual。
        已有快照时保留原值，避免恢复失败或 Plan 执行阶段覆盖真实原始模式。
        """
        if getattr(self, '_pre_agent_update_mode', None) is not None:
            return self._pre_agent_update_mode
        try:
            import hou  # type: ignore
            self._pre_agent_update_mode = hou.updateModeSetting()
        except Exception:
            self._pre_agent_update_mode = None
        return self._pre_agent_update_mode

    def _build_manual_mode_directive(self, confirm_mode: bool = True) -> str:
        """★ 若用户/hip 自身处于 Manual 更新模式，返回一段 system prompt 硬约束。

        判断依据是 _pre_agent_update_mode（在 _on_send 时记录的用户原始模式），
        而非当前 hou.updateModeSetting()：后者在 Agent 运行期间会被 Cook Guard
        临时切为 Manual，直接读会误把「Agent 临时保护」当成「用户持久设置」。
        只有当用户原始模式就是 Manual 时才注入，避免噪声。
        """
        try:
            import hou  # type: ignore
        except Exception:
            return ""
        user_mode = getattr(self, '_pre_agent_update_mode', None)
        try:
            if user_mode is None:
                return ""
            if user_mode != hou.updateMode.Manual:
                return ""
        except Exception:
            return ""
        mode_rule = (
            "4. 不要擅自把用户的更新模式改回 Auto——这是用户有意的设置。"
            if confirm_mode
            else "4. 直接执行模式下，若 Manual 导致几何验证持续为空，可调用 set_update_mode(mode=\"auto\") 将当前 hip 切到 Auto Update 后继续验证；最终总结中说明已切到 Auto Update。"
        )
        return (
            "[Houdini 状态 — 重要] 当前 hip 文件的更新模式是 **Manual（手动）**，这是用户的持久设置。\n"
            "含义：创建/修改节点（create_node、set_node_parameter、connect_nodes、"
            "set_display_flag 等）后，Houdini 不会自动 cook，视口与下游几何不会自动刷新。\n"
            "你必须遵守：\n"
            "1. 工具返回 success 只代表操作已排队，绝不能据此宣称「已生效/视口已更新/效果已完成」。\n"
            "2. 报告完成前，必须用 verify_network / check_errors / get_network_structure 确认结构、连接与错误状态；但 verify_network / get_geometry_summary 返回的空几何在 Manual 模式下是低置信验证信号，不能单独当作拓扑或参数错误证据。\n"
            "3. 若用户期望看到结果，在总结中主动说明「当前为 Manual 模式，需手动 cook 或切回 Auto 才能看到更新」。\n"
            + mode_rule
        )

    def _cook_displayed_nodes_if_manual(self):
        """★ 在 Manual 保护模式下，对当前工作区的 display 节点做针对性 cook
        
        v1.4.4 修复：Agent 运行期间处于 Manual 模式时，修改工具不触发 cook，
        导致读取工具（get_network_structure、check_errors 等）返回 stale 数据，
        AI 误以为操作未生效。
        
        策略：只 cook 当前 /obj 下各 geo 容器中设置了 Display Flag 的节点。
        这是最小范围的 cook，只刷新 AI 关注的节点数据而不触发全场景 cook。
        """
        if getattr(self, '_pre_agent_update_mode', None) is None:
            return  # 不在 Agent cook 保护模式下，无需处理
        try:
            import hou  # type: ignore
            if hou.updateModeSetting() != hou.updateMode.Manual:
                return  # 当前不是 Manual 模式，无需处理
            
            # 收集所有需要 cook 的 display 节点
            cooked = 0
            for child in hou.node('/obj').children():
                # 只处理 geo 类型容器（SOP 网络）
                if child.type().name() not in ('geo', 'subnet'):
                    continue
                try:
                    display_node = child.displayNode()
                    if display_node is not None:
                        # ★ 跳过含体积/VDB 的 display 节点：force cook 会驱动 GPU
                        #   体积重绘，与用户视口交互叠加时易引发主线程渲染竞态崩溃
                        #   （GR_VolumeVK，见 crash 分析 2026-07）。
                        if self._display_node_has_volume(display_node):
                            continue
                        display_node.cook(force=True)
                        cooked += 1
                except Exception:
                    pass  # 单个节点 cook 失败不影响其他
            if cooked:
                print(f"[Cook Guard] Manual 模式下针对性 cook 了 {cooked} 个 display 节点")
        except Exception as e:
            print(f"[Cook Guard] 针对性 cook 失败: {e}")

    @staticmethod
    def _display_node_has_volume(display_node) -> bool:
        """判断 display 节点几何是否含 Volume/VDB primitive（用于跳过强制 cook）。

        含体积/VDB 时返回 True，让调用方跳过 cook(force=True)，避免驱动
        GPU 体积重绘与用户视口交互竞态。判断失败时保守返回 False（不跳过）。
        """
        try:
            import hou  # type: ignore
            # 节点尚未 cook 过时不强制读取几何（geometry() 可能触发 cook），
            # 直接跳过以避免竞态：未 cook 的体积节点更危险。
            if display_node.needsToCook():
                return True
            geo = display_node.geometry()
            if geo is None:
                return False
            for ptype in (hou.primType.Volume, hou.primType.VDB):
                if geo.countPrimType(ptype) > 0:
                    return True
            return False
        except Exception:
            return False

    def _on_update_todo(self, todo_id: str, text: str, status: str):
        """更新 Todo 列表（跟随对话流内联显示）
        
        使用 agent 锚定的 todo_list / chat_layout，防止切换会话后
        写入错误的窗口。
        """
        try:
            # 优先使用 agent 锚定的目标（会话 A 运行时不受会话 B 影响）
            todo = self._agent_todo_list or self.todo_list
            layout = self._agent_chat_layout or self.chat_layout
            if not todo:
                return
            # 确保 todo_list 已在对应 chat_layout 中
            self._ensure_todo_in_chat(todo, layout)
        except RuntimeError:
            return  # widget 已被 clear 销毁
        if text:
            todo.add_todo(todo_id, text, status)
        else:
            todo.update_todo(todo_id, status)

    @staticmethod
    def _geometry_validation_signal_from_result(result: dict) -> dict:
        signal = result.get('validation_signal') if isinstance(result, dict) else None
        if isinstance(signal, dict):
            return {
                'manual_mode': bool(signal.get('manual_mode_detected')),
                'is_empty_geometry': bool(signal.get('display_geometry_empty')),
                'recommended_next_action': signal.get('recommended_next_action'),
            }
        if isinstance(result, dict):
            return {
                'manual_mode': bool(result.get('manual_mode')),
                'is_empty_geometry': bool(result.get('is_empty_geometry')),
                'recommended_next_action': result.get('recommended_next_action'),
            }
        return {'manual_mode': False, 'is_empty_geometry': False, 'recommended_next_action': None}

    def _apply_geometry_validation_loop_guard(self, tool_name: str, args: dict, result: dict, mode: str) -> dict:
        if not isinstance(result, dict) or not result.get('success'):
            return result
        state = getattr(self, '_geometry_validation_loop_state', None)
        if not isinstance(state, dict):
            state = {}
            self._geometry_validation_loop_state = state

        target = args.get('node_path') or args.get('parent_path') or ''
        if tool_name == 'cook_node' and target:
            entry = state.setdefault(target, {'empty_count': 0, 'cook_after_empty': False})
            if entry.get('empty_count', 0) > 0:
                entry['cook_after_empty'] = True
            return result

        if tool_name not in {'get_geometry_summary', 'verify_network'}:
            return result

        signal = self._geometry_validation_signal_from_result(result)
        if not (signal.get('manual_mode') and signal.get('is_empty_geometry')):
            if target:
                state.pop(target, None)
            return result

        entry = state.setdefault(target, {'empty_count': 0, 'cook_after_empty': False})
        entry['empty_count'] = int(entry.get('empty_count', 0) or 0) + 1
        if entry['empty_count'] >= 2 and entry.get('cook_after_empty'):
            result['validation_blocked'] = True
            result['validation_block_reason'] = 'manual_empty_geometry_after_cook'
            result['validation_confidence'] = 'blocked'
            result['recommended_next_action'] = 'temporary_auto_validate'
            hint = (
                'geometry_empty_after_cook: Manual update mode still reports empty geometry. '
                'Follow recommended_next_action=temporary_auto_validate in Direct Execute mode; '
                'do not keep using ordinary cook_node, parameter schema checks, or Sphere/Box replacement as validation.'
            )
            result['recovery_hint'] = hint
            self._append_session_diagnostics_records([
                {
                    'event_type': 'geometry_validation_loop_guard',
                    'tool': tool_name,
                    'target': target,
                    'mode': mode,
                    'manual_mode': True,
                    'is_empty_geometry': True,
                    'recommended_next_action': signal.get('recommended_next_action'),
                }
            ])
        return result

    def _after_tool_result(self, tool_name: str, result: dict) -> None:
        if tool_name != 'set_update_mode' or not isinstance(result, dict) or not result.get('success'):
            return
        if not result.get('persistent_update_mode_change'):
            return
        try:
            import hou  # type: ignore
            self._pre_agent_update_mode = hou.updateModeSetting()
        except Exception:
            self._pre_agent_update_mode = None

    def _execute_tool_with_policy(self, tool_name: str, kwargs: dict) -> dict:
        """Harness V2 policy gate for tool execution.

        This wrapper is intentionally thin and delegates real execution to the
        existing implementation so behavior can be migrated incrementally.
        """
        mode = 'plan' if self._plan_mode else ('agent' if self._agent_mode else 'ask')
        context = {
            'mode': mode,
            'plan_phase': self._plan_phase,
            'confirm_mode': bool(getattr(self, '_confirm_mode', False)),
        }
        decision = self._tool_policy_engine.decide(tool_name, kwargs, context)
        self._append_policy_timeline(tool_name, decision.action, decision.reason)

        if self._harness_state:
            self._harness_state.add_trace(
                'tool_policy',
                tool=tool_name,
                action=decision.action,
                reason=decision.reason,
            )

        if decision.action == 'deny':
            self._addStatus.emit(f"恢复建议: {tool_name} 被策略拒绝，可切到 Plan 或启用 Confirm")
            return {
                'success': False,
                'error': decision.reason or f'Tool blocked by policy: {tool_name}',
            }

        exec_kwargs = decision.patched_args if decision.patched_args is not None else kwargs

        if decision.action == 'ask':
            confirmed = self._request_tool_confirmation(tool_name, exec_kwargs)
            if self._harness_state:
                self._harness_state.add_trace(
                    'tool_policy_ask',
                    tool=tool_name,
                    confirmed=bool(confirmed),
                )
            if not confirmed:
                self._append_policy_timeline(tool_name, 'ask_cancel', decision.reason)
                return {
                    'success': False,
                    'error': decision.reason or tr('ask.user_cancel', tool_name),
                }

            self._append_session_diagnostics_records([
                {
                    'event_type': 'tool_call',
                    'phase': 'start',
                    'tool': tool_name,
                    'action': decision.action,
                    'mode': mode,
                    'args_keys': sorted(list(exec_kwargs.keys())),
                }
            ])
            started_at = time.time()
            result = self._execute_tool_impl(
                tool_name,
                exec_kwargs,
                skip_builtin_confirm=True,
            )
            result = sanitize_tool_result(result)
            result = self._apply_geometry_validation_loop_guard(tool_name, exec_kwargs, result, mode)
            self._after_tool_result(tool_name, result)
            self._append_session_diagnostics_records([
                {
                    'event_type': 'tool_call',
                    'phase': 'result',
                    'tool': tool_name,
                    'action': decision.action,
                    'mode': mode,
                    'success': bool(result.get('success')),
                    'error': str(result.get('error', '')) if not result.get('success') else '',
                    'duration_ms': int(max(0.0, time.time() - started_at) * 1000),
                }
            ])
            return result

        if decision.action == 'retry':
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_kwargs)
            current_retry = self._harness_state.policy_retry_counts.get(retry_key, 0) if self._harness_state else 0
            if current_retry >= self._policy_retry_limit:
                self._append_policy_timeline(tool_name, 'retry_limit', f"limit={self._policy_retry_limit}")
                self._append_session_diagnostics_records([
                    {
                        'event_type': 'policy_retry',
                        'tool': tool_name,
                        'action': 'retry_limit',
                        'retry_key': retry_key,
                        'retry_count': current_retry,
                        'retry_limit': self._policy_retry_limit,
                    }
                ])
                self._addStatus.emit(f"恢复建议: {tool_name} 达到重试上限，建议切 Ask 排查参数")
                return {
                    'success': False,
                    'error': (
                        f"Tool retry limit reached for {tool_name} "
                        f"({self._policy_retry_limit}/{self._policy_retry_limit})."
                    ),
                }
            if self._harness_state:
                self._harness_state.policy_retry_counts[retry_key] = current_retry + 1
                self._harness_state.retries += 1
            self._append_session_diagnostics_records([
                {
                    'event_type': 'policy_retry',
                    'tool': tool_name,
                    'action': 'retry',
                    'retry_key': retry_key,
                    'retry_count': current_retry + 1,
                    'retry_limit': self._policy_retry_limit,
                    'mode': mode,
                }
            ])

        if decision.action not in {'allow', 'retry'}:
            return {
                'success': False,
                'error': f"Unsupported policy action: {decision.action}",
            }

        started_at = time.time()
        self._append_session_diagnostics_records([
            {
                'event_type': 'tool_call',
                'phase': 'start',
                'tool': tool_name,
                'action': decision.action,
                'mode': mode,
                'args_keys': sorted(list(exec_kwargs.keys())),
            }
        ])
        result = self._execute_tool_impl(tool_name, exec_kwargs)
        result = sanitize_tool_result(result)
        result = self._apply_geometry_validation_loop_guard(tool_name, exec_kwargs, result, mode)
        self._after_tool_result(tool_name, result)
        self._append_session_diagnostics_records([
            {
                'event_type': 'tool_call',
                'phase': 'result',
                'tool': tool_name,
                'action': decision.action,
                'mode': mode,
                'success': bool(result.get('success')),
                'error': str(result.get('error', '')) if not result.get('success') else '',
                'duration_ms': int(max(0.0, time.time() - started_at) * 1000),
            }
        ])

        if decision.action == 'retry' and self._harness_state and result.get('success'):
            retry_key = decision.retry_key or build_tool_retry_key(tool_name, exec_kwargs)
            self._harness_state.policy_retry_counts.pop(retry_key, None)

        if not result.get('success'):
            self._append_policy_timeline(tool_name, 'exec_fail', str(result.get('error', '')))
            self._addStatus.emit(f"恢复建议: {tool_name} 失败，可打开 Policy 时间线查看并切换 Plan/Ask")

        return result

    def _execute_tool_with_todo(self, tool_name: str, **kwargs) -> dict:
        """执行工具，包含 Todo 相关的工具
        
        注意：此方法在后台线程调用，Houdini 操作必须通过信号调度到主线程执行。
        不依赖 hou 模块的工具（execute_shell 等）直接在后台线程执行，避免阻塞 UI。
        """
        kwargs.pop('_harness_policy_checked', None)
        kwargs.pop('_harness_skip_confirm', None)
        if self._harness_v2_enabled:
            return self._execute_tool_with_policy(tool_name, kwargs)

        return self._execute_tool_impl(tool_name, kwargs)

    def _skill_risk_level(self, skill_name: str) -> str:
        """返回 skill 的 risk_level（'low'/'normal'/'high'），未知/查询失败按最保守 'normal' 处理。

        用 name->risk_level 映射缓存到实例属性，避免每次调用都遍历 skill 列表。
        risk_level 语义：'low'=只读/不改场景（规划阶段可用）；其余=会改场景/建图（规划阶段拦）。
        """
        if not skill_name:
            return 'normal'
        cache = getattr(self, '_skill_risk_cache', None)
        if cache is None:
            cache = {}
            try:
                from ..skills import list_skills
                for info in list_skills():
                    cache[info.get('name', '')] = info.get('risk_level', 'normal')
            except Exception:
                pass
            self._skill_risk_cache = cache
        return cache.get(skill_name, 'normal')

    def _execute_tool_impl(self, tool_name: str, kwargs: dict, skip_builtin_confirm: bool = False) -> dict:
        """Execute a tool after the public harness/policy boundary has run."""
        kwargs = dict(kwargs or {})

        # ★ Stop 检测：用户请求停止时立即返回，不再排队新工具
        if self.client.is_stop_requested():
            return {"success": False, "error": "用户已请求停止"}
        
        # ★ 主线程执行器保护：timeout/shutdown 后由 executor fail closed，
        #   避免新的 Houdini 工具信号与迟到主线程操作重叠。
        executor = getattr(self, '_houdini_main_thread_executor', None)
        if executor is not None and executor.is_blocked():
            if tool_name not in self._BG_SAFE_TOOLS:
                return {
                    "success": False,
                    "error": "Houdini 主线程执行器处于阻塞状态，为避免崩溃已拒绝新的 Houdini 工具执行。请重启面板后再继续。"
                }
        
        # ★ Ask 模式安全守卫：拦截任何不在白名单的工具
        if not self._agent_mode and not self._plan_mode and tool_name not in self._ASK_MODE_TOOLS:
            # 额外检查 ToolRegistry（插件/Skill 工具可能注册了 ask 模式）
            _ask_allowed = False
            try:
                from ..utils.tool_registry import get_tool_registry
                _meta = get_tool_registry()._tools.get(tool_name)
                if _meta and _meta.enabled and "ask" in _meta.modes:
                    _ask_allowed = True
            except Exception:
                pass
            if not _ask_allowed:
                return {
                    "success": False,
                    "error": tr('ask.restricted', tool_name)
                }
        
        # ★ Plan 规划阶段安全守卫
        if self._plan_mode and self._plan_phase == 'planning':
            # run_skill 在规划阶段仅允许只读 skill（risk_level == 'low'）：
            # 只读 skill（get_node_card / analyze_* / inspect_*）可分析现网、查真实参数以设计计划；
            # 会改场景/建图的 skill（setup_*，risk_level != low）留到执行阶段。
            if tool_name == 'run_skill':
                skill_name = (kwargs or {}).get('skill_name', '')
                if self._skill_risk_level(skill_name) != 'low':
                    return {
                        "success": False,
                        "error": (f"Plan 规划阶段不允许执行会改场景/建图的 skill '{skill_name}'，"
                                  f"仅可运行只读 skill（如 get_node_card、analyze_*、inspect_*）辅助设计计划")
                    }
            else:
                allowed = self._PLAN_PLANNING_TOOLS | {'create_plan'}
                if tool_name not in allowed:
                    # 额外检查 ToolRegistry（插件/Skill 工具可能注册了 plan_planning 模式）
                    _plan_allowed = False
                    try:
                        from ..utils.tool_registry import get_tool_registry
                        _meta = get_tool_registry()._tools.get(tool_name)
                        if _meta and _meta.enabled and "plan_planning" in _meta.modes:
                            _plan_allowed = True
                    except Exception:
                        pass
                    if not _plan_allowed:
                        return {
                            "success": False,
                            "error": f"Plan 规划阶段不允许执行 {tool_name}，只能使用查询工具和 create_plan"
                        }

        
        # ★ 确认模式：对关键节点操作弹出预览确认
        if (not skip_builtin_confirm) and self._confirm_mode and tool_name in self._CONFIRM_TOOLS:
            confirmed = self._request_tool_confirmation(tool_name, kwargs)
            if not confirmed:
                return {
                    "success": False,
                    "error": tr('ask.user_cancel', tool_name)
                }
        
        # ★ 显示工具执行状态
        self._showToolStatus.emit(tool_name)
        
        try:
            # ★ Plan 模式专用工具处理
            if tool_name == "create_plan":
                return self._handle_create_plan(kwargs)
            
            elif tool_name == "update_plan_step":
                return self._handle_update_plan_step(kwargs)
            
            elif tool_name == "ask_question":
                return self._handle_ask_question(kwargs)
            
            # 处理 Todo 相关工具（纯 Python 操作，线程安全）
            if tool_name == "add_todo":
                todo_id = kwargs.get("todo_id", "")
                text = kwargs.get("text", "")
                status = kwargs.get("status", "pending")
                self._updateTodo.emit(todo_id, text, status)
                return {"success": True, "result": f"Added todo: {text}"}
            
            elif tool_name == "update_todo":
                todo_id = kwargs.get("todo_id", "")
                status = kwargs.get("status", "done")
                self._updateTodo.emit(todo_id, "", status)
                return {"success": True, "result": f"Updated todo {todo_id} to {status}"}
            
            # 不依赖 hou 的工具 → 直接在后台线程执行（避免阻塞 UI）
            if tool_name in self._BG_SAFE_TOOLS:
                return self._execute_tool_in_bg(tool_name, kwargs)
            
            # 其他工具需要在主线程执行（Houdini hou 模块操作）
            return self._execute_tool_in_main_thread(tool_name, kwargs)
        finally:
            self._hideToolStatus.emit()
    
    def _execute_tool_in_bg(self, tool_name: str, kwargs: dict) -> dict:
        """在后台线程直接执行工具（不阻塞 UI 主线程）
        
        仅用于不依赖 hou 模块的工具，如 execute_shell、search_local_doc 等。
        """
        try:
            return self.mcp.execute_tool(tool_name, kwargs)
        except Exception as e:
            import traceback
            return {"success": False, "error": tr('ai.bg_exec_err', f"{e}\n{traceback.format_exc()[:300]}")}
    
    # 主线程工具执行超时（秒）
    # 修改操作可能触发 Houdini cook，需要足够的超时时间
    _TOOL_MAIN_THREAD_TIMEOUT = 120.0

    def _execute_tool_in_main_thread(self, tool_name: str, kwargs: dict) -> dict:
        """在主线程执行工具（线程安全）
        
        Houdini 主线程 queue、timeout、blocked 和 operation envelope 由
        HoudiniMainThreadExecutor 统一管理；如果 executor 缺失，fail closed。
        """
        executor = getattr(self, '_houdini_main_thread_executor', None)
        if executor is not None:
            result = executor.execute(tool_name, kwargs)
            if executor.is_blocked():
                self._main_thread_busy = True
            return result

        return {"success": False, "error": f"Houdini 主线程执行器不可用，拒绝执行 {tool_name}"}

    def _execute_tools_batch_in_main_thread(self, batch: list) -> list:
        """在主线程批量执行只读工具（减少 N 次信号往返为 1 次）

        Args:
            batch: [(tool_name, kwargs), ...]

        Returns:
            [result_dict, ...]（与 batch 顺序一致）
        """
        executor = getattr(self, '_houdini_main_thread_executor', None)
        if executor is not None:
            results = executor.execute_batch(batch)
            if executor.is_blocked():
                self._main_thread_busy = True
            return results

        return [
            {"success": False, "error": "Houdini 主线程执行器不可用，拒绝执行 batch"}
            for _ in batch
        ]

    def _on_execute_tool_batch_main_thread(self, batch: list):
        """在主线程批量执行只读工具的槽函数

        所有工具在主线程依次执行（它们是快速的只读查询），
        然后将结果列表一次性放入队列返回给调用线程。
        """
        executor = getattr(self, '_houdini_main_thread_executor', None)
        operation_id = None
        request_batch = []
        for tool_name, kwargs in batch:
            request_kwargs = dict(kwargs or {})
            item_operation_id = request_kwargs.pop(OPERATION_ID_KEY, None)
            if operation_id is None:
                operation_id = item_operation_id
            request_batch.append((tool_name, request_kwargs))

        # ★ 读取前 Cook（v1.4.4）：批量读取也需要确保数据新鲜
        needs_cook = any(tn in self._COOK_BEFORE_READ_TOOLS for tn, _ in request_batch)
        if needs_cook:
            self._cook_displayed_nodes_if_manual()
        
        results = []
        for tool_name, kwargs in request_batch:
            try:
                result = self.mcp.execute_tool(tool_name, kwargs)
            except Exception as e:
                result = {"success": False, "error": str(e)}
            results.append(result)
        if executor is not None and operation_id is not None:
            self._tool_result_queue.put(executor.attach_result(operation_id, results))
        else:
            self._tool_result_queue.put(results)
        # ★ 吸收 Agent 操作造成的选择变化（与单工具执行同理）
        self._refresh_selection_baseline()
    # ------------------------------------------------------------------
    # Plan 模式工具处理
    # ------------------------------------------------------------------
    # 已迁移到 core/plan_mixin.py (PlanMixin)

    # 已自带 checkpoint 追踪的工具（在 _on_add_node_operation 中有专用分支）
    _SELF_TRACKING_TOOLS = frozenset({
        'create_node', 'create_nodes_batch', 'create_wrangle_node',
        'delete_node', 'set_node_parameter',
    })

    @staticmethod
    def _snapshot_network_children() -> dict:
        """快照当前网络的子节点列表 {path: {name, type, path}}"""
        try:
            import hou  # type: ignore
            network = None
            try:
                editor = hou.ui.curDesktop().paneTabOfType(hou.paneTabType.NetworkEditor)
                if editor:
                    network = editor.pwd()
            except Exception:
                pass
            if not network:
                network = hou.node('/obj/geo1') or hou.node('/obj')
            if not network:
                return {}
            return {
                node.path(): {
                    'name': node.name(),
                    'type': node.type().name(),
                    'path': node.path(),
                }
                for node in network.children()
            }
        except Exception:
            return {}

    # ------------------------------------------------------------------
    #  节点路径收集：记录工具涉及的节点，用于后续去歧义
    # ------------------------------------------------------------------

    _NODE_PATH_RE = re.compile(r'/(?:obj|out|shop|stage|tasks|ch|mat|img)/[\w/]+')

    def _collect_node_paths_from_tool(self, result: dict, arguments: dict = None):
        """从工具执行的结果和参数中提取 Houdini 节点路径，累积到 _session_node_map。"""
        import re
        paths: set[str] = set()

        # 从 result 和 arguments 中用正则提取所有形如 /obj/geo1/box1 的路径
        for source in (result, arguments):
            if not source:
                continue
            raw = json.dumps(source, default=str) if isinstance(source, dict) else str(source)
            paths.update(self._NODE_PATH_RE.findall(raw))

        # 从 _node_changes 中提取
        node_changes = result.get('_node_changes') if isinstance(result, dict) else None
        if node_changes:
            for n in node_changes.get('created', []):
                if n.get('path'):
                    paths.add(n['path'])
            for n in node_changes.get('deleted', []):
                if n.get('path'):
                    paths.add(n['path'])

        # 写入 _session_node_map: name → set[path]
        for p in paths:
            name = p.rsplit('/', 1)[-1]
            if name:
                self._session_node_map.setdefault(name, set()).add(p)

    def _resolve_bare_node_names(self, text: str) -> str:
        """保留 AI 回复中的相对/短节点引用。

        数据来源：当前会话中 AI 工具调用涉及的节点路径（_session_node_map）。
        旧版本会把裸节点名自动扩写成 /obj/... 完整路径；现在用户可见回复
        优先保留相对路径/短名称，工具参数仍使用完整路径。
        """
        return text

    @staticmethod
    def _diff_network_children(before: dict, after: dict):
        """对比前后子节点快照，返回 {created: [...], deleted: [...]} 或 None"""
        before_paths = set(before.keys())
        after_paths = set(after.keys())
        created = [after[p] for p in sorted(after_paths - before_paths)]
        deleted = [before[p] for p in sorted(before_paths - after_paths)]
        if not created and not deleted:
            return None
        return {'created': created, 'deleted': deleted}

    # ★ 会触发 Houdini cook 的工具集合
    # 这些工具执行时可能导致耗时的场景计算，需要特殊保护
    # 注意：create_node/create_nodes_batch/create_wrangle_node 已使用 run_init_scripts=False
    # 不会在节点创建时触发 cook，因此不需要 Manual 模式保护
    _COOK_TRIGGERING_TOOLS = frozenset({
        'connect_nodes', 'set_display_flag', 'set_node_parameter',
        'batch_set_parameters', 'execute_python', 'run_skill',
    })

    # ★ 需要在 Manual 保护模式下做针对性 cook 的读取工具
    # 这些工具需要读取节点最新计算结果（几何体、错误状态等），
    # 如果不 cook，AI 会看到 stale 数据从而误判操作结果
    _COOK_BEFORE_READ_TOOLS = frozenset({
        'get_network_structure', 'get_node_parameters', 'list_children',
        'check_errors', 'verify_network',
        'capture_viewport',  # 截图前需确保几何体已 cook
    })

    @QtCore.Slot(str, dict)
    def _on_execute_tool_main_thread(self, tool_name: str, kwargs: dict):
        """在主线程执行工具（槽函数）
        
        注意：此方法在主线程中执行，直接操作 Houdini API 是安全的。
        所有修改操作包裹在 undo group 中，支持一键撤销整个 Agent 操作。
        ★ 对于未自带 checkpoint 的修改工具，会在执行前后快照网络子节点以检测变更。
        
        ★ macOS 线程安全说明：
        Houdini 的 hou 模块不是线程安全的。macOS 上 Cocoa/AppKit 要求 UI 和
        场景操作必须在主线程执行，否则会导致 EXC_BAD_ACCESS。
        此方法通过 BlockingQueuedConnection 信号从后台线程触发，保证在主线程执行。
        
        ★ Cook 保护（v1.4.3）：
        对可能触发 cook 的修改工具，在执行前临时切换为手动更新模式，
        执行完毕后恢复原模式。这样 setDisplayFlag/connect 等操作不会
        立即触发耗时的场景 cook，避免阻塞主线程导致死锁。
        """
        # ★ 主线程断言（调试辅助：如果在非主线程执行，输出警告）
        _app = QtWidgets.QApplication.instance()
        if _app and _app.thread() != QtCore.QThread.currentThread():
            print(f"[⚠️ THREAD SAFETY] _on_execute_tool_main_thread 不在主线程执行! "
                  f"tool={tool_name}, current_thread={QtCore.QThread.currentThread()}")
        
        executor = getattr(self, '_houdini_main_thread_executor', None)
        if executor is not None:
            kwargs = dict(kwargs or {})
            operation_id = kwargs.pop('_ha_operation_id', None)
            result = executor.run_in_main_thread(
                tool_name=tool_name,
                kwargs=kwargs,
                execute_tool=self.mcp.execute_tool,
                cook_before_read=self._cook_displayed_nodes_if_manual,
                snapshot_network_children=self._snapshot_network_children,
                diff_network_children=self._diff_network_children,
                refresh_selection_baseline=self._refresh_selection_baseline,
                self_tracking_tools=self._SELF_TRACKING_TOOLS,
                error_formatter=lambda exc: tr('ai.tool_exec_err', str(exc)),
            )
        else:
            try:
                result = self.mcp.execute_tool(tool_name, kwargs)
            except Exception as e:
                result = {"success": False, "error": tr('ai.tool_exec_err', str(e))}

        # ★ 清除主线程忙标记：主线程 slot 已返回。
        self._main_thread_busy = False

        # ★ macOS 崩溃修复：不要在 BlockingQueuedConnection slot 内调用 processEvents()。
        if executor is not None and operation_id is not None:
            self._tool_result_queue.put(executor.attach_result(operation_id, result))
        else:
            self._tool_result_queue.put(result)
