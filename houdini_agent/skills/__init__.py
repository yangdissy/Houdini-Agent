# -*- coding: utf-8 -*-
"""
Skill 注册表 & 加载器

标准 Skill 是包含 SKILL.md 的目录 bundle。可执行 Skill 使用固定入口
scripts/main.py:run；instructions-only Skill 只提供按需领域方法，不执行代码。
用户目录仍兼容带 SKILL_INFO/run() 的旧单文件 Skill。

★ 新增标准 Skill 时，SKILL.md frontmatter 必须标明 "category"，用于 list_skills 分组导航。
  可用分类（新增分类前先复用现有的）：
        authoring   - Skill 草案生成、校验与评估
    geometry    - SOP 几何/属性/组分析
    graph       - 网络结构、节点端口/卡片、依赖追溯、契约校验
    scene       - 场景上下文、单节点报错诊断
    usd         - LOPs / USD stage 检查
    materials   - 材质指认/网络
    performance - cook 性能、缓存报告
    docs        - 文档检索
    workflow    - 一键搭建蓝图（返回节点配方，不直接建节点）
    learning    - 网络知识提取、记忆泛化/验证/召回与维护
    标准 Skill 缺少或使用未知 category 时会拒绝加载。

★ Skill 通过 list_skills / run_skill 元工具暴露给 AI；instructions-only 内容通过
    get_skill_instructions 读取，不再注册为独立 skill_xxx 工具。
★ 支持当前用户 Skill 目录（cache/users/<username>/config.ini → [skills] user_skill_dir）
"""

import os
import json
import hashlib
from types import ModuleType
import importlib
import importlib.util
import sys
import threading
import traceback
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from pathlib import Path

from ._contract import validate_metadata, validate_params, validate_run_signature


# 全局注册表：skill_name -> module
_registry: Dict[str, Any] = {}
_registry_sources: Dict[str, Dict[str, str]] = {}
_conflicted_names = set()
_load_diagnostics: List[Dict[str, str]] = []
_loaded = False
_current_username: Optional[str] = None
_search_embedder = None


@dataclass
class SkillDescriptor:
    metadata: Dict[str, Any]
    skill_root: Path
    instructions: str
    entrypoint: Optional[str] = None
    source: str = "builtin_descriptor"
    module: Any = None
    module_name: Optional[str] = None

    @property
    def SKILL_INFO(self):
        return self.metadata


def set_current_user(username: str) -> None:
    """Bind Skill discovery to one authenticated user's private directory."""
    global _current_username, _loaded
    try:
        from shared.user_paths import normalize_username
        normalized = normalize_username(username)
    except Exception:
        normalized = None
    if normalized != _current_username:
        _current_username = normalized
        _clear_registry()
        _load_diagnostics.clear()
        _loaded = False


def _get_user_skill_dir() -> Optional[Path]:
    """Read the current user's configured private Skill directory."""
    if not _current_username:
        return None
    try:
        from shared.user_paths import UserPaths
        user_paths = UserPaths(_current_username)
        user_paths.ensure_dirs()
        return user_paths.configured_skills_dir()
    except Exception:
        return None


def _user_activation_path(user_dir: Path) -> Path:
    return user_dir / ".active_skills.json"


def _write_active_user_skills(user_dir: Path, names) -> None:
    path = _user_activation_path(user_dir)
    partial = path.with_name(path.name + ".partial")
    payload = {"active_skills": sorted(set(names))}
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(partial), str(path))
    finally:
        try:
            partial.unlink()
        except OSError:
            pass


