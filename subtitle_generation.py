import os
import json
import re
import subprocess
import time

from faster_whisper import WhisperModel
from theme_config import BASE_DIR, discover_themes, ensure_theme


FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

FONTS_PATH = os.path.join(BASE_DIR, "assets", "fonts")

CURRENT_THEME = None
CLIPS_PATH = None
UPLOAD_PATH = None
SUBTITLE_TEMP_PATH = None
METADATA_PATH = None


def configure_theme(theme_name):
    global CURRENT_THEME, CLIPS_PATH, UPLOAD_PATH, SUBTITLE_TEMP_PATH, METADATA_PATH

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    CLIPS_PATH = theme_paths["clips_path"]
    UPLOAD_PATH = theme_paths["upload_path"]
    SUBTITLE_TEMP_PATH = theme_paths["subtitle_temp_path"]
    METADATA_PATH = theme_paths["metadata_path"]
    return theme_paths


configure_theme(os.getenv("SHORTFORM_THEME", "general"))

FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

SUBTITLE_MODEL_SIZE = os.getenv("SHORTFORM_SUBTITLE_MODEL", "base")
REGENERATE_UPLOAD_CLIPS = True
CAPTION_FONT_FAMILY = "Montserrat"

MAX_WORDS_PER_CAPTION = 4
MAX_CHARS_PER_CAPTION = 24
MAX_CAPTION_DURATION = 2.4
MAX_WORD_GAP = 0.55

IMPACT_WORDS = {
    "ai", "money", "debt", "credit", "loan", "loans", "default", "defaults",
    "insane", "crazy", "scary", "brutal", "truth", "wrong", "problem",
    "million", "billion", "college", "jobs", "job", "tax", "government",
    "crime", "illegal", "fraud", "scam", "risk", "danger", "interest",
    "percent", "porsche", "audi", "electric", "wealth", "income",
}


def run_subprocess(cmd, label):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print(f"\n--- {label} failed ---")
        print("Command:")
        print(" ".join(str(x) for x in cmd))
        print("\nFFmpeg stderr:")
        print(result.stderr[-4000:])
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")

    return result


def clean_filename(value):
    cleaned = "".join(
        char for char in value
        if char.isalnum() or char in [" ", ".", "_", "-"]
    ).replace(" ", "_")

    return cleaned[:150].strip("._-") or "clip"


def format_ass_time(seconds):
    total_centiseconds = max(0, int(round(float(seconds) * 100)))
    hours = total_centiseconds // 360000
    total_centiseconds %= 360000
    minutes = total_centiseconds // 6000
    total_centiseconds %= 6000
    whole_seconds = total_centiseconds // 100
    centiseconds = total_centiseconds % 100

    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def escape_ass_text(text):
    text = text.replace("\\", "")
    text = text.replace("{", "").replace("}", "")
    text = text.replace("\n", " ")
    return text.strip()


def ffmpeg_filter_path(path):
    normalized = os.path.abspath(path).replace("\\", "/")
    return normalized.replace(":", "\\:").replace("'", "\\'")


def get_video_files():
    if not os.path.isdir(CLIPS_PATH):
        return []

    files = []

    for filename in sorted(os.listdir(CLIPS_PATH)):
        lower = filename.lower()

        if not lower.endswith(".mp4"):
            continue

        if lower.endswith("_sub.mp4") or lower.endswith("_tracked.mp4"):
            continue

        files.append(os.path.join(CLIPS_PATH, filename))

    return files


def create_transcriber():
    import torch

    if torch.cuda.is_available():
        print(f"Initializing subtitle transcriber ({SUBTITLE_MODEL_SIZE} | GPU)...")
        device_type = "cuda"
        compute_type = "float16"
    else:
        print(f"Initializing subtitle transcriber ({SUBTITLE_MODEL_SIZE} | CPU int8)...")
        device_type = "cpu"
        compute_type = "int8"

    return WhisperModel(
        SUBTITLE_MODEL_SIZE,
        device=device_type,
        compute_type=compute_type,
    )


def transcribe_words(model, video_path):
    segments_iter, _ = model.transcribe(
        video_path,
        language="en",
        beam_size=5,
        best_of=5,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False,
    )

    words = []

    for segment in segments_iter:
        if not segment.words:
            continue

        for word in segment.words:
            cleaned = word.word.strip()

            if not cleaned:
                continue

            words.append({
                "word": cleaned,
                "start": float(word.start),
                "end": float(word.end),
            })

    return words


