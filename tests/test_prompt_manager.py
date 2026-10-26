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
    assert 'reuse a successful verify_network result' in prompt
    assert 'call verify_network once' in prompt
    assert 'call visual_review exactly once' in prompt
    assert 'Do not call run_skill("verify_agent_result")' in prompt
    assert 'run_skill(skill_name="verify_agent_result"' not in prompt
    assert 'temporary_auto_validate_geometry' in prompt
    assert 'restoration of the exact original mode' in prompt
    assert 'Manual mode or stale/unknown freshness' in prompt
    assert 'not a node-creation hook' in prompt


def test_core_and_fallback_use_request_scoped_verification(monkeypatch):
    for fallback in (False, True):
        with monkeypatch.context() as patches:
            if fallback:
                patches.setattr(
                    'houdini_agent.core.prompt_manager.load_prompt_template',
                    lambda name: '',
                )
            sections = build_system_prompt_sections(
                with_thinking=False, full_rules=False, language='en',
            )
            prompt = ''.join(section.content for section in sections)

        assert 'Verification Scope (MUST follow)' in prompt
        assert 'health=unknown' in prompt
        assert 'target and frame' in prompt
        assert 'missing caches only need annotation' in prompt
        assert 'do not cook geometry merely to validate these edits' in prompt
        assert 'Handoff / Organization (MUST follow)' in prompt
        assert 'unless explicitly authorized by the user or confirmed plan' in prompt
        assert 'display/render flags, object visibility, current frame, and update mode' in prompt
        assert 'An output Null does not authorize moving existing flags' in prompt
        assert 'node category and supported HOM methods' in prompt
        assert 'Call verify_network(parent_path) before completing any task' not in prompt
        assert 'Fix issues and repeat until healthy' not in prompt


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