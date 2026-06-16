# -*- coding: utf-8 -*-
"""
User Rules Manager — 用户自定义规则管理

类似 Cursor Rules 的功能，让用户长期定义上下文规则。
规则全局生效，自动注入到每次 AI 请求的 system prompt 中。

支持两种管理方式：
  1. UI 规则：通过 Rules 编辑器对话框创建/编辑，存储在 config/user_rules.json
  2. 文件规则：自动扫描 rules/ 目录下的 .md 和 .txt 文件

设计原则：
  - UI 规则可单独 enable/disable
  - 文件规则始终启用（以 _ 开头的文件除外，视为草稿/模板）
  - 所有启用的规则合并后用 <user_rules> 标签包裹注入 system prompt
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.user_paths import UserPaths, normalize_username

# ============================================================
# 路径常量
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent          # DCC-ASSET-MANAGER/
_CONFIG_DIR = _PROJECT_ROOT / "config"
_RULES_DIR = _PROJECT_ROOT / "rules"

# ============================================================
# 数据结构
# ============================================================

def _new_rule(title: str = "", content: str = "", enabled: bool = True) -> Dict[str, Any]:
    """创建一条新的 UI 规则数据"""
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "content": content,
        "enabled": enabled,
        "created_at": time.time(),
    }


# ============================================================
# 加载 / 保存 UI 规则 (config/user_rules.json)
# ============================================================

def _get_ui_rules_path(username: Optional[str]) -> Path:
    try:
        uname = normalize_username(username or "")
        return UserPaths(uname).user_rules_path()
    except Exception:
        return _CONFIG_DIR / "user_rules.json"


def _load_ui_rules(username: Optional[str]) -> List[Dict[str, Any]]:
    """从用户规则文件加载 UI 规则列表"""
    rules_file = _get_ui_rules_path(username)
    if not rules_file.exists():
        return []
    try:
        with open(rules_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"[Rules] Failed to load user_rules.json: {e}")
        return []


def _save_ui_rules(rules: List[Dict[str, Any]], username: Optional[str]):
    """保存 UI 规则到用户规则文件"""
    rules_file = _get_ui_rules_path(username)
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(rules_file, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Rules] Failed to save user_rules.json: {e}")


# ============================================================
# 文件规则扫描 (rules/*.md, *.txt)
# ============================================================

def _scan_file_rules() -> List[Dict[str, Any]]:
    """扫描 rules/ 目录下的 .md / .txt 文件，返回规则列表"""
    if not _RULES_DIR.exists():
        return []

    result: List[Dict[str, Any]] = []
    for ext in ("*.md", "*.txt"):
        for f in sorted(_RULES_DIR.glob(ext)):
            # 以 _ 开头的文件视为模板/草稿，不加载
            if f.name.startswith("_"):
                continue
            try:
                content = f.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                result.append({
                    "id": f"file:{f.name}",
                    "title": f.stem,                 # 文件名（不含扩展名）作为标题
                    "content": content,
                    "enabled": True,
                    "source": "file",                # 标记来源
                    "file_path": str(f),
                })
            except Exception as e:
                print(f"[Rules] Failed to read rule file {f.name}: {e}")
    return result


# ============================================================
# 公共 API — 模块级函数（单例风格）
# ============================================================

# 内部缓存
_ui_rules_cache: Dict[str, List[Dict[str, Any]]] = {}


def _cache_key(username: Optional[str]) -> str:
    try:
        return normalize_username(username or "default")
    except Exception:
        return "default"


def get_all_rules(username: Optional[str] = None, force_reload: bool = False) -> List[Dict[str, Any]]:
    """获取所有规则（UI 规则 + 文件规则）

    返回列表中每条规则包含:
        id, title, content, enabled, source("ui"|"file"), ...
    """
    global _ui_rules_cache
    key = _cache_key(username)
    if force_reload or key not in _ui_rules_cache:
        _ui_rules_cache[key] = _load_ui_rules(username)

    ui_rules = []
    for r in _ui_rules_cache.get(key, []):
        rule = dict(r)
        rule.setdefault("source", "ui")
        ui_rules.append(rule)

    file_rules = _scan_file_rules()
    return ui_rules + file_rules


def get_ui_rules(username: Optional[str] = None) -> List[Dict[str, Any]]:
    """仅获取 UI 规则"""
    global _ui_rules_cache
    key = _cache_key(username)
    if key not in _ui_rules_cache:
        _ui_rules_cache[key] = _load_ui_rules(username)
    return list(_ui_rules_cache.get(key, []))


def add_rule(title: str = "", content: str = "", username: Optional[str] = None) -> Dict[str, Any]:
    """添加一条新的 UI 规则"""
    global _ui_rules_cache
    key = _cache_key(username)
    if key not in _ui_rules_cache:
        _ui_rules_cache[key] = _load_ui_rules(username)
    rule = _new_rule(title=title, content=content, enabled=True)
    _ui_rules_cache[key].append(rule)
    _save_ui_rules(_ui_rules_cache[key], username)
    return rule


def update_rule(rule_id: str, username: Optional[str] = None, **kwargs):
    """更新指定 UI 规则的字段 (title, content, enabled)"""
    global _ui_rules_cache
    key = _cache_key(username)
    if key not in _ui_rules_cache:
        _ui_rules_cache[key] = _load_ui_rules(username)
    for r in _ui_rules_cache.get(key, []):
        if r.get("id") == rule_id:
            for k in ("title", "content", "enabled"):
                if k in kwargs:
                    r[k] = kwargs[k]
            _save_ui_rules(_ui_rules_cache[key], username)
            return True
    return False


def delete_rule(rule_id: str, username: Optional[str] = None) -> bool:
    """删除指定 UI 规则"""
    global _ui_rules_cache
    key = _cache_key(username)
    if key not in _ui_rules_cache:
        _ui_rules_cache[key] = _load_ui_rules(username)
    before = len(_ui_rules_cache.get(key, []))
    _ui_rules_cache[key] = [r for r in _ui_rules_cache.get(key, []) if r.get("id") != rule_id]
    if len(_ui_rules_cache.get(key, [])) < before:
        _save_ui_rules(_ui_rules_cache[key], username)
        return True
    return False


def set_rule_enabled(rule_id: str, enabled: bool, username: Optional[str] = None) -> bool:
    """设置 UI 规则的启用/禁用状态"""
    return update_rule(rule_id, username=username, enabled=enabled)


def save_all_ui_rules(rules: List[Dict[str, Any]], username: Optional[str] = None):
    """批量保存 UI 规则（从编辑器全量写回）"""
    global _ui_rules_cache
    key = _cache_key(username)
    _ui_rules_cache[key] = rules
    _save_ui_rules(_ui_rules_cache[key], username)


def reload_rules(username: Optional[str] = None):
    """强制重新加载所有规则（清除缓存）"""
    global _ui_rules_cache
    key = _cache_key(username)
    if key in _ui_rules_cache:
        del _ui_rules_cache[key]


# ============================================================
# Prompt 注入
# ============================================================

def get_rules_for_prompt(username: Optional[str] = None) -> str:
    """将所有启用的规则合并为一段文本，用 <user_rules> 标签包裹

    返回空字符串表示没有任何启用的规则。
    """
    all_rules = get_all_rules(username=username)
    enabled = [r for r in all_rules if r.get("enabled", True)]
    if not enabled:
        return ""

    parts: List[str] = []
    for r in enabled:
        title = r.get("title", "").strip()
        content = r.get("content", "").strip()
        if not content:
            continue
        if title:
            parts.append(f"## {title}\n{content}")
        else:
            parts.append(content)

    if not parts:
        return ""

    body = "\n\n".join(parts)
    return (
        "<user_rules>\n"
        "The following are custom rules defined by the user. "
        "You MUST follow them in every response.\n\n"
        f"{body}\n"
        "</user_rules>"
    )


# ============================================================
# 辅助
# ============================================================

def get_rules_dir() -> Path:
    """返回 rules/ 目录路径"""
    return _RULES_DIR


def ensure_rules_dir():
    """确保 rules/ 目录存在"""
    _RULES_DIR.mkdir(parents=True, exist_ok=True)
