import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from editorial_gates import evaluate_editorial_gates


def truecrime_package(title):
    return {
        "theme": "truecrime",
        "content_format": "popular_segment_short",
        "content_has_burned_captions": True,
        "upload_ready_requires_burned_captions": True,
        "title": title,
        "caption": "Police search turns into an evidence question.",
        "description": "Police search turns into an evidence question.",
        "source_title": "Cops Face Off With Dangerous Suspects - On Patrol: Live",
        "source_channel": "On Patrol: Live",
        "source_video_url": "https://www.youtube.com/watch?v=example",
        "clip_start_time": 864.96,
        "clip_end_time": 899.10,
        "transcript_excerpt": (
            "Both of that is going to go into evidence. What's that? "
            "The passenger's doing anything? Yeah, the front passenger is definitely "
            "getting this charge right here as well. Okay. Where was that under here? "
            "See this was on the back. This was on the floor."
        ),
        "topic_fingerprint": ["passenger", "evidence", "charge", "police", "search"],
        "theme_signal_score": 0.82,
        "transformation_score": 0.82,
        "reused_content_risk": 0.12,
        "rank_signals": {
            "captionability_score": 0.92,
            "theme_signal_score": 0.82,
            "transformation_score": 0.82,
            "reused_content_risk": 0.12,
            "topic_fingerprint": ["passenger", "evidence", "charge", "police", "search"],
        },
        "render_qc": {
            "passed": True,
            "visual_quality_score": 0.78,
            "flags": [],
            "frame_path": {
                "visual_quality_score": 0.78,
                "face_presence_rate": 0.74,
                "longest_no_face_run_ratio": 0.08,
                "alive_no_face_frame_ratio": 0.12,
                "max_face_center_offset_ratio": 0.16,
                "low_information_frame_ratio": 0.02,
            },
        },
    }


class EditorialGateQualityTests(unittest.TestCase):
    def test_supported_title_passes_context_gate(self):
        result = evaluate_editorial_gates(
            "truecrime",
            truecrime_package("Police Search Turns Into An Evidence Question"),
        )

        self.assertNotIn("title_not_supported_by_clip_context", result["flags"])

    def test_unsupported_title_fails_context_gate(self):
        result = evaluate_editorial_gates(
            "truecrime",
            truecrime_package("Police Dog Finds A Secret Tunnel"),
        )

        self.assertIn("title_not_supported_by_clip_context", result["flags"])
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
