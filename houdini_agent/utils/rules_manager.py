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
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.user_paths import UserPaths, normalize_username

# ============================================================
# 路径常量
# ============================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent          # DCC-ASSET-MANAGER/
_CONFIG_DIR = _PROJECT_ROOT / "config"
_RULES_DIR = _PROJECT_ROOT / "rules"

# ============================================================
# 限制（防止 token 爆炸）
# ============================================================

_MAX_RULE_CHARS = 8000          # 单条规则最大字符数
_MAX_TOTAL_CHARS = 32000        # 注入 prompt 的所有规则合计最大字符数

# ============================================================
# 并发保护
# ============================================================

_lock = threading.RLock()

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
    """从用户规则文件加载 UI 规则列表。

    如果文件损坏（JSON 解析失败或顶层不是 list），把它重命名为
    user_rules.json.corrupt-<timestamp>，避免后续保存覆盖丢失数据。
    """
    rules_file = _get_ui_rules_path(username)
    if not rules_file.exists():
        return []
    try:
        with open(rules_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        reason = f"top-level is {type(data).__name__}, expected list"
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"

    backup = rules_file.with_name(
        f"{rules_file.name}.corrupt-{int(time.time())}"
    )
    try:
        os.replace(rules_file, backup)
        print(f"[Rules] user_rules.json is corrupt ({reason}); backed up to {backup.name}")
    except Exception as move_err:
        print(f"[Rules] user_rules.json is corrupt ({reason}); backup failed: {move_err}")
    return []


def _save_ui_rules(rules: List[Dict[str, Any]], username: Optional[str]):
    """保存 UI 规则到用户规则文件（原子写入：tmp + os.replace）"""
    rules_file = _get_ui_rules_path(username)
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = rules_file.with_suffix(rules_file.suffix + ".tmp")
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, rules_file)
    except Exception as e:
        print(f"[Rules] Failed to save user_rules.json: {e}")
        try:
            if tmp_file.exists():
                tmp_file.unlink()
        except Exception:
            pass


# ============================================================
# 文件规则扫描 (rules/*.md, *.txt) — 带 mtime 缓存
# ============================================================

# (signature -> rules)，signature 为目录下所有规则文件的 (path, mtime, size) 元组
_file_rules_cache: Tuple[Optional[Tuple], List[Dict[str, Any]]] = (None, [])


def _file_rules_signature() -> Optional[Tuple]:
    """计算 rules/ 目录下规则文件的指纹，用于判断是否需要重扫"""
    if not _RULES_DIR.exists():
        return tuple()
    sig = []
    for ext in ("*.md", "*.txt"):
        for f in _RULES_DIR.glob(ext):
            if f.name.startswith("_"):
                continue
            try:
                st = f.stat()
                sig.append((f.name, st.st_mtime_ns, st.st_size))
            except OSError:
                continue
    sig.sort()
    return tuple(sig)


def _scan_file_rules() -> List[Dict[str, Any]]:
    """扫描 rules/ 目录下的 .md / .txt 文件，返回规则列表。

    使用 mtime + size 指纹缓存，目录无变化时跳过磁盘读取。
    """
    global _file_rules_cache
    with _lock:
        sig = _file_rules_signature()
        cached_sig, cached_rules = _file_rules_cache
        if sig == cached_sig:
            return list(cached_rules)

        if not _RULES_DIR.exists():
            _file_rules_cache = (sig, [])
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

        _file_rules_cache = (sig, result)
        return list(result)


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


def _get_cache(username: Optional[str]) -> List[Dict[str, Any]]:
    """获取指定用户的 UI 规则缓存（懒加载）"""
    key = _cache_key(username)
    with _lock:
        if key not in _ui_rules_cache:
            _ui_rules_cache[key] = _load_ui_rules(username)
        return _ui_rules_cache[key]


def get_all_rules(username: Optional[str] = None, force_reload: bool = False) -> List[Dict[str, Any]]:
    """获取所有规则（UI 规则 + 文件规则）

    返回列表中每条规则包含:
        id, title, content, enabled, source("ui"|"file"), ...
    """
    key = _cache_key(username)
    with _lock:
        if force_reload or key not in _ui_rules_cache:
            _ui_rules_cache[key] = _load_ui_rules(username)
        ui_rules = [dict(r, **({"source": r.get("source", "ui")})) for r in _ui_rules_cache[key]]

    file_rules = _scan_file_rules()
    return ui_rules + file_rules


