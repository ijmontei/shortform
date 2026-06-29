import json
import os
import re
import time
import tempfile


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(BASE_DIR, "src")
THEMES_SRC_PATH = os.path.join(SRC_PATH, "themes")
PULLED_FILE = os.path.join(SRC_PATH, "pulled.json")
EXECUTED_FILE = os.path.join(SRC_PATH, "executed_id.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "output")
TEMP_PATH = os.path.join(OUTPUT_PATH, "temp")
THEMES_OUTPUT_PATH = os.path.join(OUTPUT_PATH, "themes")
DEFAULT_THEME = "comedy"
PHASE_ONE_ACTIVE_THEMES = [
    "comedy",
    "sports",
    "gaming",
    "finance",
    "technology_ai",
    "health_fitness",
    "politics",
    "popculture",
    "truecrime",
]


def future_themes_allowed():
    return os.getenv("SHORTFORM_ALLOW_FUTURE_THEMES", "0") == "1"


def is_phase_one_theme(theme_name):
    return clean_theme_name(theme_name) in PHASE_ONE_ACTIVE_THEMES


def theme_allowed_for_active_run(theme_name):
    return is_phase_one_theme(theme_name) or future_themes_allowed()


def blocked_future_themes(themes):
    return [
        clean_theme_name(theme)
        for theme in themes or []
        if clean_theme_name(theme) and not theme_allowed_for_active_run(theme)
    ]


def phase_one_theme_list_text():
    return ", ".join(PHASE_ONE_ACTIVE_THEMES)


def requested_env_theme_names():
    requested_theme = os.getenv("SHORTFORM_THEME")
    requested_active_themes = os.getenv("SHORTFORM_ACTIVE_THEMES")

    if requested_theme:
        return [clean_theme_name(requested_theme)]

    if requested_active_themes:
        return [
            clean_theme_name(theme)
            for theme in requested_active_themes.split(",")
            if clean_theme_name(theme)
        ]

    return []


def future_theme_guard_message(themes):
    blocked = blocked_future_themes(themes)

    if not blocked:
        return ""

    return (
        "Future/phase-two theme(s) are not active for production: "
        f"{', '.join(blocked)}. "
        "Phase-one active themes are: "
        f"{phase_one_theme_list_text()}. "
        "Set SHORTFORM_ALLOW_FUTURE_THEMES=1 only when intentionally testing "
        "or producing future-theme inventory."
    )


def assert_theme_allowed_for_active_run(theme_name):
    theme = clean_theme_name(theme_name)
    message = future_theme_guard_message([theme])

    if message:
        raise SystemExit(message)

    return theme


def phase_one_theme_names():
    return [
        theme
        for theme in PHASE_ONE_ACTIVE_THEMES
        if os.path.exists(theme_config_path(theme))
    ]


def load_env_file():
    env_path = os.path.join(BASE_DIR, ".env")

    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8-sig") as f:
        for raw_line in f:
            line = raw_line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()


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
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def write_json_file(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    directory = os.path.dirname(path) or "."
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


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
    priority_channels = payload.get("priority_channels", [])
    secondary_channels = payload.get("secondary_channels", [])
    channels = payload.get("channels", [])
    youtube = payload.get("youtube", {})

    if not isinstance(youtube, dict):
        youtube = {}

    config = dict(payload)
    config["theme"] = theme
    merged_channels = []

    for channel_group in [priority_channels, secondary_channels, channels]:
        for channel in channel_group or []:
            if not isinstance(channel, str):
                continue

            channel = channel.strip()

            if channel and channel not in merged_channels:
                merged_channels.append(channel)

    config["priority_channels"] = [
        channel.strip()
        for channel in priority_channels
        if isinstance(channel, str) and channel.strip()
    ]
    config["secondary_channels"] = [
        channel.strip()
        for channel in secondary_channels
        if isinstance(channel, str) and channel.strip()
    ]
    config["episode_routing_override"] = payload.get("episode_routing_override", [])
    config["channels"] = merged_channels
    config["youtube"] = {
        **youtube,
        "channel_handle": str(youtube.get("channel_handle", "")).strip(),
        "token_file": str(youtube.get("token_file", "")).strip(),
    }
    return config


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
    requested_active_themes = os.getenv("SHORTFORM_ACTIVE_THEMES")
    allow_future = future_themes_allowed()

    if requested_theme:
        theme = clean_theme_name(requested_theme)

        if not theme_allowed_for_active_run(theme):
            return []

        ensure_theme(theme)
        return [theme]

    if requested_active_themes:
        themes = [
            clean_theme_name(theme)
            for theme in requested_active_themes.split(",")
            if clean_theme_name(theme)
        ]
        return [
            theme
            for theme in themes
            if os.path.exists(theme_config_path(theme))
            and (allow_future or theme in PHASE_ONE_ACTIVE_THEMES)
        ]

    if os.getenv("SHORTFORM_RUN_ALL_THEMES", "0") != "1" or not allow_future:
        return phase_one_theme_names()

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
        "archive_path": os.path.join(theme_output_path, "archive"),
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
            "archive_path",
            "videos_path",
            "audio_path",
            "transcriptions_path",
            "subtitle_temp_path",
            "clips_path",
            "clip_metadata_path",
        ]:
            os.makedirs(paths[key], exist_ok=True)

    return paths