def split_caption_lines(words):
    lines = []
    current = []

    for word in words:
        if current:
            current_text = " ".join(item["word"] for item in current + [word])
            current_duration = word["end"] - current[0]["start"]
            gap = word["start"] - current[-1]["end"]

            should_split = (
                len(current) >= MAX_WORDS_PER_CAPTION
                or len(current_text) > MAX_CHARS_PER_CAPTION
                or current_duration > MAX_CAPTION_DURATION
                or gap > MAX_WORD_GAP
            )

            if should_split:
                lines.append(current)
                current = []

        current.append(word)

    if current:
        lines.append(current)

    return lines


def style_word_for_ass(word, rel_start_ms, rel_end_ms):
    cleaned = escape_ass_text(word)

    if not cleaned:
        return ""

    plain = re.sub(r"[^a-zA-Z0-9]", "", cleaned).lower()
    rel_start_ms = max(0, int(rel_start_ms))
    rel_end_ms = max(rel_start_ms + 70, int(rel_end_ms))
    active_mid_ms = rel_start_ms + max(35, int((rel_end_ms - rel_start_ms) * 0.45))
    highlight_color = "&H0038D8FF" if plain in IMPACT_WORDS or re.search(r"\d", cleaned) else "&H004EEBFF"
    active_style = (
        f"\\t({rel_start_ms},{active_mid_ms},"
        f"\\c{highlight_color}\\fscx104\\fscy104\\bord5.8\\shad2.5)"
        f"\\t({active_mid_ms},{rel_end_ms},"
        "\\fscx100\\fscy100\\bord5.2\\shad2.0)"
        f"\\t({rel_end_ms},{rel_end_ms + 80},\\c&H00FFFFFF)"
    )

    return f"{{\\c&H00FFFFFF\\fscx100\\fscy100\\bord5.2\\shad2.0{active_style}}}{cleaned.upper()}"


def build_ass_subtitles(words, ass_path):
    lines = split_caption_lines(words)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{CAPTION_FONT_FAMILY},74,&H0038D8FF,&H00FFFFFF,&H00000000,&HAA000000,-1,0,0,0,100,100,0.4,0,1,5.2,2,2,80,80,330,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for line in lines:
        line_start = max(0, line[0]["start"] - 0.04)
        line_end = max(line[-1]["end"] + 0.08, line_start + 0.35)
        line_parts = []

        for word in line:
            rel_start_ms = round((word["start"] - line_start) * 1000)
            rel_end_ms = round((word["end"] - line_start) * 1000)
            line_parts.append(style_word_for_ass(
                word["word"],
                rel_start_ms,
                rel_end_ms,
            ))

        text = " ".join(part for part in line_parts if part)

        if not text:
            continue

        text = "{\\an2\\pos(540,1455)\\fad(70,70)}" + text
        events.append(
            "Dialogue: 0,"
            f"{format_ass_time(line_start)},"
            f"{format_ass_time(line_end)},"
            f"Caption,,0,0,0,,{text}"
        )

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")

    return len(events)


def burn_subtitles(input_video, ass_path, output_video):
    ass_filter = (
        f"ass='{ffmpeg_filter_path(ass_path)}'"
        f":fontsdir='{ffmpeg_filter_path(FONTS_PATH)}'"
    )

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-i", input_video,
        "-vf", ass_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_video,
    ], "Subtitle burn-in")


def load_clip_metadata_index():
    index = {}

    if not METADATA_PATH or not os.path.isdir(METADATA_PATH):
        return index

    for filename in os.listdir(METADATA_PATH):
        if not filename.endswith("_clip_review.json"):
            continue

        metadata_file = os.path.join(METADATA_PATH, filename)

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        for clip in payload.get("selected", []):
            output_file = clip.get("output_file", "")

            if not output_file:
                continue

            index[os.path.basename(output_file)] = clip

    return index