def get_ui_rules(username: Optional[str] = None) -> List[Dict[str, Any]]:
    """仅获取 UI 规则"""
    return list(_get_cache(username))


def add_rule(title: str = "", content: str = "", username: Optional[str] = None) -> Dict[str, Any]:
    """添加一条新的 UI 规则"""
    rule = _new_rule(title=title, content=content, enabled=True)
    with _lock:
        cache = _get_cache(username)
        cache.append(rule)
        _save_ui_rules(cache, username)
    return rule


def update_rule(rule_id: str, username: Optional[str] = None, **kwargs):
    """更新指定 UI 规则的字段 (title, content, enabled)"""
    with _lock:
        cache = _get_cache(username)
        for r in cache:
            if r.get("id") == rule_id:
                for k in ("title", "content", "enabled"):
                    if k in kwargs:
                        r[k] = kwargs[k]
                _save_ui_rules(cache, username)
                return True
    return False


def delete_rule(rule_id: str, username: Optional[str] = None) -> bool:
    """删除指定 UI 规则"""
    with _lock:
        key = _cache_key(username)
        cache = _get_cache(username)
        before = len(cache)
        new_cache = [r for r in cache if r.get("id") != rule_id]
        if len(new_cache) == before:
            return False
        _ui_rules_cache[key] = new_cache
        _save_ui_rules(new_cache, username)
    return True


def set_rule_enabled(rule_id: str, enabled: bool, username: Optional[str] = None) -> bool:
    """设置 UI 规则的启用/禁用状态"""
    return update_rule(rule_id, username=username, enabled=enabled)


def save_all_ui_rules(rules: List[Dict[str, Any]], username: Optional[str] = None):
    """批量保存 UI 规则（从编辑器全量写回）"""
    key = _cache_key(username)
    with _lock:
        _ui_rules_cache[key] = list(rules)
        _save_ui_rules(_ui_rules_cache[key], username)


def reload_rules(username: Optional[str] = None):
    """强制重新加载所有规则（清除缓存）"""
    global _file_rules_cache
    key = _cache_key(username)
    with _lock:
        _ui_rules_cache.pop(key, None)
        _file_rules_cache = (None, [])


# ============================================================
# Prompt 注入
# ============================================================

def get_rules_for_prompt(username: Optional[str] = None) -> str:
    """将所有启用的规则合并为一段文本，用 <user_rules> 标签包裹

    返回空字符串表示没有任何启用的规则。
    超出 _MAX_RULE_CHARS 的单条规则会被截断；
    合计超过 _MAX_TOTAL_CHARS 时按顺序丢弃后续规则，防止 token 爆炸。
    """
    all_rules = get_all_rules(username=username)
    enabled = [r for r in all_rules if r.get("enabled", True)]
    if not enabled:
        return ""

    parts: List[str] = []
    total = 0
    truncated_any = False
    dropped = 0
    for r in enabled:
        title = (r.get("title") or "").strip()
        content = (r.get("content") or "").strip()
        if not content:
            continue
        if len(content) > _MAX_RULE_CHARS:
            content = content[:_MAX_RULE_CHARS] + "\n... [truncated]"
            truncated_any = True
        block = f"## {title}\n{content}" if title else content
        if total + len(block) > _MAX_TOTAL_CHARS:
            dropped = len(enabled) - len(parts)
            break
        parts.append(block)
        total += len(block)

    if not parts:
        return ""

    body = "\n\n".join(parts)
    notes = []
    if truncated_any:
        notes.append(f"(some rules truncated at {_MAX_RULE_CHARS} chars)")
    if dropped:
        notes.append(f"({dropped} trailing rule(s) skipped to fit budget)")
    note_line = (" " + " ".join(notes)) if notes else ""

    return (
        "<user_rules>\n"
        "The following are custom rules defined by the user. "
        f"You MUST follow them in every response.{note_line}\n\n"
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
