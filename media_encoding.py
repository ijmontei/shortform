import os
import subprocess
import threading


_ENCODER_LOCK = threading.Lock()
_QSV_AVAILABLE = None


def _ffmpeg_executable():
    return os.getenv("FFMPEG_EXE", "ffmpeg")


def qsv_available():
    global _QSV_AVAILABLE

    preference = os.getenv("SHORTFORM_HARDWARE_ENCODER", "auto").strip().lower()

    if preference in {"off", "none", "software", "libx264"}:
        return False

    if _QSV_AVAILABLE is not None:
        return _QSV_AVAILABLE

    with _ENCODER_LOCK:
        if _QSV_AVAILABLE is not None:
            return _QSV_AVAILABLE

        command = [
            _ffmpeg_executable(),
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "color=c=black:s=128x128:r=30:d=0.10",
            "-an",
            "-c:v", "h264_qsv",
            "-preset", "faster",
            "-global_quality", "21",
            "-pix_fmt", "nv12",
            "-f", "null",
            "NUL" if os.name == "nt" else "/dev/null",
        ]

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            _QSV_AVAILABLE = result.returncode == 0
        except Exception:
            _QSV_AVAILABLE = False

    return _QSV_AVAILABLE


def video_encoder_args(quality=20, software_preset="veryfast"):
    if qsv_available():
        return [
            "-r", os.getenv("SHORTFORM_OUTPUT_FPS", "30"),
            "-c:v", "h264_qsv",
            "-preset", os.getenv("SHORTFORM_QSV_PRESET", "faster"),
            "-global_quality", str(max(1, int(quality))),
            "-pix_fmt", "nv12",
        ]

    return [
        "-c:v", "libx264",
        "-preset", software_preset,
        "-crf", str(max(1, int(quality))),
        "-pix_fmt", "yuv420p",
    ]


def encoder_label():
    return "h264_qsv" if qsv_available() else "libx264"


def disable_qsv():
    global _QSV_AVAILABLE

    with _ENCODER_LOCK:
        _QSV_AVAILABLE = False


def software_fallback_command(command, quality=20, software_preset="veryfast"):
    fallback = list(command)

    for index in range(len(fallback) - 1):
        if fallback[index:index + 2] != ["-c:v", "h264_qsv"]:
            continue

        end = index + 2

        while end + 1 < len(fallback) and fallback[end] in {
            "-preset",
            "-global_quality",
            "-pix_fmt",
        }:
            end += 2

        fallback[index:end] = [
            "-c:v", "libx264",
            "-preset", software_preset,
            "-crf", str(max(1, int(quality))),
            "-pix_fmt", "yuv420p",
        ]
        return fallback

    return fallback
