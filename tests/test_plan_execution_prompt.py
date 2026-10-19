# -*- coding: utf-8 -*-
"""Plan execution prompt behavior tests."""

import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs

_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.i18n import _EN, _ZH
from houdini_agent.core.send_orchestrator_mixin import _confirmed_plan_tools
from houdini_agent.core.prompt_manager import build_budgeted_system_prompt


class PlanExecutionPromptTest(unittest.TestCase):
    def test_required_prompt_routes_guides_on_demand_without_embedding_guide_text(self):
        result = build_budgeted_system_prompt(full_rules=True, max_length=1800)

        self.assertIn("run_skill('get_workflow_guide'", result.prompt)
        self.assertIn('unfamiliar multi-node setup', result.prompt)
        self.assertNotIn('# Pyro workflow', result.prompt)
        self.assertNotIn('# Solaris and USD scene assembly workflow', result.prompt)

    def test_planning_prompts_route_complex_work_through_readonly_skills(self):
        zh_prompt = _ZH['ai.plan_mode_planning_prompt']
        en_prompt = _EN['ai.plan_mode_planning_prompt']

        self.assertIn('list_skills(query=<用户的完整请求>, limit=3)', zh_prompt)
        self.assertIn('`executable=false` 的 low-risk workflow Skill', zh_prompt)
        self.assertIn('调用 `run_skill` 读取方法说明', zh_prompt)
        self.assertIn('留到确认后的执行阶段', zh_prompt)
        self.assertIn('简单单节点、单参数任务不需要 Skill discovery', zh_prompt)

        self.assertIn("list_skills(query=<the user's complete request>, limit=3)", en_prompt)
        self.assertIn('`executable=false` low-risk workflow Skill', en_prompt)
        self.assertIn('call `run_skill` to read its method instructions', en_prompt)
        self.assertIn('confirmed execution phase', en_prompt)
        self.assertIn('Skip Skill discovery for simple single-node or single-parameter tasks', en_prompt)

    def test_confirmed_plan_tools_update_progress_without_asking_again(self):
        tools = _confirmed_plan_tools([])
        names = {tool['function']['name'] for tool in tools}

        self.assertIn('update_plan_step', names)
        self.assertNotIn('ask_question', names)

    def test_zh_prompt_prefers_whole_graph_batch_execution(self):
        prompt = _ZH['ai.plan_mode_execution_prompt']
        confirmed = _ZH['ai.plan_confirmed_msg']

        self.assertIn('这已经是执行模式，不是规划阶段', prompt)
        self.assertIn('不允许再要求用户“切换到执行模式/Agent 模式”', prompt)
        self.assertIn('规划阶段的“禁止创建/修改节点”限制在这里不适用', prompt)
        self.assertIn('禁止再通过 `ask_question`、CONFIRM_BATCH 或文字询问进行二次确认', prompt)
        self.assertIn('高风险工具由系统在实际调用时单独弹出确认', prompt)
        self.assertIn('整图优先执行', prompt)
        self.assertIn('优先一次性创建整张计划图', prompt)
        self.assertIn('不要把 S1/S2/S3 当作必须逐阶段 cook 通过的锁', prompt)
        self.assertIn('validation_blocked', prompt)
        self.assertIn('manual_empty_geometry_after_cook', prompt)
        self.assertIn('不能当作几何真实为空的证据', prompt)
        self.assertIn('源 SOP 全部为空', prompt)
        self.assertIn('第一步必须检查 `update_mode` / `manual_mode`', prompt)
        self.assertIn('temporary_auto_validate_geometry', prompt)
        self.assertNotIn('授权临时切 Auto', prompt)
        self.assertIn('整体验证', confirmed)
        self.assertNotIn('逐步执行：', confirmed)

    def test_en_prompt_prefers_whole_graph_batch_execution(self):
        prompt = _EN['ai.plan_mode_execution_prompt']
        confirmed = _EN['ai.plan_confirmed_msg']

        self.assertIn('This is already execution mode, not the planning phase', prompt)
        self.assertIn('must NOT ask the user to switch to execution mode / Agent mode', prompt)
        self.assertIn('The planning-phase restriction against creating/modifying nodes does not apply here', prompt)
        self.assertIn('Do not request a second confirmation through `ask_question`, CONFIRM_BATCH, or prose', prompt)
        self.assertIn('separately confirm a high-risk tool when it is actually called', prompt)
        self.assertIn('Whole-Graph First Execution', prompt)
        self.assertIn('build the planned graph in one batch first', prompt)
        self.assertIn('Do not treat S1/S2/S3 as mandatory cook-passing locks', prompt)
        self.assertIn('validation_blocked', prompt)
        self.assertIn('manual_empty_geometry_after_cook', prompt)
        self.assertIn('must not be treated as evidence that geometry is truly empty', prompt)
        self.assertIn('all source SOPs are empty', prompt)
        self.assertIn('the first step MUST be checking `update_mode` / `manual_mode`', prompt)
        self.assertIn('temporary_auto_validate_geometry', prompt)
        self.assertNotIn('authorizes temporarily switching to Auto', prompt)
        self.assertIn('whole-network verification', confirmed)
        self.assertNotIn('step by step', confirmed)


if __name__ == "__main__":
    unittest.main()