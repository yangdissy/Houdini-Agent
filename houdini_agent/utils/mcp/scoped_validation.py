# -*- coding: utf-8 -*-
"""Transactional update-mode handling for scoped Houdini validation."""

from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass
class ScopedValidationOperationResult:
    success: bool
    payload: Any = None
    health: str = "unknown"
    cook_succeeded: bool = False
    read_succeeded: bool = False
    validation_blocked: bool = False
    block_reason: str = ""
    error: str = ""


class ScopedValidationTransaction:
    def __init__(self, get_mode, set_mode, get_auto_mode, mode_name=None):
        self._get_mode = get_mode
        self._set_mode = set_mode
        self._get_auto_mode = get_auto_mode
        self._mode_name = mode_name or self._default_mode_name

    def run(self, target: str, operation: Callable[[], ScopedValidationOperationResult]) -> Dict[str, Any]:
        try:
            original_mode = self._get_mode()
            original_mode_name = self._mode_name(original_mode)
        except Exception as exc:
            return self._failure(target, operation_error=f"无法读取原 Update Mode: {exc}")

        operation_result = None
        operation_error = ""
        restore_error = ""
        restored_mode_name = "unknown"
        restore_succeeded = False
        try:
            auto_mode = self._get_auto_mode()
            if auto_mode is None:
                operation_error = "无法进入临时 Auto 模式，已停止验证"
            else:
                self._set_mode(auto_mode)
                if self._get_mode() != auto_mode:
                    operation_error = "临时 Auto 模式未生效，已停止验证"
                else:
                    try:
                        operation_result = operation()
                    except Exception as exc:
                        operation_error = f"Scoped validation operation failed: {exc}"
        except Exception as exc:
            operation_error = f"进入临时 Auto 模式失败: {exc}"
        finally:
            try:
                self._set_mode(original_mode)
                effective_mode = self._get_mode()
                restored_mode_name = self._mode_name(effective_mode)
                restore_succeeded = effective_mode == original_mode
                if not restore_succeeded:
                    restore_error = "恢复 Update Mode 后有效模式与原模式不一致"
            except Exception as exc:
                restore_error = f"恢复 Update Mode 失败: {exc}"

        if operation_result is not None and not operation_result.success:
            operation_error = operation_result.error or operation_result.block_reason or "Scoped validation failed"

        return self._result(
            target=target,
            original_mode_name=original_mode_name,
            restored_mode_name=restored_mode_name,
            restore_succeeded=restore_succeeded,
            operation_result=operation_result,
            operation_error=operation_error,
            restore_error=restore_error,
        )

    def _result(
        self,
        target: str,
        original_mode_name: str,
        restored_mode_name: str,
        restore_succeeded: bool,
        operation_result: ScopedValidationOperationResult,
        operation_error: str,
        restore_error: str,
    ) -> Dict[str, Any]:
        completed = operation_result is not None and operation_result.success
        fresh = bool(
            completed and restore_succeeded and operation_result.cook_succeeded
            and operation_result.read_succeeded and not operation_result.validation_blocked
        )
        health = operation_result.health if fresh else "unknown"
        errors = [message for message in (restore_error, operation_error) if message]
        return {
            "success": bool(completed and restore_succeeded),
            "payload": operation_result.payload if operation_result is not None else None,
            "error": "; ".join(errors),
            "operation_error": operation_error,
            "restore_error": restore_error,
            "health": health,
            "freshness": {
                "status": "fresh" if fresh else "unknown",
                "target": target,
                "cook_succeeded": bool(operation_result and operation_result.cook_succeeded),
                "read_succeeded": bool(operation_result and operation_result.read_succeeded),
            },
            "validation_blocked": bool(operation_result and operation_result.validation_blocked),
            "block_reason": operation_result.block_reason if operation_result is not None else "",
            "original_update_mode": original_mode_name,
            "restore_attempted": True,
            "restore_succeeded": restore_succeeded,
            "restored_update_mode": restored_mode_name,
        }

    def _failure(self, target: str, operation_error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "payload": None,
            "error": operation_error,
            "operation_error": operation_error,
            "restore_error": "",
            "health": "unknown",
            "freshness": {
                "status": "unknown", "target": target,
                "cook_succeeded": False, "read_succeeded": False,
            },
            "validation_blocked": False,
            "block_reason": "",
            "original_update_mode": "unknown",
            "restore_attempted": False,
            "restore_succeeded": False,
            "restored_update_mode": "unknown",
        }

    @staticmethod
    def _default_mode_name(mode: Any) -> str:
        return mode.name() if hasattr(mode, "name") else str(mode)