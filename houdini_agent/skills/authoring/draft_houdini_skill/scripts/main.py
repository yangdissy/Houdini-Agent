# -*- coding: utf-8 -*-
"""Generate a reviewable Houdini-Agent Skill draft without writing files."""

import json

from houdini_agent.skills._contract import (
    VALID_CATEGORIES, VALID_RISK_LEVELS, normalize_parameter_definitions, valid_name,
)




def _error(message):
    return {"error": message, "written": False, "executed": False}


def _validate_parameters(parameters):
    return normalize_parameter_definitions(parameters)


def _python_literal(value):
    return repr(value)


def _render_skill(name, intent, category, parameters, risk_level, requires_hou, modifies_scene):
    metadata_parameters = {}
    signature_parts = []
    for item in parameters:
        definition = {
            "type": item["type"],
            "description": item["description"],
            "required": item["required"],
        }
        if "default" in item:
            definition["default"] = item["default"]
        for constraint in ("enum", "minimum", "maximum"):
            if constraint in item:
                definition[constraint] = item[constraint]
        metadata_parameters[item["name"]] = definition
        if item["required"] and "default" not in item:
            signature_parts.append(item["name"])
        else:
            signature_parts.append(f"{item['name']}={_python_literal(item.get('default'))}")

    metadata = {
        "name": name,
        "category": category,
        "description": intent,
        "risk_level": risk_level,
        "parameters": metadata_parameters,
        "entrypoint": "scripts/main.py:run",
    }
    lines = [
        "# -*- coding: utf-8 -*-",
        f'"""{intent}"""',
        "",
        f"def run({', '.join(signature_parts)}):",
        f'    """{intent}"""',
    ]
    if requires_hou:
        lines.extend(["    import hou  # type: ignore", ""])
    lines.extend([
        "    # TODO: Replace this draft result with the verified implementation.",
        "    return {",
        f'        "skill": "{name}",',
        '        "status": "draft",',
        '        "error": "Implementation required before this Skill can be installed.",',
        "    }",
    ])
    if modifies_scene:
        lines.extend([
            "",
            "# Scene mutation must use the existing confirmation, main-thread, Undo, and audit chain.",
        ])
    skill_markdown = (
        "---\n"
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        + f"\n---\n# {name.replace('_', ' ').title()}\n\n{intent}\n"
    )
    return skill_markdown, "\n".join(lines) + "\n"


def _render_test(category, name, parameters):
    call_arguments = []
    for item in parameters:
        if "default" in item or not item["required"]:
            continue
        example_value = {
            "string": "example",
            "integer": 1,
            "number": 1.0,
            "boolean": True,
            "array": [],
            "object": {},
        }[item["type"]]
        call_arguments.append(f"{item['name']}={_python_literal(example_value)}")
    return (
        "from pathlib import Path\n\n"
        "from houdini_agent import skills\n\n\n"
        "_DESCRIPTOR = skills._parse_skill_markdown(\n"
        f"    Path(__file__).resolve().parents[1] / \"houdini_agent\" / \"skills\" / \"{category}\" / \"{name}\" / \"SKILL.md\"\n"
        ")\n"
        "run = skills._load_descriptor_entrypoint(_DESCRIPTOR).run\n\n\n"
        f"def test_{name}_returns_structured_result():\n"
        f"    result = run({', '.join(call_arguments)})\n\n"
        "    assert isinstance(result, dict)\n"
        "    assert result.get(\"status\") != \"draft\"\n"
    )


def _similar_skills(intent, category, limit=5):
    try:
        from houdini_agent import skills
        candidates = skills.list_skills(category=category, query=intent, limit=limit)
    except Exception:
        return []
    return [
        {"name": item.get("name", ""), "description": item.get("description", "")}
        for item in candidates
    ]


def _question(question_id, question, recommendation, reason, answers):
    return {
        "status": "question",
        "question_id": question_id,
        "question": question,
        "recommendation": recommendation,
        "reason": reason,
        "instruction": "一次只向用户提出这一题，收到回答后将其写入 answers 并再次调用。",
        "next_params": {"answers": dict(answers)},
        "written": False,
        "executed": False,
    }


def _derive_design(answers):
    intent = str(answers["purpose"]).strip()
    name = str(answers.get("name") or "custom_houdini_skill").strip()
    category = str(answers.get("category") or "workflow").strip().lower()
    parameters = answers.get("parameters")
    if parameters is None:
        parameters = [{
            "name": "request",
            "type": "string",
            "description": "The concrete Houdini task or target described by the caller.",
            "required": True,
        }]
    modifies_scene = bool(answers.get("modifies_scene", False))
    requires_hou = bool(answers.get("requires_hou", True))
    risk_level = str(answers.get("risk_level") or ("normal" if modifies_scene else "low"))
    return {
        "name": name,
        "intent": intent,
        "category": category,
        "parameters": parameters,
        "requires_hou": requires_hou,
        "modifies_scene": modifies_scene,
        "risk_level": risk_level,
        "examples": answers["examples"],
        "audience_and_context": answers["audience_and_context"],
        "expected_result": answers["expected_result"],
        "boundaries": answers["boundaries"],
    }


