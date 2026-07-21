import unittest
from unittest.mock import patch

import media_encoding


class MediaEncodingTests(unittest.TestCase):
    def test_qsv_arguments_are_used_after_successful_probe(self):
        with patch.object(media_encoding, "qsv_available", return_value=True):
            args = media_encoding.video_encoder_args(quality=21)

        self.assertIn("h264_qsv", args)
        self.assertEqual(args[args.index("-r") + 1], "30")
        self.assertIn("-global_quality", args)
        self.assertNotIn("libx264", args)

    def test_software_arguments_remain_available(self):
        with patch.object(media_encoding, "qsv_available", return_value=False):
            args = media_encoding.video_encoder_args(quality=20, software_preset="fast")

        self.assertIn("libx264", args)
        self.assertIn("fast", args)

    def test_qsv_command_can_be_rewritten_for_software_fallback(self):
        command = [
            "ffmpeg", "-i", "input.mp4", "-r", "30",
            "-c:v", "h264_qsv", "-preset", "faster",
            "-global_quality", "20", "-pix_fmt", "nv12",
            "-c:a", "aac", "output.mp4",
        ]

        fallback = media_encoding.software_fallback_command(command, quality=20)

        self.assertIn("libx264", fallback)
        self.assertIn("-crf", fallback)
        self.assertNotIn("h264_qsv", fallback)
        self.assertNotIn("-global_quality", fallback)
