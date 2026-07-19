import unittest
from unittest.mock import patch

import media_encoding


class MediaEncodingTests(unittest.TestCase):
    def test_qsv_arguments_are_used_after_successful_probe(self):
        with patch.object(media_encoding, "qsv_available", return_value=True):
            args = media_encoding.video_encoder_args(quality=21)

        self.assertIn("h264_qsv", args)
        self.assertIn("-global_quality", args)
        self.assertNotIn("libx264", args)

    def test_software_arguments_remain_available(self):
        with patch.object(media_encoding, "qsv_available", return_value=False):
            args = media_encoding.video_encoder_args(quality=20, software_preset="fast")

        self.assertIn("libx264", args)
        self.assertIn("fast", args)
