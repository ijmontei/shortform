import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import daily_editorial
import upload
from metadata_generation.titles import score_title_quality, source_context_title


TRUECRIME_PASSENGER_CLIP = {
    "source_title": "Cops Face Off With Dangerous Suspects - On Patrol: Live",
    "suggested_title": "Evidence Both Passenger: The Detail That Changes The Case",
    "transcript_excerpt": (
        "Both of that is going to go into evidence. What's that? "
        "The passenger's doing anything? Yeah, the front passenger is definitely "
        "getting this charge right here as well. Okay. Where was that under here? "
        "See this was on the back. This was on the floor."
    ),
    "topic_fingerprint": ["both", "passenger", "evidence", "charge", "front"],
}


class PublicCopyQualityTests(unittest.TestCase):
    def test_public_text_cleanup_removes_common_mojibake(self):
        broken_source_title = (
            "Cops Face Off With Dangerous Suspects "
            "\u0432\u0402\u201d On Patrol: Live"
        )
        broken_hook = (
            "That\u00e2\u20ac\u2122s why this moment "
            "\u00e2\u20ac\u201d changed the whole stop"
        )

        self.assertEqual(
            daily_editorial.clean_viewer_text(broken_source_title),
            "Cops Face Off With Dangerous Suspects - On Patrol: Live",
        )
        self.assertEqual(
            daily_editorial.clean_viewer_text(broken_hook),
            "That's why this moment - changed the whole stop",
        )
        self.assertEqual(
            upload.clean_public_text(broken_hook),
            "That's why this moment - changed the whole stop",
        )

    def test_truecrime_source_context_repairs_template_title(self):
        repaired = source_context_title(
            "truecrime",
            TRUECRIME_PASSENGER_CLIP["source_title"],
            TRUECRIME_PASSENGER_CLIP,
            TRUECRIME_PASSENGER_CLIP["topic_fingerprint"],
        )

        self.assertEqual(repaired, "Police Search Turns Into An Evidence Question")

        quality = score_title_quality(
            "truecrime",
            repaired,
            topic_terms=[
                repaired,
                TRUECRIME_PASSENGER_CLIP["source_title"],
            ],
        )

        self.assertGreaterEqual(quality.get("honesty", 0.0), 0.70)
        self.assertFalse(quality.get("generic_title"))
        self.assertFalse(quality.get("weak_template_title"))

    def test_hook_generator_rejects_generic_detail_script(self):
        topic = daily_editorial.clean_headline_topic(
            "truecrime",
            TRUECRIME_PASSENGER_CLIP["suggested_title"],
            clip=TRUECRIME_PASSENGER_CLIP,
            source_title=TRUECRIME_PASSENGER_CLIP["source_title"],
            channel="On Patrol: Live",
        )
        script = daily_editorial.build_moment_hook_script(
            "truecrime",
            "This Detail",
            "standout",
            TRUECRIME_PASSENGER_CLIP,
        )

        self.assertEqual(topic, "Police Search Turns Into An Evidence Question")
        self.assertTrue(daily_editorial.public_hook_script_ok(script, topic))
        self.assertFalse(
            daily_editorial.public_hook_script_ok(
                "This detail changes how the whole story feels.",
                topic,
            )
        )


if __name__ == "__main__":
    unittest.main()
