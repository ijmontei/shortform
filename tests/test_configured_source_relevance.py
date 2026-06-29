import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation
import daily_editorial
import editorial_gates


class ConfiguredSourceRelevanceTests(unittest.TestCase):
    def test_candidate_theme_fit_trusts_configured_source_tier(self):
        candidate = SimpleNamespace(
            rank_signals={
                "source_tier": "legacy",
                "theme_signal_concerns": ["weak theme-specific signal"],
            },
            theme_signal_score=0.0,
        )

        self.assertTrue(clip_generation.candidate_theme_fit_ready(candidate))

    def test_editorial_theme_relevance_trusts_configured_source_tier(self):
        self.assertTrue(daily_editorial.clip_has_theme_relevance(
            "finance",
            {
                "source_tier": "secondary",
                "transcript_excerpt": "He told a complete story about why the meeting changed his mind.",
            },
        ))

    def test_editorial_gates_do_not_fail_trusted_source_for_theme_keywords_only(self):
        package = {
            "content_format": "daily_editorial_short",
            "title": "The Meeting That Changed His Mind",
            "caption": "A complete story with a clean turn.",
            "description": "A complete story with a clean turn.",
            "source_tier": "priority",
            "source_video_url": "https://www.youtube.com/watch?v=abc12345678",
            "source_title": "A founder explains the meeting that changed his mind",
            "source_channel": "Trusted Show",
            "transcript_excerpt": "The founder said the meeting changed his mind after one specific moment.",
            "content_has_burned_captions": True,
            "upload_ready_requires_burned_captions": True,
            "theme_signal_score": 0.0,
            "transformation_score": 0.82,
            "reused_content_risk": 0.10,
            "rank_signals": {
                "source_tier": "priority",
                "captionability_score": 0.85,
                "transcript_excerpt": "The founder said the meeting changed his mind after one specific moment.",
                "source_title": "A founder explains the meeting that changed his mind",
                "source_channel": "Trusted Show",
                "source_video_url": "https://www.youtube.com/watch?v=abc12345678",
            },
            "first_second_qc": {"passed": True},
            "render_qc": {"passed": True, "flags": [], "visual_quality_score": 0.86},
        }

        result = editorial_gates.evaluate_editorial_gates("finance", package)

        self.assertNotIn("weak_theme_signal", result["flags"])
        self.assertNotIn("off_theme_content", result["flags"])


if __name__ == "__main__":
    unittest.main()
