import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation


def render_qc(theme="technology_ai", low_information=0.08, blank_background=0.05):
    return {
        "flags": ["intermittent low-information/background speaker miss"],
        "visual_quality_score": 0.76,
        "frame_path": {
            "visual_quality_score": 0.76,
            "low_information_frame_ratio": low_information,
            "blank_background_frame_ratio": blank_background,
            "dead_frame_ratio": 0.0,
            "black_frame_ratio": 0.0,
            "face_presence_rate": 0.72,
            "alive_no_face_frame_ratio": 0.18,
            "longest_no_face_run_ratio": 0.16,
            "avg_face_center_offset_ratio": 0.18,
            "max_face_center_offset_ratio": 0.34,
            "avg_face_height_ratio": 0.14,
            "avg_face_plausibility": 0.58,
        },
        "theme": theme,
    }


class RenderQcBackgroundMissTests(unittest.TestCase):
    def test_speaker_clip_rejects_intermittent_blank_background_miss(self):
        with patch.object(clip_generation, "CURRENT_THEME", "technology_ai"):
            reasons = clip_generation.render_rejection_reasons(render_qc())

        self.assertIn("intermittent low-information/background speaker miss", reasons)
        self.assertTrue(
            any(reason.startswith("speaker crop intermittently lands") for reason in reasons)
        )

    def test_visual_action_theme_can_still_pass_alive_non_speaker_footage(self):
        qc = render_qc(theme="sports", low_information=0.03, blank_background=0.0)
        qc["flags"] = ["low final face presence", "alive frames often miss speaker"]
        qc["frame_path"].update({
            "face_presence_rate": 0.02,
            "alive_no_face_frame_ratio": 0.66,
            "longest_no_face_run_ratio": 0.52,
            "avg_face_height_ratio": 0.0,
            "avg_face_plausibility": 0.0,
        })

        with patch.object(clip_generation, "CURRENT_THEME", "sports"):
            reasons = clip_generation.render_rejection_reasons(qc)

        self.assertEqual(reasons, [])
        self.assertTrue(qc["non_speaker_visual_ok"])


if __name__ == "__main__":
    unittest.main()
