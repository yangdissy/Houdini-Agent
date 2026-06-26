# -*- coding: utf-8 -*-
"""System prompt template loading and assembly."""

from pathlib import Path

from houdini_agent.ui.i18n import get_language
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

Mandatory Verification: Call verify_and_summarize before completing any task. Fix issues and repeat until passed.

Todo: Use add_todo for complex tasks. Call update_todo immediately after each step completes.
"""


def load_prompt_template(name: str) -> str:
    """Load a prompt template from houdini_agent/prompts and cache it."""
    if name not in _PROMPT_TEMPLATE_CACHE:
        try:
            _PROMPT_TEMPLATE_CACHE[name] = (_PROMPTS_DIR / name).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"[Prompts] 模板文件缺失: {name}")
            _PROMPT_TEMPLATE_CACHE[name] = ""
    return _PROMPT_TEMPLATE_CACHE[name]


def build_system_prompt(with_thinking: bool = True, full_rules: bool = True) -> str:
    """Build the Houdini assistant system prompt from template files."""
    if get_language() == "en":
        lang_rule = "CRITICAL: You MUST reply in English for ALL user-facing text. No exceptions. Even if the user writes in another language, your reply MUST be in English."
    else:
        lang_rule = "CRITICAL: You MUST reply in the SAME language the user uses. If the user writes in Chinese, reply in Chinese. If in English, reply in English. Match the user's language exactly."

    base_prompt = (
        "You are a Houdini assistant, expert at solving problems with nodes and VEX.\n"
        f"{lang_rule}\n"
        "Never use emoji or icon symbols in replies unless the user explicitly requests them. Use plain text only.\n"
    )
    if with_thinking:
        base_prompt += load_prompt_template("system_prompt_thinking_block.txt").format(lang_rule=lang_rule)
    else:
        base_prompt += "\nOutput format: Concise, direct, action-oriented. MUST reply in the same language the user uses.\n"

    rules_file = "system_prompt_rules.txt" if full_rules else "system_prompt_rules_core.txt"
    rules_text = load_prompt_template(rules_file)
    if not rules_text and not full_rules:
        rules_text = _CORE_RULES_FALLBACK
    base_prompt += rules_text

    if full_rules:
        try:
            from houdini_agent.utils.doc_rag import get_doc_index

            labs_catalog = get_doc_index().get_labs_catalog()
            if labs_catalog:
                base_prompt += load_prompt_template("system_prompt_labs_section.txt").format(labs_catalog=labs_catalog)
        except Exception:
            pass

    return UltraOptimizer.compress_system_prompt(base_prompt)