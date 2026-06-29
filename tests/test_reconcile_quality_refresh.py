import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import reconcile_editorial_gates


class ReconcileQualityRefreshTests(unittest.TestCase):
    def test_reconcile_refreshes_preupload_qc_for_upload_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metadata = {
                "theme": "comedy",
                "content": [
                    {
                        "title": "Ready Clip",
                        "posting_status": {"youtube_shorts": "ready"},
                    },
                    {
                        "title": "Revision Clip",
                        "posting_status": {"youtube_shorts": "needs_revision"},
                    },
                ],
            }
            paths = {
                "final_metadata_file": os.path.join(temp_dir, "metadata.json"),
                "output_path": temp_dir,
                "final_videos_path": os.path.join(temp_dir, "content"),
            }

            def refresh(package):
                package["preupload_qc_refreshed"] = True
                return package

            with (
                patch.object(reconcile_editorial_gates, "ensure_theme", return_value=paths),
                patch.object(reconcile_editorial_gates, "load_json_file", return_value=metadata),
                patch.object(reconcile_editorial_gates, "write_json_file"),
                patch.object(reconcile_editorial_gates, "refresh_preupload_quality", side_effect=refresh) as refresh_mock,
                patch.object(
                    reconcile_editorial_gates,
                    "evaluate_editorial_gates",
                    return_value={"passed": True, "flags": []},
                ),
            ):
                result = reconcile_editorial_gates.reconcile_theme("comedy")

        self.assertTrue(metadata["content"][0]["preupload_qc_refreshed"])
        self.assertNotIn("preupload_qc_refreshed", metadata["content"][1])
        self.assertEqual(refresh_mock.call_count, 1)
        self.assertEqual(result["checked_count"], 2)
        self.assertEqual(result["status_counts"]["ready"], 1)
        self.assertEqual(result["status_counts"]["needs_revision"], 1)
        self.assertEqual(result["refreshed_preupload_qc_count"], 1)
        self.assertTrue(result["report_file"].endswith("reconcile_comedy_latest.json"))


if __name__ == "__main__":
    unittest.main()
