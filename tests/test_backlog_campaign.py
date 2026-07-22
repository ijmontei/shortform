import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import run
import video_fetch


class BacklogCampaignTests(unittest.TestCase):
    def test_historical_channel_fetch_returns_multiple_playable_videos(self):
        info = {
            "entries": [
                {"id": "abcdefghijk", "title": "First"},
                {"id": "lmnopqrstuv", "title": "Second"},
                {"id": "not-video", "title": "Invalid"},
            ]
        }

        with patch.object(video_fetch, "run_ytdlp_with_cookie_fallback", return_value=info):
            videos = video_fetch.videos_for_channel("https://www.youtube.com/@Example/videos", limit=3)

        self.assertEqual([item["title"] for item in videos], ["First", "Second"])
        self.assertEqual(videos[0]["video_url"], "https://www.youtube.com/watch?v=abcdefghijk")

    def test_finished_backlog_count_requires_metadata_and_existing_video(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ready_file = os.path.join(temp_dir, "ready.mp4")
            archived_file = os.path.join(temp_dir, "archived.mp4")
            open(ready_file, "wb").close()
            open(archived_file, "wb").close()
            metadata_file = os.path.join(temp_dir, "metadata.json")

            with open(metadata_file, "w", encoding="utf-8") as handle:
                json.dump({
                    "content": [
                        {
                            "video_file": ready_file,
                            "editorial_date": "2026-07-22",
                            "content_has_burned_captions": True,
                            "posting_status": {"youtube_shorts": "ready"},
                        },
                        {
                            "video_file": os.path.join(temp_dir, "missing.mp4"),
                            "posting_status": {"youtube_shorts": "ready"},
                        },
                    ],
                    "archive": [
                        {
                            "video_file": archived_file,
                            "editorial_date": "2026-07-21",
                            "content_has_burned_captions": True,
                            "posting_status": {"youtube_shorts": "failed"},
                        }
                    ],
                }, handle)

            with patch.object(run, "get_theme_paths", return_value={"final_metadata_file": metadata_file}):
                self.assertEqual(run.theme_finished_backlog_count("comedy"), 2)
                self.assertEqual(
                    run.theme_finished_backlog_count("comedy", editorial_date="2026-07-22"),
                    1,
                )

    def test_backlog_payload_reports_remaining_and_disables_uploads(self):
        args = SimpleNamespace(
            backlog_target_per_theme=500,
            source_videos_per_channel=50,
        )

        with patch.object(run, "theme_finished_backlog_count", side_effect=[120, 500]):
            payload = run.backlog_campaign_payload(["comedy", "finance"], args, stage="render")

        self.assertFalse(payload["uploads_enabled"])
        self.assertEqual(payload["themes"]["comedy"]["remaining"], 380)
        self.assertTrue(payload["themes"]["finance"]["target_met"])

    def test_backlog_cli_options_parse(self):
        with patch.object(
            sys,
            "argv",
            ["run.py", "--backlog-target-per-theme", "500", "--source-videos-per-channel", "50"],
        ):
            args = run.parse_args()

        self.assertEqual(args.backlog_target_per_theme, 500)
        self.assertEqual(args.source_videos_per_channel, 50)


if __name__ == "__main__":
    unittest.main()