def build_social_package(clip_path, output_path, words, clip_metadata):
    basename = os.path.splitext(os.path.basename(output_path))[0]
    transcript = " ".join(word["word"] for word in words)
    title = clip_metadata.get("suggested_title") or basename.replace("_upload", "").replace("_", " ")
    caption = clip_metadata.get("suggested_caption") or title
    hashtags = clip_metadata.get("hashtags") or ["#podcast", "#shorts"]
    plain_tags = [
        tag.lstrip("#")
        for tag in hashtags
        if tag.strip("#")
    ]

    package = {
        "theme": CURRENT_THEME,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(clip_path),
        "title": title[:95],
        "caption": caption,
        "hashtags": hashtags,
        "tags": plain_tags,
        "description": f"{caption}\n\n{' '.join(hashtags)}",
        "transcript_excerpt": transcript[:500],
        "hook_reason": clip_metadata.get("hook_reason", ""),
        "score": clip_metadata.get("score"),
        "platforms": {
            "youtube_shorts": {
                "title": title[:95],
                "description": f"{caption}\n\n{' '.join(hashtags)}",
                "tags": plain_tags,
                "privacy_status": "private",
            },
            "tiktok": {
                "caption": f"{caption} {' '.join(hashtags)}"[:2200],
            },
            "instagram_reels": {
                "caption": f"{caption}\n\n{' '.join(hashtags)}",
            },
            "facebook_reels": {
                "caption": f"{caption}\n\n{' '.join(hashtags)}",
            },
        },
        "posting_status": {
            "youtube_shorts": "ready",
            "tiktok": "ready",
            "instagram_reels": "ready",
            "facebook_reels": "ready",
        },
    }

    return package


def write_social_package(output_path, package):
    sidecar_path = os.path.splitext(output_path)[0] + ".json"

    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(package, f, indent=4)

    manifest_path = os.path.join(UPLOAD_PATH, "_upload_manifest.json")
    manifest = []

    if os.path.exists(manifest_path) and os.path.getsize(manifest_path) > 0:
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = []

    manifest = [
        item
        for item in manifest
        if item.get("video_file") != package["video_file"]
    ]
    manifest.append(package)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)

    return sidecar_path, manifest_path


def process_clip(model, clip_path):
    start_time = time.time()
    basename = os.path.splitext(os.path.basename(clip_path))[0]
    output_filename = clean_filename(f"{basename}_upload.mp4")
    output_path = os.path.join(UPLOAD_PATH, output_filename)

    if (
        not REGENERATE_UPLOAD_CLIPS
        and os.path.exists(output_path)
        and os.path.getsize(output_path) > 0
    ):
        print(f"Skipping existing upload clip: {output_filename}")
        return output_path

    ass_path = os.path.join(SUBTITLE_TEMP_PATH, f"{clean_filename(basename)}.ass")

    print(f"Subtitling: {os.path.basename(clip_path)}")
    words = transcribe_words(model, clip_path)

    if not words:
        raise RuntimeError(f"No subtitle words were detected for {clip_path}")

    event_count = build_ass_subtitles(words, ass_path)
    burn_subtitles(clip_path, ass_path, output_path)
    metadata_index = load_clip_metadata_index()
    package = build_social_package(
        clip_path=clip_path,
        output_path=output_path,
        words=words,
        clip_metadata=metadata_index.get(os.path.basename(clip_path), {}),
    )
    sidecar_path, manifest_path = write_social_package(output_path, package)

    print(
        f" -> Created {output_filename} with {event_count} subtitle events "
        f"in {time.time() - start_time:.2f} seconds"
    )
    print(f" -> Social package: {sidecar_path}")
    print(f" -> Upload manifest: {manifest_path}")

    return output_path


def run_subtitle_generation(limit=None, theme=None):
    if theme:
        return run_subtitle_generation_for_theme(limit=limit, theme=theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_subtitle_generation_for_theme(limit=limit, theme=requested_theme)

    for theme_name in discover_themes():
        run_subtitle_generation_for_theme(limit=limit, theme=theme_name)


def run_subtitle_generation_for_theme(limit=None, theme="general"):
    configure_theme(theme)
    run_start = time.time()
    clip_files = get_video_files()

    if limit is not None:
        clip_files = clip_files[:limit]

    print(f"=== Generating subtitles for theme: {CURRENT_THEME} ===")
    print(f"Clips found: {len(clip_files)}")
    print(f"Upload folder: {UPLOAD_PATH}\n")

    if not clip_files:
        print("No clips available for subtitle generation.")
        return

    model = create_transcriber()

    for clip_path in clip_files:
        try:
            process_clip(model, clip_path)
        except Exception as error:
            print(f" -> Failed to subtitle {clip_path}: {error}")

    print(f"\nSubtitle generation for '{CURRENT_THEME}' finished in {time.time() - run_start:.2f} seconds\n")


if __name__ == "__main__":
    run_subtitle_generation()
