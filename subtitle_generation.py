import json
import os
import re
import subprocess
import time

from theme_config import (
    BASE_DIR,
    DEFAULT_THEME,
    EXECUTED_FILE,
    discover_themes,
    ensure_theme,
    load_json_file,
    mark_stage,
    write_json_file,
)


FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

FONTS_PATH = os.path.join(BASE_DIR, "assets", "fonts")

CURRENT_THEME = None
CLIPS_PATH = None
UPLOAD_PATH = None
VIDEOS_PATH = None
AUDIO_PATH = None
TRANSCRIPTIONS_PATH = None
SUBTITLE_TEMP_PATH = None
METADATA_PATH = None
FINAL_METADATA_FILE = None


def configure_theme(theme_name):
    global CURRENT_THEME, CLIPS_PATH, UPLOAD_PATH, VIDEOS_PATH, AUDIO_PATH
    global TRANSCRIPTIONS_PATH, SUBTITLE_TEMP_PATH, METADATA_PATH, FINAL_METADATA_FILE

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    CLIPS_PATH = theme_paths["clips_path"]
    UPLOAD_PATH = theme_paths["upload_path"]
    VIDEOS_PATH = theme_paths["videos_path"]
    AUDIO_PATH = theme_paths["audio_path"]
    TRANSCRIPTIONS_PATH = theme_paths["transcriptions_path"]
    SUBTITLE_TEMP_PATH = theme_paths["subtitle_temp_path"]
    METADATA_PATH = theme_paths["metadata_path"]
    FINAL_METADATA_FILE = theme_paths["final_metadata_file"]
    return theme_paths


FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

SUBTITLE_MODEL_SIZE = os.getenv("SHORTFORM_SUBTITLE_MODEL", "base")
SUBTITLE_BEAM_SIZE = int(os.getenv("SHORTFORM_SUBTITLE_BEAM_SIZE", "1"))
SUBTITLE_BEST_OF = int(os.getenv("SHORTFORM_SUBTITLE_BEST_OF", str(SUBTITLE_BEAM_SIZE)))
REGENERATE_UPLOAD_CLIPS = os.getenv("SHORTFORM_REGENERATE_UPLOAD_CLIPS", "0") == "1"
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

THEME_ALGORITHM_TAGS = {
    "comedy": [
        "comedy", "funny", "stand up comedy", "jokes", "comedian", "humor",
        "funny shorts", "comedy shorts", "viral comedy", "podcast clips",
    ],
    "finance": [
        "finance", "money", "investing", "business", "economics", "markets",
        "personal finance", "financial education", "wealth", "finance shorts",
    ],
}

THEME_HASHTAGS = {
    "comedy": ["#comedy", "#funny", "#jokes", "#standup", "#shorts"],
    "finance": ["#finance", "#money", "#investing", "#business", "#shorts"],
}

STOP_TAG_WORDS = {
    "about", "after", "again", "because", "before", "being", "could", "every",
    "from", "have", "just", "like", "really", "right", "that", "their", "there",
    "they", "this", "those", "what", "when", "where", "which", "with", "would",
    "your", "youre", "yeah", "thing", "things", "people", "going", "think",
}


def compact_text(text, max_length):
    text = re.sub(r"\s+", " ", str(text or "")).strip()

    if len(text) <= max_length:
        return text

    return text[: max(0, max_length - 1)].rstrip(" ,.;:-") + "..."


def words_from_text(text):
    return re.findall(r"[a-zA-Z][a-zA-Z0-9']{2,}", str(text or "").lower())


def extract_keyword_tags(text, limit=6):
    counts = {}

    for word in words_from_text(text):
        normalized = word.strip("'").replace("'", "")

        if len(normalized) < 4 or normalized in STOP_TAG_WORDS:
            continue

        counts[normalized] = counts.get(normalized, 0) + 1

    ranked = sorted(counts, key=lambda item: (-counts[item], item))
    return ranked[:limit]


def unique_sequence(values):
    seen = set()
    result = []

    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.lower()

        if not cleaned or key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

    return result


