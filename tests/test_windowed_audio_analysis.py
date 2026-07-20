import json
import os
import tempfile
import unittest
import wave
from unittest.mock import patch

import numpy as np

import clip_generation


class WindowedAudioAnalysisTests(unittest.TestCase):
    def test_window_features_keep_source_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_file = os.path.join(directory, "source.m4a")
            window_file = os.path.join(directory, "window.wav")

            with open(audio_file, "wb") as f:
                f.write(b"windowed-audio-placeholder")

            samples = (
                np.sin(np.linspace(0, np.pi * 80, 16_000)) * 12_000
            ).astype(np.int16)
            with wave.open(window_file, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16_000)
                wav_file.writeframes(samples.tobytes())

            manifest = {
                "source_duration_seconds": 10,
                "windows": [{
                    "file": window_file,
                    "source_start": 4,
                    "source_end": 5,
                }],
            }
            with open(clip_generation.audio_window_manifest_path(audio_file), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            with (
                patch.object(clip_generation, "audio_path", directory),
                patch.object(clip_generation, "transcriptions_path", directory),
            ):
                payload = clip_generation.analyze_audio_features(
                    audio_file,
                    "source",
                    analysis_windows=[(4, 5)],
                    source_duration=10,
                )

        self.assertEqual(payload["analysis_scope"]["mode"], "signal_windows")
        self.assertEqual(len(payload["seconds"]), 10)
        self.assertEqual(payload["seconds"][0]["energy"], 0.0)
        self.assertGreaterEqual(payload["seconds"][4]["peak"], 0.0)

    def test_compressed_window_is_converted_before_wave_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            audio_file = os.path.join(directory, "source.m4a")
            compressed_window = os.path.join(directory, "window.m4a")

            with open(audio_file, "wb") as f:
                f.write(b"windowed-audio-placeholder")
            with open(compressed_window, "wb") as f:
                f.write(b"compressed-media-not-riff")

            manifest = {
                "source_duration_seconds": 10,
                "windows": [{
                    "file": compressed_window,
                    "source_start": 4,
                    "source_end": 5,
                }],
            }
            with open(clip_generation.audio_window_manifest_path(audio_file), "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            def fake_conversion(command, _label):
                output_file = command[-1]
                samples = np.zeros(16_000, dtype=np.int16)
                with wave.open(output_file, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(16_000)
                    wav_file.writeframes(samples.tobytes())

            with (
                patch.object(clip_generation, "audio_path", directory),
                patch.object(clip_generation, "transcriptions_path", directory),
                patch.object(clip_generation, "run_subprocess", side_effect=fake_conversion) as conversion,
            ):
                payload = clip_generation.analyze_audio_features(
                    audio_file,
                    "source",
                    analysis_windows=[(4, 5)],
                    source_duration=10,
                )

        conversion.assert_called_once()
        self.assertEqual(payload["analysis_scope"]["mode"], "signal_windows")
        self.assertEqual(len(payload["seconds"]), 10)
