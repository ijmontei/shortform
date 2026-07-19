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
        "editorial_script": "Standout: Police search turns into an evidence question.",
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

    def test_unsupported_title_is_advisory_not_blocking(self):
        result = evaluate_editorial_gates(
            "truecrime",
            truecrime_package("Police Dog Finds A Secret Tunnel"),
        )

        self.assertIn("title_not_supported_by_clip_context", result["advisory_flags"])
        self.assertNotIn("title_not_supported_by_clip_context", result["flags"])
        self.assertTrue(result["passed"])

    def test_weak_title_quality_is_advisory_not_blocking(self):
        package = truecrime_package("Top 10 Moments This Week")
        package["content_signal"] = {"topic": "Police Search Turns Into An Evidence Question"}

        result = evaluate_editorial_gates(
            "truecrime",
            package,
        )

        self.assertTrue(result["passed"])
        self.assertIn("generic_title", result["advisory_flags"])
        self.assertIn("low_title_specificity", result["advisory_flags"])
        self.assertNotIn("generic_title", result["flags"])
        self.assertNotIn("low_title_specificity", result["flags"])

    def test_low_transformation_for_configured_source_is_advisory(self):
        package = truecrime_package("Police Search Turns Into An Evidence Question")
        package["transformation_score"] = 0.22
        package["rank_signals"] = {
            **package["rank_signals"],
            "source_tier": "priority",
            "transformation_score": 0.22,
        }

        result = evaluate_editorial_gates("truecrime", package)

        self.assertTrue(result["passed"])
        self.assertIn("transformation_below_theme_minimum", result["advisory_flags"])
        self.assertNotIn("transformation_below_theme_minimum", result["flags"])

    def test_trusted_configured_source_is_not_blocked_by_off_theme_topic_language(self):
        package = truecrime_package("Studio Deal Debate")
        package.update({
            "theme": "finance",
            "caption": "A studio deal turns into a bigger business question.",
            "description": "A studio deal turns into a bigger business question.",
            "editorial_script": "A studio deal debate turns into a bigger business question.",
            "source_title": "Founder Interview",
            "source_channel": "Trusted Business Show",
            "transcript_excerpt": (
                "The studio deal became a debate because everyone expected the founder "
                "to take it, but the economics changed once the terms were explained."
            ),
            "topic_fingerprint": [],
            "theme_signal_score": 0.02,
            "rank_signals": {
                **package["rank_signals"],
                "source_tier": "priority",
                "theme_signal_score": 0.02,
                "topic_fingerprint": [],
                "source_title": "Founder Interview",
                "source_channel": "Trusted Business Show",
                "transcript_excerpt": (
                    "The studio deal became a debate because everyone expected the founder "
                    "to take it, but the economics changed once the terms were explained."
                ),
            },
        })

        result = evaluate_editorial_gates("finance", package)

        self.assertTrue(result["passed"])
        self.assertNotIn("weak_theme_signal", result["flags"])
        self.assertNotIn("weak_theme_native_title", result["flags"])
        self.assertNotIn("weak_title_theme_fit", result["flags"])

    def test_relaxed_theme_relevance_does_not_block_publishable_unconfigured_clip(self):
        package = truecrime_package("Studio Deal Debate")
        package.update({
            "theme": "finance",
            "caption": "A studio deal turns into a bigger business question.",
            "description": "A studio deal turns into a bigger business question.",
            "editorial_script": "Standout: Studio Deal Debate. Watch this.",
            "source_title": "Founder Interview",
            "source_channel": "Trusted Business Show",
            "transcript_excerpt": (
                "The studio deal became a debate because everyone expected the founder "
                "to take it, but the economics changed once the terms were explained."
            ),
            "topic_fingerprint": [],
            "theme_signal_score": 0.0,
            "rank_signals": {
                **package["rank_signals"],
                "source_tier": "",
                "theme_signal_score": 0.0,
                "topic_fingerprint": [],
                "source_title": "Founder Interview",
                "source_channel": "Trusted Business Show",
                "transcript_excerpt": (
                    "The studio deal became a debate because everyone expected the founder "
                    "to take it, but the economics changed once the terms were explained."
                ),
            },
        })

        result = evaluate_editorial_gates("finance", package)

        self.assertTrue(result["passed"])
        self.assertTrue(result["relax_theme_relevance_gates"])
        self.assertNotIn("weak_theme_signal", result["flags"])
        self.assertNotIn("off_theme_content", result["flags"])
        self.assertNotIn("weak_title_theme_fit", result["flags"])

    def test_visual_action_sports_package_can_pass_without_face_presence(self):
        package = truecrime_package("NASCAR Horsepower Changes The Race")
        package.update({
            "theme": "sports",
            "source_title": "Kyle Larson Explains The NASCAR Horsepower Debate",
            "source_channel": "Sports Show",
            "caption": "NASCAR horsepower changes the race.",
            "description": "NASCAR horsepower changes the race.",
            "editorial_script": "This NASCAR horsepower debate changes how the race feels.",
            "transcript_excerpt": "The horsepower package changes how the cars race and how drivers pass.",
            "topic_fingerprint": ["nascar", "horsepower", "race"],
            "rank_signals": {
                **package["rank_signals"],
                "source_tier": "priority",
                "source_title": "Kyle Larson Explains The NASCAR Horsepower Debate",
                "topic_fingerprint": ["nascar", "horsepower", "race"],
            },
            "render_qc": {
                "passed": True,
                "visual_quality_score": 0.72,
                "flags": ["low final face presence", "alive frames often miss speaker"],
                "frame_path": {
                    "visual_quality_score": 0.72,
                    "face_presence_rate": 0.02,
                    "longest_no_face_run_ratio": 0.54,
                    "alive_no_face_frame_ratio": 0.68,
                    "max_face_center_offset_ratio": 0.0,
                    "low_information_frame_ratio": 0.02,
                    "dead_frame_ratio": 0.0,
                    "black_frame_ratio": 0.0,
                },
            },
        })

        result = evaluate_editorial_gates("sports", package)

        self.assertTrue(result["passed"])
        self.assertNotIn("final_package_misses_speaker_too_often", result["flags"])

    def test_off_center_only_final_package_is_not_blocking(self):
        package = truecrime_package("Police Search Turns Into An Evidence Question")
        package["render_qc"] = {
            "passed": True,
            "visual_quality_score": 0.76,
            "flags": ["subject severely off-center in final crop"],
            "frame_path": {
                "visual_quality_score": 0.76,
                "face_presence_rate": 0.88,
                "longest_no_face_run_ratio": 0.06,
                "alive_no_face_frame_ratio": 0.08,
                "max_face_center_offset_ratio": 0.76,
                "low_information_frame_ratio": 0.01,
                "dead_frame_ratio": 0.0,
                "black_frame_ratio": 0.0,
            },
        }

        result = evaluate_editorial_gates("truecrime", package)

        self.assertTrue(result["passed"])
        self.assertNotIn("final_package_severe_off_center", result["flags"])

    def test_off_center_with_missing_speaker_still_fails_as_background_lock(self):
        package = truecrime_package("Police Search Turns Into An Evidence Question")
        package["render_qc"] = {
            "passed": True,
            "visual_quality_score": 0.76,
            "flags": ["subject severely off-center in final crop"],
            "frame_path": {
                "visual_quality_score": 0.76,
                "face_presence_rate": 0.40,
                "longest_no_face_run_ratio": 0.20,
                "alive_no_face_frame_ratio": 0.46,
                "max_face_center_offset_ratio": 0.76,
                "low_information_frame_ratio": 0.01,
                "dead_frame_ratio": 0.0,
                "black_frame_ratio": 0.0,
            },
        }

        result = evaluate_editorial_gates("truecrime", package)

        self.assertFalse(result["passed"])
        self.assertIn("final_package_probable_background_lock", result["flags"])

    def test_background_lock_still_fails_for_visual_action_theme(self):
        package = truecrime_package("NASCAR Horsepower Changes The Race")
        package.update({
            "theme": "sports",
            "source_title": "Kyle Larson Explains The NASCAR Horsepower Debate",
            "source_channel": "Sports Show",
            "caption": "NASCAR horsepower changes the race.",
            "description": "NASCAR horsepower changes the race.",
            "editorial_script": "This NASCAR horsepower debate changes how the race feels.",
            "transcript_excerpt": "The horsepower package changes how the cars race and how drivers pass.",
            "rank_signals": {
                **package["rank_signals"],
                "source_tier": "priority",
                "source_title": "Kyle Larson Explains The NASCAR Horsepower Debate",
            },
            "render_qc": {
                "passed": True,
                "visual_quality_score": 0.72,
                "flags": ["probable background lock instead of speaker"],
                "frame_path": {
                    "visual_quality_score": 0.72,
                    "face_presence_rate": 0.02,
                    "longest_no_face_run_ratio": 0.54,
                    "alive_no_face_frame_ratio": 0.68,
                    "max_face_center_offset_ratio": 0.75,
                    "low_information_frame_ratio": 0.02,
                    "dead_frame_ratio": 0.0,
                    "black_frame_ratio": 0.0,
                },
            },
        })

        result = evaluate_editorial_gates("sports", package)

        self.assertFalse(result["passed"])
        self.assertIn("final_package_probable_background_lock", result["flags"])


if __name__ == "__main__":
    unittest.main()