def _read_active_user_skills(user_dir: Path) -> Optional[set]:
    path = _user_activation_path(user_dir)
    if not path.exists():
        existing = {
            item.stem for item in user_dir.glob("*.py")
            if not item.name.startswith("_") and item.is_file() and not item.is_symlink()
        }
        existing.update(
            item.name for item in user_dir.iterdir()
            if item.is_dir() and not item.is_symlink()
            and (item / "SKILL.md").is_file()
            and item.name.isidentifier()
        )
        try:
            _write_active_user_skills(user_dir, existing)
        except Exception as exc:
            print(f"[Skills] 初始化用户 Skill 激活清单失败，拒绝加载用户 Skill: {exc}")
            return None
        return existing
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        names = payload.get("active_skills")
        if not isinstance(names, list) or not all(
                isinstance(name, str) and name.isidentifier() for name in names):
            raise ValueError("active_skills must be a list of identifiers")
        return set(names)
    except Exception as exc:
        print(f"[Skills] 用户 Skill 激活清单无效，拒绝加载用户 Skill: {exc}")
        return None


def set_user_skill_active(name: str, active: bool) -> None:
    """Persist one user Skill activation decision without importing its source."""
    user_dir = _get_user_skill_dir()
    if user_dir is None:
        raise RuntimeError("No active user Skill directory is available.")
    names = _read_active_user_skills(user_dir)
    if names is None:
        raise RuntimeError("User Skill activation manifest is invalid.")
    if active:
        names.add(name)
    else:
        names.discard(name)
    _write_active_user_skills(user_dir, names)


def _record_load_diagnostic(skill_file: Path, phase: str, message: str) -> None:
    _load_diagnostics.append({
        "skill_file": str(skill_file),
        "phase": phase,
        "error_code": "skill_load_failed",
        "message": str(message),
    })


def _clear_registry() -> None:
    for skill in _registry.values():
        if isinstance(skill, SkillDescriptor) and skill.module_name:
            sys.modules.pop(skill.module_name, None)
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith(__name__ + ".") or not isinstance(module, ModuleType):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file and not Path(module_file).is_file():
            sys.modules.pop(module_name, None)
    _registry.clear()
    _registry_sources.clear()
    _conflicted_names.clear()


def _register_skill(name: str, skill: Any, source: str, path: Path) -> bool:
    candidate = {"source": source, "path": str(path)}
    previous = _registry_sources.get(name)
    if previous is not None or name in _conflicted_names:
        _registry.pop(name, None)
        _registry_sources.pop(name, None)
        _conflicted_names.add(name)
        previous_text = (
            f"{previous['source']}:{previous['path']}" if previous
            else "another rejected candidate"
        )
        _record_load_diagnostic(
            path,
            "duplicate_name",
            f"Duplicate Skill name '{name}' conflicts with {previous_text}; all candidates rejected.",
        )
        return False
    _registry[name] = skill
    _registry_sources[name] = candidate
    return True


def get_skill_diagnostics() -> List[Dict[str, str]]:
    """Return structured diagnostics from the latest Skill discovery pass."""
    _load_all()
    return [dict(item) for item in _load_diagnostics]


