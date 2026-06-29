import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation


class UnlimitedClipSelectionTests(unittest.TestCase):
    def test_legacy_theme_candidate_count_does_not_cap_production_selection(self):
        with patch.object(
            clip_generation,
            "active_clip_rules",
            return_value={"theme_candidates_per_video": 15},
        ):
            self.assertIsNone(clip_generation.active_theme_candidates_per_video("comedy"))

    def test_ranked_candidate_window_returns_every_candidate_without_cap(self):
        candidates = [
            SimpleNamespace(score=0.20, readiness_score=0.80, popularity_score=0.10, arc_score=0.50, rank_signals={}),
            SimpleNamespace(score=0.90, readiness_score=0.70, popularity_score=0.20, arc_score=0.40, rank_signals={}),
            SimpleNamespace(score=0.60, readiness_score=0.95, popularity_score=0.30, arc_score=0.80, rank_signals={}),
        ]

        ranked = clip_generation.ranked_candidate_window(candidates, limit=None)

        self.assertEqual(len(ranked), 3)
        self.assertEqual([item.score for item in ranked], [0.90, 0.60, 0.20])

    def test_ranked_candidate_window_only_caps_when_explicit(self):
        candidates = [
            SimpleNamespace(score=0.20, readiness_score=0.80, popularity_score=0.10, arc_score=0.50, rank_signals={}),
            SimpleNamespace(score=0.90, readiness_score=0.70, popularity_score=0.20, arc_score=0.40, rank_signals={}),
            SimpleNamespace(score=0.60, readiness_score=0.95, popularity_score=0.30, arc_score=0.80, rank_signals={}),
        ]

        ranked = clip_generation.ranked_candidate_window(candidates, limit=2)

        self.assertEqual(len(ranked), 2)
        self.assertEqual([item.score for item in ranked], [0.90, 0.60])


if __name__ == "__main__":
    unittest.main()
