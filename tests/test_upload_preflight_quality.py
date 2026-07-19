import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import upload


class UploadPreflightQualityTests(unittest.TestCase):
    def test_render_preflight_reuses_current_render_time_qc(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            signature = upload.media_file_signature(media.name)
            package = {
                "theme": "comedy",
                "video_file": media.name,
                "render_qc": {
                    "passed": True,
                    "flags": [],
                    "rejection_reasons": [],
                    "intro_audio": {"flags": []},
                    "render_time_qc_complete": True,
                    "validated_file_signature": signature,
                },
            }
            fake_content_qc = types.SimpleNamespace(
                analyze_asset=lambda *_args, **_kwargs: self.fail("frame QC should be reused"),
                analyze_audio_start=lambda *_args, **_kwargs: self.fail("audio QC should be reused"),
            )

            with patch.dict(sys.modules, {"content_qc": fake_content_qc}):
                upload.refresh_package_render_qc(package)
                upload.refresh_package_intro_audio_qc(package)

        self.assertTrue(package["render_qc"]["upload_preflight_reused_render_qc"])
        self.assertTrue(package["render_qc"]["upload_preflight_reused_audio_qc"])

    def test_intro_audio_preflight_rejects_clipped_audio(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "video_file": media.name,
                "render_qc": {
                    "passed": True,
                    "flags": [],
                    "rejection_reasons": [],
                },
            }
            fake_content_qc = types.SimpleNamespace(
                analyze_audio_start=lambda _path: {
                    "flags": ["possible clipped/distorted intro audio"],
                    "onset_seconds": 0.12,
                }
            )

            with patch.dict(sys.modules, {"content_qc": fake_content_qc}):
                upload.refresh_package_intro_audio_qc(package)

        render_qc = package["render_qc"]
        self.assertFalse(render_qc["passed"])
        self.assertTrue(render_qc["rejected"])
        self.assertIn("possible clipped/distorted intro audio", render_qc["flags"])
        self.assertIn("possible clipped/distorted intro audio", render_qc["rejection_reasons"])
        self.assertTrue(render_qc["upload_preflight_audio_refreshed"])

    def test_render_preflight_keeps_tail_miss_as_soft_review_flag(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "theme": "sports",
                "video_file": media.name,
                "render_qc": {
                    "passed": True,
                    "flags": [],
                    "rejection_reasons": [],
                },
            }
            fake_content_qc = types.SimpleNamespace(
                analyze_asset=lambda *_args, **_kwargs: {
                    "contact_sheet": "sheet.jpg",
                    "frame_sample_window": {"asset_type": "final_upload_source"},
                    "frame_qc": {
                        "flags": ["source playback ends without a strong face"],
                        "visual_quality_score": 0.82,
                    },
                }
            )

            with patch.dict(sys.modules, {"content_qc": fake_content_qc}):
                upload.refresh_package_render_qc(package)

        render_qc = package["render_qc"]
        self.assertTrue(render_qc["passed"])
        self.assertFalse(render_qc["rejected"])
        self.assertIn("source playback ends without a strong face", render_qc["flags"])
        self.assertNotIn("source playback ends without a strong face", render_qc["rejection_reasons"])
        self.assertTrue(render_qc["upload_preflight_refreshed"])

    def test_render_preflight_still_rejects_background_lock(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "theme": "sports",
                "video_file": media.name,
                "render_qc": {
                    "passed": True,
                    "flags": [],
                    "rejection_reasons": [],
                },
            }
            fake_content_qc = types.SimpleNamespace(
                analyze_asset=lambda *_args, **_kwargs: {
                    "contact_sheet": "sheet.jpg",
                    "frame_sample_window": {"asset_type": "final_upload_source"},
                    "frame_qc": {
                        "flags": ["probable background lock instead of speaker"],
                        "visual_quality_score": 0.62,
                    },
                }
            )

            with patch.dict(sys.modules, {"content_qc": fake_content_qc}):
                upload.refresh_package_render_qc(package)

        render_qc = package["render_qc"]
        self.assertFalse(render_qc["passed"])
        self.assertTrue(render_qc["rejected"])
        self.assertIn("probable background lock instead of speaker", render_qc["rejection_reasons"])

    def test_render_preflight_does_not_reject_off_center_only(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "theme": "sports",
                "video_file": media.name,
                "render_qc": {
                    "passed": True,
                    "flags": [],
                    "rejection_reasons": [],
                },
            }
            fake_content_qc = types.SimpleNamespace(
                analyze_asset=lambda *_args, **_kwargs: {
                    "contact_sheet": "sheet.jpg",
                    "frame_sample_window": {"asset_type": "final_upload_source"},
                    "frame_qc": {
                        "flags": ["subject severely off-center in final crop"],
                        "visual_quality_score": 0.74,
                    },
                }
            )

            with patch.dict(sys.modules, {"content_qc": fake_content_qc}):
                upload.refresh_package_render_qc(package)

        render_qc = package["render_qc"]
        self.assertTrue(render_qc["passed"])
        self.assertFalse(render_qc["rejected"])
        self.assertIn("subject severely off-center in final crop", render_qc["flags"])
        self.assertNotIn("subject severely off-center in final crop", render_qc["rejection_reasons"])

    def test_upload_does_not_repeat_editorial_copy_review_by_default(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "theme": "comedy",
                "video_file": media.name,
                "content_has_burned_captions": True,
                "upload_ready_requires_burned_captions": True,
                "render_qc": {
                    "passed": True,
                    "rejected": False,
                    "flags": [],
                    "rejection_reasons": [],
                    "intro_audio": {"flags": []},
                    "render_time_qc_complete": True,
                    "validated_file_signature": upload.media_file_signature(media.name),
                },
            }

            with (
                patch.object(upload, "evaluate_editorial_gates", side_effect=AssertionError("copy QA repeated")),
                patch.dict(os.environ, {"SHORTFORM_RECHECK_EDITORIAL_GATES_ON_UPLOAD": "0"}),
            ):
                reason = upload.review_skip_reason(package)

        self.assertEqual(reason, "")

    def test_upload_still_blocks_render_qc_failure(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as media:
            package = {
                "theme": "comedy",
                "video_file": media.name,
                "content_has_burned_captions": True,
                "render_qc": {
                    "passed": False,
                    "rejected": True,
                    "flags": ["probable background lock instead of speaker"],
                    "rejection_reasons": ["probable background lock instead of speaker"],
                    "intro_audio": {"flags": []},
                    "render_time_qc_complete": True,
                    "validated_file_signature": upload.media_file_signature(media.name),
                },
            }

            reason = upload.review_skip_reason(package)

        self.assertIn("render QC failed", reason)
        self.assertFalse(upload.force_can_bypass_review_skip({"privacy_status": "private"}, reason))


if __name__ == "__main__":
    unittest.main()