def _interview(name, intent, category, parameters, examples, requires_hou,
               modifies_scene, risk_level, answers, confirmed):
    answers = dict(answers or {})
    supplied = {
        "name": name,
        "intent": intent,
        "category": category,
        "parameters": parameters,
        "examples": examples,
        "requires_hou": requires_hou,
        "modifies_scene": modifies_scene,
        "risk_level": risk_level,
    }
    for key, value in supplied.items():
        if value is not None:
            answers[key] = value

    if intent is not None:
        answers["purpose"] = intent
    questions = (
        ("purpose", "你希望这个 Skill 主要是干什么的？它要帮组员完成哪件事？",
         "用日常工作语言描述能力，例如“检查模型 UV 问题并告诉我哪里需要修”，不用考虑函数名或参数。",
         "先理解用途，技术形式由 Skill 根据代码库约定推导。"),
        ("audience_and_context", "谁会在什么工作场景下使用它？",
         "说明使用者、工作阶段和触发时机，例如“模型组交付前检查当前选中的 SOP”。",
         "使用场景决定它应该读取什么上下文，以及是否值得做成可复用 Skill。"),
        ("expected_result", "使用后，组员最希望得到什么结果？",
         "描述用户能看到或继续使用的结果，例如问题清单、修复建议、节点蓝图或已完成的场景修改。",
         "输出形态比内部实现方式更能定义成功标准。"),
        ("boundaries", "这个 Skill 有哪些事情不应该做，或者遇到什么情况必须停下来？",
         "优先写清不能误改的内容、需要人工确认的动作，以及输入不存在时如何处理。",
         "边界用于避免 Skill 为了完成任务而扩大权限或静默修改数据。"),
        ("examples", "请给一个组员真实会说的请求，再给一个容易出错的例子。",
         "例如“检查 /obj/geo1/OUT 的 UV”以及“节点不存在或没有 UV 时要明确提示”。",
         "真实表达会用于评估 Skill 是否真的解决组员的问题。"),
    )
    for question_id, question, recommendation, reason in questions:
        if question_id not in answers:
            return _question(question_id, question, recommendation, reason, answers), None

    summary = _derive_design(answers)
    if not confirmed:
        result = _question(
            "confirmed",
            "我根据用途整理了下面的 Skill 设计，是否准确，可以生成可评审草稿了吗？",
            "重点确认它解决的工作问题、产出和禁止事项；技术名称、分类和参数可在摘要中修正。",
            "确认前不生成实现草稿，避免把未决设计固化成代码。",
            answers,
        )
        result["design_summary"] = summary
        return result, None
    return None, summary


def run(name=None, intent=None, category=None, parameters=None, examples=None, requires_hou=None,
        modifies_scene=None, risk_level=None, answers=None, confirmed=False):
    """Return a reviewable Skill draft without writing or executing it."""
    direct_draft = name is not None and intent is not None and category is not None and answers is None
    if not direct_draft:
        question, design = _interview(
            name, intent, category, parameters, examples, requires_hou,
            modifies_scene, risk_level, answers, confirmed,
        )
        if question:
            return question
        name = design["name"]
        intent = design["intent"]
        category = design["category"]
        parameters = design["parameters"]
        examples = design["examples"]
        requires_hou = design["requires_hou"]
        modifies_scene = design["modifies_scene"]
        risk_level = design["risk_level"]

    name = str(name or "").strip()
    intent = str(intent or "").strip()
    category = str(category or "").strip().lower()
    risk_level = str(risk_level or "low").strip().lower()
    if not valid_name(name):
        return _error("'name' must be a lowercase snake_case Python identifier.")
    if not intent:
        return _error("'intent' is required.")
    if category not in VALID_CATEGORIES:
        return _error(f"Unknown category '{category}'. Use one of: {', '.join(sorted(VALID_CATEGORIES))}")
    if risk_level not in VALID_RISK_LEVELS:
        return _error("'risk_level' must be low, normal, or high.")
    normalized_parameters, parameter_error = _validate_parameters(parameters)
    if parameter_error:
        return _error(parameter_error)
    if modifies_scene and risk_level == "low":
        return _error("A scene-mutating Skill cannot be drafted with risk_level='low'.")

    module_path = f"houdini_agent/skills/{category}/{name}/scripts/main.py"
    test_path = f"tests/test_{name}.py"
    review_checks = [
        "Confirm no existing Skill already owns this behavior.",
        "Replace the draft body with a deterministic implementation that returns a dict.",
        "Add behavior assertions before installation; the generated smoke test must initially fail.",
        "Run Skill metadata, loader, and focused behavior tests.",
    ]
    if requires_hou:
        review_checks.append("Verify all hou access runs through the Houdini runtime and main-thread boundary.")
    if modifies_scene:
        review_checks.append("Route mutation through confirmation, Undo, audit, and cache invalidation infrastructure.")
    if category == "workflow":
        review_checks.append("Return a blueprint only; execute it through create_nodes_batch with dry_run=True first.")

    evals = [
        {"id": index + 1, "prompt": str(prompt), "expected_output": intent}
        for index, prompt in enumerate((examples or [])[:3]) if str(prompt).strip()
    ]
    skill_markdown, skill_source = _render_skill(
        name, intent, category, normalized_parameters, risk_level,
        bool(requires_hou), bool(modifies_scene),
    )
    skill_root = f"houdini_agent/skills/{category}/{name}"
    return {
        "status": "ready",
        "name": name,
        "category": category,
        "module_path": module_path,
        "test_path": test_path,
        "skill_source": skill_source,
        "skill_files": {
            "SKILL.md": skill_markdown,
            "scripts/main.py": skill_source,
        },
        "skill_root": skill_root,
        "test_source": _render_test(category, name, normalized_parameters),
        "similar_skills": _similar_skills(intent, category),
        "evaluation_cases": evals,
        "compatibility": {
            "requires_hou": bool(requires_hou),
            "modifies_scene": bool(modifies_scene),
            "risk_level": risk_level,
            "loader_contract": "SKILL.md + scripts/main.py:run -> dict",
        },
        "review_checks": review_checks,
        "written": False,
        "executed": False,
    }