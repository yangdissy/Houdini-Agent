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


def test_full_prompt_delegates_execute_python_confirmation_to_harness():
    sections = build_system_prompt_sections(
        with_thinking=False,
        full_rules=True,
        language='en',
    )
    prompt = ''.join(section.content for section in sections)

    assert 'execute_python requires user confirmation' not in prompt
    assert 'do not ask the user for a separate prose confirmation' in prompt
    assert 'confirmation mode and Harness policy' in prompt


def test_core_prompt_requires_governed_python_for_missing_scene_capabilities():
    sections = build_system_prompt_sections(
        with_thinking=False,
        full_rules=False,
        language='en',
    )
    prompt = ''.join(section.content for section in sections)

    assert 'Use upsert_spare_parameter' in prompt
    assert 'call execute_python directly as the governed fallback' in prompt
    assert 'not supported by upsert_spare_parameter' in prompt
    assert 'is not bypassing governance' in prompt


def test_core_prompt_requires_result_verification_at_task_completion():
    sections = build_system_prompt_sections(
        with_thinking=False,
        full_rules=False,
        language='en',
    )
    prompt = ''.join(section.content for section in sections)

    assert 'Task Completion Verification (MUST follow)' in prompt
    assert 'final Plan step' in prompt
    assert 'about to claim the task is complete' in prompt
    assert 'run_skill(skill_name="verify_agent_result"' in prompt
    assert 'temporary_auto_validate_geometry' in prompt
    assert 'restores the exact original mode' in prompt
    assert 'current mode is Auto and freshness is established, do not call it' in prompt
    assert 'not a node-creation hook' in prompt


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