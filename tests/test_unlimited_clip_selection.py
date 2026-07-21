import os
import sys
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation


class UnlimitedClipSelectionTests(unittest.TestCase):
    def make_candidate(self, index, score=0.75, source_key=None, source_title=None):
        return clip_generation.CandidateClip(
            start_time=float(index * 70),
            end_time=float(index * 70 + 45),
            score=score,
            audio_score=0.65,
            text_score=0.55,
            opening_score=0.60,
            comment_score=0.55,
            popularity_score=0.55,
            arc_score=0.70,
            readiness_score=0.82,
            pacing_score=0.70,
            duration_score=0.70,
            boundary_score=0.90,
            diversity_score=1.0,
            transcript_excerpt=f"This is a complete thought about topic {index}.",
            hook_reason="question hook",
            topic_fingerprint=[f"topic{index}"],
            suggested_title=f"Why Topic {index} Matters",
            suggested_caption=f"Why Topic {index} Matters",
            source_state_key=source_key or f"theme|video-{index}",
            source_video_url=f"https://www.youtube.com/watch?v={index:011d}"[-43:],
            source_title=source_title or f"Source Interview {index}",
        )

    def test_daily_policy_caps_per_source_candidates_independently_of_legacy_rule(self):
        with patch.object(
            clip_generation,
            "active_clip_rules",
            return_value={"theme_candidates_per_video": 15},
        ):
            self.assertEqual(clip_generation.active_theme_candidates_per_video("comedy"), 12)

    def test_ranked_candidate_window_returns_every_candidate_without_cap(self):
        candidates = [
            SimpleNamespace(score=0.20, readiness_score=0.80, popularity_score=0.10, arc_score=0.50, rank_signals={}),
            SimpleNamespace(score=0.90, readiness_score=0.70, popularity_score=0.20, arc_score=0.40, rank_signals={}),
            SimpleNamespace(score=0.60, readiness_score=0.95, popularity_score=0.30, arc_score=0.80, rank_signals={}),
        ]

        ranked = clip_generation.ranked_candidate_window(candidates, limit=None)

        self.assertEqual(len(ranked), 3)
        self.assertEqual(set(item.score for item in ranked), {0.90, 0.60, 0.20})

    def test_ranked_candidate_window_only_caps_when_explicit(self):
        candidates = [
            SimpleNamespace(score=0.20, readiness_score=0.80, popularity_score=0.10, arc_score=0.50, rank_signals={}),
            SimpleNamespace(score=0.90, readiness_score=0.70, popularity_score=0.20, arc_score=0.40, rank_signals={}),
            SimpleNamespace(score=0.60, readiness_score=0.95, popularity_score=0.30, arc_score=0.80, rank_signals={}),
        ]

        ranked = clip_generation.ranked_candidate_window(candidates, limit=2)

        self.assertEqual(len(ranked), 2)
        self.assertEqual(set(item.score for item in ranked), {0.90, 0.60})

    def test_global_ranking_inventory_keeps_unfinished_cached_sources(self):
        theme_records = [
            ("comedy|fresh", {"stages": {}}),
            ("comedy|ranked_not_selected", {"stages": {"clips_ranked_not_selected": True}}),
            ("comedy|clips_scored", {"stages": {"clips_scored": True}}),
            ("comedy|subtitled", {"stages": {"subtitled": True}}),
            ("comedy|uploaded", {"stages": {"uploaded": True}}),
            ("comedy|executed", {"stages": {}}),
        ]

        records = clip_generation.theme_records_for_global_ranking(
            theme_records,
            {"comedy|executed": {"funnel_status": "uploaded"}},
        )

        self.assertEqual(
            [state_key for state_key, _ in records],
            ["comedy|fresh", "comedy|ranked_not_selected", "comedy|clips_scored"],
        )

    def test_daily_render_pool_attempt_limit_caps_oversized_reports(self):
        with patch.object(clip_generation, "DAILY_RENDER_ACCEPTED_TARGET", 25), \
             patch.object(clip_generation, "DAILY_RENDER_ACCEPTED_TARGET_GLOBAL_OVERRIDE", True), \
             patch.object(clip_generation, "DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER", 4), \
             patch.object(clip_generation, "DAILY_RENDER_POOL_MIN_ATTEMPTS", 60):
            self.assertEqual(
                clip_generation.daily_render_pool_attempt_limit("truecrime", selected_count=531),
                100,
            )

    def test_render_target_is_theme_neutral_without_explicit_override(self):
        self.assertEqual(
            clip_generation.daily_render_target("truecrime"),
            clip_generation.daily_render_target("sports"),
        )

    def test_theme_render_target_can_be_explicitly_overridden(self):
        with patch.object(clip_generation, "THEME_RENDER_ACCEPTED_TARGET_OVERRIDES", {"truecrime": 80}), \
             patch.object(clip_generation, "DAILY_RENDER_ACCEPTED_TARGET_GLOBAL_OVERRIDE", False):
            self.assertEqual(clip_generation.daily_render_target("truecrime"), 80)

    def test_selected_clips_from_report_uses_top_daily_attempt_window(self):
        candidates = [
            self.make_candidate(index, score=0.20 + index / 1000)
            for index in range(130)
        ]
        candidates[-1].source_title = "Bodycam surveillance court audio"
        report = {"render_pool": [asdict(candidate) for candidate in candidates]}

        with patch.object(clip_generation, "CURRENT_THEME", "truecrime"), \
             patch.object(clip_generation, "DAILY_RENDER_ACCEPTED_TARGET", 25), \
             patch.object(clip_generation, "DAILY_RENDER_ACCEPTED_TARGET_GLOBAL_OVERRIDE", True), \
             patch.object(clip_generation, "DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER", 4), \
             patch.object(clip_generation, "DAILY_RENDER_POOL_MIN_ATTEMPTS", 60):
            groups = clip_generation.selected_clips_by_source_from_report(report, {})

        grouped_count = sum(len(group["clips"]) for group in groups.values())
        self.assertEqual(grouped_count, 100)

    def test_candidate_render_priority_penalizes_obvious_visual_risk(self):
        clean = self.make_candidate(1, score=0.8, source_title="Clean studio interview")
        risky = self.make_candidate(2, score=0.8, source_title="Bodycam surveillance court audio")

        self.assertGreater(
            clip_generation.candidate_render_priority_score(clean),
            clip_generation.candidate_render_priority_score(risky),
        )

    def test_candidate_render_priority_rewards_titleable_transcript(self):
        strong = self.make_candidate(
            3,
            score=0.78,
            source_title="Studio interview about bad surgery stories",
        )
        strong.transcript_excerpt = (
            "He explains why people panic before surgery and tells a complete story "
            "about the exact moment the doctor changed his mind."
        )
        strong.suggested_title = "Why People Panic Before Surgery"
        strong.topic_fingerprint = ["surgery panic", "doctor changed his mind"]

        generic = self.make_candidate(
            4,
            score=0.78,
            source_title="Studio interview about bad surgery stories",
        )
        generic.transcript_excerpt = strong.transcript_excerpt
        generic.suggested_title = "The Moment Worth Rewatching"
        generic.topic_fingerprint = ["surgery panic", "doctor changed his mind"]

        self.assertGreater(
            clip_generation.candidate_render_priority_score(strong),
            clip_generation.candidate_render_priority_score(generic),
        )


if __name__ == "__main__":
    unittest.main()
