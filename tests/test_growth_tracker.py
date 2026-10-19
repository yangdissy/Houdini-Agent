# -*- coding: utf-8 -*-

import math
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from houdini_agent.utils.growth_tracker import GrowthTracker, TaskMetric
from houdini_agent.utils.reward_engine import TAG_USER_PRAISED, TAG_USER_REJECTED


class GrowthTrackerMetricsTest(unittest.TestCase):
    def _tracker(self, temp_dir: str) -> GrowthTracker:
        return GrowthTracker(store=None, file_path=Path(temp_dir) / "growth_profile.json")

    def test_growth_score_uses_reward_and_error_density_trends(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            samples = (
                [TaskMetric(success=True, error_count=2, retry_count=1,
                            tool_call_count=12, reward=0.30) for _ in range(30)]
                + [TaskMetric(success=True, error_count=0, retry_count=0,
                              tool_call_count=11, reward=0.85) for _ in range(30)]
            )
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

    def test_trend_compares_latest_30_with_preceding_30(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tracker.record_task(TaskMetric(reward=0.0))
            for _ in range(30):
                tracker.record_task(TaskMetric(reward=0.2))
            for _ in range(30):
                tracker.record_task(TaskMetric(reward=0.8))

            metrics = tracker.get_growth_metrics()

            self.assertEqual(metrics["recent_sample_count"], 30)
            self.assertEqual(metrics["baseline_sample_count"], 30)
            self.assertTrue(metrics["trend_reliable"])
            self.assertEqual(metrics["avg_reward"], 0.8)
            self.assertEqual(metrics["reward_trend"], 0.6)

    def test_no_tool_tasks_do_not_inflate_tool_efficiency(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tool_task = TaskMetric(tool_call_count=10)
            tracker.record_task(tool_task)
            tracker.record_task(TaskMetric(tool_call_count=0))

            metrics = tracker.get_growth_metrics()

            expected = round(tracker._tool_efficiency_score(tool_task), 3)
            self.assertEqual(metrics["tool_efficiency"], expected)
            self.assertEqual(metrics["tool_efficiency_sample_count"], 1)

    def test_tool_efficiency_trend_compares_matching_complexity_buckets(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            for _ in range(30):
                tracker.record_task(TaskMetric(tool_call_count=20))
            for _ in range(30):
                tracker.record_task(TaskMetric(tool_call_count=2))

            metrics = tracker.get_growth_metrics()

            self.assertEqual(metrics["tool_efficiency_trend"], 0.0)
            self.assertEqual(metrics["tool_efficiency_bucket_counts"], {
                "simple_tool": 30,
                "complex_tool": 0,
            })

    def test_growth_score_stays_neutral_until_trend_is_reliable(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tracker.record_task(TaskMetric(success=False, error_count=2, reward=0.1))
            tracker.record_task(TaskMetric(success=True, error_count=0, reward=0.9))

            metrics = tracker.get_growth_metrics()

            self.assertFalse(metrics["trend_reliable"])
            self.assertEqual(metrics["growth_score"], 0.0)

    def test_error_metrics_distinguish_recovered_and_unresolved_tasks(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tracker.record_task(TaskMetric(success=True, error_count=1))
            tracker.record_task(TaskMetric(success=False, error_count=1))
            tracker.record_task(TaskMetric(success=True, error_count=0))

            metrics = tracker.get_growth_metrics()

            self.assertEqual(metrics["incident_rate"], 0.667)
            self.assertEqual(metrics["recovered_error_rate"], 0.333)
            self.assertEqual(metrics["unresolved_failure_rate"], 0.333)

    def test_record_task_normalizes_counts_reward_and_tags(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            metric = TaskMetric(
                error_count=-2,
                retry_count=-1,
                tool_call_count=-4,
                reward=1.5,
                tags=["vex_related", "vex_related"],
            )

            tracker.record_task(metric)

            self.assertEqual(metric.error_count, 0)
            self.assertEqual(metric.retry_count, 0)
            self.assertEqual(metric.tool_call_count, 0)
            self.assertEqual(metric.reward, 1.0)
            self.assertEqual(metric.tags, ["vex_related"])

    def test_record_task_rejects_non_finite_reward(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)

            with self.assertRaises(ValueError):
                tracker.record_task(TaskMetric(reward=math.nan))

            self.assertEqual(tracker.get_growth_metrics()["total_tasks"], 0)

    def test_user_feedback_updates_matching_task_metric(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tracker.record_task(TaskMetric(episodic_id="ep-1", reward=0.5))

            praised = tracker.apply_user_feedback("ep-1", positive=True)
            rejected = tracker.apply_user_feedback("ep-1", positive=False)

            self.assertEqual(praised["reward"], 0.85)
            self.assertEqual(rejected["reward"], 0.15)
            metric = list(tracker._metrics)[0]
            self.assertEqual(metric.reward, 0.15)
            self.assertNotIn(TAG_USER_PRAISED, metric.tags)
            self.assertEqual(metric.tags.count(TAG_USER_REJECTED), 1)

    def test_user_feedback_for_unknown_task_has_no_side_effect(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            tracker.record_task(TaskMetric(episodic_id="ep-1", reward=0.5))

            result = tracker.apply_user_feedback("missing", positive=True)

            self.assertIn("error", result)
            metric = list(tracker._metrics)[0]
            self.assertEqual(metric.reward, 0.5)
            self.assertEqual(metric.tags, [])

    def test_low_evidence_personality_is_not_injected(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)

            description = tracker.get_personality_description()

            self.assertIn("尚无足够证据", description)
            self.assertNotIn("中等风险容忍度", description)

    def test_user_rejection_can_reduce_learned_proactivity(self):
        with TemporaryDirectory() as temp_dir:
            tracker = self._tracker(temp_dir)
            for index in range(8):
                tracker.record_task(TaskMetric(
                    episodic_id=f"ep-{index}",
                    success=True,
                    tool_call_count=12,
                    tags=["complex_task"],
                ))
            learned = tracker.personality.proactivity

            tracker.apply_user_feedback("ep-7", positive=False)

            self.assertGreater(learned, 0.5)
            self.assertLess(tracker.personality.proactivity, learned)

    def test_old_personality_profile_loads_without_evidence(self):
        with TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "growth_profile.json"
            profile_path.write_text(json.dumps({
                "personality": {
                    "efficiency_bias": 0.4,
                    "risk_tolerance": 0.6,
                    "verbosity": 0.5,
                    "proactivity": 0.7,
                }
            }), encoding="utf-8")

            tracker = GrowthTracker(store=None, file_path=profile_path)

            self.assertEqual(tracker.personality.proactivity, 0.7)
            self.assertIn("尚无足够证据", tracker.get_personality_description())

    def test_feedback_and_personality_evidence_survive_reload(self):
        with TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "growth_profile.json"
            tracker = GrowthTracker(store=None, file_path=profile_path)
            tracker.record_task(TaskMetric(
                episodic_id="ep-1",
                success=True,
                tool_call_count=12,
                tags=["complex_task"],
            ))
            tracker.apply_user_feedback("ep-1", positive=True)

            loaded = GrowthTracker(store=None, file_path=profile_path)

            metric = list(loaded._metrics)[0]
            self.assertEqual(metric.episodic_id, "ep-1")
            self.assertEqual(metric.reward, 0.85)
            self.assertIn(TAG_USER_PRAISED, metric.tags)
            self.assertEqual(
                loaded._personality_evidence,
                tracker._personality_evidence,
            )


if __name__ == "__main__":
    unittest.main()