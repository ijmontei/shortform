import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import daily_editorial
import upload


class SourceCompletionTrackingTests(unittest.TestCase):
    def test_editorial_ready_package_marks_underlying_sources_completed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            executed_file = os.path.join(temp_dir, "executed.json")
            pulled_file = os.path.join(temp_dir, "pulled.json")
            metadata_file = os.path.join(temp_dir, "metadata.json")
            video_file = os.path.join(temp_dir, "ready.mp4")
            source_key = "comedy|https://www.youtube.com/watch?v=abc123"
            package = {
                "theme": "comedy",
                "content_format": "daily_editorial_short",
                "content_has_burned_captions": True,
                "upload_ready_requires_burned_captions": True,
                "posting_status": {"youtube_shorts": "ready"},
                "video_file": video_file,
                "source_state_key": "comedy|editorial|2026-06-30|1",
                "underlying_source_state_keys": [source_key],
                "source_video_url": "https://www.youtube.com/watch?v=abc123",
                "source_title": "A complete interview moment",
                "editorial_gates": {"passed": True, "flags": []},
                "render_qc": {"passed": True, "flags": [], "rejection_reasons": []},
            }

            with open(video_file, "wb") as handle:
                handle.write(b"mp4")

            with open(pulled_file, "w", encoding="utf-8") as handle:
                json.dump({source_key: {"theme": "comedy", "video_url": package["source_video_url"]}}, handle)

            with (
                patch.object(daily_editorial, "EXECUTED_FILE", executed_file),
                patch.object(daily_editorial, "PULLED_FILE", pulled_file),
            ):
                daily_editorial.mark_editorial_sources_completed("comedy", [package], metadata_file)

            with open(executed_file, "r", encoding="utf-8") as handle:
                executed = json.load(handle)
            with open(pulled_file, "r", encoding="utf-8") as handle:
                pulled = json.load(handle)

            self.assertIn(source_key, executed)
            self.assertEqual(executed[source_key]["funnel_status"], "subtitled")
            self.assertEqual(executed[source_key]["subtitle_status"], "complete")
            self.assertIn(package["video_file"], executed[source_key]["final_video_files"])
            self.assertIn(metadata_file, executed[source_key]["metadata_files"])
            self.assertEqual(pulled[source_key]["funnel_status"], "upload_ready")
            self.assertEqual(pulled[source_key]["subtitle_status"], "complete")

    def test_upload_marks_underlying_sources_uploaded(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            executed_file = os.path.join(temp_dir, "executed.json")
            source_key = "finance|https://www.youtube.com/watch?v=abc123"
            package = {
                "theme": "finance",
                "title": "The Money Question Nobody Asked",
                "video_file": os.path.join(temp_dir, "ready.mp4"),
                "source_state_key": "finance|editorial|2026-06-30|1",
                "underlying_source_state_keys": [source_key],
                "source_video_url": "https://www.youtube.com/watch?v=abc123",
                "source_title": "Finance Interview",
            }

            with (
                patch.object(upload, "EXECUTED_FILE", executed_file),
                patch.object(upload, "CURRENT_THEME", "finance"),
            ):
                upload.mark_executed_uploaded(package, {"id": "yt123"})

            with open(executed_file, "r", encoding="utf-8") as handle:
                executed = json.load(handle)

            self.assertIn(source_key, executed)
            self.assertEqual(executed[source_key]["funnel_status"], "uploaded")
            self.assertEqual(executed[source_key]["upload_status"], "uploaded")
            self.assertEqual(executed[source_key]["youtube_uploads"][0]["video_id"], "yt123")


if __name__ == "__main__":
    unittest.main()
