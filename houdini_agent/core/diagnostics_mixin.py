# -*- coding: utf-8 -*-
"""Diagnostics and policy timeline helpers for AITab."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from houdini_agent.qt_compat import QtWidgets, QtCore


class DiagnosticsMixin:
    def _refresh_mode_guard_ui(self):
        """刷新输入区模式风险提示与策略时间线入口。"""
        mode = 'PLAN' if self._plan_mode else ('AGENT' if self._agent_mode else 'ASK')
        if mode == 'ASK':
            guard = 'RO'
            color = '#10b981'
        elif self._confirm_mode:
            guard = 'CONFIRM'
            color = '#f59e0b'
        else:
            guard = 'HIGH-RISK'
            color = '#ef4444'

        hint = f"{mode} | {guard}"
        # 状态快照去重:避免 Qt setStyleSheet/setText 在值未变时仍触发全树样式重算 —
        # 是 Houdini 20.5 QHeaderView race 的高频源头之一。
        cache = self.__dict__.setdefault('_mode_guard_cache', {})
        if hasattr(self, 'mode_guard_label') and self.mode_guard_label:
            style = f"color:{color}; font-weight:600;"
            if cache.get('hint') != hint:
                self.mode_guard_label.setText(hint)
                cache['hint'] = hint
            if cache.get('style') != style:
                self.mode_guard_label.setStyleSheet(style)
                cache['style'] = style

            lines = [
                f"当前模式: {mode}",
                f"确认开关: {'ON' if self._confirm_mode else 'OFF'}",
                f"策略失败次数: {self._policy_failure_count}",
            ]
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
            text = f"Policy {n}"
            btn_style = "color:#ef4444;" if self._policy_failure_count > 0 else ""
            if cache.get('btn_text') != text:
                self.policy_timeline_btn.setText(text)
                cache['btn_text'] = text
            if cache.get('btn_style') != btn_style:
                self.policy_timeline_btn.setStyleSheet(btn_style)
                cache['btn_style'] = btn_style

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
                            last_recorded_at = row.get('recorded_at') or last_recorded_at
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

        return {
            'schema_version': 1,
            'exported_at': datetime.now().isoformat(),
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
            f"Call records: {len(payload['calls'])}"
        )
        response.finalize()
        return str(path)
