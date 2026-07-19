import os
import unittest
from unittest.mock import patch

import runtime_budget


class RuntimeBudgetTests(unittest.TestCase):
    def test_configures_production_deadline_before_run_deadline(self):
        with patch.dict(os.environ, {}, clear=False):
            result = runtime_budget.configure_run_budget(
                max_runtime_hours=12,
                upload_reserve_minutes=75,
                now=1_000,
            )

            self.assertTrue(result["enabled"])
            self.assertEqual(result["run_deadline"], 44_200)
            self.assertEqual(result["production_deadline"], 39_700)
            self.assertEqual(runtime_budget.remaining_seconds(now=1_100), 38_600)
            self.assertEqual(runtime_budget.remaining_seconds(production=False, now=1_100), 43_100)

    def test_zero_hours_disables_deadline(self):
        with patch.dict(os.environ, {}, clear=False):
            result = runtime_budget.configure_run_budget(0, now=1_000)

            self.assertFalse(result["enabled"])
            self.assertTrue(runtime_budget.can_start_work(999_999))

    def test_stage_and_theme_deadlines_narrow_production_only(self):
        with patch.dict(os.environ, {}, clear=False):
            runtime_budget.configure_run_budget(12, upload_reserve_minutes=60, now=1_000)
            runtime_budget.set_stage_deadline(20_000)
            runtime_budget.set_theme_deadline(10_000)

            self.assertEqual(runtime_budget.remaining_seconds(now=2_000), 8_000)
            self.assertEqual(runtime_budget.remaining_seconds(production=False, now=2_000), 42_200)

    def test_weighted_and_fair_deadlines_allocate_remaining_time(self):
        with patch.dict(os.environ, {}, clear=False):
            runtime_budget.configure_run_budget(10, upload_reserve_minutes=0, now=1_000)
            stage_deadline = runtime_budget.weighted_slice_deadline(
                remaining_stage_weights=10,
                current_weight=2,
                now=1_000,
            )
            theme_deadline = runtime_budget.fair_slice_deadline(
                stage_deadline,
                remaining_items=4,
                now=1_000,
            )

            self.assertEqual(stage_deadline, 8_200)
            self.assertEqual(theme_deadline, 2_800)
