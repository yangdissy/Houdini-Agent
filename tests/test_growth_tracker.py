# -*- coding: utf-8 -*-

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.growth_tracker import GrowthTracker, TaskMetric


class GrowthTrackerMetricsTest(unittest.TestCase):
    def _tracker(self, temp_dir: str) -> GrowthTracker:
        return GrowthTracker(store=None, file_path=Path(temp_dir) / "growth_profile.json")

    def test_growth_score_uses_reward_and_error_density_trends(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            samples = [
                TaskMetric(success=True, error_count=2, retry_count=1, tool_call_count=12, reward=0.30),
                TaskMetric(success=True, error_count=1, retry_count=1, tool_call_count=10, reward=0.40),
                TaskMetric(success=True, error_count=0, retry_count=0, tool_call_count=6, reward=0.75),
                TaskMetric(success=True, error_count=0, retry_count=0, tool_call_count=4, reward=0.85),
            ]
            for metric in samples:
                tracker.record_task(metric)

            metrics = tracker.get_growth_metrics()

            self.assertEqual(metrics["success_rate_trend"], 0.0)
            self.assertGreater(metrics["reward_trend"], 0.0)
            self.assertLess(metrics["error_density_trend"], 0.0)
            self.assertGreater(metrics["tool_efficiency_trend"], 0.0)
            self.assertGreater(metrics["growth_score"], 0.0)

    def test_empty_metrics_include_quality_fields(self):
        with TemporaryDirectory() as temp_dir:
            metrics = self._tracker(temp_dir).get_growth_metrics()

            self.assertEqual(metrics["avg_reward"], 0.0)
            self.assertEqual(metrics["reward_trend"], 0.0)
            self.assertEqual(metrics["error_density"], 0.0)
            self.assertEqual(metrics["tool_efficiency"], 1.0)


if __name__ == "__main__":
    unittest.main()