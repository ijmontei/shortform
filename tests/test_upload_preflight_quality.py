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


if __name__ == "__main__":
    unittest.main()
