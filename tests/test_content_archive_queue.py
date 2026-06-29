import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from content_archive import archive_overflow_packages, promote_archive_packages


def ready_package(path, title):
    return {
        "title": title,
        "video_file": path,
        "content_format": "daily_editorial_short",
        "source_state_key": title.lower().replace(" ", "_"),
        "posting_status": {"youtube_shorts": "ready"},
        "content_has_burned_captions": True,
    }


class ContentArchiveQueueTests(unittest.TestCase):
    def test_overflow_packages_move_to_archive_after_queue_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            content_dir = os.path.join(temp_dir, "content")
            archive_dir = os.path.join(temp_dir, "archive")
            os.makedirs(content_dir, exist_ok=True)

            first = os.path.join(content_dir, "first.mp4")
            second = os.path.join(content_dir, "second.mp4")

            for path in [first, second]:
                with open(path, "wb") as handle:
                    handle.write(b"video")

            content = [ready_package(first, "First"), ready_package(second, "Second")]
            retained, archive, archived = archive_overflow_packages(content, [], archive_dir, queue_limit=1)

            self.assertEqual(len(retained), 1)
            self.assertEqual(len(archive), 1)
            self.assertEqual(len(archived), 1)
            self.assertTrue(retained[0]["video_file"].endswith("first.mp4"))
            self.assertTrue(os.path.exists(archive[0]["video_file"]))
            self.assertIn(os.path.abspath(archive_dir), os.path.abspath(archive[0]["video_file"]))
            self.assertEqual(archive[0]["archive_status"], "archived_overflow")

    def test_promote_archive_packages_moves_back_to_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            content_dir = os.path.join(temp_dir, "content")
            archive_dir = os.path.join(temp_dir, "archive")
            os.makedirs(archive_dir, exist_ok=True)

            archived_file = os.path.join(archive_dir, "queued.mp4")
            with open(archived_file, "wb") as handle:
                handle.write(b"video")

            archive = [ready_package(archived_file, "Queued")]
            remaining_archive, promoted = promote_archive_packages(archive, [], content_dir, queue_limit=15)

            self.assertEqual(remaining_archive, [])
            self.assertEqual(len(promoted), 1)
            self.assertTrue(os.path.exists(promoted[0]["video_file"]))
            self.assertIn(os.path.abspath(content_dir), os.path.abspath(promoted[0]["video_file"]))
            self.assertEqual(promoted[0]["archive_status"], "promoted")


if __name__ == "__main__":
    unittest.main()
