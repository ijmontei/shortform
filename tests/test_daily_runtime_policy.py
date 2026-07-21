import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation
import daily_editorial
import run


class DailyRuntimePolicyTests(unittest.TestCase):
    def test_default_daily_targets_prioritize_consistent_ten_clip_cycles(self):
        self.assertEqual(clip_generation.PREFERRED_FINISHED_TARGET, 10)
        self.assertEqual(clip_generation.daily_render_target("comedy"), 10)
        self.assertEqual(daily_editorial.EDITORIAL_FINAL_PACKAGE_TARGET, 10)
        self.assertEqual(run.resolved_editorial_package_target(), 10)

    def test_default_discovery_depth_is_bounded(self):
        self.assertEqual(clip_generation.INITIAL_AUDIO_PREFETCH_SOURCES_PER_THEME, 4)
        self.assertEqual(clip_generation.MIN_SCORED_SOURCES_PER_THEME, 4)
        self.assertEqual(clip_generation.MAX_UNSCORED_SOURCES_PER_THEME, 6)
        self.assertEqual(clip_generation.SOURCE_CANDIDATE_CAP, 12)
        self.assertEqual(clip_generation.SIGNAL_TRANSCRIPT_MAX_WINDOWS, 4)
        self.assertEqual(clip_generation.CLIP_TRANSCRIBE_BEAM_SIZE, 1)
        self.assertEqual(clip_generation.ANALYSIS_AUDIO_MAX_ABR, 96)
        self.assertEqual(clip_generation.FACE_TARGET_SAMPLE_COUNT, 16)
        self.assertEqual(clip_generation.FINAL_FRAME_PATH_SAMPLE_COUNT, 10)

    def test_default_editorial_animation_uses_daily_render_settings(self):
        self.assertEqual(daily_editorial.EDITORIAL_INTRO_FPS, 24)
        self.assertEqual(daily_editorial.EDITORIAL_INTRO_BACKGROUND_FPS, 2.0)
        self.assertIn("daily target 10 finished clip(s) per theme", run.clip_generation_volume_label(["comedy"]))

    def test_default_framing_uses_only_the_lean_fallback_set(self):
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(clip_generation, "active_theme_profile", return_value={"profile": "comedy"}),
        ):
            os.environ.pop("SHORTFORM_ENABLE_EXPENSIVE_FRAMING_FALLBACKS", None)
            self.assertEqual(
                clip_generation.fallback_framing_strategies(),
                ["stable_face_lock", "center_safe"],
            )

    def test_faceless_center_crop_is_limited_to_visual_first_themes(self):
        preflight = {
            "flags": ["low preflight face presence"],
            "face_frames": 0,
            "alive_frame_rate": 0.96,
            "dead_frame_ratio": 0.0,
            "black_frame_ratio": 0.0,
            "avg_edge_density": 0.03,
        }

        with patch.object(clip_generation, "active_theme_allows_non_speaker_visual", return_value=True):
            self.assertTrue(clip_generation.preflight_allows_center_safe_render(preflight))

        with patch.object(clip_generation, "active_theme_allows_non_speaker_visual", return_value=False):
            self.assertFalse(clip_generation.preflight_allows_center_safe_render(preflight))

    def test_warning_only_raw_render_remains_editorially_usable(self):
        clip = {
            "theme": "comedy",
            "render_qc": {
                "frame_qc_version": daily_editorial.CURRENT_FRAME_QC_VERSION,
                "passed": False,
                "flags": ["unstable final subject position"],
                "visual_quality_score": 0.82,
                "frame_path": {
                    "face_presence_rate": 0.75,
                    "longest_no_face_run_ratio": 0.18,
                    "alive_no_face_frame_ratio": 0.20,
                    "avg_face_center_offset_ratio": 0.24,
                    "max_face_center_offset_ratio": 0.50,
                    "avg_face_plausibility": 0.70,
                },
            },
        }

        self.assertTrue(daily_editorial.clip_is_popular_segment_usable(clip))


if __name__ == "__main__":
    unittest.main()
