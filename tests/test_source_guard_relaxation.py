import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import theme_profile


def profile():
    return {
        "theme_signals": {
            "positive_keywords": ["finance", "market", "investing"],
            "negative_keywords": ["celebrity"],
            "source_guard": {
                "hard_negative_keywords": ["full match"],
                "min_positive_hits_by_tier": {
                    "priority": 1,
                    "secondary": 1,
                    "legacy": 1,
                },
                "negative_override_min_positive_hits": 2,
            },
        },
    }


class SourceGuardRelaxationTests(unittest.TestCase):
    def test_configured_source_without_theme_keyword_is_allowed_by_default(self):
        disqualified, hits = theme_profile.source_guard_disqualification(
            profile(),
            {
                "title": "A wild story with a famous founder",
                "channel_url": "https://www.youtube.com/@TrustedShow/videos",
                "source_tier": "legacy",
            },
        )

        self.assertFalse(disqualified)
        self.assertEqual(hits, [])

    def test_hard_negative_does_not_block_configured_source_by_default(self):
        disqualified, hits = theme_profile.source_guard_disqualification(
            profile(),
            {
                "title": "Full match replay with no interview",
                "channel_url": "https://www.youtube.com/@TrustedShow/videos",
                "source_tier": "priority",
            },
        )

        self.assertFalse(disqualified)
        self.assertEqual(hits, [])

    def test_hard_negative_blocks_unconfigured_source(self):
        disqualified, hits = theme_profile.source_guard_disqualification(
            profile(),
            {
                "title": "Full match replay with no interview",
                "channel_url": "https://www.youtube.com/@RandomShow/videos",
                "source_tier": "",
            },
        )

        self.assertTrue(disqualified)
        self.assertEqual(hits, ["full match"])

    def test_strict_source_guard_can_restore_positive_keyword_requirement(self):
        with patch.object(theme_profile, "STRICT_SOURCE_GUARD", True):
            disqualified, hits = theme_profile.source_guard_disqualification(
                profile(),
                {
                    "title": "A wild story with a famous founder",
                    "channel_url": "https://www.youtube.com/@TrustedShow/videos",
                    "source_tier": "secondary",
                },
            )

        self.assertTrue(disqualified)
        self.assertEqual(hits, ["missing_source_positive_signal:0/1"])


if __name__ == "__main__":
    unittest.main()
