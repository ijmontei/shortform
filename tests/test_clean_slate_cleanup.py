import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import run


class CleanSlateCleanupTests(unittest.TestCase):
    def test_clean_slate_removes_revision_holding_folders(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "truecrime")
            temp_theme_root = os.path.join(temp_dir, "temp", "truecrime")
            metadata_path = os.path.join(temp_theme_root, "metadata")
            paths = {
                "output_path": theme_root,
                "final_videos_path": os.path.join(theme_root, "content"),
                "final_metadata_file": os.path.join(theme_root, "metadata.json"),
                "clips_path": os.path.join(temp_theme_root, "clips"),
                "subtitle_temp_path": os.path.join(temp_theme_root, "subtitles"),
                "metadata_path": metadata_path,
            }

            for folder in [
                paths["final_videos_path"],
                os.path.join(theme_root, "needs_revision"),
                os.path.join(theme_root, "rejected"),
                paths["clips_path"],
                paths["subtitle_temp_path"],
                metadata_path,
            ]:
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, "artifact.txt"), "w", encoding="utf-8") as handle:
                    handle.write("stale")

            with open(paths["final_metadata_file"], "w", encoding="utf-8") as handle:
                handle.write("{}")

            def fake_paths(_theme, create=False):
                if create:
                    for key in [
                        "output_path",
                        "final_videos_path",
                        "clips_path",
                        "subtitle_temp_path",
                        "metadata_path",
                    ]:
                        os.makedirs(paths[key], exist_ok=True)
                return paths

            with (
                patch.object(run, "get_theme_paths", side_effect=fake_paths),
                patch.object(run, "reset_funnel_state_for_themes", return_value=(0, 0)) as reset_mock,
            ):
                result = run.clean_generated_artifacts(["truecrime"])

            self.assertGreaterEqual(len(result["removed_paths"]), 5)
            self.assertFalse(os.path.exists(os.path.join(theme_root, "needs_revision", "artifact.txt")))
            self.assertFalse(os.path.exists(os.path.join(theme_root, "rejected", "artifact.txt")))
            self.assertFalse(os.path.exists(paths["final_metadata_file"]))
            self.assertTrue(result["preserved_funnel_history"])
            reset_mock.assert_not_called()

    def test_clean_slate_can_explicitly_reset_funnel_history(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "truecrime")
            temp_theme_root = os.path.join(temp_dir, "temp", "truecrime")
            paths = {
                "output_path": theme_root,
                "final_videos_path": os.path.join(theme_root, "content"),
                "final_metadata_file": os.path.join(theme_root, "metadata.json"),
                "clips_path": os.path.join(temp_theme_root, "clips"),
                "subtitle_temp_path": os.path.join(temp_theme_root, "subtitles"),
                "metadata_path": os.path.join(temp_theme_root, "metadata"),
            }

            def fake_paths(_theme, create=False):
                if create:
                    for key in ["output_path", "final_videos_path", "clips_path", "subtitle_temp_path", "metadata_path"]:
                        os.makedirs(paths[key], exist_ok=True)
                return paths

            with (
                patch.object(run, "get_theme_paths", side_effect=fake_paths),
                patch.object(run, "reset_funnel_state_for_themes", return_value=(3, 7)) as reset_mock,
            ):
                result = run.clean_generated_artifacts(["truecrime"], reset_funnel_history=True)

            reset_mock.assert_called_once()
            self.assertFalse(result["preserved_funnel_history"])
            self.assertEqual(result["removed_executed_records"], 3)
            self.assertEqual(result["reset_pulled_records"], 7)

    def test_clean_slate_preserves_unuploaded_ready_queue_when_history_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "technology_ai")
            temp_theme_root = os.path.join(temp_dir, "temp", "technology_ai")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            ready_video = os.path.join(content_dir, "ready_upload.mp4")
            paths = {
                "output_path": theme_root,
                "archive_path": archive_dir,
                "final_videos_path": content_dir,
                "final_metadata_file": metadata_file,
                "clips_path": os.path.join(temp_theme_root, "clips"),
                "subtitle_temp_path": os.path.join(temp_theme_root, "subtitles"),
                "metadata_path": os.path.join(temp_theme_root, "metadata"),
            }

            os.makedirs(content_dir, exist_ok=True)
            os.makedirs(paths["clips_path"], exist_ok=True)
            with open(ready_video, "wb") as handle:
                handle.write(b"ready")
            run.write_json_file(metadata_file, {
                "theme": "technology_ai",
                "content": [{
                    "theme": "technology_ai",
                    "title": "AI Advisors Make Coordination Harder",
                    "video_file": ready_video,
                    "source_state_key": "technology_ai|https://example.com/video",
                    "content_format": "daily_editorial_short",
                    "posting_status": {"youtube_shorts": "ready"},
                }],
                "archive": [],
                "daily_editorial": {"date": "2026-06-30"},
            })

            def fake_paths(_theme, create=False):
                if create:
                    for key in [
                        "output_path",
                        "archive_path",
                        "final_videos_path",
                        "clips_path",
                        "subtitle_temp_path",
                        "metadata_path",
                    ]:
                        os.makedirs(paths[key], exist_ok=True)
                return paths

            with (
                patch.object(run, "get_theme_paths", side_effect=fake_paths),
                patch.object(run, "reset_funnel_state_for_themes", return_value=(0, 0)) as reset_mock,
            ):
                result = run.clean_generated_artifacts(["technology_ai"])

            reset_mock.assert_not_called()
            self.assertEqual(result["preserved_upload_ready_packages"], 1)
            self.assertFalse(os.path.exists(ready_video))
            restored = run.load_json_file(metadata_file, {})
            self.assertEqual(restored["content"], [])
            self.assertEqual(len(restored["archive"]), 1)
            self.assertEqual(restored["archive"][0]["archive_status"], "preserved_clean_slate")
            self.assertTrue(os.path.exists(restored["archive"][0]["video_file"]))
            self.assertIn(os.path.abspath(archive_dir), os.path.abspath(restored["archive"][0]["video_file"]))
            self.assertTrue(result["preserved_funnel_history"])

    def test_clean_slate_can_discard_backlog_without_resetting_source_history(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "technology_ai")
            temp_theme_root = os.path.join(temp_dir, "temp", "technology_ai")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            paths = {
                "output_path": theme_root,
                "archive_path": archive_dir,
                "final_videos_path": content_dir,
                "final_metadata_file": metadata_file,
                "clips_path": os.path.join(temp_theme_root, "clips"),
                "subtitle_temp_path": os.path.join(temp_theme_root, "subtitles"),
                "metadata_path": os.path.join(temp_theme_root, "metadata"),
            }

            for directory in (content_dir, archive_dir, paths["clips_path"], paths["metadata_path"]):
                os.makedirs(directory, exist_ok=True)

            with open(os.path.join(archive_dir, "old.mp4"), "wb") as handle:
                handle.write(b"old")
            run.write_json_file(metadata_file, {"content": [], "archive": []})

            def fake_paths(_theme, create=False):
                if create:
                    for key in ["output_path", "archive_path", "final_videos_path", "clips_path", "subtitle_temp_path", "metadata_path"]:
                        os.makedirs(paths[key], exist_ok=True)
                return paths

            with (
                patch.object(run, "get_theme_paths", side_effect=fake_paths),
                patch.object(run, "reset_funnel_state_for_themes", return_value=(0, 0)) as reset_mock,
            ):
                result = run.clean_generated_artifacts(
                    ["technology_ai"],
                    discard_existing_backlog=True,
                )

            reset_mock.assert_not_called()
            self.assertTrue(result["preserved_funnel_history"])
            self.assertTrue(result["discarded_existing_backlog"])
            self.assertEqual(result["preserved_upload_ready_packages"], 0)
            self.assertFalse(os.path.exists(os.path.join(archive_dir, "old.mp4")))


if __name__ == "__main__":
    unittest.main()
