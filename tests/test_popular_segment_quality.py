import os
import sys
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


if __name__ == "__main__":
    unittest.main()
