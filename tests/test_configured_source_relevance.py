import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation


class ConfiguredSourceRelevanceTests(unittest.TestCase):
    def candidate(self, title):
        quality = clip_generation.score_title_quality("finance", title, topic_terms=["studio deal"])
        return clip_generation.CandidateClip(
            start_time=30.0,
            end_time=75.0,
            score=0.95,
            audio_score=0.8,
            text_score=0.75,
            opening_score=0.8,
            comment_score=0.0,
            popularity_score=0.0,
            arc_score=0.82,
            readiness_score=0.86,
            pacing_score=0.8,
            duration_score=0.9,
            boundary_score=0.86,
            diversity_score=1.0,
            theme_signal_score=0.04,
            rank_signals={
                "source_tier": "priority",
                "readiness_tier": "strong",
                "title_quality": quality,
            },
            transcript_excerpt=(
                "The guest tells a complete story about a studio deal that almost fell apart "
                "and why the final decision surprised everyone in the room."
            ),
            topic_fingerprint=["studio deal"],
            suggested_title=title,
        )

    def test_configured_source_gets_neutral_theme_signal_floor(self):
        with patch.object(clip_generation, "CONFIGURED_SOURCE_THEME_SIGNAL_FLOOR", 0.50):
            result = clip_generation.apply_configured_source_theme_signal_floor(
                {
                    "theme_signal_score": 0.08,
                    "signals": {"positive_keyword_hits": []},
                    "concerns": ["weak theme-specific signal", "other note"],
                },
                "priority",
            )

        self.assertEqual(result["theme_signal_score"], 0.50)
        self.assertTrue(result["signals"]["configured_source_relevance_trusted"])
        self.assertEqual(result["signals"]["raw_theme_signal_score"], 0.08)
        self.assertNotIn("weak theme-specific signal", result["concerns"])
        self.assertIn("other note", result["concerns"])

    def test_relevance_floor_can_be_disabled(self):
        with patch.dict(os.environ, {"SHORTFORM_TRUST_CONFIGURED_SOURCE_RELEVANCE": "0"}):
            result = clip_generation.apply_configured_source_theme_signal_floor(
                {"theme_signal_score": 0.08, "signals": {}, "concerns": ["weak theme-specific signal"]},
                "priority",
            )

        self.assertEqual(result["theme_signal_score"], 0.08)
        self.assertNotIn("configured_source_relevance_trusted", result.get("signals", {}))
        self.assertIn("weak theme-specific signal", result["concerns"])

    def test_unconfigured_source_does_not_get_theme_signal_floor(self):
        result = clip_generation.apply_configured_source_theme_signal_floor(
            {"theme_signal_score": 0.08, "signals": {}, "concerns": []},
            "",
        )

        self.assertEqual(result["theme_signal_score"], 0.08)
        self.assertNotIn("configured_source_relevance_trusted", result.get("signals", {}))

    def test_configured_source_can_pass_without_theme_keywords_when_title_is_publishable(self):
        with patch.object(clip_generation, "CURRENT_THEME", "finance"):
            self.assertTrue(
                clip_generation.candidate_selection_ready(
                    self.candidate("The Studio Deal Nobody Expected")
                )
            )

    def test_configured_source_uses_standard_readiness_in_unlimited_backlog_mode(self):
        candidate = self.candidate("The Studio Deal Nobody Expected")
        candidate.readiness_score = 0.66
        candidate.popularity_score = 0.50
        candidate.rank_signals["readiness_score"] = 0.66
        candidate.rank_signals["popularity_score"] = 0.50

        with (
            patch.object(clip_generation, "CURRENT_THEME", "finance"),
            patch.object(clip_generation, "active_min_readiness_score", return_value=0.62),
            patch.object(clip_generation, "UNLIMITED_BACKLOG_MIN_READINESS_SCORE", 0.70),
        ):
            self.assertTrue(clip_generation.candidate_selection_ready(candidate))

    def test_configured_source_keeps_complete_clip_with_raw_public_title_advisory(self):
        with patch.object(clip_generation, "CURRENT_THEME", "finance"):
            self.assertTrue(
                clip_generation.candidate_selection_ready(
                    self.candidate("How does that shape the perspective now being the boss")
                )
            )

    def test_selection_recomputes_title_quality_instead_of_trusting_stale_cache(self):
        candidate = self.candidate("Which Is What Agents Have")
        candidate.rank_signals["title_quality"] = {
            "length_ok": True,
            "specificity": 1.0,
            "honesty": 1.0,
            "not_clickbait": True,
            "theme_native_title": True,
            "generic_title": False,
            "raw_dialogue_fragment": False,
            "mechanical_title": False,
            "keyword_soup_title": False,
            "repetitive_title": False,
            "source_title_like": False,
            "source_only_title": False,
        }

        with patch.object(clip_generation, "CURRENT_THEME", "technology_ai"):
            self.assertTrue(clip_generation.candidate_selection_ready(candidate))

        self.assertTrue(candidate.rank_signals.get("title_quality_advisory_only"))
        self.assertNotEqual(candidate.rank_signals["title_quality"].get("specificity"), 1.0)

    def test_title_too_close_to_source_title_is_rejected(self):
        self.assertTrue(
            clip_generation.title_too_close_to_source_title(
                "Going to a NASCAR Race for the FIRST Time!",
                "Going to a NASCAR Race for the FIRST Time!",
            )
        )
        self.assertTrue(
            clip_generation.title_too_close_to_source_title(
                "The NBA Offseason Is About To Get Crazy: Matt Barnes Predicts What's Next",
                "The NBA Offseason Is About To Get Crazy: Matt Barnes Predicts What's Next",
            )
        )
        self.assertFalse(
            clip_generation.title_too_close_to_source_title(
                "Matt Barnes' Undrafted NBA Comeback",
                "The NBA Offseason Is About To Get Crazy: Matt Barnes Predicts What's Next",
            )
        )

    def test_source_title_copy_is_advisory_when_clip_is_otherwise_usable(self):
        candidate = self.candidate("Going to a NASCAR Race for the FIRST Time!")
        candidate.source_title = "Going to a NASCAR Race for the FIRST Time!"

        with patch.object(clip_generation, "CURRENT_THEME", "sports"):
            self.assertTrue(clip_generation.candidate_selection_ready(candidate))

        self.assertTrue(candidate.rank_signals.get("title_quality_advisory_only"))

    def test_configured_source_score_prioritizes_watchability_over_theme_keywords(self):
        weights = {
            "hook": 0.10,
            "payoff": 0.10,
            "standalone_context": 0.10,
            "theme_signal": 0.50,
            "public_popularity": 0.10,
            "captionability": 0.05,
            "visual_quality": 0.05,
            "transformation": 0.10,
        }
        arc_details = {
            "arc_hook_score": 1.0,
            "arc_payoff_score": 1.0,
            "arc_standalone_score": 1.0,
        }

        with (
            patch.object(clip_generation, "CURRENT_THEME", "finance"),
            patch.object(clip_generation, "CONFIGURED_SOURCE_THEME_WEIGHT_CAP", 0.07),
            patch.object(clip_generation, "get_scoring_weights", return_value=weights),
            patch.object(clip_generation, "get_risk_controls", return_value={}),
        ):
            configured_score, configured_components = clip_generation.theme_weighted_candidate_score(
                text_score=1.0,
                opening_score=1.0,
                arc_details=arc_details,
                popularity_score=1.0,
                captionability_score=1.0,
                boundary_score=1.0,
                pacing_score=1.0,
                transformation_score=1.0,
                reused_content_risk=0.0,
                theme_signal_score=0.0,
                source_tier="priority",
            )
            unconfigured_score, unconfigured_components = clip_generation.theme_weighted_candidate_score(
                text_score=1.0,
                opening_score=1.0,
                arc_details=arc_details,
                popularity_score=1.0,
                captionability_score=1.0,
                boundary_score=1.0,
                pacing_score=1.0,
                transformation_score=1.0,
                reused_content_risk=0.0,
                theme_signal_score=0.0,
                source_tier="",
            )

        self.assertGreater(configured_score, unconfigured_score)
        self.assertGreater(configured_score, 0.80)
        self.assertEqual(
            configured_components["theme_weighting_strategy"],
            "configured_source_watchability",
        )
        self.assertEqual(configured_components["effective_theme_signal_weight"], 0.07)
        self.assertEqual(unconfigured_components["theme_weighting_strategy"], "theme_weighted")
        self.assertEqual(unconfigured_components["effective_theme_signal_weight"], 0.50)

    def test_trusted_source_transformation_uses_complete_arc_instead_of_theme_keywords(self):
        with patch.object(clip_generation, "get_risk_controls", return_value={}):
            result = clip_generation.score_transformation_candidate(
                theme_name="finance",
                intro_mode="voice_setup",
                theme_signal_result={"theme_signal_score": 0.02},
                title_quality={
                    "specificity": 0.82,
                    "theme_native_title": True,
                    "generic_title": False,
                    "mechanical_title": False,
                    "repetitive_title": False,
                },
                popularity_score=0.0,
                source_tier="priority",
                readiness_score=0.78,
                arc_details={
                    "arc_hook_score": 0.72,
                    "arc_payoff_score": 0.76,
                    "arc_standalone_score": 0.74,
                },
            )

        self.assertGreaterEqual(result["transformation_score"], 0.68)
        self.assertIn("trusted source with complete viewer arc", result["transformation_notes"])
        self.assertNotIn("theme-specific editorial signal", result["transformation_notes"])

    def test_build_suggested_copy_polishes_transcript_specific_title(self):
        text = (
            "Generative AI cannot follow instructions because the model keeps missing "
            "exact constraints and builders need better evals."
        )

        with (
            patch.object(clip_generation, "CURRENT_THEME", "finance"),
            patch.object(
                clip_generation,
                "transcript_specific_title_for_theme",
                return_value="Generative AI cannot follow instructions",
            ),
            patch.object(clip_generation, "title_supported_by_clip", return_value=True),
        ):
            title, *_ = clip_generation.build_suggested_copy(
                text,
                "hook phrase: AI",
                ["generative ai", "instructions"],
                source_record={"title": "AI benchmark interview"},
            )

        self.assertEqual(title, "Generative AI Cannot Follow Instructions")


if __name__ == "__main__":
    unittest.main()