def _parse_skill_markdown(
    path: Path, source: str = "builtin_descriptor") -> SkillDescriptor:
    """Parse strict JSON-compatible frontmatter without executing Skill code."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with JSON frontmatter between --- markers.")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("SKILL.md frontmatter is not closed.")
    metadata = json.loads(text[4:marker])
    allowed_fields = {
        "name", "description", "category", "risk_level", "parameters", "entrypoint",
    }
    unknown = sorted(set(metadata) - allowed_fields)
    if unknown:
        raise ValueError(f"Unknown SKILL.md frontmatter fields: {', '.join(unknown)}")
    metadata_error = validate_metadata(metadata)
    if metadata_error:
        raise ValueError(metadata_error)
    skill_root = path.parent.resolve()
    if skill_root.name != metadata["name"]:
        raise ValueError("Skill name must match its directory name.")
    entrypoint = metadata.get("entrypoint")
    if entrypoint is not None and not isinstance(entrypoint, str):
        raise ValueError("SKILL.md entrypoint must be a string.")
    if entrypoint is not None and entrypoint != "scripts/main.py:run":
        raise ValueError("Skill entrypoint must be scripts/main.py:run.")
    return SkillDescriptor(
        metadata=dict(metadata),
        skill_root=skill_root,
        instructions=text[marker + 5:].strip(),
        entrypoint=entrypoint,
        source=source,
    )


def _load_descriptor_entrypoint(descriptor: SkillDescriptor):
    if descriptor.module is not None:
        return descriptor.module
    if not descriptor.entrypoint:
        return None
    relative_path, separator, function_name = descriptor.entrypoint.partition(":")
    if not separator or not function_name:
        raise ValueError("Skill entrypoint must use relative/path.py:function format.")
    entrypoint_path = (descriptor.skill_root / relative_path).resolve()
    try:
        entrypoint_path.relative_to(descriptor.skill_root)
    except ValueError:
        raise ValueError("Skill entrypoint escapes the Skill directory.")
    if entrypoint_path.is_symlink() or not entrypoint_path.is_file():
        raise ValueError("Skill entrypoint must be a regular file inside the Skill directory.")
    source_key = descriptor.source.replace("_descriptor", "")
    path_key = hashlib.sha256(str(entrypoint_path).encode("utf-8")).hexdigest()[:12]
    module_name = (
        f"houdini_skill_entrypoints.{source_key}_"
        f"{descriptor.metadata['name']}_{path_key}"
    )
    spec = importlib.util.spec_from_file_location(module_name, str(entrypoint_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run_fn = getattr(module, function_name, None)
    signature_error = validate_run_signature(descriptor.metadata, run_fn)
    if signature_error:
        raise ValueError(signature_error)
    descriptor.module = module
    descriptor.module_name = module_name
    sys.modules[module_name] = module
    return module


def _load_skill_descriptors(
    skill_dir: Path, allowed_names: Optional[set] = None,
    source: str = "builtin_descriptor"):
    if not skill_dir.is_dir():
        return
    for skill_file in sorted(skill_dir.glob("*/SKILL.md")):
        if allowed_names is not None and skill_file.parent.name not in allowed_names:
            continue
        try:
            descriptor = _parse_skill_markdown(skill_file, source=source)
            name = descriptor.metadata["name"]
            _register_skill(name, descriptor, source, skill_file)
        except Exception as exc:
            _record_load_diagnostic(skill_file, "descriptor_contract", str(exc))


def _load_skills_from_dir(skill_dir: Path, prefix: str = "", package: Optional[str] = None,
                          allowed_names: Optional[set] = None):
    """从指定目录加载 skill 模块"""
    if not skill_dir.is_dir():
        return

    for f in sorted(skill_dir.rglob("*.py")):
        if f.name.startswith("_"):
            continue
        relative_path = f.relative_to(skill_dir)
        if any(
                (skill_dir / Path(*relative_path.parts[:index]) / "SKILL.md").is_file()
                for index in range(1, len(relative_path.parts))):
            continue
        if allowed_names is not None and f.stem not in allowed_names:
            continue
        relative_module = relative_path.with_suffix("")
        module_name = ".".join(relative_module.parts)
        try:
            if package:
                qualified_name = f"{package}.{module_name}"
                cached = sys.modules.get(qualified_name)
                cached_file = getattr(cached, "__file__", None)
                if cached_file and not Path(cached_file).is_file():
                    sys.modules.pop(qualified_name, None)
                mod = importlib.import_module(qualified_name)
            else:
                spec = importlib.util.spec_from_file_location(
                    f"houdini_skills.{prefix}{module_name.replace('.', '_')}", str(f))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)

            info = getattr(mod, "SKILL_INFO", None)
            run_fn = getattr(mod, "run", None)
            expected_name = f.stem if allowed_names is not None else None
            metadata_error = validate_metadata(
                info, expected_name=expected_name, legacy=allowed_names is not None
            )
            if metadata_error:
                raise ValueError(metadata_error)
            signature_error = validate_run_signature(info, run_fn) if info.get("parameters") else None
            if signature_error:
                raise ValueError(signature_error)
            source = "user_legacy" if allowed_names is not None else "builtin_legacy"
            _register_skill(info["name"], mod, source, f)
        except Exception as e:
            _record_load_diagnostic(f, "import_or_contract", str(e))
            print(f"[Skills] 加载 {prefix}{module_name} 失败: {e}")


def _load_all():
    """扫描 skills/ 目录（内置 + 用户），加载所有 skill 模块"""
    global _registry, _loaded
    if _loaded:
        return

    # 1. 内置 skill 目录
    builtin_dir = Path(__file__).parent
    _load_skills_from_dir(builtin_dir, package=__name__)
    for category_dir in sorted(
            item for item in builtin_dir.iterdir()
            if item.is_dir() and item.name in {
                "authoring", "docs", "geometry", "graph", "learning", "materials",
                "performance", "scene", "usd", "workflow",
            }):
        _load_skill_descriptors(category_dir)

    # 2. 用户自定义 skill 目录
    user_dir = _get_user_skill_dir()
    if user_dir:
        active_names = _read_active_user_skills(user_dir)
        if active_names is not None:
            _load_skills_from_dir(user_dir, prefix="user_", allowed_names=active_names)
            _load_skill_descriptors(
                user_dir, allowed_names=active_names, source="user_descriptor"
            )
        print(f"[Skills] 用户 Skill 目录: {user_dir}")

    _loaded = True
    _prewarm_search_embedder()
    if _registry:
        print(f"[Skills] 已加载 {len(_registry)} 个 skill: {', '.join(_registry.keys())}")

    # Skill 仅通过 run_skill / list_skills 元工具暴露给 AI，不再注册为
    # 独立的 skill_xxx 工具。原因：独立工具会被 50+ 工具列表淹没，AI 几乎
    # 不会主动选用；且独立工具走 ToolRegistry 回退路径绕过了 undo group。
    # 保留 run_skill 元工具两步走（list_skills → run_skill）更可控。


def _get_search_embedder():
    global _search_embedder
    if _search_embedder is None:
        from ..utils.embedding import LocalEmbedder
        _search_embedder = LocalEmbedder(load_semantic_model=False)
    return _search_embedder


def _prewarm_search_embedder() -> None:
    # 首次 import embedding（numpy 等）约 0.7s，提前在后台完成，避免首个 list_skills(query) 等待
    def _warm():
        try:
            _get_search_embedder()
        except Exception:
            pass
    threading.Thread(target=_warm, name="skill-embedder-warmup", daemon=True).start()


def _is_skill_enabled(skill_name: str, disabled: Optional[set] = None) -> bool:
    """读取 ToolRegistry 中持久化的单 Skill 禁用状态。"""
    try:
        if disabled is None:
            from ..utils.tool_registry import get_tool_registry
            disabled = get_tool_registry().get_disabled_tools()
        return f"skill_{skill_name}" not in disabled
    except Exception:
        return True


def list_skills(category: Optional[str] = None, query: Optional[str] = None,
                limit: int = 5) -> List[Dict[str, Any]]:
    """返回所有已注册 skill 的元数据

    Args:
        category: 可选，按分类过滤（如 'geometry'/'graph'/'usd'）。为 None 时返回全部。
        query: 可选，用自然语言按名称、描述和参数说明做语义排序。
        limit: query 非空时的最大返回数。
    """
    _load_all()
    try:
        from ..utils.tool_registry import get_tool_registry
        disabled = get_tool_registry().get_disabled_tools()
    except Exception:
        disabled = set()
    result = []
    for name, mod in _registry.items():
        if not _is_skill_enabled(name, disabled):
            continue
        info = dict(getattr(mod, "SKILL_INFO", {}))
        info.setdefault("name", name)
        info.setdefault("category", "other")
        info["executable"] = not isinstance(mod, SkillDescriptor) or bool(mod.entrypoint)
        if category and info.get("category") != category:
            continue
        result.append(info)
    if not query or not query.strip() or not result:
        return sorted(result, key=lambda info: (info.get("category", "other"), info.get("name", "")))

    texts = []
    for info in result:
        parameters = info.get("parameters", {})
        parameter_text = " ".join(
            f"{name} {details.get('description', '')}"
            for name, details in parameters.items()
        )
        texts.append(
            f"{info.get('name', '')} {info.get('category', '')} "
            f"{info.get('description', '')} {parameter_text}"
        )

    ranked = []
    try:
        embedder = _get_search_embedder()
        query_vector = embedder.encode(query)
        scores = embedder.batch_cosine_similarity(
            query_vector, embedder.encode_batch(texts)
        )
        ranked = sorted(
            zip(scores, result), key=lambda item: float(item[0]), reverse=True
        )
    except Exception as exc:
        print(f"[Skills] 语义发现失败，回退关键词匹配: {exc}")

    if not ranked:
        words = {word for word in query.lower().split() if word}
        ranked = sorted(
            ((sum(word in text.lower() for word in words), info)
             for text, info in zip(texts, result)),
            key=lambda item: item[0], reverse=True,
        )
        ranked = [item for item in ranked if item[0] > 0]

    return [info for _, info in ranked[:max(1, int(limit))]]


def is_hou_free_skill(skill_name: str) -> bool:
    """docs 类 Skill 只读本地文档、不调用 hou，可在后台线程运行。"""
    _load_all()
    mod = _registry.get(skill_name)
    if mod is None:
        return False
    return getattr(mod, "SKILL_INFO", {}).get("category") == "docs"


def run_skill(skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """执行指定 skill

    Args:
        skill_name: skill 名称
        params: 传给 run() 的参数

    Returns:
        skill 返回的字典，或包含 error 的字典
    """
    _load_all()

    if not _is_skill_enabled(skill_name):
        return {"error_kind": "skill_disabled", "error": f"Skill 已禁用: {skill_name}"}

    mod = _registry.get(skill_name)
    if mod is None:
        available = ", ".join(_registry.keys()) or "(无)"
        return {
            "error_kind": "skill_not_found",
            "error": f"Skill 不存在: {skill_name}\n可用 skill: {available}",
        }

    if isinstance(mod, SkillDescriptor):
        if not mod.entrypoint:
            return {
                "name": skill_name,
                "instructions": mod.instructions,
                "instructions_only": True,
            }
        try:
            loaded_module = _load_descriptor_entrypoint(mod)
        except Exception as exc:
            return {"error_kind": "skill_load_failed", "error": f"Skill 加载失败: {exc}"}
        _, _, function_name = mod.entrypoint.partition(":")
        run_fn = getattr(loaded_module, function_name, None)
    else:
        run_fn = getattr(mod, "run", None)
    if not callable(run_fn):
        return {"error_kind": "skill_no_run", "error": f"Skill '{skill_name}' 没有 run() 函数"}

    validated_params, validation_error = validate_params(
        getattr(mod, "SKILL_INFO", {}), params
    )
    if validation_error:
        if "error_kind" not in validation_error:
            validation_error["error_kind"] = "params_invalid"
        return validation_error

    try:
        result = run_fn(**validated_params)
        if not isinstance(result, dict):
            result = {"result": str(result)}
        return result
    except Exception as e:
        return {
            "error_kind": "runtime_error",
            "error": f"Skill 执行失败: {e}\n{traceback.format_exc()[:500]}",
        }


def get_skill_instructions(skill_name: str) -> Dict[str, Any]:
    """Return one descriptor Skill's instructions without executing its entrypoint."""
    _load_all()
    skill = _registry.get(skill_name)
    if not isinstance(skill, SkillDescriptor):
        return {"error": f"Skill 没有标准 SKILL.md instructions: {skill_name}"}
    return {
        "name": skill_name,
        "instructions": skill.instructions,
        "executable": bool(skill.entrypoint),
    }


def reload_skills():
    """重新加载所有 skill（开发调试用）"""
    global _registry, _load_diagnostics, _loaded
    _clear_registry()
    _load_diagnostics.clear()
    _loaded = False
    _load_all()
