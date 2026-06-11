import json
import os
import re
import time


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(BASE_DIR, "src")
THEMES_SRC_PATH = os.path.join(SRC_PATH, "themes")
PULLED_FILE = os.path.join(SRC_PATH, "pulled.json")
EXECUTED_FILE = os.path.join(SRC_PATH, "executed_id.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "output")
TEMP_PATH = os.path.join(OUTPUT_PATH, "temp")
THEMES_OUTPUT_PATH = os.path.join(OUTPUT_PATH, "themes")
DEFAULT_THEME = "self_improvement"


def clean_theme_name(theme_name):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(theme_name).strip().lower())
    cleaned = cleaned.strip("_-")
    return cleaned or DEFAULT_THEME


def video_state_key(theme_name, video_url):
    return f"{clean_theme_name(theme_name)}|{video_url}"


def load_json_file(path, default):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def write_json_file(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)


def utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def mark_stage(record, stage_name, timestamp=None):
    timestamp = timestamp or utc_timestamp()
    stages = record.setdefault("stages", {})
    stages[stage_name] = timestamp
    record[f"{stage_name}_at"] = timestamp
    return timestamp


def theme_config_path(theme_name):
    return os.path.join(THEMES_SRC_PATH, f"{clean_theme_name(theme_name)}.json")


def load_theme_config(theme_name):
    theme = clean_theme_name(theme_name)
    payload = load_json_file(theme_config_path(theme), {"theme": theme, "channels": []})
    channels = payload.get("channels", [])

    return {
        "theme": theme,
        "channels": [
            channel.strip()
            for channel in channels
            if isinstance(channel, str) and channel.strip()
        ],
    }


def write_theme_config(theme_name, channels):
    theme = clean_theme_name(theme_name)
    unique_channels = []

    for channel in channels:
        channel = str(channel).strip()

        if channel and channel not in unique_channels:
            unique_channels.append(channel)

    write_json_file(theme_config_path(theme), {
        "theme": theme,
        "channels": unique_channels,
    })


def ensure_theme(theme_name=DEFAULT_THEME, channels=None):
    theme = clean_theme_name(theme_name)
    os.makedirs(THEMES_SRC_PATH, exist_ok=True)
    os.makedirs(SRC_PATH, exist_ok=True)

    if not os.path.exists(theme_config_path(theme)):
        write_theme_config(theme, channels or [])
    elif channels is not None:
        existing = load_theme_config(theme)["channels"]
        write_theme_config(theme, existing + list(channels))

    return get_theme_paths(theme, create=True)


def discover_themes():
    os.makedirs(THEMES_SRC_PATH, exist_ok=True)
    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        ensure_theme(requested_theme)
        return [clean_theme_name(requested_theme)]

    themes = [
        clean_theme_name(os.path.splitext(filename)[0])
        for filename in sorted(os.listdir(THEMES_SRC_PATH))
        if filename.lower().endswith(".json")
    ]

    return themes


def get_theme_paths(theme_name=DEFAULT_THEME, create=False):
    theme = clean_theme_name(theme_name)
    theme_output_path = os.path.join(THEMES_OUTPUT_PATH, theme)
    theme_temp_path = os.path.join(TEMP_PATH, theme)

    paths = {
        "theme": theme,
        "theme_config_file": theme_config_path(theme),
        "pulled_file": PULLED_FILE,
        "executed_file": EXECUTED_FILE,
        "output_path": theme_output_path,
        "final_videos_path": os.path.join(theme_output_path, "content"),
        "final_metadata_file": os.path.join(theme_output_path, "metadata.json"),
        "temp_path": theme_temp_path,
        "videos_path": os.path.join(theme_temp_path, "downloads", "videos"),
        "audio_path": os.path.join(theme_temp_path, "downloads", "audio"),
        "transcriptions_path": os.path.join(theme_temp_path, "transcripts"),
        "subtitle_temp_path": os.path.join(theme_temp_path, "subtitles"),
        "clips_path": os.path.join(theme_temp_path, "clips"),
        "clip_metadata_path": os.path.join(theme_temp_path, "metadata"),
        "upload_path": os.path.join(theme_output_path, "content"),
        "metadata_path": os.path.join(theme_temp_path, "metadata"),
    }

    if create:
        for key in [
            "final_videos_path",
            "videos_path",
            "audio_path",
            "transcriptions_path",
            "subtitle_temp_path",
            "clips_path",
            "clip_metadata_path",
        ]:
            os.makedirs(paths[key], exist_ok=True)

    return paths
