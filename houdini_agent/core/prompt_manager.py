# -*- coding: utf-8 -*-
"""System prompt template loading and assembly."""

from pathlib import Path
from dataclasses import dataclass
from typing import List

from houdini_agent.utils.ultra_optimizer import UltraOptimizer

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_TEMPLATE_CACHE: dict = {}

_CORE_RULES_FALLBACK = """
Node Path Output Rules: In user-facing replies, prefer relative or short node references (e.g. box1, geo1/box1, or ../geo1/box1) when the current network is clear. Use full /obj/... paths only when needed to avoid ambiguity, preserve clickable navigation, or quote actual tool output.

Fake Tool Call Prevention (highest priority): NEVER write "[ok] tool:" or "[Tool Result]" in replies. Call tools via function calling only.

Tool Call Parameter Rules: Verify all required parameters before calling. Tool node_path parameters must use full Houdini paths, because tools need exact lookup paths. Fix parameter errors and retry - don't call check_errors for tool failures.

Safe Operation: Before setting parameters, call get_node_parameters. No duplicate queries per round. After creating a node, use the returned path.

Node Creation Failure: If create_node fails, call search_node_types to find the correct type name and retry.

Wrangle Run Over: addpoint()/addprim() code MUST use Detail mode (class=0), not Points - would create duplicates per input point.

VEX Writing: New wrangle -> create_wrangle_node; existing wrangle -> set_node_parameter(parm_name="snippet"). Never use execute_python for VEX. After writing, call check_errors.

Mandatory Verification: Call verify_network(parent_path) before completing any task. Fix issues and repeat until healthy with non-zero geometry evidence.

Todo: Use add_todo for complex tasks. Call update_todo immediately after each step completes.
"""


@dataclass(frozen=True)
class PromptSection:
    """A stable, independently budgetable system-prompt section."""

    section_id: str
    content: str
    required: bool = True


@dataclass(frozen=True)
class PromptBudgetResult:
    """Rendered prompt plus the section IDs kept or omitted by budgeting."""

    prompt: str
    kept_section_ids: List[str]
    omitted_section_ids: List[str]


def load_prompt_template(name: str) -> str:
    """Load a prompt template from houdini_agent/prompts and cache it."""
    if name not in _PROMPT_TEMPLATE_CACHE:
        try:
            _PROMPT_TEMPLATE_CACHE[name] = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"[Prompts] 模板文件缺失: {name}")
            _PROMPT_TEMPLATE_CACHE[name] = ""
    return _PROMPT_TEMPLATE_CACHE[name]


def build_system_prompt_sections(
    with_thinking: bool = True,
    full_rules: bool = True,
    language: str = None,
) -> List[PromptSection]:
    """Build ordered system-prompt sections without flattening their ownership."""
    if language is None:
        from houdini_agent.ui.i18n import get_language

        language = get_language()
    if language == "en":
        lang_rule = "CRITICAL: You MUST reply in English for ALL user-facing text. No exceptions. Even if the user writes in another language, your reply MUST be in English."
    else:
        lang_rule = "CRITICAL: You MUST reply in the SAME language the user uses. If the user writes in Chinese, reply in Chinese. If in English, reply in English. Match the user's language exactly."

    persona = (
        "You are a Houdini assistant, expert at solving problems with nodes and VEX.\n"
        f"{lang_rule}\n"
        "Never use emoji or icon symbols in replies unless the user explicitly requests them. Use plain text only.\n"
    )
    if with_thinking:
        persona += load_prompt_template("system_prompt_thinking_block.txt").format(lang_rule=lang_rule)
    else:
        persona += "\nOutput format: Concise, direct, action-oriented. MUST reply in the same language the user uses.\n"

    sections = [PromptSection('persona', persona)]

    rules_text = load_prompt_template("system_prompt_rules_core.txt")
    if not rules_text:
        rules_text = _CORE_RULES_FALLBACK
    sections.append(PromptSection('guidance_core', rules_text))

    if full_rules:
        extra_text = load_prompt_template("system_prompt_rules_extra.txt")
        if extra_text:
            sections.append(PromptSection('guidance_extended', extra_text, required=False))
        try:
            from houdini_agent.utils.doc_rag import get_doc_index

            labs_catalog = get_doc_index().get_labs_catalog()
            if labs_catalog:
                sections.append(PromptSection(
                    'labs_catalog',
                    load_prompt_template("system_prompt_labs_section.txt").format(
                        labs_catalog=labs_catalog
                    ),
                    required=False,
                ))
        except Exception:
            pass

    return sections


def build_system_prompt(with_thinking: bool = True, full_rules: bool = True) -> str:
    """Build the Houdini assistant system prompt from ordered sections."""
    sections = build_system_prompt_sections(with_thinking, full_rules)
    return UltraOptimizer.compress_system_prompt(''.join(section.content for section in sections))


def build_budgeted_system_prompt(
    with_thinking: bool = True,
    full_rules: bool = True,
    max_length: int = 1800,
) -> PromptBudgetResult:
    """Keep required sections whole and omit optional sections that exceed the budget."""
    sections = build_system_prompt_sections(with_thinking, full_rules)
    kept = []
    omitted = []
    length = 0
    for section in sections:
        if section.required or length + len(section.content) <= max_length:
            kept.append(section)
            length += len(section.content)
        else:
            omitted.append(section.section_id)
    return PromptBudgetResult(
        prompt=UltraOptimizer.compress_system_prompt(
            ''.join(section.content for section in kept)
        ),
        kept_section_ids=[section.section_id for section in kept],
        omitted_section_ids=omitted,
    )