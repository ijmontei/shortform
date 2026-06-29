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
                patch.object(run, "reset_funnel_state_for_themes", return_value=(0, 0)),
            ):
                result = run.clean_generated_artifacts(["truecrime"])

            self.assertGreaterEqual(len(result["removed_paths"]), 5)
            self.assertFalse(os.path.exists(os.path.join(theme_root, "needs_revision", "artifact.txt")))
            self.assertFalse(os.path.exists(os.path.join(theme_root, "rejected", "artifact.txt")))
            self.assertFalse(os.path.exists(paths["final_metadata_file"]))


if __name__ == "__main__":
    unittest.main()
