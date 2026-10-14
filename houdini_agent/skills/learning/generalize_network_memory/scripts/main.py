# -*- coding: utf-8 -*-
"""Generalize a concrete Houdini workflow memory into a reusable rule."""

import re
from typing import Any, Dict




_ABSOLUTE_NODE_PATH = re.compile(r"/(?:obj|stage|out|mat|shop|ch|img|tasks)/[^\s,;]+")
_HIP_FILE = re.compile(r"\b[^\s/\\]+\.hip(?:nc|lc)?\b", re.IGNORECASE)
_NUMBERED_NODE = re.compile(r"\b([A-Za-z_]+)\d+\b")


def generalize_memory(memory_text: str, contract: Dict[str, Any] = None) -> Dict[str, Any]:
    text = (memory_text or "").strip()
    if not text:
        return {"error": "memory_text 不能为空。"}
    generalized = _ABSOLUTE_NODE_PATH.sub("<网络节点>", text)
    generalized = _HIP_FILE.sub("<来源HIP>", generalized)
    generalized = _NUMBERED_NODE.sub(r"\1", generalized)
    generalized = re.sub(r"(?:<网络节点>)(?:\s*->\s*<网络节点>)+", "<节点链>", generalized)
    contract = contract or {}
    prerequisites = []
    required_attributes = contract.get("required_attributes", [])
    if required_attributes:
        prerequisites.append("输入应提供属性: " + ", ".join(required_attributes))
    if contract.get("boundary_inputs"):
        prerequisites.append(f"需要 {len(contract['boundary_inputs'])} 个边界输入")
    limitations = []
    if contract.get("time_dependent_nodes"):
        limitations.append("结果依赖时间或帧，静态缓存复用前需重新验证。")
    if contract.get("external_dependencies"):
        limitations.append("存在外部文件或路径依赖，迁移前必须重新绑定。")
    draft = (
        "通用 Houdini 工作流规则\n"
        f"前置条件: {'；'.join(prerequisites) or '根据目标网络确认输入类型和属性'}\n"
        f"核心流程: {generalized}\n"
        f"适用边界: {' '.join(limitations) or '节点类型、参数和输入契约一致时适用。'}\n"
        "验证方法: 检查节点错误、边界输入、关键属性与最终输出，再决定是否复用。"
    )[:2000]
    return {
        "original_length": len(text),
        "generalized_text": generalized,
        "prerequisites": prerequisites,
        "limitations": limitations,
        "memory_draft": draft,
    }


def run(memory_text: str, contract: Dict[str, Any] = None) -> Dict[str, Any]:
    return generalize_memory(memory_text, contract)