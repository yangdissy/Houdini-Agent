# -*- coding: utf-8 -*-
"""
团队记忆共享开关

每个用户可随时关闭"自动把长期记忆里的技术类经验同步给团队共享库"这个行为。
默认开启；首次初始化记忆系统时会告知一次。

设置持久化在用户自己的 memory 目录下
（cache/users/<username>/memory/team_export_settings.json），
不使用 dev_feature_toggles.py 的全局环境变量机制——那是开发者本机专用的
调试开关，不适合作为每个普通用户的隐私偏好开关（环境变量不便于在设置 UI
里持久化展示/切换，且不区分用户）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict

from shared.user_paths import UserPaths, normalize_username

_DEFAULT_SETTINGS: Dict = {"enabled": True, "notice_shown": False}

# 覆盖已存在文件的原子 rename 在网络共享盘（SMB）上偶发失败（同类问题在
# memory_store.py 的 SQLite WAL 里也有记录），因此这里做重试 + 非原子直写兜底，
# 避免"第一次能关，第二次打不开"这种因单次 replace 失败被静默吞掉的情况。
_SAVE_RETRY_ATTEMPTS = 3
_SAVE_RETRY_DELAY_SECONDS = 0.05


def _settings_path(username: str) -> Path:
    return UserPaths(normalize_username(username)).memory_dir() / "team_export_settings.json"


def load_team_export_settings(username: str) -> Dict:
    """读取用户的团队记忆共享设置，缺省/损坏时回退默认值。"""
    path = _settings_path(username)
    if not path.exists():
        return dict(_DEFAULT_SETTINGS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULT_SETTINGS)
        merged = dict(_DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def _save_team_export_settings(username: str, settings: Dict) -> None:
    uname = normalize_username(username)
    user_paths = UserPaths(uname)
    user_paths.ensure_dirs()
    path = _settings_path(uname)
    tmp_path = path.with_suffix(".json.tmp")
    text = json.dumps(settings, ensure_ascii=False, indent=2)

    last_error: Exception = None
    for attempt in range(_SAVE_RETRY_ATTEMPTS):
        try:
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(_SAVE_RETRY_DELAY_SECONDS)

    # 原子 rename 反复失败（常见于网络盘 replace 已存在文件时的锁协议问题）：
    # 退化为直接覆盖写，牺牲原子性换可靠性，好过设置被静默丢弃。
    try:
        path.write_text(text, encoding="utf-8")
        try:
            tmp_path.unlink()
        except OSError:
            pass
    except OSError:
        raise last_error


def is_team_export_enabled(username: str) -> bool:
    """是否允许把当前用户的技术类长期记忆导出给团队共享库（默认 True）。"""
    return bool(load_team_export_settings(username).get("enabled", True))


def set_team_export_enabled(username: str, enabled: bool) -> None:
    settings = load_team_export_settings(username)
    settings["enabled"] = bool(enabled)
    _save_team_export_settings(username, settings)


def has_shown_team_export_notice(username: str) -> bool:
    return bool(load_team_export_settings(username).get("notice_shown", False))


def mark_team_export_notice_shown(username: str) -> None:
    settings = load_team_export_settings(username)
    if not settings.get("notice_shown"):
        settings["notice_shown"] = True
        _save_team_export_settings(username, settings)
