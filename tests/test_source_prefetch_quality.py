import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import clip_generation


class SourcePrefetchQualityTests(unittest.TestCase):
    def test_full_event_vod_is_disqualified_before_audio_download(self):
        record = {
            "video_url": "https://www.youtube.com/watch?v=example",
            "title": "Live From Highground [June 2026] - Day Two!",
        }

        disqualified, reasons = clip_generation.source_quality_disqualification(record)

        self.assertTrue(disqualified)
        self.assertTrue(any("broadcast/live-event vod" in reason for reason in reasons))

    def test_prefetch_does_not_download_disqualified_broadcast_vod(self):
        record = {
            "video_url": "https://www.youtube.com/watch?v=example",
            "title": "TLAW vs DCG | MSI 2026 | Stage | Game 03",
        }

        with patch.object(clip_generation, "download_audio_for_scoring") as download_mock:
            with self.assertRaises(clip_generation.SkippableVideoError):
                clip_generation.prefetch_audio_for_record(record)

        download_mock.assert_not_called()
        self.assertTrue(record.get("source_guard_disqualified"))
        self.assertTrue(record.get("source_quality_disqualified"))

    def test_creator_interview_is_not_broadcast_vod(self):
        record = {
            "video_url": "https://www.youtube.com/watch?v=example",
            "title": "Nadeshot on Building 100 Thieves and the Future of Esports",
        }

        disqualified, reasons = clip_generation.source_quality_disqualification(record)

        self.assertFalse(disqualified)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
