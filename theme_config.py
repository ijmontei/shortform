import os
import re
import shutil


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(BASE_DIR, "src")
THEMES_SRC_PATH = os.path.join(SRC_PATH, "themes")
OUTPUT_PATH = os.path.join(BASE_DIR, "output")
THEMES_OUTPUT_PATH = os.path.join(OUTPUT_PATH, "themes")
DEFAULT_THEME = "general"


def clean_theme_name(theme_name):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(theme_name).strip().lower())
    cleaned = cleaned.strip("_-")
    return cleaned or DEFAULT_THEME


def ensure_theme(theme_name=DEFAULT_THEME):
    theme = clean_theme_name(theme_name)
    theme_src_path = os.path.join(THEMES_SRC_PATH, theme)
    os.makedirs(theme_src_path, exist_ok=True)

    channels_file = os.path.join(theme_src_path, "channels.txt")
    legacy_channels_file = os.path.join(SRC_PATH, "channels.txt")

    if (
        theme == DEFAULT_THEME
        and not os.path.exists(channels_file)
        and os.path.exists(legacy_channels_file)
    ):
        shutil.copyfile(legacy_channels_file, channels_file)

    paths = get_theme_paths(theme, create=True)

    if theme == DEFAULT_THEME:
        for legacy_name, theme_key in [
            ("id.json", "id_file"),
            ("executed_id.json", "executed_id_file"),
        ]:
            legacy_file = os.path.join(SRC_PATH, legacy_name)

            if not os.path.exists(paths[theme_key]) and os.path.exists(legacy_file):
                shutil.copyfile(legacy_file, paths[theme_key])

    return paths


def discover_themes():
    os.makedirs(THEMES_SRC_PATH, exist_ok=True)
    themes = []

    for name in sorted(os.listdir(THEMES_SRC_PATH)):
        theme_src_path = os.path.join(THEMES_SRC_PATH, name)
        channels_file = os.path.join(theme_src_path, "channels.txt")

        if os.path.isdir(theme_src_path) and os.path.exists(channels_file):
            themes.append(clean_theme_name(name))

    if not themes:
        ensure_theme(DEFAULT_THEME)
        themes.append(DEFAULT_THEME)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        requested_theme = clean_theme_name(requested_theme)
        ensure_theme(requested_theme)
        return [requested_theme]

    return themes


def get_theme_paths(theme_name=DEFAULT_THEME, create=False):
    theme = clean_theme_name(theme_name)
    theme_src_path = os.path.join(THEMES_SRC_PATH, theme)
    theme_output_path = os.path.join(THEMES_OUTPUT_PATH, theme)

    paths = {
        "theme": theme,
        "src_path": theme_src_path,
        "channels_file": os.path.join(theme_src_path, "channels.txt"),
        "id_file": os.path.join(theme_src_path, "id.json"),
        "executed_id_file": os.path.join(theme_src_path, "executed_id.json"),
        "output_path": theme_output_path,
        "videos_path": os.path.join(theme_output_path, "temp", "videos"),
        "audio_path": os.path.join(theme_output_path, "temp", "audios"),
        "transcriptions_path": os.path.join(theme_output_path, "temp", "transcripts"),
        "subtitle_temp_path": os.path.join(theme_output_path, "temp", "subtitles"),
        "clips_path": os.path.join(theme_output_path, "clips"),
        "upload_path": os.path.join(theme_output_path, "upload"),
        "metadata_path": os.path.join(theme_output_path, "metadata"),
    }

    if create:
        os.makedirs(theme_src_path, exist_ok=True)

        for key in [
            "videos_path",
            "audio_path",
            "transcriptions_path",
            "subtitle_temp_path",
            "clips_path",
            "upload_path",
            "metadata_path",
        ]:
            os.makedirs(paths[key], exist_ok=True)

    return paths
