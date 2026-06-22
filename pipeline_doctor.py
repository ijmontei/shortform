import os
import shutil
import sys

import yt_dlp

import ytdlp_auth
from theme_config import BASE_DIR, discover_themes, get_theme_paths, load_theme_config


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")


def status_line(ok, label, detail=""):
    marker = "OK" if ok else "FAIL"
    text = f"[{marker}] {label}"

    if detail:
        text = f"{text}: {detail}"

    print(text)
    return ok


def find_executable(primary_path, fallback_name):
    if os.path.exists(primary_path):
        return primary_path

    resolved = shutil.which(fallback_name)
    return resolved or ""


def check_runtime():
    checks = []
    checks.append(status_line(sys.version_info >= (3, 10), "Python", sys.version.split()[0]))

    ffmpeg = find_executable(FFMPEG_EXE, "ffmpeg")
    ffprobe = find_executable(FFPROBE_EXE, "ffprobe")
    checks.append(status_line(bool(ffmpeg), "FFmpeg", ffmpeg or "not found"))
    checks.append(status_line(bool(ffprobe), "FFprobe", ffprobe or "not found"))

    version = getattr(yt_dlp.version, "__version__", "")
    checks.append(status_line(bool(version), "yt-dlp", version or "unknown"))
    return checks


def check_themes():
    checks = []
    themes = discover_themes()
    checks.append(status_line(bool(themes), "Themes discovered", ", ".join(themes) or "none"))

    for theme in themes:
        config = load_theme_config(theme)
        paths = get_theme_paths(theme)
        channels = config.get("channels", [])
        youtube = config.get("youtube", {})
        handle = youtube.get("channel_handle", "")
        token_file = youtube.get("token_file", "")

        checks.append(status_line(bool(channels), f"{theme} channels", f"{len(channels)} configured"))

        if handle:
            detail = handle

            if token_file:
                detail = f"{detail}, token={token_file}"

            checks.append(status_line(True, f"{theme} YouTube routing", detail))
        else:
            checks.append(status_line(False, f"{theme} YouTube routing", f"missing youtube.channel_handle in {paths['theme_config_file']}"))

    return checks


def check_auth():
    if not ytdlp_auth.media_auth_required():
        return [status_line(True, "Restricted-video auth", "not required by current environment")]

    try:
        result = ytdlp_auth.verify_youtube_auth()
    except Exception as error:
        return [status_line(False, "Restricted-video auth", str(error).splitlines()[0])]

    return [status_line(True, "Restricted-video auth", f"{result['id']} - {result['title']}")]


def run_doctor(include_auth=True):
    print(f"shortform pipeline doctor: {BASE_DIR}\n")
    checks = []
    checks.extend(check_runtime())
    print("")
    checks.extend(check_themes())
    print("")

    if include_auth:
        checks.extend(check_auth())
        print("")

    passed = all(checks)
    status_line(passed, "Pipeline doctor", "all checks passed" if passed else "one or more checks failed")
    return passed


if __name__ == "__main__":
    sys.exit(0 if run_doctor(include_auth=True) else 1)
