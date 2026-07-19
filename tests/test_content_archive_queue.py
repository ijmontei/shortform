import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import content_archive


class ContentArchiveQueueTests(unittest.TestCase):
    def test_prepare_upload_queue_drops_metadata_for_missing_video_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "technology_ai")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            os.makedirs(content_dir, exist_ok=True)
            os.makedirs(archive_dir, exist_ok=True)
            content_archive.write_json_file(metadata_file, {
                "theme": "technology_ai",
                "content": [{
                    "title": "Missing Clip",
                    "video_file": os.path.join(content_dir, "missing.mp4"),
                    "content_format": "daily_editorial_short",
                    "source_state_key": "technology_ai|missing",
                    "posting_status": {"youtube_shorts": "ready"},
                }],
                "archive": [],
            })
            paths = {
                "output_path": theme_root,
                "final_videos_path": content_dir,
                "archive_path": archive_dir,
                "final_metadata_file": metadata_file,
            }

            with patch.object(content_archive, "ensure_theme", return_value=paths):
                result = content_archive.prepare_upload_queue("technology_ai", queue_limit=15)

            metadata = content_archive.load_json_file(metadata_file, {})
            self.assertEqual(result["dropped_missing_count"], 1)
            self.assertEqual(metadata["content"], [])
            self.assertEqual(metadata["archive"], [])
            self.assertEqual(metadata["dropped_missing_outputs"][0]["title"], "Missing Clip")

    def test_prepare_upload_queue_moves_revision_packages_out_of_content(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "sports")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            video_file = os.path.join(content_dir, "needs_revision.mp4")
            os.makedirs(content_dir, exist_ok=True)
            with open(video_file, "wb") as handle:
                handle.write(b"video")
            content_archive.write_json_file(metadata_file, {
                "theme": "sports",
                "content": [{
                    "title": "Needs Work",
                    "video_file": video_file,
                    "content_format": "popular_segment_short",
                    "source_state_key": "sports|revision",
                    "posting_status": {"youtube_shorts": "needs_revision"},
                }],
                "archive": [],
            })
            paths = {
                "output_path": theme_root,
                "final_videos_path": content_dir,
                "archive_path": archive_dir,
                "final_metadata_file": metadata_file,
            }

            with patch.object(content_archive, "ensure_theme", return_value=paths):
                result = content_archive.prepare_upload_queue("sports", queue_limit=15)

            metadata = content_archive.load_json_file(metadata_file, {})
            self.assertEqual(result["revision_moved_count"], 1)
            self.assertEqual(metadata["content"], [])
            self.assertEqual(len(metadata["needs_revision"]), 1)
            self.assertEqual(metadata["needs_revision"][0]["title"], "Needs Work")

    def test_prepare_upload_queue_rescues_orphan_content_videos(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "popculture")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            orphan_file = os.path.join(content_dir, "2026-07-07_popculture_popular_01_Lost_Clip_upload.mp4")
            os.makedirs(content_dir, exist_ok=True)
            os.makedirs(archive_dir, exist_ok=True)

            with open(orphan_file, "wb") as handle:
                handle.write(b"video")

            content_archive.write_json_file(metadata_file, {
                "theme": "popculture",
                "content": [],
                "archive": [],
            })
            paths = {
                "output_path": theme_root,
                "final_videos_path": content_dir,
                "archive_path": archive_dir,
                "final_metadata_file": metadata_file,
            }

            with patch.object(content_archive, "ensure_theme", return_value=paths):
                result = content_archive.prepare_upload_queue("popculture", queue_limit=15)

            metadata = content_archive.load_json_file(metadata_file, {})
            self.assertEqual(result["rescued_orphan_count"], 1)
            self.assertEqual(len(metadata["content"]), 1)
            self.assertEqual(metadata["content"][0]["video_file"], orphan_file)
            self.assertEqual(metadata["content"][0]["posting_status"]["youtube_shorts"], "ready")
            self.assertTrue(metadata["content"][0]["content_has_burned_captions"])

    def test_prepare_upload_queue_promotes_archive_until_queue_limit(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            theme_root = os.path.join(temp_dir, "themes", "gaming")
            content_dir = os.path.join(theme_root, "content")
            archive_dir = os.path.join(theme_root, "archive")
            metadata_file = os.path.join(theme_root, "metadata.json")
            os.makedirs(content_dir, exist_ok=True)
            os.makedirs(archive_dir, exist_ok=True)
            content_file = os.path.join(content_dir, "content.mp4")
            archived_file = os.path.join(archive_dir, "archived.mp4")

            for path in (content_file, archived_file):
                with open(path, "wb") as handle:
                    handle.write(b"video")

            content_archive.write_json_file(metadata_file, {
                "theme": "gaming",
                "content": [{
                    "title": "Queued Clip",
                    "video_file": content_file,
                    "content_format": "popular_segment_short",
                    "source_state_key": "gaming|queued",
                    "posting_status": {"youtube_shorts": "ready"},
                }],
                "archive": [{
                    "title": "Archived Clip",
                    "video_file": archived_file,
                    "content_format": "popular_segment_short",
                    "source_state_key": "gaming|archived",
                    "posting_status": {"youtube_shorts": "ready"},
                }],
            })
            paths = {
                "output_path": theme_root,
                "final_videos_path": content_dir,
                "archive_path": archive_dir,
                "final_metadata_file": metadata_file,
            }

            with patch.object(content_archive, "ensure_theme", return_value=paths):
                result = content_archive.prepare_upload_queue("gaming", queue_limit=2)

            metadata = content_archive.load_json_file(metadata_file, {})
            self.assertEqual(result["promoted_count"], 1)
            self.assertEqual(len(metadata["content"]), 2)
            self.assertEqual(len(metadata["archive"]), 0)
            self.assertTrue(os.path.exists(os.path.join(content_dir, "archived.mp4")))


if __name__ == "__main__":
    unittest.main()
