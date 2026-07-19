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


class PopularSegmentQualityTests(unittest.TestCase):
    def test_failed_source_render_qc_blocks_popular_segment(self):
        with (
            patch.object(daily_editorial, "clip_render_qc", return_value={"passed": False, "flags": []}),
            patch.object(daily_editorial, "clip_is_editorial_usable", return_value=True) as usable_mock,
        ):
            self.assertFalse(daily_editorial.clip_is_popular_segment_usable({"theme": "truecrime"}))
            usable_mock.assert_not_called()

    def test_passed_source_render_qc_delegates_to_editorial_gate(self):
        with (
            patch.object(daily_editorial, "clip_render_qc", return_value={"passed": True, "flags": []}),
            patch.object(daily_editorial, "clip_is_editorial_usable", return_value=True) as usable_mock,
        ):
            self.assertTrue(daily_editorial.clip_is_popular_segment_usable({"theme": "comedy"}))
            usable_mock.assert_called_once()

    def test_distinct_clips_from_one_source_are_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            first_file = os.path.join(directory, "first.mp4")
            second_file = os.path.join(directory, "second.mp4")

            for path in (first_file, second_file):
                with open(path, "wb") as handle:
                    handle.write(b"video")

            clips = [
                {
                    "output_file": first_file,
                    "source_state_key": "comedy|source",
                    "source_video_url": "https://www.youtube.com/watch?v=source",
                    "source_title": "Long Interview",
                    "start_time": 60,
                    "end_time": 105,
                    "score": 0.88,
                    "opening_score": 0.80,
                    "render_qc": {"passed": True},
                },
                {
                    "output_file": second_file,
                    "source_state_key": "comedy|source",
                    "source_video_url": "https://www.youtube.com/watch?v=source",
                    "source_title": "Long Interview",
                    "start_time": 600,
                    "end_time": 645,
                    "score": 0.84,
                    "opening_score": 0.78,
                    "render_qc": {"passed": True},
                },
            ]
            records = [{
                "state_key": "comedy|source",
                "video_url": "https://www.youtube.com/watch?v=source",
                "title": "Long Interview",
                "channel_name": "Interview Channel",
            }]

            with (
                patch.object(daily_editorial, "load_theme_source_records", return_value=records),
                patch.object(daily_editorial, "clip_is_popular_segment_usable", return_value=True),
                patch.object(daily_editorial, "enrich_clip_popularity", return_value=0.4),
                patch.object(daily_editorial, "popular_segment_publishable_copy", return_value=True),
                patch.object(daily_editorial, "download_youtube_thumbnail", return_value=""),
                patch.object(daily_editorial, "POPULAR_SEGMENT_REQUIRE_SIGNAL", False),
            ):
                items = daily_editorial.popular_segment_items("comedy", {}, clips)

        self.assertEqual(len(items), 2)
        self.assertEqual({item["clip"]["start_time"] for item in items}, {60, 600})

    def test_finished_editorial_packages_are_reused_for_topups(self):
        with tempfile.TemporaryDirectory() as directory:
            video_file = os.path.join(directory, "ready.mp4")
            metadata_file = os.path.join(directory, "metadata.json")

            with open(video_file, "wb") as handle:
                handle.write(b"video")

            package = {
                "editorial_date": "2026-07-19",
                "video_file": video_file,
                "content_format": "popular_segment_short",
                "content_has_burned_captions": True,
                "upload_ready_requires_burned_captions": True,
                "posting_status": {"youtube_shorts": "ready"},
                "render_qc": {"passed": True, "rejected": False, "rejection_reasons": []},
            }
            with open(metadata_file, "w", encoding="utf-8") as handle:
                json.dump({"content": [], "archive": [package]}, handle)

            packages = daily_editorial.reusable_editorial_packages(
                {"final_metadata_file": metadata_file},
                "2026-07-19",
            )

        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["video_file"], video_file)

    def test_reused_archive_package_stays_out_of_live_content_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            video_file = os.path.join(directory, "archived.mp4")
            metadata_file = os.path.join(directory, "metadata.json")

            with open(video_file, "wb") as handle:
                handle.write(b"video")

            package = {
                "theme": "comedy",
                "editorial_date": "2026-07-19",
                "video_file": video_file,
                "content_has_burned_captions": True,
                "underlying_source_state_keys": [],
            }
            with open(metadata_file, "w", encoding="utf-8") as handle:
                json.dump({"content": [], "archive": [package]}, handle)

            paths = {"final_metadata_file": metadata_file}
            brief = {"date": "2026-07-19"}
            with patch.dict(os.environ, {"SHORTFORM_DEFER_EDITORIAL_SOURCE_COMPLETION": "1"}):
                daily_editorial.save_editorial_metadata("comedy", paths, [package], brief)

            with open(metadata_file, "r", encoding="utf-8") as handle:
                saved = json.load(handle)

        self.assertEqual(saved["content"], [])
        self.assertEqual(len(saved["archive"]), 1)


if __name__ == "__main__":
    unittest.main()
