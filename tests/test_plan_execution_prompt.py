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

        self.assertIn('整图优先执行', prompt)
        self.assertIn('优先一次性创建整张计划图', prompt)
        self.assertIn('不要把 S1/S2/S3 当作必须逐阶段 cook 通过的锁', prompt)
        self.assertIn('整体验证', confirmed)
        self.assertNotIn('逐步执行：', confirmed)

    def test_en_prompt_prefers_whole_graph_batch_execution(self):
        prompt = _EN['ai.plan_mode_execution_prompt']
        confirmed = _EN['ai.plan_confirmed_msg']

        self.assertIn('Whole-Graph First Execution', prompt)
        self.assertIn('build the planned graph in one batch first', prompt)
        self.assertIn('Do not treat S1/S2/S3 as mandatory cook-passing locks', prompt)
        self.assertIn('whole-network verification', confirmed)
        self.assertNotIn('step by step', confirmed)


if __name__ == "__main__":
    unittest.main()