def build_platform_caption(title, caption, description, hashtags):
    summary = description or caption or title
    summary = compact_text(summary, 220)
    hashtag_text = " ".join(unique_sequence(hashtags)[:5])
    return f"{summary}\n\n{hashtag_text}".strip()


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
    from faster_whisper import WhisperModel

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
        beam_size=SUBTITLE_BEAM_SIZE,
        best_of=SUBTITLE_BEST_OF,
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


def source_prefix_from_clip_path(clip_path):
    basename = os.path.splitext(os.path.basename(clip_path))[0]
    return re.sub(r"_\d+$", "", basename)


def output_path_for_source_clip(source_clip_file):
    basename = os.path.splitext(os.path.basename(source_clip_file))[0]
    output_filename = clean_filename(f"{basename}_upload.mp4")
    return os.path.join(UPLOAD_PATH, output_filename)


def load_source_clip_metadata(prefix):
    review_file = os.path.join(METADATA_PATH, f"{prefix}_clip_review.json")

    if not os.path.exists(review_file) or os.path.getsize(review_file) == 0:
        return []

    try:
        with open(review_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []

    return payload.get("selected", [])


def source_uploads_complete(prefix):
    selected_clips = load_source_clip_metadata(prefix)

    if not selected_clips:
        return False

    rendered_source_clips = [
        clip
        for clip in selected_clips
        if clip.get("output_file")
    ]

    if not rendered_source_clips:
        return False

    for clip in rendered_source_clips:
        output_path = output_path_for_source_clip(clip["output_file"])

        if not os.path.exists(output_path) or os.path.getsize(output_path) <= 0:
            return False

    return True


def safe_delete_file(path, allowed_roots):
    if not path:
        return False

    absolute_path = os.path.abspath(path)
    normalized_path = os.path.normcase(absolute_path)
    normalized_roots = [
        os.path.normcase(os.path.abspath(root))
        for root in allowed_roots
        if root
    ]

    if not any(
        normalized_path == root or normalized_path.startswith(root + os.sep)
        for root in normalized_roots
    ):
        return False

    if not os.path.isfile(absolute_path):
        return False

    try:
        os.remove(absolute_path)
        return True
    except OSError:
        return False


def delete_matching_files(folder, prefix, allowed_roots):
    deleted = 0

    if not folder or not os.path.isdir(folder):
        return deleted

    for filename in os.listdir(folder):
        if filename == prefix or filename.startswith(f"{prefix}_") or filename.startswith(f"{prefix}."):
            if safe_delete_file(os.path.join(folder, filename), allowed_roots):
                deleted += 1

    return deleted


def cleanup_completed_source_temp(prefix):
    if not prefix:
        return 0

    allowed_roots = [
        CLIPS_PATH,
        VIDEOS_PATH,
        AUDIO_PATH,
        TRANSCRIPTIONS_PATH,
        SUBTITLE_TEMP_PATH,
        METADATA_PATH,
    ]
    deleted = 0

    for folder in allowed_roots:
        deleted += delete_matching_files(folder, prefix, allowed_roots)

    if deleted:
        print(f" -> Cleaned {deleted} temp files for completed source: {prefix}")

    return deleted


def get_source_state_key_for_clip(clip_path, metadata_index=None):
    metadata_index = metadata_index or load_clip_metadata_index()
    clip_metadata = metadata_index.get(os.path.basename(clip_path), {})
    return clip_metadata.get("source_state_key", "")


def source_is_executed(source_state_key):
    if not source_state_key:
        return False

    executed = load_json_file(EXECUTED_FILE, {})
    return isinstance(executed, dict) and source_state_key in executed


def build_social_package(clip_path, output_path, words, clip_metadata):
    basename = os.path.splitext(os.path.basename(output_path))[0]
    transcript = " ".join(word["word"] for word in words)
    title = clip_metadata.get("suggested_title") or basename.replace("_upload", "").replace("_", " ")
    title = compact_text(title, 95)
    caption = clip_metadata.get("suggested_caption") or title
    caption = compact_text(caption, 160)
    theme_hashtags = THEME_HASHTAGS.get(CURRENT_THEME, ["#podcast", "#shorts"])
    hashtags = unique_sequence((clip_metadata.get("hashtags") or []) + theme_hashtags)[:8]
    description = (
        clip_metadata.get("suggested_description")
        or caption
    )
    description = compact_text(description, 280)
    plain_hashtag_tags = [tag.lstrip("#") for tag in hashtags if tag.strip("#")]
    algorithm_tags = THEME_ALGORITHM_TAGS.get(CURRENT_THEME, [])
    transcript_tags = extract_keyword_tags(
        " ".join([
            transcript,
            clip_metadata.get("transcript_excerpt", ""),
            clip_metadata.get("source_title", ""),
            title,
        ]),
        limit=8,
    )
    high_level_tags = ["shorts", "podcast", "interview", "viral", CURRENT_THEME.replace("_", " ")]
    all_tags = unique_sequence(algorithm_tags + plain_hashtag_tags + transcript_tags + high_level_tags)[:20]
    platform_caption = build_platform_caption(title, caption, description, hashtags)

    package = {
        "theme": CURRENT_THEME,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(clip_path),
        "source_state_key": clip_metadata.get("source_state_key", ""),
        "source_video_url": clip_metadata.get("source_video_url", ""),
        "source_title": clip_metadata.get("source_title", ""),
        "title": title,
        "caption": caption,
        "hashtags": hashtags,
        "tags": all_tags,
        "description": description,
        "transcript_excerpt": transcript[:500],
        "hook_reason": clip_metadata.get("hook_reason", ""),
        "score": clip_metadata.get("score"),
        "review": {
            "quality_rating": "",
            "approved": False,
            "rejection_reason": "",
            "notes": "",
        },
        "platforms": {
            "youtube_shorts": {
                "title": title,
                "description": f"{description}\n\n{' '.join(hashtags)}",
                "tags": all_tags,
                "privacy_status": "private",
            },
            "tiktok": {
                "caption": platform_caption[:2200],
            },
            "instagram_reels": {
                "caption": platform_caption,
            },
            "facebook_reels": {
                "caption": platform_caption,
            },
        },
        "posting_status": {
            "youtube_shorts": "ready",
            "tiktok": "ready",
            "instagram_reels": "ready",
            "facebook_reels": "ready",
        },
        "platform_metrics": {
            "youtube_shorts": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
            "tiktok": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
            "instagram_reels": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
            "facebook_reels": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
        },
    }

    return package


def write_social_package(output_path, package):
    metadata = {
        "theme": CURRENT_THEME,
        "content": [],
    }

    if os.path.exists(FINAL_METADATA_FILE) and os.path.getsize(FINAL_METADATA_FILE) > 0:
        try:
            with open(FINAL_METADATA_FILE, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            metadata = {
                "theme": CURRENT_THEME,
                "content": [],
            }

    content = metadata.get("content", [])
    content = [
        item
        for item in content
        if item.get("video_file") != package["video_file"]
    ]
    content.append(package)
    metadata["theme"] = CURRENT_THEME
    metadata["content"] = content

    with open(FINAL_METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    return FINAL_METADATA_FILE


def mark_video_completed(package):
    source_state_key = package.get("source_state_key")

    if not source_state_key:
        return

    executed = load_json_file(EXECUTED_FILE, {})

    if not isinstance(executed, dict):
        executed = {}

    existing = executed.get(source_state_key, {})
    final_video_files = existing.get("final_video_files", [])
    metadata_files = existing.get("metadata_files", [])
    final_video_file = package.get("video_file", "")

    if final_video_file and final_video_file not in final_video_files:
        final_video_files.append(final_video_file)

    source_prefix = source_prefix_from_clip_path(package.get("source_clip_file", ""))

    for clip in load_source_clip_metadata(source_prefix):
        source_output_file = clip.get("output_file", "")

        if not source_output_file:
            continue

        upload_file = os.path.abspath(output_path_for_source_clip(source_output_file))

        if os.path.exists(upload_file) and upload_file not in final_video_files:
            final_video_files.append(upload_file)

    if FINAL_METADATA_FILE not in metadata_files:
        metadata_files.append(FINAL_METADATA_FILE)

    completed_record = {
        **existing,
        "theme": package.get("theme", CURRENT_THEME),
        "video_url": package.get("source_video_url", ""),
        "title": package.get("source_title", ""),
        "funnel_status": "subtitled",
        "subtitle_status": "complete",
        "upload_status": existing.get("upload_status", "pending"),
        "final_video_count": len(final_video_files),
        "final_video_files": final_video_files,
        "metadata_files": metadata_files,
    }
    mark_stage(completed_record, "subtitled")
    mark_stage(completed_record, "completed")
    executed[source_state_key] = completed_record
    write_json_file(EXECUTED_FILE, executed)


def finalize_source_if_complete(prefix, package):
    safe_delete_file(package.get("source_clip_file", ""), [CLIPS_PATH])

    if not source_uploads_complete(prefix):
        return False

    mark_video_completed(package)
    cleanup_completed_source_temp(prefix)
    return True


def process_clip(model, clip_path):
    start_time = time.time()
    basename = os.path.splitext(os.path.basename(clip_path))[0]
    source_prefix = source_prefix_from_clip_path(clip_path)
    output_filename = clean_filename(f"{basename}_upload.mp4")
    output_path = os.path.join(UPLOAD_PATH, output_filename)

    if (
        not REGENERATE_UPLOAD_CLIPS
        and os.path.exists(output_path)
        and os.path.getsize(output_path) > 0
    ):
        print(f"Skipping existing upload clip: {output_filename}")
        metadata_index = load_clip_metadata_index()
        package = build_social_package(
            clip_path=clip_path,
            output_path=output_path,
            words=[],
            clip_metadata=metadata_index.get(os.path.basename(clip_path), {}),
        )
        write_social_package(output_path, package)
        finalize_source_if_complete(source_prefix, package)
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
    metadata_file = write_social_package(output_path, package)
    finalize_source_if_complete(source_prefix, package)

    print(
        f" -> Created {output_filename} with {event_count} subtitle events "
        f"in {time.time() - start_time:.2f} seconds"
    )
    print(f" -> Theme metadata: {metadata_file}")

    return output_path


def run_subtitle_generation(limit=None, theme=None):
    if theme:
        return run_subtitle_generation_for_theme(limit=limit, theme=theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_subtitle_generation_for_theme(limit=limit, theme=requested_theme)

    for theme_name in discover_themes():
        run_subtitle_generation_for_theme(limit=limit, theme=theme_name)


def run_subtitle_generation_for_theme(limit=None, theme=DEFAULT_THEME):
    configure_theme(theme)
    run_start = time.time()
    clip_files = get_video_files()

    if limit is not None:
        clip_files = clip_files[:limit]

    print(f"=== Generating subtitles for theme: {CURRENT_THEME} ===")
    print(f"Clips found: {len(clip_files)}")
    print(f"Content folder: {UPLOAD_PATH}")
    print(f"Metadata file: {FINAL_METADATA_FILE}\n")

    if not clip_files:
        print("No clips available for subtitle generation.")
        return

    metadata_index = load_clip_metadata_index()
    pending_clip_files = []

    for clip_path in clip_files:
        if not os.path.exists(clip_path):
            continue

        source_state_key = get_source_state_key_for_clip(clip_path, metadata_index)

        if source_is_executed(source_state_key):
            source_prefix = source_prefix_from_clip_path(clip_path)
            print(f"Skipping already executed source: {source_state_key}")
            cleanup_completed_source_temp(source_prefix)
            continue

        pending_clip_files.append(clip_path)

    if not pending_clip_files:
        print("No unexecuted clips need subtitle generation.")
        return

    model = create_transcriber()

    for clip_path in pending_clip_files:
        try:
            process_clip(model, clip_path)
        except Exception as error:
            print(f" -> Failed to subtitle {clip_path}: {error}")

    print(f"\nSubtitle generation for '{CURRENT_THEME}' finished in {time.time() - run_start:.2f} seconds\n")


if __name__ == "__main__":
    run_subtitle_generation()
