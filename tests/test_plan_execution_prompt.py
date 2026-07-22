# -*- coding: utf-8 -*-
"""Plan execution prompt behavior tests."""

import unittest

from tests.test_import_smoke import _install_qt_stubs, _install_thirdparty_stubs

_install_thirdparty_stubs()
_install_qt_stubs()

from houdini_agent.ui.i18n import _EN, _ZH


class PlanExecutionPromptTest(unittest.TestCase):
    def test_zh_prompt_prefers_whole_graph_batch_execution(self):
        prompt = _ZH['ai.plan_mode_execution_prompt']
        confirmed = _ZH['ai.plan_confirmed_msg']

        self.assertIn('这已经是执行模式，不是规划阶段', prompt)
        self.assertIn('不允许再要求用户“切换到执行模式/Agent 模式”', prompt)
        self.assertIn('规划阶段的“禁止创建/修改节点”限制在这里不适用', prompt)
        self.assertIn('整图优先执行', prompt)
        self.assertIn('优先一次性创建整张计划图', prompt)
        self.assertIn('不要把 S1/S2/S3 当作必须逐阶段 cook 通过的锁', prompt)
        self.assertIn('validation_blocked', prompt)
        self.assertIn('manual_empty_geometry_after_cook', prompt)
        self.assertIn('不能当作几何真实为空的证据', prompt)
        self.assertIn('源 SOP 全部为空', prompt)
        self.assertIn('第一步必须检查 `update_mode` / `manual_mode`', prompt)
        self.assertIn('set_update_mode(mode="auto")', prompt)
        self.assertNotIn('授权临时切 Auto', prompt)
        self.assertIn('整体验证', confirmed)
        self.assertNotIn('逐步执行：', confirmed)

    def test_en_prompt_prefers_whole_graph_batch_execution(self):
        prompt = _EN['ai.plan_mode_execution_prompt']
        confirmed = _EN['ai.plan_confirmed_msg']

        self.assertIn('This is already execution mode, not the planning phase', prompt)
        self.assertIn('must NOT ask the user to switch to execution mode / Agent mode', prompt)
        self.assertIn('The planning-phase restriction against creating/modifying nodes does not apply here', prompt)
        self.assertIn('Whole-Graph First Execution', prompt)
        self.assertIn('build the planned graph in one batch first', prompt)
        self.assertIn('Do not treat S1/S2/S3 as mandatory cook-passing locks', prompt)
        self.assertIn('validation_blocked', prompt)
        self.assertIn('manual_empty_geometry_after_cook', prompt)
        self.assertIn('must not be treated as evidence that geometry is truly empty', prompt)
        self.assertIn('all source SOPs are empty', prompt)
        self.assertIn('the first step MUST be checking `update_mode` / `manual_mode`', prompt)
        self.assertIn('set_update_mode(mode="auto")', prompt)
        self.assertNotIn('authorizes temporarily switching to Auto', prompt)
        self.assertIn('whole-network verification', confirmed)
        self.assertNotIn('step by step', confirmed)


if __name__ == "__main__":
    unittest.main()