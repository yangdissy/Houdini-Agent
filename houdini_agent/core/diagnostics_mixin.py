# -*- coding: utf-8 -*-
"""Diagnostics and policy timeline helpers for AITab."""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from houdini_agent.qt_compat import QtWidgets, QtCore
from ..ui.i18n import tr


class DiagnosticsMixin:
    _diagnostics_write_lock = threading.Lock()

    def _refresh_mode_guard_ui(self):
        """刷新输入区模式风险提示与策略时间线入口。"""
        mode = 'PLAN' if self._plan_mode else ('AGENT' if self._agent_mode else 'ASK')
        if mode == 'ASK':
            hint = tr('guard.readonly')
            risk = 'readonly'
        elif self._confirm_mode:
            hint = tr('guard.confirm')
            risk = 'confirm'
        else:
            hint = tr('guard.high_risk')
            risk = 'high'

        # 状态快照去重:避免 Qt setStyleSheet/setText 在值未变时仍触发全树样式重算 —
        # 是 Houdini 20.5 QHeaderView race 的高频源头之一。
        cache = self.__dict__.setdefault('_mode_guard_cache', {})
        if hasattr(self, 'mode_guard_label') and self.mode_guard_label:
            if cache.get('hint') != hint:
                self.mode_guard_label.setText(hint)
                cache['hint'] = hint
            if cache.get('risk') != risk:
                self.mode_guard_label.setProperty('risk', risk)
                self.mode_guard_label.style().unpolish(self.mode_guard_label)
                self.mode_guard_label.style().polish(self.mode_guard_label)
                cache['risk'] = risk

            if mode == 'ASK':
                lines = [tr('guard.readonly.tooltip')]
            elif self._confirm_mode:
                lines = [tr('guard.confirm.tooltip')]
            else:
                lines = [tr('guard.high_risk.tooltip')]
            for item in self._policy_timeline_records[-5:]:
                lines.append(
                    f"{item.get('time', '')} {item.get('tool', '')} -> {item.get('action', '')}"
                )
            tip = "\n".join(lines)
            if cache.get('tip') != tip:
                self.mode_guard_label.setToolTip(tip)
                cache['tip'] = tip

        if hasattr(self, 'policy_timeline_btn') and self.policy_timeline_btn:
            n = len(self._policy_timeline_records)
            has_failures = self._policy_failure_count > 0
            text = (
                tr('safety.attention', self._policy_failure_count)
                if has_failures else tr('safety.records', n)
            )
            if cache.get('btn_text') != text:
                self.policy_timeline_btn.setText(text)
                cache['btn_text'] = text
            if cache.get('btn_failures') != has_failures:
                self.policy_timeline_btn.setProperty('failures', has_failures)
                self.policy_timeline_btn.style().unpolish(self.policy_timeline_btn)
                self.policy_timeline_btn.style().polish(self.policy_timeline_btn)
                cache['btn_failures'] = has_failures
            safety_tip = tr('safety.tooltip')
            if cache.get('btn_tip') != safety_tip:
                self.policy_timeline_btn.setToolTip(safety_tip)
                cache['btn_tip'] = safety_tip

    def _append_policy_timeline(self, tool_name: str, action: str, reason: str = ""):
        item = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'tool': tool_name,
            'action': action,
            'reason': (reason or '').strip(),
        }
        self._policy_timeline_records.append(item)
        if len(self._policy_timeline_records) > 200:
            self._policy_timeline_records = self._policy_timeline_records[-200:]
        if action in {'deny', 'ask_cancel', 'retry_limit', 'exec_fail'}:
            self._policy_failure_count += 1
        try:
            mode = 'plan' if self._plan_mode else ('agent' if self._agent_mode else 'ask')
            self._append_session_diagnostics_records([
                {
                    'event_type': 'policy_decision',
                    'tool': tool_name,
                    'action': action,
                    'reason': (reason or '').strip(),
                    'mode': mode,
                    'plan_phase': getattr(self, '_plan_phase', 'idle'),
                    'confirm_mode': bool(getattr(self, '_confirm_mode', False)),
                    'failure_count': int(getattr(self, '_policy_failure_count', 0) or 0),
                }
            ])
        except Exception:
            pass
        self._refresh_mode_guard_ui()

    def _get_session_diagnostics_jsonl_path(self, session_id: Optional[str] = None) -> Path:
        sid = (session_id or self._session_id or "unknown").strip() or "unknown"
        cache_dir = getattr(self, '_cache_dir', None)
        if not isinstance(cache_dir, Path):
            cache_dir = Path('.')
        diag_dir = cache_dir / "diagnostics"
        diag_dir.mkdir(parents=True, exist_ok=True)
        return diag_dir / f"session_{sid}.jsonl"

    def _append_session_diagnostics_records(self, records: list, session_id: Optional[str] = None):
        """Append-only session diagnostics records (JSONL)."""
        if not records:
            return
        sid = (session_id or self._session_id or "unknown").strip() or "unknown"
        try:
            path = self._get_session_diagnostics_jsonl_path(sid)
            now_iso = datetime.now().isoformat()
            with self._diagnostics_write_lock:
                with open(path, 'a', encoding='utf-8') as f:
                    for rec in records:
                        row = dict(rec or {})
                        row.setdefault('schema_version', 1)
                        row.setdefault('session_id', sid)
                        row.setdefault('recorded_at', now_iso)
                        row.setdefault('event_type', 'unknown')
                        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            print(f"[Diagnostics] 写入 session jsonl 失败: {e}")

    def _show_policy_menu(self):
        """显示策略/诊断菜单。"""
        menu = QtWidgets.QMenu(self)
        menu.addAction("Policy Timeline", self._show_policy_timeline_dialog)
        menu.addAction("Export Diagnostics JSON", self._export_diagnostics_json)
        menu.exec_(self.policy_timeline_btn.mapToGlobal(
            QtCore.QPoint(0, self.policy_timeline_btn.height())
        ))

    def _show_policy_timeline_dialog(self):
        """显示最近策略决策时间线，并提供快速恢复动作。"""
        lines = ["最近策略时间线（最新在下）：", ""]
        records = self._policy_timeline_records[-30:]
        if not records:
            lines.append("暂无策略记录。")
        else:
            for rec in records:
                reason = rec.get('reason', '')
                if reason:
                    lines.append(
                        f"{rec.get('time', '')} | {rec.get('tool', '')} | {rec.get('action', '')} | {reason}"
                    )
                else:
                    lines.append(
                        f"{rec.get('time', '')} | {rec.get('tool', '')} | {rec.get('action', '')}"
                    )

        lines.append("")
        lines.append("快速恢复：")
        lines.append("1) 切换到 Plan 模式（更稳）")
        lines.append("2) 切换到 Ask 模式（只读排查）")

        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("Policy Timeline")
        msg_box.setText("\n".join(lines))
        btn_plan = msg_box.addButton("切到 Plan", QtWidgets.QMessageBox.ActionRole)
        btn_ask = msg_box.addButton("切到 Ask", QtWidgets.QMessageBox.ActionRole)
        btn_close = msg_box.addButton("关闭", QtWidgets.QMessageBox.RejectRole)
        msg_box.exec_()
        clicked = msg_box.clickedButton()
        if clicked == btn_plan and hasattr(self, 'mode_combo'):
            self.mode_combo.setCurrentIndex(2)
        elif clicked == btn_ask and hasattr(self, 'mode_combo'):
            self.mode_combo.setCurrentIndex(1)
        elif clicked == btn_close:
            return

    def _append_harness_trace_records(self, records: list, session_id: Optional[str] = None):
        """追加写入 Harness trace（jsonl），用于回放与诊断。"""
        if not records:
            return
        sid = (session_id or self._session_id or "unknown").strip() or "unknown"
        try:
            trace_dir = self._cache_dir / "harness_trace"
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_file = trace_dir / f"session_{sid}.jsonl"
            now_iso = datetime.now().isoformat()
            with open(trace_file, 'a', encoding='utf-8') as f:
                for rec in records:
                    row = dict(rec or {})
                    row.setdefault('session_id', sid)
                    row.setdefault('recorded_at', now_iso)
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[Harness Trace] 写入失败: {e}")

    @staticmethod
    def _operation_receipt_from_row(row: dict) -> Optional[dict]:
        if not isinstance(row, dict) or row.get('event_type') != 'operation_receipt':
            return None
        operation_id = row.get('operation_id')
        if not isinstance(operation_id, str) or not operation_id:
            return None
        return {
            key: row.get(key)
            for key in (
                'protocol_version', 'request_ref', 'operation_id', 'kind', 'tool_name', 'state', 'created_at',
                'updated_at', 'batch_size', 'wait_status', 'thread_still_running',
                'scene_consistency', 'success', 'error_code', 'error_detail', 'result_available',
                'session_id', 'arguments_sha256', 'contract_version', 'executor_id',
                'houdini_version', 'scene_id', 'hip_path', 'revision', 'recorded_at',
            )
            if row.get(key) is not None
        }

    @staticmethod
    def _project_interrupted_receipt(receipt: dict) -> dict:
        projected = dict(receipt)
        if projected.get('state') in {'accepted', 'running'}:
            projected['state'] = 'abandoned'
            projected['wait_status'] = 'process_interrupted'
            projected['scene_consistency'] = 'unknown'
            projected['success'] = None
        return projected

    def _read_operation_receipts(self, session_id: str) -> list:
        path = self._get_session_diagnostics_jsonl_path(session_id)
        if not path.exists():
            return []
        records = {}
        order = {}
        with open(path, 'r', encoding='utf-8') as f:
            for line_index, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    receipt = self._operation_receipt_from_row(json.loads(line))
                except Exception:
                    continue
                if receipt is None:
                    continue
                operation_id = receipt['operation_id']
                records[operation_id] = receipt
                order[operation_id] = line_index
        return [
            self._project_interrupted_receipt(item)
            for item in sorted(
                records.values(),
                key=lambda item: order.get(item['operation_id'], 0),
            )
        ]

    def _build_diagnostics_payload(self) -> dict:
        """Build a compact diagnostics payload without conversation message content."""
        session_id = self._session_id or "unknown"
        provider = self._current_provider() if hasattr(self, '_current_provider') else ""
        model = self.model_combo.currentText() if hasattr(self, 'model_combo') else ""
        mode = 'plan' if self._plan_mode else ('agent' if self._agent_mode else 'ask')
        session_audit_jsonl = None
        session_audit_exists = False
        session_audit_records = 0
        session_audit_last_recorded_at = None
        session_audit_stale = None
        external_job_records = []
        operation_records = {}
        operation_order = {}
        try:
            session_audit_path = self._get_session_diagnostics_jsonl_path(session_id)
            session_audit_jsonl = str(session_audit_path)
            session_audit_exists = session_audit_path.exists()
            if session_audit_exists:
                last_recorded_at = None
                with open(session_audit_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        session_audit_records += 1
                        try:
                            row = json.loads(line)
                            if not isinstance(row, dict):
                                continue
                            last_recorded_at = row.get('recorded_at') or last_recorded_at
                            receipt = self._operation_receipt_from_row(row)
                            if receipt is not None:
                                operation_id = receipt['operation_id']
                                operation_records[operation_id] = receipt
                                if operation_id:
                                    operation_order[operation_id] = session_audit_records
                            if str(row.get('event_type') or '').startswith('job_'):
                                external_job_records.append({
                                    key: row.get(key)
                                    for key in (
                                        'event_type', 'recorded_at', 'operation_id',
                                        'kind', 'decision', 'exit_code', 'artifacts',
                                    )
                                    if row.get(key) is not None
                                })
                        except Exception:
                            pass
                session_audit_last_recorded_at = last_recorded_at
                if last_recorded_at:
                    try:
                        last_dt = datetime.fromisoformat(str(last_recorded_at))
                        session_audit_stale = (datetime.now() - last_dt).total_seconds() > 300
                    except Exception:
                        session_audit_stale = None
        except Exception:
            pass

        try:
            from ..utils.mcp.external_jobs import ExternalProcessJobAdapter  # noqa: F401
            external_jobs_available = True
        except Exception:
            external_jobs_available = False

        external_job_events = external_job_records[-100:]
        external_job_counts = {}
        for record in external_job_records:
            event_type = str(record.get('event_type') or 'unknown')
            external_job_counts[event_type] = external_job_counts.get(event_type, 0) + 1

        operation_items = sorted(
            operation_records.values(),
            key=lambda item: operation_order.get(item.get('operation_id'), 0),
        )[-100:]
        for item in operation_items:
            item.update(self._project_interrupted_receipt(item))

        try:
            from ..utils.tool_registry import get_tool_registry
            registry = get_tool_registry()
            registered_tool_names = sorted(registry._tools)
        except Exception:
            registered_tool_names = []

        # ---- 会话级 summary 聚合：打开 diagnostics 就能一眼看到失败分布 ----
        # 基于 operation_records（终态 receipt），聚合 success/failure/inconclusive。
        tool_calls_total = 0
        tool_calls_succeeded = 0
        tool_calls_failed = 0
        failure_by_tool: dict = {}
        error_code_counts: dict = {}
        top_error_details: list = []
        tool_usage_counts: dict = {}
        for receipt in operation_records.values():
            # 只统计终态 receipt（completed / failed / abandoned），跳过中间态
            state = receipt.get('state')
            if state not in ('completed', 'failed', 'abandoned'):
                continue
            if receipt.get('success') is None:
                continue
            tool_calls_total += 1
            tool_name = str(receipt.get('tool_name') or 'unknown')
            tool_usage_counts[tool_name] = tool_usage_counts.get(tool_name, 0) + 1
            if receipt.get('success'):
                tool_calls_succeeded += 1
            else:
                tool_calls_failed += 1
                failure_by_tool[tool_name] = failure_by_tool.get(tool_name, 0) + 1
                error_code = str(receipt.get('error_code') or 'unknown')
                error_code_counts[error_code] = error_code_counts.get(error_code, 0) + 1
                detail = receipt.get('error_detail')
                if detail:
                    top_error_details.append({
                        'tool_name': tool_name,
                        'error_code': error_code,
                        'error_detail': str(detail)[:200],
                        'recorded_at': receipt.get('recorded_at'),
                    })
        # 按时间倒序保留最近 10 条详细错误
        top_error_details.sort(key=lambda item: str(item.get('recorded_at') or ''), reverse=True)
        top_error_details = top_error_details[:10]
        # failure_by_tool 按失败次数倒序
        failure_by_tool_sorted = dict(
            sorted(failure_by_tool.items(), key=lambda kv: kv[1], reverse=True)
        )
        tool_usage_sorted = dict(
            sorted(tool_usage_counts.items(), key=lambda kv: kv[1], reverse=True)
        )

        # 策略动作直方 + execute_python 裸改占比（分母为修改类工具调用数）
        policy_action_counts: dict = {}
        for rec in (getattr(self, '_policy_timeline_records', []) or []):
            action = str(rec.get('action') or 'unknown')
            policy_action_counts[action] = policy_action_counts.get(action, 0) + 1
        try:
            from .harness_policy_config import SCENE_MUTATION_TOOLS
            mutation_calls = sum(
                count for name, count in tool_usage_counts.items()
                if name in SCENE_MUTATION_TOOLS
            )
        except Exception:
            mutation_calls = 0
        python_calls = int(tool_usage_counts.get('execute_python', 0))
        execute_python_ratio = (
            round(python_calls / mutation_calls, 4) if mutation_calls > 0 else 0.0
        )

        return {
            'schema_version': 1,
            'exported_at': datetime.now().isoformat(),
            'summary': {
                'tool_calls_total': tool_calls_total,
                'tool_calls_succeeded': tool_calls_succeeded,
                'tool_calls_failed': tool_calls_failed,
                'failure_rate': (
                    round(tool_calls_failed / tool_calls_total, 4)
                    if tool_calls_total > 0 else 0.0
                ),
                'failure_by_tool': failure_by_tool_sorted,
                'error_code_counts': error_code_counts,
                'top_error_details': top_error_details,
                'tool_usage_counts': tool_usage_sorted,
                'policy_action_counts': policy_action_counts,
                'execute_python_ratio': execute_python_ratio,
            },
            'session': {
                'id': session_id,
                'username': getattr(self, '_username', 'default'),
                'mode': mode,
                'plan_phase': getattr(self, '_plan_phase', 'idle'),
                'confirm_mode': bool(getattr(self, '_confirm_mode', False)),
                'auto_read_mode': getattr(self, '_auto_read_mode', ''),
                'conversation_messages': len(getattr(self, '_conversation_history', []) or []),
                'session_audit_jsonl': session_audit_jsonl,
                'session_audit_exists': session_audit_exists,
                'session_audit_records': session_audit_records,
                'session_audit_last_recorded_at': session_audit_last_recorded_at,
                'session_audit_stale': session_audit_stale,
            },
            'runtime': {
                'provider': provider,
                'model': model,
                'is_running': bool(getattr(self, '_is_running', False)),
                'harness_v2_enabled': bool(getattr(self, '_harness_v2_enabled', False)),
                'policy_retry_limit': getattr(self, '_policy_retry_limit', None),
                'pending_user_switch': getattr(self, '_pending_user_switch', None),
                'registered_tool_names': registered_tool_names,
                'last_selected_tool_names': list(
                    getattr(self, '_last_selected_tool_names', []) or []
                ),
            },
            'external_jobs': {
                'module_available': external_jobs_available,
                'runtime_configured': getattr(self, '_external_job_adapter', None) is not None,
                'event_counts': external_job_counts,
                'events': external_job_events,
            },
            'operations': {
                'total_count': len(operation_records),
                'items': operation_items,
            },
            'token_stats': dict(getattr(self, '_token_stats', {}) or {}),
            'policy': {
                'failure_count': int(getattr(self, '_policy_failure_count', 0) or 0),
                'timeline': list(getattr(self, '_policy_timeline_records', []) or [])[-200:],
                'retry_counts': dict(getattr(getattr(self, '_harness_state', None), 'policy_retry_counts', {}) or {}),
            },
            'harness': {
                'runtime_trace': list(getattr(getattr(self, '_harness_state', None), 'trace', []) or [])[-300:],
                'executor_trace': list(getattr(self, '_harness_trace_records', []) or [])[-500:],
            },
            'calls': list(getattr(self, '_call_records', []) or [])[-100:],
        }

    def _export_diagnostics_json(self) -> Optional[str]:
        """Export policy/timing diagnostics to a JSON file."""
        try:
            diag_dir = self._cache_dir / "diagnostics"
            diag_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            session_id = (self._session_id or "unknown").strip() or "unknown"
            path = diag_dir / f"diagnostics_{session_id}_{stamp}.json"
            payload = self._build_diagnostics_payload()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Diagnostics Export Failed", str(e))
            return None

        response = self._add_ai_response()
        response.add_status("Diagnostics exported")
        response.set_content(
            "诊断信息已导出。\n\n"
            f"文件: {path}\n"
            f"Policy 记录: {len(payload['policy']['timeline'])}\n"
            f"Harness trace: {len(payload['harness']['executor_trace'])}\n"
            f"Call records: {len(payload['calls'])}\n"
            f"External jobs: {len(payload['external_jobs']['events'])} events, "
            f"runtime configured={payload['external_jobs']['runtime_configured']}"
        )
        response.finalize()
        return str(path)
