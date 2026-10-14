# -*- coding: utf-8 -*-

from houdini_agent.core.prompt_manager import (
    PromptSection,
    build_budgeted_system_prompt,
    build_system_prompt_sections,
)


def test_core_prompt_contains_only_required_sections():
    sections = build_system_prompt_sections(
        with_thinking=False,
        full_rules=False,
        language='en',
    )

    assert [section.section_id for section in sections] == [
        'persona',
        'guidance_core',
    ]
    assert all(section.required for section in sections)


def test_full_prompt_adds_extended_guidance_once(monkeypatch):
    monkeypatch.setattr(
        'houdini_agent.core.prompt_manager.load_prompt_template',
        lambda name: {
            'system_prompt_rules_core.txt': 'CORE',
            'system_prompt_rules_extra.txt': 'EXTRA',
            'system_prompt_thinking_block.txt': 'THINK {lang_rule}',
        }.get(name, ''),
    )

    sections = build_system_prompt_sections(
        with_thinking=True,
        full_rules=True,
        language='en',
    )
    section_ids = [section.section_id for section in sections]

    assert section_ids[:3] == ['persona', 'guidance_core', 'guidance_extended']
    assert len(section_ids) == len(set(section_ids))
    assert sections[2].required is False


def test_budget_keeps_required_sections_whole_and_omits_optional(monkeypatch):
    sections = [
        PromptSection('persona', 'PERSONA'),
        PromptSection('guidance_core', 'CORE-RULE-MUST-STAY-WHOLE'),
        PromptSection('guidance_extended', 'OPTIONAL', required=False),
    ]
    monkeypatch.setattr(
        'houdini_agent.core.prompt_manager.build_system_prompt_sections',
        lambda *args, **kwargs: sections,
    )

    result = build_budgeted_system_prompt(max_length=10)

    assert result.prompt == 'PERSONACORE-RULE-MUST-STAY-WHOLE'
    assert result.kept_section_ids == ['persona', 'guidance_core']
    assert result.omitted_section_ids == ['guidance_extended']