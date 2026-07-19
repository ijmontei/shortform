import os
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import content_qc
import daily_editorial


class QcAndIntroSafetyTests(unittest.TestCase):
    def test_downloaded_video_sections_are_reviewable_assets(self):
        path = os.path.join(
            ROOT,
            "output",
            "temp",
            "sports",
            "downloads",
            "videos",
            "sample_section_1.mp4",
        )

        self.assertEqual(content_qc.classify_asset(path), "downloaded_source_section")

    def test_final_upload_qc_excludes_revision_assets_by_default(self):
        content_path = os.path.join(ROOT, "output", "themes", "sports", "content", "ready.mp4")
        archive_path = os.path.join(ROOT, "output", "themes", "sports", "archive", "backlog.mp4")
        revision_path = os.path.join(ROOT, "output", "themes", "sports", "needs_revision", "fix_me.mp4")

        self.assertEqual(content_qc.classify_asset(content_path), "final_upload")
        self.assertEqual(content_qc.classify_asset(archive_path), "final_upload")
        self.assertEqual(content_qc.classify_asset(revision_path), "other")
        self.assertEqual(
            content_qc.classify_asset(revision_path, include_revision_assets=True),
            "final_upload",
        )

    def test_intro_duration_extends_to_fit_mastered_voice(self):
        with (
            patch.object(daily_editorial, "EDITORIAL_INTRO_TARGET_SECONDS", 5.2),
            patch.object(daily_editorial, "EDITORIAL_INTRO_MAX_SECONDS", 6.25),
            patch.object(daily_editorial, "EDITORIAL_INTRO_ABSOLUTE_MAX_SECONDS", 7.25),
            patch.object(daily_editorial, "INTRO_AUDIO_SAFETY_PAD_SECONDS", 0.45),
            patch.object(daily_editorial, "get_duration", return_value=6.5),
        ):
            duration = daily_editorial.editorial_intro_duration("intro.wav")

        self.assertGreater(duration, 6.25)
        self.assertEqual(duration, 6.95)

    def test_atempo_chain_splits_large_tempo_into_safe_filters(self):
        filters = daily_editorial.atempo_filter_chain(4.2)

        self.assertGreaterEqual(len(filters), 2)
        self.assertTrue(all(item.startswith("atempo=") for item in filters))

    def test_narration_tempo_default_stays_under_clear_speech_limit(self):
        self.assertLessEqual(daily_editorial.NARRATION_MAX_TEMPO, 1.12)

    def test_narration_defaults_keep_voice_natural(self):
        self.assertAlmostEqual(daily_editorial.NARRATION_PITCH, 1.0)
        self.assertAlmostEqual(daily_editorial.NARRATION_BASS_GAIN, 0.0)
        self.assertEqual(daily_editorial.elevenlabs_tts_text("Number 3: test."), "Number 3: test.")
        self.assertNotIn("deeper voice", daily_editorial.elevenlabs_tts_text("Number 3: test."))

    def test_narration_text_strips_prompt_language_before_tts(self):
        text = (
            "[clear social video host, natural voice, crisp consanants, "
            "confident delivery, no rush dialogue] Number 4: This joke flips the room."
        )

        sanitized = daily_editorial.elevenlabs_tts_text(text)

        self.assertEqual(sanitized, "Number 4: This joke flips the room.")
        self.assertNotIn("crisp", sanitized.lower())
        self.assertNotIn("delivery", sanitized.lower())
        self.assertNotIn("dialogue", sanitized.lower())

    def test_final_upload_frame_qc_samples_source_playback_window(self):
        final_path = os.path.join(
            ROOT,
            "output",
            "themes",
            "technology_ai",
            "content",
            "sample_upload.mp4",
        )
        metadata = {
            "content": [{
                "video_file": final_path,
                "intro_duration": 5.2,
                "rank_card_duration": 0.7,
                "source_play_duration": 42.0,
            }]
        }
        asset = {
            "path": final_path,
            "theme": "technology_ai",
            "asset_type": "final_upload",
        }

        with patch.object(content_qc, "load_json_file", return_value=metadata):
            window = content_qc.frame_sample_window_for_asset(asset, {"duration": 55.0})

        self.assertEqual(window["asset_type"], "final_upload_source")
        self.assertAlmostEqual(window["start_seconds"], 5.9)
        self.assertAlmostEqual(window["end_seconds"], 47.9)

    def test_mild_single_frame_center_jitter_is_not_severe_off_center(self):
        metrics = [
            {
                "plausible_face": True,
                "is_black": False,
                "low_info": False,
                "face_center_offset": 0.12,
                "largest_face_height_ratio": 0.20,
                "largest_face_skin_ratio": 0.30,
                "largest_face_edge_density": 0.08,
                "edge_density": 0.04,
                "laplacian": 500.0,
            }
            for _ in range(19)
        ]
        metrics.append({
            "plausible_face": True,
            "is_black": False,
            "low_info": False,
            "face_center_offset": 0.48,
            "largest_face_height_ratio": 0.20,
            "largest_face_skin_ratio": 0.30,
            "largest_face_edge_density": 0.08,
            "edge_density": 0.04,
            "laplacian": 500.0,
        })

        summary = content_qc.summarize_frame_metrics(metrics, "final_upload_source")

        self.assertNotIn("severe off-center frames", summary["flags"])
        self.assertGreater(summary["severe_face_center_offset_ratio"], 0.0)

    def test_sustained_center_miss_is_severe_off_center(self):
        metrics = [
            {
                "plausible_face": True,
                "is_black": False,
                "low_info": False,
                "face_center_offset": 0.54 if index < 4 else 0.16,
                "largest_face_height_ratio": 0.20,
                "largest_face_skin_ratio": 0.30,
                "largest_face_edge_density": 0.08,
                "edge_density": 0.04,
                "laplacian": 500.0,
            }
            for index in range(20)
        ]

        summary = content_qc.summarize_frame_metrics(metrics, "final_upload_source")

        self.assertIn("severe off-center frames", summary["flags"])

    def test_speaker_clip_ending_on_weak_face_is_flagged(self):
        metrics = [
            {
                "plausible_face": index < 9,
                "is_black": False,
                "low_info": False,
                "face_center_offset": 0.14 if index < 9 else None,
                "largest_face_height_ratio": 0.22 if index < 9 else 0.0,
                "largest_face_skin_ratio": 0.30,
                "largest_face_edge_density": 0.08,
                "edge_density": 0.04,
                "laplacian": 500.0,
            }
            for index in range(10)
        ]

        summary = content_qc.summarize_frame_metrics(metrics, "final_upload_source")

        self.assertIn("source playback ends without a strong face", summary["flags"])

    def test_tail_face_warning_is_not_secondary_rejection_reason(self):
        reasons = daily_editorial.editorial_secondary_frame_rejection_reasons({
            "sample_asset_type": "final_upload_source",
            "flags": ["source playback ends without a strong face"],
            "face_presence_rate": 0.92,
            "longest_no_face_run_ratio": 0.08,
            "avg_face_center_offset": 0.12,
            "max_face_center_offset": 0.18,
        })

        self.assertEqual(reasons, [])

    def test_secondary_off_center_warning_is_advisory_not_rejection(self):
        frame_qc = {
            "sample_asset_type": "final_upload_source",
            "flags": ["subject often off center", "severe off-center frames"],
            "face_presence_rate": 0.86,
            "longest_no_face_run_ratio": 0.05,
            "avg_face_center_offset": 0.34,
            "max_face_center_offset": 0.50,
        }

        self.assertEqual(daily_editorial.editorial_secondary_frame_rejection_reasons(frame_qc), [])
        advisories = daily_editorial.editorial_secondary_frame_advisory_reasons(frame_qc)
        self.assertTrue(any("off-center subject" in reason for reason in advisories))
        self.assertTrue(any("severe off-center frames" in reason for reason in advisories))

    def test_relaxed_theme_relevance_keeps_watchable_off_theme_clip_eligible(self):
        clip = {
            "theme": "finance",
            "transcript_excerpt": "The comedian tells a story about a strange dinner and the room starts laughing.",
            "source_tier": "",
            "render_qc": {
                "passed": True,
                "visual_quality_score": 0.74,
                "flags": [],
                "frame_path": {
                    "face_presence_rate": 0.82,
                    "longest_no_face_run_ratio": 0.08,
                    "alive_no_face_frame_ratio": 0.12,
                    "avg_face_center_offset_ratio": 0.16,
                    "max_face_center_offset_ratio": 0.22,
                    "avg_face_plausibility": 0.70,
                },
            },
        }

        self.assertFalse(daily_editorial.clip_has_theme_relevance("finance", clip))
        self.assertTrue(daily_editorial.clip_is_editorial_usable(clip))

    def test_plain_interview_closeup_is_not_low_information(self):
        frame = np.full((1920, 1080, 3), 112, dtype=np.uint8)
        frame[:, :360] = 62
        frame[300:1200, 280:820] = 188
        frame[420:900, 380:720] = 94

        metrics = content_qc.frame_metrics(frame, faces=[(380, 260, 300, 420)])

        self.assertFalse(metrics["low_info"])
        self.assertFalse(metrics["is_black"])

    def test_flat_empty_frame_is_low_information(self):
        frame = np.full((1920, 1080, 3), 24, dtype=np.uint8)

        metrics = content_qc.frame_metrics(frame, faces=[])

        self.assertTrue(metrics["low_info"])


if __name__ == "__main__":
    unittest.main()
