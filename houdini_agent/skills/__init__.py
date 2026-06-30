# -*- coding: utf-8 -*-
"""
Skill 注册表 & 加载器

Skill 是预定义的 Python 代码片段，在 Houdini 环境中执行。
每个 skill 文件放在 skills/ 目录下，包含:
  - SKILL_INFO: dict  (name, description, parameters)
  - run(**kwargs) -> dict  入口函数

★ Skill 通过 list_skills / run_skill 元工具暴露给 AI，不再注册为独立 skill_xxx 工具。
★ 支持用户自定义 Skill 目录（config/houdini_ai.ini → [skills] user_skill_dir）
"""

import os
import importlib
import importlib.util
import traceback
from typing import Dict, Any, Optional, List
from pathlib import Path


# 全局注册表：skill_name -> module
_registry: Dict[str, Any] = {}
_loaded = False


def _get_user_skill_dir() -> Optional[Path]:
    """从 config/houdini_ai.ini 读取用户自定义 Skill 目录"""
    try:
        import configparser
        config_dir = Path(__file__).resolve().parent.parent.parent / "config"
        ini_path = config_dir / "houdini_ai.ini"
        if not ini_path.exists():
            return None
        cfg = configparser.ConfigParser()
        cfg.read(str(ini_path), encoding='utf-8')
        user_dir = cfg.get("skills", "user_skill_dir", fallback="").strip()
        if user_dir:
            p = Path(user_dir)
            if p.is_dir():
                return p
            else:
                print(f"[Skills] 用户 Skill 目录不存在: {user_dir}")
    except Exception:
        pass
    return None


def _load_skills_from_dir(skill_dir: Path, prefix: str = ""):
    """从指定目录加载 skill 模块"""
    if not skill_dir.is_dir():
        return

    for f in sorted(skill_dir.glob("*.py")):
        if f.name.startswith("_"):
            continue
        module_name = f.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"houdini_skills.{prefix}{module_name}", str(f))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            info = getattr(mod, "SKILL_INFO", None)
            run_fn = getattr(mod, "run", None)
            if info and run_fn and callable(run_fn):
                name = info.get("name", module_name)
                _registry[name] = mod
        except Exception as e:
            print(f"[Skills] 加载 {prefix}{module_name} 失败: {e}")


def _load_all():
    """扫描 skills/ 目录（内置 + 用户），加载所有 skill 模块"""
    global _registry, _loaded
    if _loaded:
        return

    # 1. 内置 skill 目录
    builtin_dir = Path(__file__).parent
    _load_skills_from_dir(builtin_dir)

    # 2. 用户自定义 skill 目录
    user_dir = _get_user_skill_dir()
    if user_dir:
        _load_skills_from_dir(user_dir, prefix="user_")
        print(f"[Skills] 用户 Skill 目录: {user_dir}")

    _loaded = True
    if _registry:
        print(f"[Skills] 已加载 {len(_registry)} 个 skill: {', '.join(_registry.keys())}")

    # Skill 仅通过 run_skill / list_skills 元工具暴露给 AI，不再注册为
    # 独立的 skill_xxx 工具。原因：独立工具会被 50+ 工具列表淹没，AI 几乎
    # 不会主动选用；且独立工具走 ToolRegistry 回退路径绕过了 undo group。
    # 保留 run_skill 元工具两步走（list_skills → run_skill）更可控。


def list_skills() -> List[Dict[str, Any]]:
    """返回所有已注册 skill 的元数据"""
    _load_all()
    result = []
    for name, mod in _registry.items():
        info = dict(getattr(mod, "SKILL_INFO", {}))
        info.setdefault("name", name)
        result.append(info)
    return result


def run_skill(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """执行指定 skill

    Args:
        skill_name: skill 名称
        params: 传给 run() 的参数

    Returns:
        skill 返回的字典，或包含 error 的字典
    """
    _load_all()

    mod = _registry.get(skill_name)
    if mod is None:
        available = ", ".join(_registry.keys()) or "(无)"
        return {"error": f"Skill 不存在: {skill_name}\n可用 skill: {available}"}

    run_fn = getattr(mod, "run", None)
    if not callable(run_fn):
        return {"error": f"Skill '{skill_name}' 没有 run() 函数"}

    try:
        result = run_fn(**params)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except Exception as e:
        return {"error": f"Skill 执行失败: {e}\n{traceback.format_exc()[:500]}"}


def reload_skills():
    """重新加载所有 skill（开发调试用）"""
    global _registry, _loaded
    _registry.clear()
    _loaded = False
    _load_all()
