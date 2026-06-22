import json
import math
import os
import re
import subprocess
import struct
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from datetime import datetime

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

import ytdlp_auth
from theme_config import BASE_DIR, DEFAULT_THEME, PULLED_FILE, discover_themes, ensure_theme, load_json_file, utc_timestamp, write_json_file
from popularity_signals import (
    build_popularity_profile_from_info,
    build_youtube_data_api_profile,
    load_cached_popularity_profile,
    merge_popularity_profiles,
    save_popularity_profile,
    score_popularity_for_window,
)


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"

DAILY_TOPIC_COUNT = max(1, int(os.getenv("SHORTFORM_DAILY_TOPIC_COUNT", "10")))
EDITORIAL_COUNTDOWN_SIZE = max(1, int(os.getenv("SHORTFORM_EDITORIAL_COUNTDOWN_SIZE", "5")))
EDITORIAL_CLIPS_PER_SHORT = max(1, min(2, int(os.getenv("SHORTFORM_EDITORIAL_CLIPS_PER_SHORT", "1"))))
RENDER_RECAP_COMPILATION = os.getenv("SHORTFORM_EDITORIAL_RENDER_RECAP", "1") != "0"
APPEND_METADATA = os.getenv("SHORTFORM_EDITORIAL_APPEND_METADATA", "0") == "1"
NARRATION_RATE = int(os.getenv("SHORTFORM_NARRATION_RATE", "1"))
NARRATION_VOLUME = int(os.getenv("SHORTFORM_NARRATION_VOLUME", "100"))
TTS_PROVIDER = os.getenv("SHORTFORM_TTS_PROVIDER", "elevenlabs").strip().lower()
ALLOW_WINDOWS_TTS_FALLBACK = os.getenv("SHORTFORM_ALLOW_WINDOWS_TTS_FALLBACK", "1") == "1"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", os.getenv("SHORTFORM_ELEVENLABS_API_KEY", "")).strip()
ELEVENLABS_VOICE_ID = os.getenv(
    "ELEVENLABS_VOICE_ID",
    os.getenv("SHORTFORM_ELEVENLABS_VOICE_ID", "hnhZe040y4V3QPXXZVDO"),
).strip()
ELEVENLABS_FALLBACK_VOICE_IDS = [
    voice_id.strip()
    for voice_id in os.getenv("SHORTFORM_ELEVENLABS_FALLBACK_VOICE_IDS", "").split(",")
    if voice_id.strip()
]
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3").strip()
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_192").strip()
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.22"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.96"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.88"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "1") != "0"
NARRATION_PITCH = float(os.getenv("SHORTFORM_NARRATION_PITCH", "1.0"))
NARRATION_BASS_GAIN = float(os.getenv("SHORTFORM_NARRATION_BASS_GAIN", "0.0"))
NARRATION_LOUDNESS_I = float(os.getenv("SHORTFORM_NARRATION_LOUDNESS_I", "-16.0"))
NARRATION_TARGET_SECONDS = float(os.getenv("SHORTFORM_NARRATION_TARGET_SECONDS", "4.45"))
INTRO_SOURCE_AUDIO_VOLUME = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_SOURCE_AUDIO_VOLUME", "0.025"))
CLIP_SOURCE_AUDIO_VOLUME = float(os.getenv("SHORTFORM_EDITORIAL_CLIP_AUDIO_VOLUME", "1.0"))
EDITORIAL_INTRO_TARGET_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_SECONDS", "5.0"))
EDITORIAL_INTRO_MAX_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_MAX_SECONDS", "5.0"))
EDITORIAL_TOTAL_MAX_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_TOTAL_MAX_SECONDS", "58.0"))
EDITORIAL_TRANSITION_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_TRANSITION_SECONDS", "0.45"))
EDITORIAL_RANK_CARD_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_RANK_CARD_SECONDS", "0.0"))
EDITORIAL_CLIP_MIN_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_CLIP_MIN_SECONDS", "7.0"))
EDITORIAL_PERIOD_LABEL = os.getenv("SHORTFORM_EDITORIAL_PERIOD_LABEL", "this week").strip() or "this week"
EDITORIAL_BOARD_SOURCE_LIMIT = max(5, int(os.getenv("SHORTFORM_EDITORIAL_BOARD_SOURCE_LIMIT", "12")))
EDITORIAL_HARD_REJECT_BAD_OUTPUTS = os.getenv("SHORTFORM_EDITORIAL_HARD_REJECT_BAD_OUTPUTS", "1") != "0"
MIN_EDITORIAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_EDITORIAL_VISUAL_QUALITY", "0.55"))
RENDER_POPULAR_SEGMENT_SHORTS = os.getenv("SHORTFORM_RENDER_POPULAR_SEGMENTS", "1") != "0"
POPULAR_SEGMENTS_PER_THEME = max(0, int(os.getenv("SHORTFORM_POPULAR_SEGMENTS_PER_THEME", "0")))
POPULAR_SEGMENT_REQUIRE_SIGNAL = os.getenv("SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL", "0") != "0"
POPULAR_SEGMENT_MIN_SCORE = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_MIN_SCORE", "0.12"))
POPULAR_SEGMENT_INTRO_SECONDS = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_INTRO_SECONDS", "2.85"))
POPULAR_SEGMENT_MAX_SECONDS = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_MAX_SECONDS", "58.0"))
YOUTUBE_DATA_API_KEY = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
ENABLE_YOUTUBE_DATA_API_SIGNALS = os.getenv("SHORTFORM_ENABLE_YOUTUBE_DATA_API_SIGNALS", "1") != "0"
YOUTUBE_DATA_API_COMMENT_PAGES = max(1, int(os.getenv("SHORTFORM_YOUTUBE_DATA_API_COMMENT_PAGES", "1")))

FONT_DIR = os.path.join(BASE_DIR, "assets", "fonts")
FONT_FILE = os.getenv("SHORTFORM_EDITORIAL_FONT", os.path.join(FONT_DIR, "Montserrat-wght.ttf"))
FONT_BOLD_FILE = os.getenv("SHORTFORM_EDITORIAL_BOLD_FONT", os.path.join(FONT_DIR, "BarlowCondensed-ExtraBold.ttf"))
FONT_META_FILE = os.getenv("SHORTFORM_EDITORIAL_META_FONT", os.path.join(FONT_DIR, "BarlowCondensed-SemiBold.ttf"))
FONT_DISPLAY_FILE = os.getenv("SHORTFORM_EDITORIAL_DISPLAY_FONT", os.path.join(FONT_DIR, "Anton-Regular.ttf"))
FONT_ACCENT_FILE = os.getenv("SHORTFORM_EDITORIAL_ACCENT_FONT", os.path.join(FONT_DIR, "BebasNeue-Regular.ttf"))

STYLE_ADJECTIVES = [
    "most surprising",
    "most useful",
    "most heated",
    "most controversial",
    "smartest",
    "wildest",
    "funniest",
    "coolest",
    "most unexpected",
    "most overlooked",
    "most revealing",
    "most important",
    "most interesting",
    "most practical",
    "strangest",
    "most debated",
    "biggest",
    "most underrated",
    "sharpest",
    "most uncomfortable",
]
ADJECTIVE_ROTATION_FILE = os.path.join(BASE_DIR, "src", "adjective_rotation.json")

THEME_TAGS = {
    "comedy": {
        "label": "comedy",
        "hashtags": ["#comedy", "#funny", "#podcast", "#shorts"],
        "tags": ["comedy", "funny", "podcast clips", "comedy shorts", "comedian", "humor"],
    },
    "finance": {
        "label": "finance",
        "hashtags": ["#finance", "#money", "#business", "#shorts"],
        "tags": ["finance", "money", "business", "economics", "investing", "finance shorts"],
    },
    "sports": {
        "label": "sports",
        "hashtags": ["#sports", "#athlete", "#podcast", "#shorts"],
        "tags": ["sports", "athlete interviews", "sports podcast", "nba", "nfl", "sports shorts"],
    },
    "lifestyle": {
        "label": "lifestyle",
        "hashtags": ["#lifestyle", "#wellness", "#mindset", "#shorts"],
        "tags": ["lifestyle", "wellness", "mindset", "self improvement", "health", "lifestyle podcast"],
    },
    "gaming": {
        "label": "gaming",
        "hashtags": ["#gaming", "#videogames", "#gamingnews", "#shorts"],
        "tags": ["gaming", "video games", "gaming podcast", "game developer", "esports", "gaming shorts"],
    },
}

STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "could", "every",
    "from", "have", "just", "like", "really", "right", "that", "their", "there",
    "they", "this", "those", "what", "when", "where", "which", "with", "would",
    "your", "youre", "yeah", "thing", "things", "people", "going", "think",
    "podcast", "episode", "shorts", "short", "video", "clip", "clips",
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
        print(" ".join(str(part) for part in cmd))
        print("\nFFmpeg stderr:")
        print(result.stderr[-4000:])
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")

    return result


def compact_text(text, max_length):
    text = re.sub(r"\s+", " ", str(text or "")).strip()

    if len(text) <= max_length:
        return text

    return text[: max(0, max_length - 1)].rstrip(" ,.;:-") + "..."


def clean_filename(value):
    cleaned = "".join(
        char for char in str(value or "")
        if char.isalnum() or char in [" ", ".", "_", "-"]
    ).replace(" ", "_")
    return cleaned[:150].strip("._-") or "editorial"


def words_from_text(text):
    return re.findall(r"[a-zA-Z][a-zA-Z0-9']{2,}", str(text or "").lower())


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


def get_duration(media_path):
    result = subprocess.run(
        [
            FFPROBE_EXE,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        return 0.0

    try:
        return float(result.stdout.strip() or 0)
    except ValueError:
        return 0.0


def ffmpeg_path(path):
    return os.path.abspath(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def drawtext_text(text):
    text = compact_text(text, 180)
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = text.replace("‘", "")
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")
    text = text.replace("\n", " ")
    return text


def fitted_topic_font_size(text):
    estimated_chars = max(1, len(text))
    estimated_width_per_font_px = 0.62
    max_width = 940
    return max(36, min(58, int(max_width / (estimated_chars * estimated_width_per_font_px))))


def fitted_label_font_size(text, max_width=760, max_size=44, min_size=30):
    estimated_chars = max(1, len(text))
    estimated_width_per_font_px = 0.62
    return max(min_size, min(max_size, int(max_width / (estimated_chars * estimated_width_per_font_px))))


def countdown_slot_for_rank(rank, total_count):
    return max(1, int(total_count) - int(rank) + 1)


def period_label():
    return EDITORIAL_PERIOD_LABEL.replace("_", " ")


def theme_profile(theme):
    default = {
        "label": theme.replace("_", " "),
        "hashtags": ["#podcast", "#recap", "#shorts"],
        "tags": ["podcast", "recap", "shorts", theme.replace("_", " ")],
    }
    return {**default, **THEME_TAGS.get(theme, {})}


def normalized_adjective_queue(queue):
    cleaned = unique_sequence(queue)
    cleaned = [item for item in cleaned if item in STYLE_ADJECTIVES]

    for adjective in STYLE_ADJECTIVES:
        if adjective not in cleaned:
            cleaned.append(adjective)

    return cleaned


def load_adjective_rotation_state():
    state = load_json_file(ADJECTIVE_ROTATION_FILE, {"themes": {}})

    if not isinstance(state, dict):
        state = {"themes": {}}

    state.setdefault("themes", {})
    return state


def save_adjective_rotation_state(state):
    write_json_file(ADJECTIVE_ROTATION_FILE, state)


def take_next_adjectives(theme, count):
    state = load_adjective_rotation_state()
    theme_state = state["themes"].setdefault(theme, {})
    queue = normalized_adjective_queue(theme_state.get("queue", STYLE_ADJECTIVES))
    selected = []

    for _ in range(max(0, count)):
        adjective = queue.pop(0)
        selected.append(adjective)
        queue.append(adjective)

    theme_state["queue"] = queue
    theme_state["last_used"] = selected
    theme_state["updated_at"] = utc_timestamp()
    save_adjective_rotation_state(state)
    return selected


def load_rendered_clip_reviews(metadata_path):
    clips = []

    if not os.path.isdir(metadata_path):
        return clips

    for filename in sorted(os.listdir(metadata_path)):
        if not filename.endswith("_clip_review.json"):
            continue

        path = os.path.join(metadata_path, filename)

        try:
            payload = load_json_file(path, {})
        except Exception:
            continue

        changed = False

        for clip in payload.get("selected", []):
            output_file = clip.get("output_file", "")

            if output_file and os.path.exists(output_file):
                if not clip_is_editorial_usable(clip):
                    changed = changed or bool(clip.pop("_render_qc_augmented", False))
                    continue

                changed = changed or bool(clip.pop("_render_qc_augmented", False))
                clip["_review_file"] = path
                clips.append(clip)

        if changed:
            persist_payload = json.loads(json.dumps(payload))

            for persisted_clip in persist_payload.get("selected", []):
                persisted_clip.pop("_review_file", None)
                persisted_clip.pop("_render_qc_augmented", None)

            write_json_file(path, persist_payload)

    return clips


def clip_render_qc(clip):
    value = clip.get("render_qc")

    if (
        isinstance(value, dict)
        and value
        and (
            value.get("visual_quality_score") is not None
            or value.get("frame_path")
        )
    ):
        return value

    output_file = clip.get("output_file", "")

    if not output_file or not os.path.exists(output_file):
        return {}

    try:
        import clip_generation

        frame_qc = clip_generation.analyze_final_frame_path(output_file, max_samples=12)
        existing_flags = []

        if isinstance(value, dict):
            existing_flags = [
                flag
                for flag in value.get("flags", [])
                if flag not in {"low framing confidence"}
            ]

        render_qc = {
            "passed": not frame_qc.get("flags"),
            "flags": sorted(set(existing_flags + list(frame_qc.get("flags", [])))),
            "visual_quality_score": frame_qc.get("visual_quality_score", 0.0),
            "frame_path": frame_qc,
            "render_strategy": (value or {}).get("render_strategy", "legacy_on_demand_audit") if isinstance(value, dict) else "legacy_on_demand_audit",
        }
        clip["render_qc"] = render_qc
        clip["_render_qc_augmented"] = True
        return render_qc
    except Exception:
        return {}


def clip_visual_quality_score(clip):
    render_qc = clip_render_qc(clip)

    if not render_qc:
        return 0.62

    return float(render_qc.get("visual_quality_score") or render_qc.get("attempt_quality_score") or 0.0)


def clip_is_editorial_usable(clip):
    render_qc = clip_render_qc(clip)

    if not render_qc:
        return True

    flags = set(render_qc.get("flags") or [])
    hard_flags = {
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
        "possible black frames",
        "missing audio",
        "unexpected resolution",
    }

    if flags & hard_flags:
        return False

    return clip_visual_quality_score(clip) >= 0.52


def editorial_output_rejection_reasons(frame_qc):
    flags = set(frame_qc.get("flags") or [])
    hard_flags = {
        "could not open final render",
        "no final render frames",
        "no readable final frames",
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
    }
    reasons = sorted(flags & hard_flags)
    visual_score = float(frame_qc.get("visual_quality_score") or 0.0)

    if visual_score < MIN_EDITORIAL_VISUAL_QUALITY:
        reasons.append(
            f"low editorial visual quality score ({visual_score:.2f} < {MIN_EDITORIAL_VISUAL_QUALITY:.2f})"
        )

    return reasons


def finalize_editorial_package(package, label):
    output_file = package.get("video_file", "")

    if not output_file or not os.path.exists(output_file):
        package.setdefault("posting_status", {})["youtube_shorts"] = "failed"
        package.setdefault("review", {})["rejection_reason"] = "missing rendered editorial output"
        return package

    try:
        import clip_generation

        frame_qc = clip_generation.analyze_final_frame_path(output_file, max_samples=24)
    except Exception as error:
        frame_qc = {
            "flags": [f"final editorial QA failed: {error}"],
            "visual_quality_score": 0.0,
        }

    rejection_reasons = editorial_output_rejection_reasons(frame_qc)
    package["render_qc"] = {
        "passed": not rejection_reasons,
        "flags": sorted(set(list(frame_qc.get("flags") or []) + rejection_reasons)),
        "visual_quality_score": frame_qc.get("visual_quality_score", 0.0),
        "frame_path": frame_qc,
        "rejected": bool(rejection_reasons),
        "rejection_reasons": rejection_reasons,
        "render_strategy": "editorial_post_render_gate",
    }

    if rejection_reasons:
        package.setdefault("posting_status", {})["youtube_shorts"] = "failed"
        review = package.setdefault("review", {})
        review["approved"] = False
        review["rejection_reason"] = "; ".join(rejection_reasons)
        print(f" -> Rejecting {label}: {', '.join(rejection_reasons)}")

        if EDITORIAL_HARD_REJECT_BAD_OUTPUTS:
            try:
                os.remove(output_file)
            except OSError:
                pass

            package["video_file"] = ""

    return package


def package_is_upload_ready(package):
    return (
        bool(package.get("video_file"))
        and os.path.exists(package.get("video_file", ""))
        and (package.get("posting_status") or {}).get("youtube_shorts") == "ready"
        and not (package.get("render_qc") or {}).get("rejected")
    )


def editorial_clip_score(clip):
    base_score = float(clip.get("score") or 0)
    visual_score = clip_visual_quality_score(clip)
    render_qc = clip_render_qc(clip)
    penalty = 0.0

    if render_qc and not render_qc.get("passed", True):
        penalty += 0.05

    if "unstable final subject position" in set(render_qc.get("flags") or []):
        penalty += 0.035

    return base_score + 0.12 * visual_score - penalty


def topic_label_from_clip(clip):
    suggested_title = compact_text(clip.get("suggested_title", ""), 58).strip(" .")

    if suggested_title and len(words_from_text(suggested_title)) >= 4:
        return suggested_title

    terms = [
        str(term).replace("_", " ").replace("'", "").replace("’", "").strip().lower()
        for term in clip.get("topic_fingerprint", [])
        if str(term).strip()
    ]
    terms = [
        term
        for term in terms
        if term not in STOPWORDS and len(term) >= 4
    ]

    if terms:
        return compact_text(" / ".join(terms[:2]).title(), 44)

    text = " ".join([
        clip.get("suggested_title", ""),
        clip.get("transcript_excerpt", ""),
        clip.get("source_title", ""),
    ])
    counts = {}

    for word in words_from_text(text):
        normalized = word.strip("'").replace("'", "")

        if normalized in STOPWORDS or len(normalized) < 4:
            continue

        counts[normalized] = counts.get(normalized, 0) + 1

    ranked = sorted(counts, key=lambda word: (-counts[word], word))

    if ranked:
        return compact_text(" ".join(ranked[:2]).title(), 44)

    return "The Big Takeaway"


def group_clips_by_topic(clips):
    groups = {}

    for clip in clips:
        topic = topic_label_from_clip(clip)
        key = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_") or "takeaway"
        groups.setdefault(key, {
            "topic": topic,
            "clips": [],
            "sources": set(),
        })
        groups[key]["clips"].append(clip)
        source = clip.get("source_title") or clip.get("source_video_url") or ""

        if source:
            groups[key]["sources"].add(source)

    ranked_groups = []

    for group in groups.values():
        group_clips = sorted(group["clips"], key=editorial_clip_score, reverse=True)
        max_score = float(group_clips[0].get("score") or 0)
        avg_score = sum(float(item.get("score") or 0) for item in group_clips) / max(1, len(group_clips))
        avg_visual = sum(clip_visual_quality_score(item) for item in group_clips) / max(1, len(group_clips))
        group["clips"] = group_clips
        group["score"] = (
            max_score
            + 0.08 * math.log1p(len(group_clips))
            + 0.06 * math.log1p(len(group["sources"]))
            + 0.20 * avg_score
            + 0.10 * avg_visual
        )
        ranked_groups.append(group)

    return sorted(ranked_groups, key=lambda item: item["score"], reverse=True)


def clip_state_key(theme, clip):
    return clip.get("source_state_key") or f"{theme}|{clip.get('source_video_url', '')}"


def record_state_key(theme, record):
    return record.get("state_key") or f"{theme}|{record.get('video_url', '')}"


def youtube_video_id(video_url):
    parsed = urllib.parse.urlparse(str(video_url or "").strip())
    host = parsed.netloc.lower().replace("www.", "")

    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]

    query_video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]

    if query_video_id:
        return query_video_id

    parts = [part for part in parsed.path.split("/") if part]

    for marker in ["shorts", "embed", "live", "v"]:
        if marker in parts:
            marker_index = parts.index(marker)

            if marker_index + 1 < len(parts):
                return parts[marker_index + 1]

    return ""


def source_thumbnail_cache_dir(paths):
    directory = os.path.join(paths["metadata_path"], "editorial", "_thumbnails")
    os.makedirs(directory, exist_ok=True)
    return directory


def download_youtube_thumbnail(paths, video_url):
    video_id = youtube_video_id(video_url)

    if not video_id:
        return ""

    cache_file = os.path.join(source_thumbnail_cache_dir(paths), clean_filename(video_id) + ".jpg")

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 1200:
        return cache_file

    request_headers = {"User-Agent": "Mozilla/5.0"}
    thumbnail_urls = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
    ]

    for thumbnail_url in thumbnail_urls:
        try:
            request = urllib.request.Request(thumbnail_url, headers=request_headers)

            with urllib.request.urlopen(request, timeout=12) as response:
                image_bytes = response.read()

            if len(image_bytes) < 1200:
                continue

            with open(cache_file, "wb") as f:
                f.write(image_bytes)

            return cache_file
        except (OSError, urllib.error.URLError, urllib.error.HTTPError):
            continue

    return cache_file if os.path.exists(cache_file) else ""


def load_theme_source_records(theme):
    pulled = load_json_file(PULLED_FILE, {})
    records = []

    for key, record in pulled.items():
        if record.get("theme") != theme:
            continue

        item = dict(record)
        item.setdefault("state_key", key)
        records.append(item)

    return sorted(records, key=lambda item: item.get("pulled_at") or item.get("fetched_at") or "", reverse=True)


def source_audio_candidates(theme, record):
    audio_dir = os.path.join(BASE_DIR, "output", "temp", theme, "downloads", "audio")
    cleaned_title = record.get("_last_cleaned_title") or record.get("clip_prefix") or ""

    if not cleaned_title:
        return []

    extensions = [".m4a", ".mp3", ".opus", ".wav", ".webm", ".aac"]
    return [os.path.join(audio_dir, f"{cleaned_title}{extension}") for extension in extensions]


def max_clip_end_by_source(theme, clips):
    ends = {}

    for clip in clips:
        key = clip_state_key(theme, clip)
        end_time = float(clip.get("end_time") or 0)

        if end_time > ends.get(key, 0):
            ends[key] = end_time

    return ends


def best_clip_by_source(theme, clips):
    best = {}

    for clip in clips:
        key = clip_state_key(theme, clip)
        score = float(clip.get("score") or 0)

        if key not in best or score > float(best[key].get("score") or 0):
            best[key] = clip

    return best


def source_duration_seconds(theme, record, fallback_clip_ends):
    for candidate in source_audio_candidates(theme, record):
        if os.path.exists(candidate):
            duration = get_duration(candidate)

            if duration > 0:
                return duration

    for field in ["duration", "duration_seconds", "source_duration"]:
        duration = float(record.get(field) or 0)

        if duration > 0:
            return duration

    return float(fallback_clip_ends.get(record_state_key(theme, record), 0) or 0)


def watched_hours_for_sources(theme, records, clips):
    fallback_clip_ends = max_clip_end_by_source(theme, clips)
    seen = set()
    total_seconds = 0.0

    for record in records:
        key = record_state_key(theme, record)

        if key in seen:
            continue

        seen.add(key)
        total_seconds += source_duration_seconds(theme, record, fallback_clip_ends)

    return total_seconds / 3600.0


def format_hours_phrase(hours):
    hours = max(0.1, float(hours or 0))

    if hours < 1:
        minutes = max(1, round(hours * 60))
        return f"{minutes} minutes"

    if hours < 10:
        value = round(hours, 1)
        return f"{value:g} hours"

    return f"{round(hours)} hours"


def first_label_character(text):
    match = re.search(r"[A-Za-z0-9]", str(text or ""))
    return match.group(0).upper() if match else "#"


KNOWN_CHANNEL_LABELS = {
    "joerogan": "Joe Rogan",
    "theovon": "Theo Von",
    "ucwzcmiiclhbuzyjwijaseg": "Kill Tony",
    "badfriends": "Bad Friends",
    "ymhstudios": "YMH Studios",
    "officialflagrant": "Flagrant",
    "tigerbelly": "TigerBelly",
    "andrewsantinowhiskeyginger": "Whiskey Ginger",
    "stavvysworld": "Stavvy's World",
    "areyougarbage": "Are You Garbage",
}


def humanize_channel_slug(slug):
    slug = re.sub(r"[_\-]+", " ", str(slug or "").strip("@/ "))
    slug = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()

    if not slug:
        return "Podcast Channel"

    if slug.islower():
        return slug.title()

    return slug


def channel_label_from_url(channel_url):
    parsed = urllib.parse.urlparse(str(channel_url or "").strip())
    parts = [part for part in parsed.path.split("/") if part and part.lower() not in {"videos", "featured", "shorts"}]

    if not parts:
        return "Podcast Channel"

    slug = parts[-1].strip("@")
    normalized = re.sub(r"[^a-z0-9]+", "", slug.lower())

    if normalized in KNOWN_CHANNEL_LABELS:
        return KNOWN_CHANNEL_LABELS[normalized]

    if normalized.startswith("uc") and len(normalized) > 12:
        return "Podcast Channel"

    return humanize_channel_slug(slug)


def channel_label_for_record(record):
    for field in ["channel_name", "channel", "uploader", "creator", "source_channel"]:
        if record.get(field):
            return compact_text(record[field], 38)

    return compact_text(channel_label_from_url(record.get("channel_url", "")), 38)


def clip_summary(clip, fallback_topic=""):
    title = compact_text(clip.get("suggested_title") or fallback_topic, 78).strip(" .")

    if title:
        return title

    excerpt = compact_text(clip.get("transcript_excerpt", ""), 96).strip(" .")
    return excerpt or "Best moment from the scan"


def source_banner_summary(record, source_best_clip, adjective, theme_label):
    if source_best_clip:
        return clip_summary(source_best_clip)

    if record.get("_last_error_type"):
        return channel_label_for_record(record)

    return channel_label_for_record(record)


def editorial_popularity_cache_dir(paths):
    directory = os.path.join(paths["metadata_path"], "_popularity")
    os.makedirs(directory, exist_ok=True)
    return directory


def load_or_fetch_editorial_popularity_profile(paths, video_url, cleaned_title=""):
    if not video_url:
        return {}

    cache_dir = editorial_popularity_cache_dir(paths)
    cached = load_cached_popularity_profile(cache_dir, video_url, cleaned_title)
    api_signals_requested = bool(
        ENABLE_YOUTUBE_DATA_API_SIGNALS
        and YOUTUBE_DATA_API_KEY
    )

    if cached is not None and (
        not api_signals_requested
        or cached.get("fetched_with_youtube_data_api")
    ):
        return cached

    if yt_dlp is None:
        profile = cached or {}
    else:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 14,
                "extractor_retries": 1,
                "retries": 2,
            }

            info = ytdlp_auth.run_ytdlp_with_auth_retry(
                opts,
                lambda ydl: ydl.extract_info(video_url, download=False),
                reason="editorial popularity metadata",
            )

            profile = build_popularity_profile_from_info(info or {})
        except Exception as error:
            profile = cached or {
                "video_id": "",
                "title": cleaned_title,
                "duration": 0,
                "heatmap": [],
                "timestamp_markers": [],
                "chapters": [],
                "sources": [],
                "error": str(error)[:300],
            }

    if api_signals_requested:
        try:
            api_profile = build_youtube_data_api_profile(
                video_url,
                YOUTUBE_DATA_API_KEY,
                duration=profile.get("duration", 0),
                pages_per_order=YOUTUBE_DATA_API_COMMENT_PAGES,
            )
            profile = merge_popularity_profiles(profile, api_profile)
            profile["fetched_with_youtube_data_api"] = True
        except Exception as error:
            profile["fetched_with_youtube_data_api"] = False
            profile["youtube_data_api_error"] = str(error)[:300]

    save_popularity_profile(cache_dir, video_url, profile, cleaned_title)
    return profile


def clip_existing_popularity_score(clip):
    score = float(clip.get("popularity_score") or 0)

    if score > 0:
        return score

    rank_signals = clip.get("rank_signals") or {}
    return float(rank_signals.get("popularity_score") or 0)


def enrich_clip_popularity(theme, paths, clip):
    score = clip_existing_popularity_score(clip)
    rank_signals = clip.get("rank_signals")

    if not isinstance(rank_signals, dict):
        rank_signals = {}
        clip["rank_signals"] = rank_signals

    if score > 0:
        return score

    video_url = clip.get("source_video_url", "")
    cleaned_title = clean_filename(clip.get("source_title") or video_url)
    profile = load_or_fetch_editorial_popularity_profile(paths, video_url, cleaned_title)
    details = score_popularity_for_window(profile, clip.get("start_time", 0), clip.get("end_time", 0))
    score = float(details.get("score") or 0)
    clip["popularity_score"] = score
    rank_signals["popularity_score"] = score
    rank_signals["popularity_source"] = details.get("source", "")
    rank_signals["popularity_heatmap_score"] = float(details.get("heatmap_score") or 0)
    rank_signals["popularity_timestamp_score"] = float(details.get("timestamp_score") or 0)
    rank_signals["popularity_chapter_score"] = float(details.get("chapter_score") or 0)
    rank_signals["popularity_profile_sources"] = details.get("profile_sources", [])
    return score


def popular_sort_score(clip):
    popularity_score = clip_existing_popularity_score(clip)
    quality_score = float(clip.get("score") or 0)
    opening_score = float(clip.get("opening_score") or 0)
    comment_score = float(clip.get("comment_score") or 0)
    comment_topic_score = float((clip.get("rank_signals") or {}).get("comment_topic_score") or 0)
    visual_score = clip_visual_quality_score(clip)
    return (
        0.58 * popularity_score
        + 0.17 * quality_score
        + 0.08 * opening_score
        + 0.04 * comment_score
        + 0.05 * comment_topic_score
        + 0.08 * visual_score
    )


def popular_segment_items(theme, paths, rendered_clips):
    records = load_theme_source_records(theme)
    records_by_key = {record_state_key(theme, record): record for record in records}
    records_by_url = {record.get("video_url", ""): record for record in records}
    grouped = {}

    for clip in rendered_clips:
        if not clip.get("output_file") or not os.path.exists(clip.get("output_file", "")):
            continue

        popularity_score = enrich_clip_popularity(theme, paths, clip)

        if POPULAR_SEGMENT_REQUIRE_SIGNAL and popularity_score < POPULAR_SEGMENT_MIN_SCORE:
            continue

        key = clip_state_key(theme, clip)
        grouped.setdefault(key, []).append(clip)

    items = []

    for key, clips in grouped.items():
        best_clip = max(clips, key=popular_sort_score)
        source_record = records_by_key.get(key) or records_by_url.get(best_clip.get("source_video_url", "")) or {}
        items.append({
            "source_state_key": key,
            "source_title": best_clip.get("source_title") or source_record.get("title") or "Podcast interview",
            "source_video_url": best_clip.get("source_video_url") or source_record.get("video_url", ""),
            "channel_label": channel_label_for_record(source_record),
            "clip": best_clip,
            "popularity_score": clip_existing_popularity_score(best_clip),
            "sort_score": popular_sort_score(best_clip),
            "thumbnail_file": download_youtube_thumbnail(paths, best_clip.get("source_video_url") or source_record.get("video_url", "")),
        })

    items = sorted(items, key=lambda item: item["sort_score"], reverse=True)

    if POPULAR_SEGMENTS_PER_THEME > 0:
        items = items[:POPULAR_SEGMENTS_PER_THEME]

    return items


def build_countdown_context(theme, paths, rendered_clips, topic_groups, adjective):
    theme_label = theme_profile(theme)["label"]
    records = load_theme_source_records(theme)
    records_by_video_url = {record.get("video_url", ""): record for record in records}
    source_best = best_clip_by_source(theme, rendered_clips)
    top_entries = []
    total_count = len(topic_groups)

    for index, topic in enumerate(topic_groups, start=1):
        clip = topic["clips"][0]
        source_record = records_by_video_url.get(clip.get("source_video_url", ""), {})
        slot = countdown_slot_for_rank(index, total_count)
        top_entries.append({
            "slot": slot,
            "rank_index": index,
            "topic": topic["topic"],
            "title": compact_text(clip.get("source_title") or topic["topic"], 72),
            "summary": clip_summary(clip, topic["topic"]),
            "source_title": compact_text(clip.get("source_title") or "source episode", 72),
            "source_state_key": clip_state_key(theme, clip),
            "source_video_url": clip.get("source_video_url", ""),
            "channel_label": channel_label_for_record(source_record),
            "clip_file": clip.get("output_file", ""),
            "thumbnail_file": download_youtube_thumbnail(paths, clip.get("source_video_url", "")),
            "score": float(topic.get("score") or clip.get("score") or 0),
        })

    top_by_key = {entry["source_state_key"]: entry for entry in top_entries}
    source_banners = []

    for record in records:
        key = record_state_key(theme, record)
        source_best_clip = source_best.get(key)
        top_entry = top_by_key.get(key)
        banner_clip = top_entry.get("clip_file") if top_entry else (source_best_clip or {}).get("output_file", "")
        thumbnail_file = (
            (top_entry or {}).get("thumbnail_file")
            or download_youtube_thumbnail(paths, record.get("video_url", ""))
        )
        source_banners.append({
            "title": compact_text(record.get("title") or record.get("video_url") or "Interview", 74),
            "summary": compact_text(source_banner_summary(record, source_best_clip, adjective, theme_label), 92),
            "channel_label": channel_label_for_record(record),
            "letter": first_label_character(record.get("title") or record.get("video_url")),
            "source_state_key": key,
            "is_top": bool(top_entry),
            "slot": top_entry["slot"] if top_entry else None,
            "clip_file": banner_clip if banner_clip and os.path.exists(banner_clip) else "",
            "thumbnail_file": thumbnail_file if thumbnail_file and os.path.exists(thumbnail_file) else "",
        })

    seen_keys = {entry["source_state_key"] for entry in source_banners}

    for entry in top_entries:
        if entry["source_state_key"] in seen_keys:
            continue

        source_banners.append({
            "title": entry["source_title"],
            "summary": entry["summary"],
            "letter": first_label_character(entry["source_title"]),
            "source_state_key": entry["source_state_key"],
            "is_top": True,
            "slot": entry["slot"],
            "channel_label": entry.get("channel_label", "Podcast Channel"),
            "clip_file": entry.get("clip_file", ""),
            "thumbnail_file": entry.get("thumbnail_file", ""),
        })

    source_banners = source_banners[:EDITORIAL_BOARD_SOURCE_LIMIT]

    for entry in top_entries:
        if entry["source_state_key"] not in {banner["source_state_key"] for banner in source_banners}:
            source_banners.append({
                "title": entry["source_title"],
                "summary": entry["summary"],
                "letter": first_label_character(entry["source_title"]),
                "source_state_key": entry["source_state_key"],
                "is_top": True,
                "slot": entry["slot"],
                "channel_label": entry.get("channel_label", "Podcast Channel"),
                "clip_file": entry.get("clip_file", ""),
                "thumbnail_file": entry.get("thumbnail_file", ""),
            })

    return {
        "theme": theme,
        "theme_label": theme_label,
        "adjective": adjective,
        "watched_hours": watched_hours_for_sources(theme, records, rendered_clips),
        "source_count": len(records),
        "source_banners": source_banners,
        "top_entries": top_entries,
    }


def attach_countdown_context(topic_groups, context):
    top_by_index = {entry["rank_index"]: entry for entry in context["top_entries"]}

    for index, topic in enumerate(topic_groups, start=1):
        entry = top_by_index.get(index)
        topic["_countdown_context"] = context
        topic["_countdown_entry"] = entry
        topic["_total_count"] = len(topic_groups)
        topic["_countdown_slot"] = entry["slot"] if entry else countdown_slot_for_rank(index, len(topic_groups))


def fallback_countdown_context(theme, paths, topic_item, adjective):
    clips = load_rendered_clip_reviews(paths["metadata_path"])
    topic_groups = group_clips_by_topic(clips)[:EDITORIAL_COUNTDOWN_SIZE] or [topic_item]
    context = build_countdown_context(theme, paths, clips, topic_groups, adjective)
    attach_countdown_context(topic_groups, context)
    return context


def elevenlabs_tts_text(text):
    if ELEVENLABS_MODEL_ID != "eleven_v3":
        return text

    return (
        "[engaging social video host, expressive pacing, confident conversational tone, "
        f"high inflection, natural pauses] {text}"
    )


def process_narration_audio(input_path, scratch_dir, date_key, theme, rank):
    pitch = max(0.55, min(1.15, NARRATION_PITCH))
    raw_duration = max(0.1, get_duration(input_path))
    target_ceiling = max(3.0, EDITORIAL_INTRO_MAX_SECONDS - 0.35)
    target_duration = max(2.6, min(target_ceiling, NARRATION_TARGET_SECONDS))
    tempo = max(1.0, min(2.0, raw_duration / target_duration))
    output_path = os.path.join(scratch_dir, f"{date_key}_{theme}_{rank:02d}_intro_mastered.wav")

    if abs(pitch - 1.0) < 0.01 and abs(NARRATION_BASS_GAIN) < 0.1 and tempo <= 1.01:
        return input_path

    audio_filters = ["aresample=44100"]

    if abs(pitch - 1.0) >= 0.01:
        audio_filters.append(f"rubberband=pitch={pitch:.3f}")

    if tempo > 1.01:
        audio_filters.append(f"atempo={tempo:.3f}")

    if abs(NARRATION_BASS_GAIN) >= 0.1:
        audio_filters.append(f"bass=g={NARRATION_BASS_GAIN:.2f}:f=110:w=0.65")

    audio_filters.extend([
        "treble=g=-0.6:f=4200:w=0.8",
        "alimiter=limit=0.94",
        f"loudnorm=I={NARRATION_LOUDNESS_I:.1f}:TP=-1.5:LRA=8",
    ])
    audio_filter = ",".join(audio_filters)

    try:
        run_subprocess([
            FFMPEG_EXE,
            "-y",
            "-i", input_path,
            "-af", audio_filter,
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            output_path,
        ], "Narration pitch and mastering")
        return output_path
    except Exception as error:
        print(f" -> Narration mastering unavailable; using raw voiceover: {error}")
        return input_path


def synthesize_elevenlabs_intro(text, audio_path, voice_id=None):
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("Missing ELEVENLABS_API_KEY")

    voice_id = (voice_id or ELEVENLABS_VOICE_ID).strip()
    query = urllib.parse.urlencode({"output_format": ELEVENLABS_OUTPUT_FORMAT})
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?{query}"
    payload = {
        "text": elevenlabs_tts_text(text),
        "model_id": ELEVENLABS_MODEL_ID,
        "voice_settings": {
            "stability": ELEVENLABS_STABILITY,
            "similarity_boost": ELEVENLABS_SIMILARITY_BOOST,
            "style": ELEVENLABS_STYLE,
            "use_speaker_boost": ELEVENLABS_SPEAKER_BOOST,
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            audio_bytes = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ElevenLabs TTS failed: HTTP {error.code} {detail[:600]}") from error

    if not audio_bytes:
        raise RuntimeError("ElevenLabs TTS returned empty audio")

    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    return audio_path


def synthesize_windows_narration(text, wav_path, scratch_dir):
    text_file = os.path.join(scratch_dir, f"{clean_filename(os.path.basename(wav_path))}.txt")

    with open(text_file, "w", encoding="utf-8") as f:
        f.write(text)

    command = (
        "$ErrorActionPreference = 'Stop'; "
        "Add-Type -AssemblyName System.Speech; "
        f"$text = Get-Content -Raw -LiteralPath '{text_file}'; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$speaker.Rate = {NARRATION_RATE}; "
        f"$speaker.Volume = {NARRATION_VOLUME}; "
        f"$speaker.SetOutputToWaveFile('{wav_path}'); "
        "$speaker.Speak($text); "
        "$speaker.Dispose();"
    )
    run_subprocess([
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", command,
    ], "Windows narration synthesis")

    return wav_path


def synthesize_intro_audio(text, scratch_dir, date_key, theme, rank):
    os.makedirs(scratch_dir, exist_ok=True)

    if TTS_PROVIDER == "elevenlabs":
        voice_ids = []

        for voice_id in [ELEVENLABS_VOICE_ID, *ELEVENLABS_FALLBACK_VOICE_IDS]:
            if voice_id and voice_id not in voice_ids:
                voice_ids.append(voice_id)

        last_error = None

        for voice_index, voice_id in enumerate(voice_ids):
            audio_path = os.path.join(scratch_dir, f"{date_key}_{theme}_{rank:02d}_intro_{voice_index + 1}.mp3")

            try:
                return process_narration_audio(
                    synthesize_elevenlabs_intro(text, audio_path, voice_id),
                    scratch_dir,
                    date_key,
                    theme,
                    rank,
                )
            except Exception as error:
                last_error = error
                if voice_index < len(voice_ids) - 1:
                    print(" -> ElevenLabs voice unavailable; trying fallback voice.")
                    continue

            if not ALLOW_WINDOWS_TTS_FALLBACK:
                raise

            print(f" -> ElevenLabs TTS unavailable; falling back to Windows voice: {last_error}")

    elif TTS_PROVIDER != "windows":
        raise RuntimeError(f"Unsupported SHORTFORM_TTS_PROVIDER: {TTS_PROVIDER}")

    wav_path = os.path.join(scratch_dir, f"{date_key}_{theme}_{rank:02d}_intro.wav")
    return process_narration_audio(
        synthesize_windows_narration(text, wav_path, scratch_dir),
        scratch_dir,
        date_key,
        theme,
        rank,
    )


def spoken_topic(topic):
    topic = compact_text(topic.strip(), 82).rstrip(" .!?")
    if not topic:
        return "this moment"

    return topic[0].lower() + topic[1:]


def build_editorial_intro(theme, topic, rank, total_count, adjective, clip):
    theme_label = theme_profile(theme)["label"]
    context = clip.get("_countdown_context") or {}
    hours_phrase = format_hours_phrase(context.get("watched_hours", 0))

    return (
        f"I watched {hours_phrase} of {theme_label}. "
        f"Top {total_count} {adjective} moments."
    )


def build_output_package(theme, output_path, source_clip, topic_item, rank, adjective, date_key, is_recap=False):
    profile = theme_profile(theme)
    theme_label = profile["label"]
    topic = topic_item["topic"]
    total_count = int(topic_item.get("_total_count") or DAILY_TOPIC_COUNT)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    best_clip = topic_item["clips"][0]
    title = (
        f"Today's {theme_label.title()} Podcast Recap"
        if is_recap
        else compact_text(f"#{countdown_slot}: {topic} | {adjective.title()} {theme_label.title()} Podcast Moments", 95)
    )
    description = (
        f"Ranking the {adjective} moments from {period_label()} {theme_label} podcasts. "
        f"Number {countdown_slot} is about {topic}."
    )
    hashtags = unique_sequence(profile["hashtags"] + ["#podcastscan", "#recap", "#shorts"])[:8]
    tags = unique_sequence(profile["tags"] + [
        "podcast recap",
        "daily podcast recap",
        "podcast scan",
        topic.lower(),
        adjective,
        theme_label,
    ])[:24]

    return {
        "theme": theme,
        "content_format": "daily_editorial_recap" if is_recap else "daily_editorial_short",
        "editorial_date": date_key,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(source_clip) if source_clip else "",
        "source_state_key": f"{theme}|editorial|{date_key}|{rank}",
        "source_video_url": best_clip.get("source_video_url", ""),
        "source_title": best_clip.get("source_title", ""),
        "title": title,
        "caption": compact_text(description, 160),
        "hashtags": hashtags,
        "tags": tags,
        "description": compact_text(description, 320),
        "transcript_excerpt": best_clip.get("transcript_excerpt", ""),
        "hook_reason": f"daily {adjective} theme: {topic}",
        "score": topic_item.get("score", best_clip.get("score")),
        "review": {
            "quality_rating": "",
            "approved": False,
            "rejection_reason": "",
            "notes": "",
        },
        "platforms": {
            "youtube_shorts": {
                "title": title[:100],
                "description": f"{description}\n\n{' '.join(hashtags)}",
                "tags": tags,
                "privacy_status": "private",
            }
        },
        "posting_status": {
            "youtube_shorts": "ready",
        },
        "platform_uploads": {},
        "platform_metrics": {
            "youtube_shorts": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
        },
    }


def visual_style(rank):
    return {
        "accent": "0xFFE08A",
        "accent2": "0x6F8FAF",
        "cream": "0xFFF4B8",
        "mint": "0xB7D7C2",
        "blue": "0x6F8FAF",
        "dark": "0x2E3440",
        "name": "archive_channel_palette",
    }


def selected_topic_clips(topic_item):
    selected = []

    for clip in topic_item.get("clips", []):
        output_file = clip.get("output_file", "")

        if output_file and os.path.exists(output_file) and clip_is_editorial_usable(clip):
            selected.append(clip)

        if len(selected) >= EDITORIAL_CLIPS_PER_SHORT:
            break

    return selected


def clip_play_duration_for(source_clip, per_clip_limit):
    source_duration = get_duration(source_clip)

    if source_duration <= 0:
        return max(EDITORIAL_CLIP_MIN_SECONDS, per_clip_limit)

    minimum = min(EDITORIAL_CLIP_MIN_SECONDS, source_duration)
    return max(minimum, min(source_duration, per_clip_limit))


def input_index_for_path(path, input_paths):
    normalized = os.path.normcase(os.path.abspath(path))

    for index, existing in enumerate(input_paths):
        if os.path.normcase(os.path.abspath(existing)) == normalized:
            return index

    input_paths.append(path)
    return len(input_paths) - 1


def banner_y_expression(index, intro_duration):
    spacing = 146
    base_y = index * spacing
    scroll_speed = 116
    reset_distance = max(1, spacing * EDITORIAL_BOARD_SOURCE_LIMIT)
    return f"mod({base_y}-t*{scroll_speed},{reset_distance})+510"


def top_board_y(index):
    return 466 + index * 225


def board_display_entries(top_entries, countdown_slot=None, window_size=5):
    entries = sorted(
        top_entries or [],
        key=lambda entry: int(entry.get("slot") or 0),
    )

    if not entries or countdown_slot is None:
        return entries[:window_size]

    slot_to_entry = {
        int(entry.get("slot") or 0): entry
        for entry in entries
        if int(entry.get("slot") or 0) > 0
    }
    slots = sorted(slot_to_entry)

    if len(slots) <= window_size:
        return [slot_to_entry[slot] for slot in slots]

    current_slot = int(countdown_slot or slots[0])
    min_slot = slots[0]
    max_slot = slots[-1]
    half_window = window_size // 2
    start_slot = current_slot - half_window
    start_slot = max(min_slot, min(start_slot, max_slot - window_size + 1))
    target_slots = [slot for slot in range(start_slot, start_slot + window_size) if slot in slot_to_entry]

    if len(target_slots) < window_size:
        for slot in slots:
            if slot not in target_slots:
                target_slots.append(slot)

            if len(target_slots) >= window_size:
                break

    return [slot_to_entry[slot] for slot in sorted(target_slots[:window_size])]


def source_banner_from_entry(entry):
    title = entry.get("source_title") or entry.get("title") or entry.get("topic") or "Source episode"

    return {
        "title": compact_text(title, 74),
        "summary": compact_text(entry.get("summary") or entry.get("topic") or "Top countdown moment", 92),
        "channel_label": entry.get("channel_label") or "Podcast Channel",
        "letter": first_label_character(title),
        "source_state_key": entry.get("source_state_key"),
        "is_top": True,
        "slot": entry.get("slot"),
        "clip_file": entry.get("clip_file", ""),
        "thumbnail_file": entry.get("thumbnail_file", ""),
    }


def ensure_display_banners(source_banners, display_entries):
    banners = list(source_banners or [])
    seen = {banner.get("source_state_key") for banner in banners}

    for entry in display_entries or []:
        key = entry.get("source_state_key")

        if key and key not in seen:
            banners.append(source_banner_from_entry(entry))
            seen.add(key)

    return banners


def trophy_color_for_slot(slot):
    if int(slot or 0) == 1:
        return (255, 224, 138, 255)

    if int(slot or 0) == 2:
        return (220, 228, 230, 255)

    if int(slot or 0) == 3:
        return (199, 128, 78, 255)

    return (183, 215, 194, 230)


def draw_trophy_icon(draw, x, y, scale, fill, outline):
    cup_w = int(34 * scale)
    cup_h = int(30 * scale)
    stem_w = int(10 * scale)
    base_w = int(34 * scale)
    bowl = [
        (x, y),
        (x + cup_w, y),
        (x + int(cup_w * 0.78), y + cup_h),
        (x + int(cup_w * 0.22), y + cup_h),
    ]
    draw.polygon(bowl, fill=fill, outline=outline)
    draw.arc((x - int(13 * scale), y + int(3 * scale), x + int(12 * scale), y + int(29 * scale)), 82, 282, fill=fill, width=max(2, int(3 * scale)))
    draw.arc((x + cup_w - int(12 * scale), y + int(3 * scale), x + cup_w + int(13 * scale), y + int(29 * scale)), -102, 98, fill=fill, width=max(2, int(3 * scale)))
    stem_x = x + int((cup_w - stem_w) / 2)
    draw.rounded_rectangle((stem_x, y + cup_h - 1, stem_x + stem_w, y + cup_h + int(18 * scale)), radius=max(1, int(2 * scale)), fill=fill, outline=outline)
    base_x = x + int((cup_w - base_w) / 2)
    draw.rounded_rectangle((base_x, y + cup_h + int(17 * scale), base_x + base_w, y + cup_h + int(27 * scale)), radius=max(1, int(3 * scale)), fill=fill, outline=outline)


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def ease_out_cubic(value):
    value = clamp(value)
    return 1 - pow(1 - value, 3)


def ease_in_out_cubic(value):
    value = clamp(value)

    if value < 0.5:
        return 4 * value * value * value

    return 1 - pow(-2 * value + 2, 3) / 2


def color_tuple(value, alpha=255):
    text = str(value or "").replace("0x", "").replace("#", "").strip()

    if len(text) != 6:
        return (255, 255, 255, alpha)

    return (
        int(text[0:2], 16),
        int(text[2:4], 16),
        int(text[4:6], 16),
        alpha,
    )


def font_path_or_fallback(path, fallback):
    if path and os.path.exists(path):
        return path

    if fallback and os.path.exists(fallback):
        return fallback

    return r"C:\Windows\Fonts\arial.ttf"


def editorial_intro_duration():
    target = min(EDITORIAL_INTRO_TARGET_SECONDS, EDITORIAL_INTRO_MAX_SECONDS)
    return max(3.25, min(5.25, target))


def pil_font(path, size):
    try:
        return ImageFont.truetype(font_path_or_fallback(path, FONT_FILE), int(size))
    except OSError:
        return ImageFont.load_default()


def fitted_pil_font(path, text, max_width, max_size, min_size):
    size = max_size

    while size > min_size:
        font = pil_font(path, size)
        bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), str(text or ""), font=font)

        if bbox[2] - bbox[0] <= max_width:
            return font

        size -= 2

    return pil_font(path, min_size)


def draw_truncated_text(draw, xy, text, font, fill, max_width, max_chars=80, stroke_width=0, stroke_fill=None):
    value = compact_text(text, max_chars)

    while value and draw.textbbox((0, 0), value, font=font, stroke_width=stroke_width)[2] > max_width:
        value = compact_text(value[:-4], max(4, len(value) - 1))

    draw.text(
        xy,
        value,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def multiply_alpha(image, alpha_multiplier):
    image = image.convert("RGBA")
    r, g, b, a = image.split()
    a = ImageEnhance.Brightness(a).enhance(clamp(alpha_multiplier))
    image.putalpha(a)
    return image


def center_crop(image, size):
    image = image.convert("RGBA")
    src_w, src_h = image.size
    target_w, target_h = size
    scale = max(target_w / max(1, src_w), target_h / max(1, src_h))
    resized = image.resize((int(src_w * scale) + 1, int(src_h * scale) + 1), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def thumbnail_image(path, size, letter, accent):
    if path and os.path.exists(path):
        try:
            return center_crop(Image.open(path), size)
        except OSError:
            pass

    image = Image.new("RGBA", size, (18, 18, 24, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0] - 1, size[1] - 1), outline=accent, width=5)
    font = pil_font(FONT_ACCENT_FILE, max(28, int(size[1] * 0.48)))
    bbox = draw.textbbox((0, 0), letter, font=font)
    draw.text(
        ((size[0] - (bbox[2] - bbox[0])) / 2, (size[1] - (bbox[3] - bbox[1])) / 2 - 4),
        letter,
        font=font,
        fill=accent,
    )
    return image


def make_scan_banner_card(banner, accent, accent2, fonts):
    width, height = 964, 124
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    title = compact_text(banner.get("title", ""), 58)
    channel_label = compact_text(banner.get("channel_label") or "Podcast Channel", 48)
    letter = banner.get("letter") or first_label_character(title)
    thumb = thumbnail_image(banner.get("thumbnail_file", ""), (120, 82), letter, accent)

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle((10, 8, width - 10, height - 8), radius=10, outline=(accent[0], accent[1], accent[2], 168), width=5)
    glow_draw.rounded_rectangle((18, 18, width - 18, height - 18), radius=8, outline=(accent2[0], accent2[1], accent2[2], 92), width=3)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(10)))

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((14, 14, width - 6, height - 2), radius=10, fill=(0, 0, 0, 118))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(7)))

    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=9, fill=(11, 16, 24, 224), outline=(255, 255, 255, 58), width=2)
    draw.polygon([(0, 0), (width * 0.45, 0), (width * 0.25, height), (0, height)], fill=(accent[0], accent[1], accent[2], 42))
    draw.polygon([(width * 0.64, 0), (width, 0), (width, height), (width * 0.52, height)], fill=(accent2[0], accent2[1], accent2[2], 28))
    draw.rectangle((0, 0, 10, height), fill=accent)
    draw.rectangle((10, 0, 14, height), fill=(255, 255, 255, 48))
    draw.line((22, 8, width - 26, 8), fill=(255, 244, 184, 82), width=2)
    draw.line((22, height - 9, width - 26, height - 9), fill=(183, 215, 194, 76), width=2)
    draw.rounded_rectangle((22, 13, 156, 111), radius=7, fill=(accent[0], accent[1], accent[2], 238))
    draw.rounded_rectangle((26, 17, 152, 107), radius=6, outline=(255, 244, 184, 210), width=3)
    image.alpha_composite(thumb, (28, 21))
    draw.rectangle((28, 21, 147, 102), outline=(0, 0, 0, 210), width=2)
    draw_truncated_text(draw, (174, 24), title, fonts["card_title"], (255, 255, 255, 255), 734, 72, stroke_width=2, stroke_fill=(0, 0, 0, 190))
    draw.rounded_rectangle((174, 72, 174 + min(520, 92 + len(channel_label) * 8), 102), radius=5, fill=(0, 0, 0, 92), outline=(255, 255, 255, 28), width=1)
    draw_truncated_text(draw, (188, 74), channel_label, fonts["small"], (accent2[0], accent2[1], accent2[2], 235), 520, 52, stroke_width=1, stroke_fill=(0, 0, 0, 150))
    return image


def make_final_banner_card(entry, accent, accent2, fonts, is_current, is_played):
    width, height = 964, 176
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    slot = int(entry.get("slot") or 0)
    title = compact_text(entry.get("source_title") or entry.get("title") or "", 52)
    summary = compact_text(entry.get("summary") or entry.get("topic") or "", 64)
    letter = first_label_character(title)
    thumb = thumbnail_image(entry.get("thumbnail_file", ""), (174, 132), letter, accent)
    trophy_color = trophy_color_for_slot(slot)
    rank_is_podium = slot in {1, 2, 3}
    rank_color = trophy_color if rank_is_podium else (accent2[0], accent2[1], accent2[2], 238)

    base_fill = (255, 224, 138, 88) if is_current else ((31, 38, 50, 216) if is_played else (37, 45, 60, 236))
    outline = (255, 224, 138, 255) if is_current else ((accent2[0], accent2[1], accent2[2], 148) if not is_played else (183, 215, 194, 48))
    text_alpha = 255 if not is_played else 122
    summary_alpha = 236 if not is_played else 118
    title_x = 350 if rank_is_podium else 324

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_color = (255, 224, 138, 210) if is_current else ((accent2[0], accent2[1], accent2[2], 112) if not is_played else (0, 0, 0, 0))
    glow_draw.rounded_rectangle((6, 6, width - 7, height - 7), radius=10, outline=glow_color, width=5)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9 if is_current else 6)))

    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=9, fill=base_fill, outline=outline, width=4 if is_current else 2)
    draw.polygon([(0, 0), (width * 0.42, 0), (width * 0.25, height), (0, height)], fill=(255, 224, 138, 32 if is_current else 18))
    draw.polygon([(width * 0.52, 0), (width, 0), (width, height), (width * 0.72, height)], fill=(accent2[0], accent2[1], accent2[2], 26 if not is_played else 10))
    draw.rectangle((0, 0, 12, height), fill=(255, 224, 138, 255) if is_current else (accent2[0], accent2[1], accent2[2], 138))
    draw.rectangle((12, 0, 16, height), fill=(255, 255, 255, 52 if not is_played else 22))
    draw.line((28, 10, width - 28, 10), fill=(255, 244, 184, 98 if not is_played else 32), width=2)
    draw.line((28, height - 11, width - 28, height - 11), fill=(accent2[0], accent2[1], accent2[2], 88 if not is_played else 30), width=2)
    draw.rounded_rectangle((20, 20, 198, 156), radius=7, fill=(0, 0, 0, 220), outline=(255, 255, 255, 34), width=1)
    draw.rounded_rectangle((24, 24, 194, 152), radius=5, outline=(255, 224, 138, 190 if is_current else 84), width=3)
    image.alpha_composite(thumb, (22, 22))
    draw_truncated_text(draw, (226, 22), f"#{slot}", fonts["slot"], rank_color if not is_played else (255, 255, 255, 96), 92, 8, stroke_width=3, stroke_fill=(0, 0, 0, 210))

    if rank_is_podium:
        draw_trophy_icon(draw, 278, 103, 0.86, trophy_color if not is_played else (255, 255, 255, 86), (46, 52, 64, 220))
    else:
        draw.rounded_rectangle((236, 118, 304, 127), radius=4, fill=(rank_color[0], rank_color[1], rank_color[2], 178 if not is_played else 62))
        draw.rounded_rectangle((236, 135, 286, 141), radius=3, fill=(255, 224, 138, 122 if is_current else 44))

    draw_truncated_text(draw, (title_x, 30), title, fonts["final_title"], (255, 255, 255, text_alpha), 890 - title_x, 58, stroke_width=1, stroke_fill=(0, 0, 0, 160))
    draw_truncated_text(draw, (title_x, 80), summary, fonts["regular"], (255, 255, 255, summary_alpha), 900 - title_x, 70)

    if is_current:
        draw.rounded_rectangle((694, 110, 920, 152), radius=4, fill=(255, 224, 138, 245), outline=(255, 244, 184, 180), width=1)
        draw_truncated_text(draw, (724, 117), "NOW PLAYING", fonts["badge"], (46, 52, 64, 245), 178, 16)
    else:
        status = "PLAYED" if is_played else "COMING UP"
        draw_truncated_text(draw, (title_x, 124), status, fonts["badge"], (255, 255, 255, 118), 200, 16)

    return image


def open_background_capture(background_video):
    if cv2 is None or not background_video or not os.path.exists(background_video):
        return None

    capture = cv2.VideoCapture(background_video)

    if not capture.isOpened():
        return None

    return capture


def next_background_image(capture):
    if capture is None:
        return None

    ok, frame = capture.read()

    if not ok:
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ok, frame = capture.read()

    if not ok:
        return None

    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame).convert("RGBA")


def intro_background_frame(t, accent, accent2, background_capture=None):
    width, height = 1080, 1920
    video_frame = next_background_image(background_capture)

    if video_frame:
        frame = center_crop(video_frame, (width, height)).filter(ImageFilter.GaussianBlur(18))
        frame = ImageEnhance.Brightness(frame).enhance(0.42)
        frame = ImageEnhance.Color(frame).enhance(1.18)
        dark_layer = Image.new("RGBA", (width, height), (0, 0, 0, 112))
        frame = Image.alpha_composite(frame, dark_layer)
    else:
        frame = Image.new("RGBA", (width, height), (5, 5, 7, 255))
        draw = ImageDraw.Draw(frame)

        for y in range(height):
            ratio = y / height
            red = int(8 + 34 * ratio + 10 * math.sin(t * 1.2 + ratio * 5.4))
            blue = int(12 + 48 * (1 - abs(ratio - 0.42)) + 18 * math.sin(t * 0.8 + ratio * 4.0))
            draw.line((0, y, width, y), fill=(max(0, red), 5, max(10, blue), 255))

    draw = ImageDraw.Draw(frame)

    draw.rectangle((0, 0, width, 330), fill=(0, 0, 0, 210))
    draw.rectangle((0, 1600, width, height), fill=(0, 0, 0, 188))
    draw.rectangle((0, 330, width, 337), fill=accent2)
    draw.rectangle((0, 1590, width, 1597), fill=accent)
    return frame


def countdown_intro_timing(intro_duration):
    duration = max(3.25, float(intro_duration or 4.0))
    spin_end = min(max(1.24, duration * 0.38), max(1.05, duration - 2.25))
    final_start = min(duration - 1.58, spin_end + 0.52)
    final_lock = min(duration - 0.38, final_start + 1.14)
    return spin_end, final_start, final_lock


def wheel_offset_at(t, spin_end):
    accel_end = min(0.46, spin_end * 0.26)
    cruise_end = max(accel_end + 0.4, spin_end * 0.68)
    max_speed = 1240.0
    slow_speed = 72.0

    if t <= accel_end:
        return 0.5 * max_speed * t * t / max(0.1, accel_end)

    accel_distance = 0.5 * max_speed * accel_end

    if t <= cruise_end:
        return accel_distance + max_speed * (t - accel_end)

    slow_time = max(0.1, spin_end - cruise_end)
    elapsed = min(slow_time, t - cruise_end)
    decel = (max_speed - slow_speed) / slow_time
    return accel_distance + max_speed * (cruise_end - accel_end) + (max_speed * elapsed) - (0.5 * decel * elapsed * elapsed)


def wheel_card_layout(index, card, offset, wheel_top, wheel_height, row_spacing, total_scroll, lock_center):
    raw_y = wheel_top + ((index * row_spacing - offset) % total_scroll)

    if raw_y > wheel_top + wheel_height:
        raw_y -= total_scroll

    center = raw_y + card.height / 2
    focus = clamp(1 - abs(center - lock_center) / 620)
    return {
        "x": 58 + int((1 - focus) * 52),
        "y": int(raw_y),
        "scale": 0.84 + (focus * 0.18),
        "alpha": 0.34 + (focus * 0.66),
        "visible": 365 <= raw_y <= 1760,
    }


def create_wheel_sfx(scratch_dir, date_key, theme, rank, intro_duration):
    sample_rate = 44100
    total_samples = max(1, int(intro_duration * sample_rate))
    spin_end, final_start, final_lock = countdown_intro_timing(intro_duration)
    path = os.path.join(scratch_dir, clean_filename(f"{date_key}_{theme}_{rank}_wheel_sfx") + ".wav")
    samples = [0.0] * total_samples

    for sample_index in range(total_samples):
        t = sample_index / sample_rate

        if t < spin_end:
            progress = clamp(t / max(0.1, spin_end))
            sweep = math.sin(2 * math.pi * (82 + progress * 78) * t)
            samples[sample_index] += sweep * 0.018 * (1 - progress * 0.32)

    tick_times = []
    t = 0.18

    while t < spin_end:
        progress = clamp(t / max(0.1, spin_end))
        interval = 0.045 + 0.18 * abs(progress - 0.52)
        tick_times.append(t)
        t += interval

    tick_times.extend([spin_end + 0.10, spin_end + 0.32, min(intro_duration - 0.9, spin_end + 0.74)])

    for tick_number, tick_time in enumerate(tick_times):
        start = int(tick_time * sample_rate)
        tick_length = int((0.032 if tick_time <= spin_end else 0.085) * sample_rate)
        frequency = 920 if tick_time <= spin_end else 185
        amplitude = 0.16 if tick_time <= spin_end else 0.28

        for offset in range(tick_length):
            sample_index = start + offset

            if sample_index >= total_samples:
                break

            age = offset / sample_rate
            envelope = math.exp(-age * (92 if tick_time <= spin_end else 24))
            click = math.sin(2 * math.pi * frequency * age) * envelope
            click += math.sin(2 * math.pi * (frequency * 1.7) * age) * envelope * 0.28
            samples[sample_index] += click * amplitude

    with wave.open(path, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)

        for sample in samples:
            value = int(max(-1.0, min(1.0, sample)) * 32767)
            wav.writeframes(struct.pack("<hh", value, value))

    return path


def paste_rotated(base, layer, x, y, angle, alpha=1.0):
    layer = multiply_alpha(layer, alpha)

    if abs(angle) > 0.1:
        layer = layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)

    base.alpha_composite(layer, (int(x), int(y)))


def draw_intro_header(draw, ranking_title, ranking_subtitle, fonts, accent, t):
    pulse_x = int(5 * math.sin(t * 5.5))
    draw.text(
        (54 + pulse_x, 54),
        ranking_title,
        font=fonts["headline"],
        fill=(255, 255, 255, 245),
        stroke_width=2,
        stroke_fill=(0, 0, 0, 190),
    )
    draw.text((58, 136), ranking_subtitle, font=fonts["subtitle"], fill=(255, 255, 255, 196))
    draw.rectangle((58, 216, 58 + int(360 + 46 * math.sin(t * 3.2)), 222), fill=accent)


def render_countdown_intro_video(theme, scratch_dir, date_key, rank, intro_duration, ranking_title, ranking_subtitle, context, top_entries, source_banners, countdown_slot, style, background_video=None):
    output_path = os.path.join(scratch_dir, clean_filename(f"{date_key}_{theme}_{rank}_countdown_intro") + ".mp4")
    fps = max(24, min(30, int(os.getenv("SHORTFORM_EDITORIAL_INTRO_FPS", "30"))))
    width, height = 1080, 1920
    accent = color_tuple(style["accent"])
    accent2 = color_tuple(style["accent2"])
    display_font = font_path_or_fallback(FONT_DISPLAY_FILE, FONT_BOLD_FILE)
    accent_font = font_path_or_fallback(FONT_ACCENT_FILE, FONT_DISPLAY_FILE)
    bold_font = font_path_or_fallback(FONT_BOLD_FILE, FONT_FILE)
    meta_font = font_path_or_fallback(FONT_META_FILE, FONT_FILE)
    fonts = {
        "headline": fitted_pil_font(display_font, ranking_title, 970, 66, 42),
        "subtitle": pil_font(meta_font, 36),
        "section": pil_font(accent_font, 48),
        "regular": pil_font(meta_font, 30),
        "small": pil_font(meta_font, 25),
        "card_title": pil_font(bold_font, 32),
        "final_title": pil_font(bold_font, 34),
        "badge": pil_font(meta_font, 24),
        "slot": pil_font(display_font, 64),
        "lock": pil_font(display_font, 92),
    }
    source_banners = source_banners or []
    top_entries = top_entries or []
    display_entries = board_display_entries(top_entries, countdown_slot=countdown_slot, window_size=5)
    display_keys = {entry.get("source_state_key") for entry in display_entries}
    current_entry = next(
        (entry for entry in display_entries if int(entry.get("slot") or 0) == int(countdown_slot or 0)),
        None,
    )
    source_banners = ensure_display_banners(source_banners, display_entries)
    scan_cards = [make_scan_banner_card(banner, accent, accent2, fonts) for banner in source_banners]
    source_index_by_key = {
        banner.get("source_state_key"): index
        for index, banner in enumerate(source_banners)
    }
    final_cards = [
        make_final_banner_card(
            entry,
            accent,
            accent2,
            fonts,
            int(entry.get("slot") or 0) == countdown_slot,
            int(entry.get("slot") or 0) > countdown_slot,
        )
        for entry in display_entries
    ]
    spin_end, final_start, final_lock = countdown_intro_timing(intro_duration)
    row_spacing = 150
    wheel_top = 505
    wheel_height = 1230
    lock_center = 940
    total_scroll = max(row_spacing * max(1, len(source_banners)), wheel_height + row_spacing)
    frame_count = max(1, int(math.ceil(intro_duration * fps)))
    background_capture = open_background_capture(background_video)

    process = subprocess.Popen(
        [
            FFMPEG_EXE,
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "-",
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            output_path,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        for frame_index in range(frame_count):
            t = frame_index / fps
            frame = intro_background_frame(t, accent, accent2, background_capture)
            draw = ImageDraw.Draw(frame)
            draw_intro_header(draw, ranking_title, ranking_subtitle, fonts, accent, t)

            if t < final_start:
                lane_progress = ease_in_out_cubic((t - spin_end) / max(0.1, final_lock - spin_end))
                lane_alpha = int(36 + 128 * lane_progress)
                draw.rounded_rectangle(
                    (42, 820, 1038, 1070),
                    radius=14,
                    fill=(accent2[0], accent2[1], accent2[2], int(18 + 38 * lane_progress)),
                    outline=(accent[0], accent[1], accent[2], lane_alpha),
                    width=4,
                )
                if current_entry:
                    current_slot = int(current_entry.get("slot") or countdown_slot)
                    draw.text(
                        (64, 846),
                        f"#{current_slot}",
                        font=fonts["lock"],
                        fill=(accent[0], accent[1], accent[2], int(70 + 120 * lane_progress)),
                        stroke_width=2,
                        stroke_fill=(0, 0, 0, int(120 * lane_progress)),
                    )

                offset = wheel_offset_at(min(t, spin_end), spin_end)
                lock_progress = ease_in_out_cubic((t - spin_end) / max(0.1, final_lock - spin_end))
                survivor_morph = ease_in_out_cubic((t - (spin_end - 0.15)) / max(0.1, final_lock - spin_end + 0.15))

                for index, (banner, card) in enumerate(zip(source_banners, scan_cards)):
                    layout = wheel_card_layout(
                        index,
                        card,
                        offset,
                        wheel_top,
                        wheel_height,
                        row_spacing,
                        total_scroll,
                        lock_center,
                    )

                    if not layout["visible"]:
                        continue

                    scale = layout["scale"]
                    x = layout["x"]
                    y = layout["y"]
                    alpha = layout["alpha"]
                    angle = 0.0
                    key = banner.get("source_state_key")

                    if survivor_morph > 0 and key in display_keys:
                        alpha *= max(0.18, 1 - survivor_morph * 0.82)

                    if lock_progress > 0 and key not in display_keys:
                        side = -1 if index % 2 == 0 else 1
                        sweep = ease_out_cubic(lock_progress)
                        center_pull = int((lock_center - (y + card.height / 2)) * 0.18 * sweep)
                        x += int(side * sweep * (260 + (index % 3) * 42))
                        y += center_pull + int(math.sin(index * 1.7 + t * 8.5) * 12 * sweep)
                        angle = side * sweep * 2.8
                        alpha *= max(0.0, 1 - sweep * 0.82)
                        scale *= max(0.72, 1 - sweep * 0.16)

                    if lock_progress > 0.05 and key in display_keys:
                        target_index = next(
                            (entry_index for entry_index, entry in enumerate(display_entries) if entry.get("source_state_key") == key),
                            0,
                        )
                        target_y = top_board_y(target_index)
                        y += int((target_y - y) * lock_progress * 0.22)
                        x += int((58 - x) * lock_progress * 0.18)
                        scale *= 1 + lock_progress * 0.04

                    scaled_w = int(card.width * scale)
                    scaled_h = int(card.height * scale)
                    scaled = card.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
                    paste_rotated(frame, scaled, x, y, angle, alpha)

            final_progress = ease_in_out_cubic((t - spin_end) / max(0.1, final_lock - spin_end))

            if final_progress > 0:
                for index, card in enumerate(final_cards):
                    entry = display_entries[index]
                    key = entry.get("source_state_key")
                    source_index = source_index_by_key.get(key, index)
                    source_card = scan_cards[source_index] if source_index < len(scan_cards) else card
                    source_layout = wheel_card_layout(
                        source_index,
                        source_card,
                        wheel_offset_at(spin_end, spin_end),
                        wheel_top,
                        wheel_height,
                        row_spacing,
                        total_scroll,
                        lock_center,
                    )
                    source_scale = source_layout["scale"] if source_layout["visible"] else 0.92
                    start_x = source_layout["x"] if source_layout["visible"] else 82
                    start_y = source_layout["y"] if source_layout["visible"] else int(760 + index * 142)
                    target_x = 58
                    target_y = top_board_y(index)
                    card_progress = ease_in_out_cubic((t - spin_end - index * 0.055) / max(0.1, final_lock - spin_end))
                    source_width = int(source_card.width * source_scale)
                    source_height = int(source_card.height * source_scale)
                    card_width = int(source_width + (964 - source_width) * card_progress)
                    card_height = int(source_height + (176 - source_height) * card_progress)
                    x = int(start_x + (target_x - start_x) * card_progress)
                    y = int(start_y + (target_y - start_y) * card_progress)
                    alpha = min(1.0, final_progress + 0.1)
                    source_alpha = max(0.0, 1 - card_progress * 1.28) * alpha
                    final_alpha = clamp((card_progress - 0.18) / 0.72) * alpha
                    glow_alpha = int(95 * final_progress * (0.6 + 0.4 * math.sin(t * 9 + index)))

                    draw.rounded_rectangle(
                        (42, target_y - 12, 1038, target_y + 188),
                        radius=12,
                        fill=(accent2[0], accent2[1], accent2[2], int(12 * final_alpha)),
                        outline=(accent[0], accent[1], accent[2], max(0, glow_alpha)),
                        width=3,
                    )

                    if int(entry.get("slot") or 0) == countdown_slot:
                        pulse = 0.5 + 0.5 * math.sin(t * 9.5)
                        draw.rounded_rectangle(
                            (x - 10, y - 10, x + card_width + 10, y + card_height + 10),
                            radius=10,
                            outline=(accent2[0], accent2[1], accent2[2], int(110 + 100 * pulse * final_progress)),
                            width=8,
                        )

                    if source_alpha > 0.01:
                        source_layer = source_card.resize((card_width, max(1, int(source_height + (card_height - source_height) * 0.35))), Image.Resampling.LANCZOS)
                        paste_rotated(frame, source_layer, x, y, 0, source_alpha)

                    if final_alpha > 0.01:
                        layer = card.resize((card_width, card_height), Image.Resampling.LANCZOS)
                        paste_rotated(frame, layer, x, y, 0, final_alpha)

            flattened = Image.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 255)), frame)
            process.stdin.write(flattened.convert("RGB").tobytes())
    finally:
        if process.stdin:
            process.stdin.close()

    stdout, stderr = process.communicate()

    if background_capture is not None:
        background_capture.release()

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"Countdown intro render failed: {detail}")

    return output_path


def watched_header_text(context):
    hours = format_hours_phrase(context.get("watched_hours", 0))
    theme_label = str(context.get("theme_label") or "podcast").upper()
    return f"WATCHED {hours.upper()} OF {theme_label} INTERVIEWS"


def _render_editorial_short_legacy(theme, topic_item, rank, adjective, date_key, paths):
    scratch_dir = os.path.join(paths["metadata_path"], "editorial", date_key)
    os.makedirs(scratch_dir, exist_ok=True)
    output_dir = paths["final_videos_path"]
    os.makedirs(output_dir, exist_ok=True)

    topic_clips = selected_topic_clips(topic_item)

    if not topic_clips:
        raise RuntimeError(f"No rendered source clips found for topic: {topic_item.get('topic', '')}")

    best_clip = topic_clips[0]
    source_clip = best_clip["output_file"]
    topic = topic_item["topic"]
    total_count = int(topic_item.get("_total_count") or DAILY_TOPIC_COUNT)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    script = build_editorial_intro(theme, topic, rank, total_count, adjective, best_clip)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, rank)
    intro_duration = max(2.4, min(EDITORIAL_INTRO_MAX_SECONDS, get_duration(intro_audio) + 0.2))
    transition_duration = max(1.0, EDITORIAL_TRANSITION_SECONDS) if len(topic_clips) > 1 else 0.0
    available_clip_time = max(
        len(topic_clips) * EDITORIAL_CLIP_MIN_SECONDS,
        EDITORIAL_TOTAL_MAX_SECONDS - intro_duration - (transition_duration * (len(topic_clips) - 1)),
    )
    per_clip_limit = available_clip_time / len(topic_clips)
    clip_durations = [
        clip_play_duration_for(clip["output_file"], per_clip_limit)
        for clip in topic_clips
    ]

    style = visual_style(rank)
    theme_label = theme_profile(theme)["label"]
    theme_label_upper = theme_label.upper()
    period_upper = period_label().upper()
    output_filename = clean_filename(f"{date_key}_{theme}_countdown_{countdown_slot:02d}_{topic}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    ranking_title = f"RANKING THE {adjective.upper()} MOMENTS"
    ranking_subtitle = f"FROM {period_upper} {theme_label_upper} PODCASTS"
    moment_label = f"#{countdown_slot}"
    topic_text = compact_text(topic.upper(), 90)
    topic_font_size = fitted_topic_font_size(topic_text)
    ranking_font_size = fitted_label_font_size(ranking_title, max_width=760, max_size=42, min_size=30)
    source_texts = [
        compact_text(clip.get("source_title") or "source episode", 64)
        for clip in topic_clips
    ]

    font_regular = ffmpeg_path(FONT_FILE if os.path.exists(FONT_FILE) else "Arial")
    font_bold = ffmpeg_path(FONT_BOLD_FILE if os.path.exists(FONT_BOLD_FILE) else FONT_FILE)
    accent = style["accent"]
    accent2 = style["accent2"]

    filters = [
        f"[0:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=18:2,eq=brightness=-0.55:saturation=0.85,setsar=1[open_bg]",
        f"[0:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=650:1156:force_original_aspect_ratio=increase,crop=650:1156,setsar=1[open_card0]",
    ]

    if len(topic_clips) > 1:
        filters.append(
            f"[1:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=330:586:force_original_aspect_ratio=increase,crop=330:586,setsar=1[open_card1]"
        )

    filters.append(
        "[open_bg]"
        "drawbox=x=0:y=0:w=1080:h=300:color=black@0.80:t=fill,"
        "drawbox=x=0:y=1660:w=1080:h=260:color=black@0.74:t=fill,"
        f"drawbox=x=0:y=300:w=1080:h=8:color={accent2}@0.95:t=fill,"
        f"drawbox=x=0:y=1652:w=1080:h=8:color={accent}@0.95:t=fill[open_base]"
    )

    if len(topic_clips) > 1:
        filters.append("[open_base][open_card1]overlay=x=682:y=746:shortest=1[open_stack]")
        filters.append("[open_stack][open_card0]overlay=x='74+12*sin(t*3.2)':y=505:shortest=1[open_cards]")
        open_card_box = (
            f"[open_cards]drawbox=x=56:y=486:w=684:h=1194:color={accent}@0.92:t=6,"
            f"drawbox=x=666:y=728:w=362:h=630:color=white@0.72:t=4,"
            f"drawtext=fontfile='{font_bold}':text='CLIP 2':x=704:y=686:fontsize=34:fontcolor={accent}"
        )
    else:
        filters.append("[open_base][open_card0]overlay=x='215+12*sin(t*3.2)':y=480:shortest=1[open_cards]")
        open_card_box = f"[open_cards]drawbox=x=196:y=461:w=688:h=1194:color={accent}@0.92:t=6"

    filters.append(
        open_card_box + ","
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(moment_label)}':x=58:y=34:fontsize=122:fontcolor={accent},"
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(ranking_title)}':x=222:y=62:fontsize={ranking_font_size}:fontcolor=white,"
        f"drawtext=fontfile='{font_regular}':text='{drawtext_text(ranking_subtitle)}':x=224:y=124:fontsize=33:fontcolor=white@0.82,"
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(topic_text)}':x=58:y=1698:fontsize={topic_font_size}:fontcolor=white:line_spacing=8,"
        f"drawtext=fontfile='{font_regular}':text='{drawtext_text(source_texts[0])}':x=60:y=1810:fontsize=30:fontcolor=white@0.72,"
        "format=yuv420p[open_v]"
    )

    video_labels = ["[open_v]"]
    audio_labels = ["[open_a]"]
    intro_input_index = len(topic_clips)

    for index, clip in enumerate(topic_clips):
        duration = clip_durations[index]
        source_text = source_texts[index]
        clip_badge = f"CLIP {index + 1}/{len(topic_clips)}" if len(topic_clips) > 1 else "FULL MOMENT"
        clip_title = compact_text(f"{moment_label}  {topic_text}", 82)
        clip_title_size = fitted_label_font_size(clip_title, max_width=770, max_size=40, min_size=28)

        filters.append(
            f"[{index}:v]trim=0:{duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[clip{index}_base]"
        )
        filters.append(
            f"[clip{index}_base]drawbox=x=0:y=0:w=1080:h=176:color=black@0.62:t=fill,"
            f"drawbox=x=0:y=176:w=1080:h=6:color={accent2}@0.95:t=fill,"
            f"drawbox=x=0:y=1700:w=1080:h=142:color=black@0.42:t=fill,"
            f"drawbox=x=0:y=1700:w=1080:h=5:color={accent}@0.95:t=fill,"
            f"drawtext=fontfile='{font_bold}':text='{drawtext_text(moment_label)}':x=48:y=30:fontsize=78:fontcolor={accent},"
            f"drawtext=fontfile='{font_bold}':text='{drawtext_text(clip_title)}':x=188:y=42:fontsize={clip_title_size}:fontcolor=white,"
            f"drawtext=fontfile='{font_regular}':text='{drawtext_text(clip_badge)}':x=190:y=102:fontsize=27:fontcolor=white@0.72,"
            f"drawtext=fontfile='{font_regular}':text='{drawtext_text(source_text)}':x=54:y=1734:fontsize=29:fontcolor=white@0.90,"
            f"drawbox=x=0:y=1908:w='1080*t/{duration:.3f}':h=12:color={accent2}@0.95:t=fill[clip{index}_label]"
        )

        if len(topic_clips) > 1:
            pip_index = 1 if index == 0 else 0
            pip_label = "NEXT" if index == 0 else "FIRST CLIP"
            filters.append(
                f"[{pip_index}:v]trim=0:{min(3.4, duration):.3f},setpts=PTS-STARTPTS,scale=286:508:force_original_aspect_ratio=increase,crop=286:508,setsar=1[pip{index}]"
            )
            filters.append(
                f"[clip{index}_label]drawbox=x=736:y=1002:w=316:h=594:color=black@0.54:t=fill,"
                f"drawbox=x=736:y=1002:w=316:h=594:color={accent}@0.92:t=5,"
                f"drawtext=fontfile='{font_bold}':text='{drawtext_text(pip_label)}':x=756:y=1020:fontsize=30:fontcolor={accent},"
                f"drawtext=fontfile='{font_regular}':text='preview':x=756:y=1058:fontsize=22:fontcolor=white@0.70[pip_slot{index}]"
            )
            filters.append(
                f"[pip_slot{index}][pip{index}]overlay=x=751:y=1092:enable='between(t,0,3.4)':shortest=0,format=yuv420p[clip{index}_v]"
            )
        else:
            filters.append(f"[clip{index}_label]format=yuv420p[clip{index}_v]")

        video_labels.append(f"[clip{index}_v]")

        if index < len(topic_clips) - 1:
            next_label = "NEXT CLIP"
            filters.append(
                f"[{index + 1}:v]trim=0:{transition_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=12:1,eq=brightness=-0.35:saturation=1.05,setsar=1[trans{index}_bg]"
            )
            filters.append(
                f"[trans{index}_bg]drawbox=x=0:y=0:w=1080:h=1920:color=black@0.36:t=fill,"
                f"drawbox=x=0:y=812:w=1080:h=296:color={accent2}@0.84:t=fill,"
                f"drawbox=x=0:y=1108:w=1080:h=8:color={accent}@0.96:t=fill,"
                f"drawtext=fontfile='{font_bold}':text='{drawtext_text(next_label)}':x=64:y=885:fontsize=86:fontcolor=white,"
                f"drawtext=fontfile='{font_regular}':text='{drawtext_text(moment_label)} CONTINUES':x=64:y=1010:fontsize=34:fontcolor=black@0.78,"
                "format=yuv420p"
                f"[trans{index}_v]"
            )
            video_labels.append(f"[trans{index}_v]")

    filters.append(
        f"[0:a]atrim=0:{intro_duration:.3f},volume={INTRO_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS[intro_bed]"
    )
    filters.append(
        f"[{intro_input_index}:a]atrim=0:{intro_duration:.3f},volume=1.0,asetpts=PTS-STARTPTS[intro_voice]"
    )
    filters.append(
        "[intro_bed][intro_voice]amix=inputs=2:duration=longest:dropout_transition=0,"
        "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[open_a]"
    )

    for index, duration in enumerate(clip_durations):
        filters.append(
            f"[{index}:a]atrim=0:{duration:.3f},volume={CLIP_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS,"
            f"aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip{index}_a]"
        )
        audio_labels.append(f"[clip{index}_a]")

        if index < len(topic_clips) - 1:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate=44100:d={transition_duration:.3f}[trans{index}_a]"
            )
            audio_labels.append(f"[trans{index}_a]")

    filters.append("".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0[v]")
    filters.append("".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[a]")
    filter_complex = ";".join(filters)

    input_args = []

    for clip in topic_clips:
        input_args.extend(["-i", clip["output_file"]])

    input_args.extend(["-i", intro_audio])

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "Editorial countdown short render")

    package = build_output_package(
        theme=theme,
        output_path=output_path,
        source_clip=source_clip,
        topic_item=topic_item,
        rank=rank,
        adjective=adjective,
        date_key=date_key,
    )
    package["editorial_script"] = script
    package["intro_audio_file"] = os.path.abspath(intro_audio)
    package["intro_duration"] = intro_duration
    package["source_play_duration"] = sum(clip_durations)
    package["source_clip_files"] = [os.path.abspath(clip["output_file"]) for clip in topic_clips]
    package["clip_durations"] = clip_durations
    package["countdown_slot"] = countdown_slot
    package["countdown_total"] = total_count
    package["clips_in_short"] = len(topic_clips)
    package["visual_style"] = style["name"]
    return package


def render_editorial_short(theme, topic_item, rank, adjective, date_key, paths):
    scratch_dir = os.path.join(paths["metadata_path"], "editorial", date_key)
    os.makedirs(scratch_dir, exist_ok=True)
    output_dir = paths["final_videos_path"]
    os.makedirs(output_dir, exist_ok=True)

    context = topic_item.get("_countdown_context")

    if not context:
        context = fallback_countdown_context(theme, paths, topic_item, adjective)
        topic_item["_countdown_context"] = context

    reel_adjective = context.get("adjective") or adjective
    topic_clips = [dict(clip) for clip in selected_topic_clips(topic_item)]

    if not topic_clips:
        raise RuntimeError(f"No rendered source clips found for topic: {topic_item.get('topic', '')}")

    best_clip = topic_clips[0]
    best_clip["_countdown_context"] = context
    source_clip = best_clip["output_file"]
    topic = topic_item["topic"]
    total_count = int(topic_item.get("_total_count") or len(context.get("top_entries", [])) or EDITORIAL_COUNTDOWN_SIZE)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    current_entry = topic_item.get("_countdown_entry") or {
        "slot": countdown_slot,
        "topic": topic,
        "summary": clip_summary(best_clip, topic),
        "source_title": best_clip.get("source_title") or "source episode",
        "clip_file": source_clip,
    }
    script = build_editorial_intro(theme, topic, rank, total_count, reel_adjective, best_clip)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, rank)
    intro_duration = editorial_intro_duration()
    rank_card_duration = max(0.0, min(0.7, EDITORIAL_RANK_CARD_SECONDS))
    transition_duration = EDITORIAL_TRANSITION_SECONDS if len(topic_clips) > 1 else 0.0
    fixed_visual_time = intro_duration + rank_card_duration + (transition_duration * (len(topic_clips) - 1))
    available_clip_time = max(
        len(topic_clips) * EDITORIAL_CLIP_MIN_SECONDS,
        EDITORIAL_TOTAL_MAX_SECONDS - fixed_visual_time,
    )
    per_clip_limit = available_clip_time / len(topic_clips)
    clip_durations = [
        clip_play_duration_for(clip["output_file"], per_clip_limit)
        for clip in topic_clips
    ]

    style = visual_style(rank)
    theme_label = context.get("theme_label") or theme_profile(theme)["label"]
    output_filename = clean_filename(f"{date_key}_{theme}_countdown_{countdown_slot:02d}_{topic}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    ranking_title = f"TOP {total_count} {reel_adjective.upper()} MOMENTS THIS WEEK"
    ranking_subtitle = watched_header_text(context)
    moment_label = f"#{countdown_slot}"
    number_label = f"NUMBER {countdown_slot}"
    topic_text = compact_text((current_entry.get("topic") or topic).upper(), 90)
    topic_font_size = fitted_topic_font_size(topic_text)
    source_texts = [
        compact_text(clip.get("source_title") or "source episode", 64)
        for clip in topic_clips
    ]

    font_regular = ffmpeg_path(font_path_or_fallback(FONT_FILE, r"C:\Windows\Fonts\arial.ttf"))
    font_bold = ffmpeg_path(font_path_or_fallback(FONT_BOLD_FILE, FONT_FILE))
    font_meta = ffmpeg_path(font_path_or_fallback(FONT_META_FILE, FONT_FILE))
    font_display = ffmpeg_path(font_path_or_fallback(FONT_DISPLAY_FILE, FONT_BOLD_FILE))
    accent = style["accent"]
    accent2 = style["accent2"]
    cream = style.get("cream", "0xFFF4B8")
    mint = style.get("mint", "0xB7D7C2")
    dark = style.get("dark", "0x2E3440")
    archive_label = f"THE {theme_label.upper()} ARCHIVE"
    top_entries = context.get("top_entries", [])[:total_count]
    source_banners = context.get("source_banners", [])[:EDITORIAL_BOARD_SOURCE_LIMIT]
    input_paths = []

    for entry in top_entries:
        clip_file = entry.get("clip_file", "")

        if clip_file and os.path.exists(clip_file):
            input_index_for_path(clip_file, input_paths)

    for banner in source_banners:
        clip_file = banner.get("clip_file", "")

        if clip_file and os.path.exists(clip_file):
            input_index_for_path(clip_file, input_paths)

    for clip in topic_clips:
        input_index_for_path(clip["output_file"], input_paths)

    if not input_paths:
        input_paths.append(source_clip)

    intro_visual_file = render_countdown_intro_video(
        theme=theme,
        scratch_dir=scratch_dir,
        date_key=date_key,
        rank=rank,
        intro_duration=intro_duration,
        ranking_title=ranking_title,
        ranking_subtitle=ranking_subtitle,
        context=context,
        top_entries=top_entries,
        source_banners=source_banners,
        countdown_slot=countdown_slot,
        style=style,
        background_video=source_clip,
    )
    wheel_sfx = create_wheel_sfx(scratch_dir, date_key, theme, rank, intro_duration)
    intro_visual_index = input_index_for_path(intro_visual_file, input_paths)
    wheel_sfx_index = input_index_for_path(wheel_sfx, input_paths)
    board_bg_index = input_index_for_path(source_clip, input_paths)
    current_input_index = input_index_for_path(source_clip, input_paths)
    intro_input_index = len(input_paths)

    filters = [
        f"[{intro_visual_index}:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920,setsar=1,fade=t=out:st={max(0.1, intro_duration - 0.32):.3f}:d=0.32,format=yuv420p[open_v]",
    ]

    video_labels = ["[open_v]"]
    audio_labels = ["[open_a]"]

    if rank_card_duration > 0.05:
        filters.append(
            f"[{current_input_index}:v]trim=0:{rank_card_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=18:2,eq=brightness=-0.62:saturation=0.8,setsar=1[rank_bg]"
        )
        filters.append(
            "[rank_bg]"
            f"drawbox=x=0:y=0:w=1080:h=1920:color={dark}@0.42:t=fill,"
            f"drawbox=x=50:y=656:w=980:h=516:color={dark}@0.88:t=fill,"
            f"drawbox=x=50:y=656:w=980:h=516:color={cream}@0.72:t=5,"
            f"drawbox=x=50:y=656:w=18:h=516:color={accent}@0.96:t=fill,"
            f"drawbox=x=80:y=704:w=236:h=104:color={accent}@0.92:t=fill,"
            f"drawtext=fontfile='{font_display}':text='{drawtext_text(number_label)}':x=104:y=714:fontsize=68:fontcolor={dark},"
            f"drawtext=fontfile='{font_bold}':text='{drawtext_text(topic_text)}':x=88:y=866:fontsize={topic_font_size}:fontcolor=white,"
            f"drawtext=fontfile='{font_meta}':text='{drawtext_text(archive_label)}':x=90:y=1044:fontsize=35:fontcolor={mint}@0.90,"
            f"fade=t=in:st=0:d=0.12,fade=t=out:st={max(0.1, rank_card_duration - 0.18):.3f}:d=0.18,format=yuv420p[rank_v]"
        )
        video_labels.append("[rank_v]")
        audio_labels.append("[rank_a]")

    for index, clip in enumerate(topic_clips):
        duration = clip_durations[index]
        clip_input_index = input_index_for_path(clip["output_file"], input_paths)
        source_text = source_texts[index]
        clip_badge = f"CLIP {index + 1}/{len(topic_clips)}" if len(topic_clips) > 1 else "TOP MOMENT"
        clip_title = compact_text(f"{moment_label}  {topic_text}", 82)
        clip_title_size = fitted_label_font_size(clip_title, max_width=770, max_size=40, min_size=28)
        source_font_size = fitted_label_font_size(source_text, max_width=760, max_size=29, min_size=22)
        cta_start = max(0.1, duration - 2.4)
        end_cta = "SUBSCRIBE FOR MORE" if countdown_slot == 1 else f"CHECK MY CHANNEL FOR NUMBER {countdown_slot - 1}"
        cta_kicker = "FINAL MOMENT" if countdown_slot == 1 else "UP NEXT"
        cta_font_size = fitted_label_font_size(end_cta, max_width=790, max_size=54, min_size=38)
        now_playing_detail = f"{moment_label} OF {total_count}"
        left_rail_y = "mod(t*270\\,2140)-220"
        right_rail_y = "1920-mod(t*230\\,2140)"

        filters.append(
            f"[{clip_input_index}:v]trim=0:{duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[clip{index}_base]"
        )
        filters.append(
            f"[clip{index}_base]fade=t=in:st=0:d=0.20,"
            f"eq=contrast=1.05:saturation=1.06,"
            f"drawbox=x=0:y=0:w=1080:h=1920:color={dark}@0.06:t=fill,"
            f"drawbox=x=0:y=0:w=24:h=1920:color={dark}@0.54:t=fill,"
            f"drawbox=x=1056:y=0:w=24:h=1920:color={dark}@0.46:t=fill,"
            f"drawbox=x=24:y='{left_rail_y}':w=7:h=220:color={accent}@0.88:t=fill,"
            f"drawbox=x=1049:y='{right_rail_y}':w=7:h=190:color={mint}@0.66:t=fill,"
            f"drawbox=x=32:y=210:w=180:h=5:color={cream}@0.50:t=fill,"
            f"drawbox=x=32:y=210:w=5:h=190:color={cream}@0.50:t=fill,"
            f"drawbox=x=868:y=210:w=180:h=5:color={cream}@0.46:t=fill,"
            f"drawbox=x=1043:y=210:w=5:h=190:color={cream}@0.46:t=fill,"
            f"drawbox=x=32:y=1498:w=5:h=246:color={accent}@0.72:t=fill,"
            f"drawbox=x=32:y=1739:w=176:h=5:color={accent}@0.72:t=fill,"
            f"drawbox=x=34:y=34:w=178:h=116:color={dark}@0.86:t=fill,"
            f"drawbox=x=34:y=34:w=178:h=116:color={accent}@0.96:t=4,"
            f"drawbox=x=46:y=138:w=152:h=7:color={mint}@0.78:t=fill,"
            f"drawtext=fontfile='{font_display}':text='{drawtext_text(moment_label)}':x=54:y=38:fontsize=82:fontcolor={accent}:shadowcolor=black@0.55:shadowx=3:shadowy=3,"
            f"drawbox=x=614:y=38:w=428:h=106:color={dark}@0.83:t=fill,"
            f"drawbox=x=614:y=38:w=428:h=106:color={mint}@0.72:t=2,"
            f"drawbox=x=614:y=38:w=13:h=106:color={accent}@0.94:t=fill,"
            f"drawtext=fontfile='{font_bold}':text='{drawtext_text(archive_label)}':x=642:y=57:fontsize=30:fontcolor={cream},"
            f"drawtext=fontfile='{font_meta}':text='{drawtext_text(clip_badge)}':x=642:y=104:fontsize=24:fontcolor=white@0.74,"
            f"drawbox=x=118:y=782:w=844:h=156:color=black@0.76:t=fill:enable='lt(t,0.86)',"
            f"drawbox=x=118:y=782:w=844:h=156:color={accent}@0.94:t=5:enable='lt(t,0.86)',"
            f"drawbox=x=118:y=782:w=16:h=156:color={accent}@0.96:t=fill:enable='lt(t,0.86)',"
            f"drawtext=fontfile='{font_display}':text='NOW PLAYING':x=(w-text_w)/2:y=800:fontsize=70:fontcolor={cream}:shadowcolor=black@0.65:shadowx=3:shadowy=3:enable='lt(t,0.86)',"
            f"drawtext=fontfile='{font_meta}':text='{drawtext_text(now_playing_detail)}':x=(w-text_w)/2:y=878:fontsize=32:fontcolor={mint}@0.94:enable='lt(t,0.86)',"
            f"drawbox=x=46:y=1630:w=832:h=154:color=black@0.76:t=fill,"
            f"drawbox=x=46:y=1630:w=832:h=154:color={mint}@0.74:t=2,"
            f"drawbox=x=46:y=1630:w='10+18*abs(sin(t*5.2))':h=154:color={accent}@0.95:t=fill,"
            f"drawtext=fontfile='{font_bold}':text='{drawtext_text(clip_title)}':x=82:y=1657:fontsize={clip_title_size}:fontcolor=white:shadowcolor=black@0.45:shadowx=2:shadowy=2,"
            f"drawtext=fontfile='{font_meta}':text='{drawtext_text(source_text)}':x=84:y=1724:fontsize={source_font_size}:fontcolor={cream}@0.90,"
            f"drawbox=x=54:y=1850:w=972:h=8:color={dark}@0.64:t=fill,"
            f"drawbox=x=54:y=1850:w='972*t/{duration:.3f}':h=8:color={accent}@0.98:t=fill,"
            f"drawbox=x=54:y=1864:w='972*t/{duration:.3f}':h=3:color={mint}@0.74:t=fill,"
            f"drawbox=x=92:y=1434:w=896:h=164:color=black@0.82:t=fill:enable='gte(t,{cta_start:.3f})',"
            f"drawbox=x=92:y=1434:w=896:h=164:color={accent}@0.98:t=5:enable='gte(t,{cta_start:.3f})',"
            f"drawbox=x=92:y=1434:w=16:h=164:color={accent}@0.98:t=fill:enable='gte(t,{cta_start:.3f})',"
            f"drawtext=fontfile='{font_meta}':text='{drawtext_text(cta_kicker)}':x=136:y=1460:fontsize=31:fontcolor={mint}@0.92:enable='gte(t,{cta_start:.3f})',"
            f"drawtext=fontfile='{font_display}':text='{drawtext_text(end_cta)}':x=(w-text_w)/2:y=1494:fontsize={cta_font_size}:fontcolor={cream}:shadowcolor=black@0.66:shadowx=3:shadowy=3:enable='gte(t,{cta_start:.3f})',"
            f"format=yuv420p[clip{index}_v]"
        )

        video_labels.append(f"[clip{index}_v]")

        if index < len(topic_clips) - 1:
            next_label = "NEXT CLIP"
            board_transition_start = max(0.0, intro_duration - transition_duration - 0.8)
            filters.append(
                f"[{intro_visual_index}:v]trim=start={board_transition_start:.3f}:duration={transition_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920,setsar=1,"
                f"drawbox=x=84:y=1398:w=912:h=124:color={dark}@0.86:t=fill,"
                f"drawbox=x=84:y=1398:w=912:h=124:color={accent}@0.95:t=4,"
                f"drawtext=fontfile='{font_display}':text='{drawtext_text(next_label)}':x=122:y=1414:fontsize=60:fontcolor={cream},"
                f"drawtext=fontfile='{font_meta}':text='{drawtext_text(moment_label)} CONTINUES':x=126:y=1484:fontsize=31:fontcolor={mint}@0.92,"
                f"format=yuv420p[trans{index}_v]"
            )
            video_labels.append(f"[trans{index}_v]")

    filters.append(
        f"[{board_bg_index}:a]atrim=0:{intro_duration:.3f},volume={INTRO_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS[intro_bed]"
    )
    filters.append(
        f"[{intro_input_index}:a]atrim=0:{intro_duration:.3f},volume=1.0,asetpts=PTS-STARTPTS[intro_voice]"
    )
    filters.append(
        f"[{wheel_sfx_index}:a]atrim=0:{intro_duration:.3f},volume=0.44,asetpts=PTS-STARTPTS[wheel_sfx]"
    )
    filters.append(
        "[intro_bed][intro_voice][wheel_sfx]amix=inputs=3:duration=longest:dropout_transition=0,"
        "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[open_a]"
    )
    if rank_card_duration > 0.05:
        filters.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100:d={rank_card_duration:.3f}[rank_a]"
        )

    for index, duration in enumerate(clip_durations):
        clip_input_index = input_index_for_path(topic_clips[index]["output_file"], input_paths)
        filters.append(
            f"[{clip_input_index}:a]atrim=0:{duration:.3f},volume={CLIP_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS,"
            f"aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip{index}_a]"
        )
        audio_labels.append(f"[clip{index}_a]")

        if index < len(topic_clips) - 1:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate=44100:d={transition_duration:.3f}[trans{index}_a]"
            )
            audio_labels.append(f"[trans{index}_a]")

    filters.append("".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0[v]")
    filters.append("".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[a]")
    filter_complex = ";".join(filters)

    input_args = []

    for input_path in input_paths:
        input_args.extend(["-i", input_path])

    input_args.extend(["-i", intro_audio])

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "Editorial watched-hours countdown render")

    package = build_output_package(
        theme=theme,
        output_path=output_path,
        source_clip=source_clip,
        topic_item=topic_item,
        rank=rank,
        adjective=reel_adjective,
        date_key=date_key,
    )
    package["editorial_script"] = script
    package["intro_audio_file"] = os.path.abspath(intro_audio)
    package["intro_duration"] = intro_duration
    package["rank_card_duration"] = rank_card_duration
    package["source_play_duration"] = sum(clip_durations)
    package["source_clip_files"] = [os.path.abspath(clip["output_file"]) for clip in topic_clips]
    package["clip_durations"] = clip_durations
    package["countdown_slot"] = countdown_slot
    package["countdown_total"] = total_count
    package["clips_in_short"] = len(topic_clips)
    package["watched_hours"] = context.get("watched_hours", 0)
    package["source_count"] = context.get("source_count", 0)
    package["visual_style"] = style["name"]
    return finalize_editorial_package(package, f"countdown short #{countdown_slot}")


def popular_segment_signal_source(item):
    clip = item.get("clip") or {}
    rank_signals = clip.get("rank_signals") or {}
    source = rank_signals.get("popularity_source") or ""

    if source:
        return source

    if float(item.get("popularity_score") or 0) > 0:
        return "public_popularity_signal"

    return "internal_quality_fallback"


def popular_segment_labels(item):
    source = popular_segment_signal_source(item)

    if source == "youtube_heatmap":
        return "MOST REPLAYED", "REPLAY HOTSPOT", "VIEWERS KEPT REPLAYING THIS PART"

    if source in {"timestamp_mentions", "chapters", "public_popularity_signal"}:
        return "MOST POPULAR", "POPULARITY SIGNAL", "THE PART PEOPLE KEPT COMING BACK TO"

    return "BEST MOMENT", "TOP PICK", "THE MOMENT THAT STOOD OUT"


def build_popular_segment_script(theme, item):
    channel = item.get("channel_label") or "this podcast"
    source = popular_segment_signal_source(item)

    if source == "youtube_heatmap":
        return f"Most replayed moment from {channel}. This is the part people kept coming back to."

    if source in {"timestamp_mentions", "chapters", "public_popularity_signal"}:
        return f"Most popular moment from {channel}. This is the part worth watching."

    return f"Best moment from {channel}. This is the part that stood out."


def build_popular_output_package(theme, output_path, item, index, date_key, script, intro_audio, intro_duration, clip_duration):
    profile = theme_profile(theme)
    theme_label = profile["label"]
    clip = item["clip"]
    source_title = item.get("source_title") or clip.get("source_title") or "Podcast interview"
    channel = item.get("channel_label") or "Podcast Channel"
    topic = clip_summary(clip, source_title)
    signal_source = popular_segment_signal_source(item)
    title_prefix = "Most Replayed" if signal_source == "youtube_heatmap" else ("Most Popular" if signal_source != "internal_quality_fallback" else "Best Moment")
    title = compact_text(f"{title_prefix} From {channel} | {theme_label.title()} Podcast Clip", 96)
    description = (
        f"The most replayed/popular segment from {source_title}. "
        f"This moment is about {topic}."
    )
    hashtags = unique_sequence(profile["hashtags"] + ["#mostreplayed", "#podcastclip", "#shorts"])[:8]
    tags = unique_sequence(profile["tags"] + [
        "most replayed podcast moment",
        "popular podcast segment",
        "podcast clip",
        channel.lower(),
        source_title.lower(),
        topic.lower(),
    ])[:24]

    return {
        "theme": theme,
        "content_format": "popular_segment_short",
        "editorial_date": date_key,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(clip.get("output_file", "")),
        "source_state_key": f"{theme}|popular|{date_key}|{index}|{item.get('source_state_key', '')}",
        "source_video_url": item.get("source_video_url") or clip.get("source_video_url", ""),
        "source_title": source_title,
        "title": title,
        "caption": compact_text(description, 160),
        "hashtags": hashtags,
        "tags": tags,
        "description": compact_text(description, 320),
        "transcript_excerpt": clip.get("transcript_excerpt", ""),
        "hook_reason": f"popular segment signal: {clip.get('rank_signals', {}).get('popularity_source', 'replay/popularity')}",
        "score": item.get("sort_score", clip.get("score")),
        "popularity_score": item.get("popularity_score", 0),
        "content_signal": {
            "type": "most_replayed_or_popular_segment",
            "popularity_score": item.get("popularity_score", 0),
            "source": signal_source,
            "profile_sources": clip.get("rank_signals", {}).get("popularity_profile_sources", []),
        },
        "editorial_script": script,
        "intro_audio_file": os.path.abspath(intro_audio),
        "intro_duration": intro_duration,
        "source_play_duration": clip_duration,
        "visual_style": "popular_segment_premium",
        "review": {
            "quality_rating": "",
            "approved": False,
            "rejection_reason": "",
            "notes": "",
        },
        "platforms": {
            "youtube_shorts": {
                "title": title[:100],
                "description": f"{description}\n\n{' '.join(hashtags)}",
                "tags": tags,
                "privacy_status": "private",
            }
        },
        "posting_status": {
            "youtube_shorts": "ready",
        },
        "platform_uploads": {},
        "platform_metrics": {
            "youtube_shorts": {"posted": False, "views": 0, "likes": 0, "comments": 0, "shares": 0},
        },
    }


def render_popular_segment_short(theme, item, index, date_key, paths):
    scratch_dir = os.path.join(paths["metadata_path"], "editorial", date_key)
    os.makedirs(scratch_dir, exist_ok=True)
    output_dir = paths["final_videos_path"]
    os.makedirs(output_dir, exist_ok=True)

    clip = item["clip"]
    source_clip = clip.get("output_file", "")

    if not source_clip or not os.path.exists(source_clip):
        raise RuntimeError(f"Missing rendered source clip for popular segment: {item.get('source_title', '')}")

    source_title = compact_text(item.get("source_title") or clip.get("source_title") or "Podcast interview", 76)
    channel = compact_text(item.get("channel_label") or "Podcast Channel", 42)
    topic = compact_text(clip_summary(clip, source_title), 82)
    style = visual_style(index)
    accent = style["accent"]
    accent2 = style["accent2"]
    cream = style.get("cream", "0xFFF4B8")
    mint = style.get("mint", "0xB7D7C2")
    dark = style.get("dark", "0x2E3440")
    profile = theme_profile(theme)
    archive_label = f"THE {profile['label'].upper()} ARCHIVE"
    signal_label, popularity_label, detail_label = popular_segment_labels(item)
    script = build_popular_segment_script(theme, item)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, 1000 + index)
    intro_duration = max(2.2, min(4.0, POPULAR_SEGMENT_INTRO_SECONDS))
    clip_duration = clip_play_duration_for(source_clip, max(POPULAR_SEGMENT_MAX_SECONDS - intro_duration, EDITORIAL_CLIP_MIN_SECONDS))
    output_filename = clean_filename(f"{date_key}_{theme}_popular_{index:02d}_{source_title}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    source_title_size = fitted_label_font_size(source_title, max_width=860, max_size=44, min_size=28)
    topic_size = fitted_label_font_size(topic, max_width=770, max_size=40, min_size=27)
    channel_size = fitted_label_font_size(channel, max_width=560, max_size=31, min_size=22)
    font_bold = ffmpeg_path(font_path_or_fallback(FONT_BOLD_FILE, FONT_FILE))
    font_meta = ffmpeg_path(font_path_or_fallback(FONT_META_FILE, FONT_FILE))
    font_display = ffmpeg_path(font_path_or_fallback(FONT_DISPLAY_FILE, FONT_BOLD_FILE))

    filters = [
        f"[0:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=18:2,eq=brightness=-0.34:saturation=1.10,setsar=1[intro_bg]",
        "[intro_bg]"
        f"drawbox=x=0:y=0:w=1080:h=1920:color={dark}@0.24:t=fill,"
        f"drawtext=fontfile='{font_display}':text='POPULAR':x=44:y=244:fontsize=154:fontcolor={cream}@0.11,"
        f"drawbox=x=54:y=390:w=972:h=748:color=black@0.70:t=fill,"
        f"drawbox=x=54:y=390:w=972:h=748:color={accent}@0.88:t=5,"
        f"drawbox=x=54:y=390:w=18:h=748:color={accent}@0.98:t=fill,"
        f"drawbox=x=92:y=446:w=372:h=78:color={accent}@0.96:t=fill,"
        f"drawtext=fontfile='{font_display}':text='{drawtext_text(signal_label)}':x=112:y=452:fontsize=50:fontcolor={dark},"
        f"drawbox=x=748:y=446:w=232:h=78:color={dark}@0.78:t=fill,"
        f"drawbox=x=748:y=446:w=232:h=78:color={mint}@0.68:t=2,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(popularity_label)}':x=774:y=470:fontsize=25:fontcolor={cream},"
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(source_title)}':x=94:y=610:fontsize={source_title_size}:fontcolor=white:line_spacing=8:shadowcolor=black@0.52:shadowx=3:shadowy=3,"
        f"drawtext=fontfile='{font_meta}':text='FROM {drawtext_text(channel.upper())}':x=96:y=784:fontsize={channel_size}:fontcolor={mint}@0.94,"
        f"drawbox=x=94:y=872:w=700:h=4:color={accent2}@0.80:t=fill,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(detail_label)}':x=96:y=908:fontsize=31:fontcolor={cream}@0.96,"
        f"drawbox=x=96:y=1000:w=492:h=52:color={accent2}@0.52:t=fill,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(detail_label)}':x=118:y=1011:fontsize=25:fontcolor=white@0.86,"
        f"fade=t=out:st={max(0.1, intro_duration - 0.24):.3f}:d=0.24,format=yuv420p[intro_v]",
        f"[0:v]trim=0:{clip_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,eq=contrast=1.06:saturation=1.05,setsar=1[clip_base]",
        "[clip_base]"
        f"fade=t=in:st=0:d=0.16,"
        f"drawbox=x=0:y=0:w=1080:h=1920:color={dark}@0.035:t=fill,"
        f"drawbox=x=36:y=42:w=286:h=78:color=black@0.72:t=fill,"
        f"drawbox=x=36:y=42:w=286:h=78:color={accent}@0.88:t=3,"
        f"drawbox=x=36:y=42:w=11:h=78:color={accent}@0.98:t=fill,"
        f"drawtext=fontfile='{font_display}':text='{drawtext_text(signal_label)}':x=62:y=50:fontsize=38:fontcolor={cream}:shadowcolor=black@0.45:shadowx=2:shadowy=2,"
        f"drawbox=x=640:y=42:w=386:h=78:color=black@0.66:t=fill,"
        f"drawbox=x=640:y=42:w=386:h=78:color={mint}@0.58:t=2,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(archive_label)}':x=664:y=57:fontsize=27:fontcolor={cream},"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(channel.upper())}':x=664:y=88:fontsize=20:fontcolor=white@0.70,"
        f"drawbox=x=74:y=1600:w=870:h=166:color=black@0.73:t=fill,"
        f"drawbox=x=74:y=1600:w=870:h=166:color={mint}@0.62:t=2,"
        f"drawbox=x=74:y=1600:w=14:h=166:color={accent}@0.96:t=fill,"
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(topic.upper())}':x=108:y=1628:fontsize={topic_size}:fontcolor=white:shadowcolor=black@0.48:shadowx=2:shadowy=2,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(source_title)}':x=110:y=1708:fontsize=25:fontcolor={cream}@0.88,"
        f"drawbox=x=74:y=1848:w=932:h=7:color=black@0.52:t=fill,"
        f"drawbox=x=74:y=1848:w='932*t/{clip_duration:.3f}':h=7:color={accent}@0.98:t=fill,"
        f"drawbox=x=74:y=1861:w='932*t/{clip_duration:.3f}':h=3:color={mint}@0.78:t=fill,"
        f"format=yuv420p[clip_v]",
        f"[0:a]atrim=0:{intro_duration:.3f},volume={INTRO_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS[intro_bed]",
        f"[1:a]atrim=0:{intro_duration:.3f},volume=1.0,asetpts=PTS-STARTPTS[intro_voice]",
        "[intro_bed][intro_voice]amix=inputs=2:duration=longest:dropout_transition=0,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[intro_a]",
        f"[0:a]atrim=0:{clip_duration:.3f},volume={CLIP_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip_a]",
        "[intro_v][clip_v]concat=n=2:v=1:a=0[v]",
        "[intro_a][clip_a]concat=n=2:v=0:a=1[a]",
    ]

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-i", source_clip,
        "-i", intro_audio,
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ], "Popular segment short render")

    package = build_popular_output_package(
        theme=theme,
        output_path=output_path,
        item=item,
        index=index,
        date_key=date_key,
        script=script,
        intro_audio=intro_audio,
        intro_duration=intro_duration,
        clip_duration=clip_duration,
    )
    return finalize_editorial_package(package, f"popular segment #{index}")


def render_recap_compilation(theme, date_key, packages, paths):
    if not packages:
        return None

    scratch_dir = os.path.join(paths["metadata_path"], "editorial", date_key)
    concat_file = os.path.join(scratch_dir, f"{date_key}_{theme}_recap_concat.txt")
    output_path = os.path.join(paths["final_videos_path"], clean_filename(f"{date_key}_{theme}_full_daily_recap") + "_upload.mp4")

    with open(concat_file, "w", encoding="utf-8") as f:
        for package in packages:
            video_file = os.path.abspath(package["video_file"]).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{video_file}'\n")

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ], "Daily recap compilation")

    pseudo_topic = {
        "topic": "Full Daily Countdown",
        "clips": [{
            "source_title": "Daily podcast scan",
            "source_video_url": "",
            "transcript_excerpt": "",
            "score": max(float(item.get("score") or 0) for item in packages),
        }],
        "score": max(float(item.get("score") or 0) for item in packages),
    }
    package = build_output_package(
        theme=theme,
        output_path=output_path,
        source_clip=packages[0]["video_file"],
        topic_item=pseudo_topic,
        rank=0,
        adjective="full",
        date_key=date_key,
        is_recap=True,
    )
    package["editorial_parts"] = [item["video_file"] for item in packages]
    return finalize_editorial_package(package, "full daily recap")


def save_editorial_metadata(theme, paths, packages, brief):
    metadata_path = paths["final_metadata_file"]
    metadata = {
        "theme": theme,
        "content": [],
        "daily_editorial": brief,
    }

    if APPEND_METADATA and os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0:
        metadata = load_json_file(metadata_path, metadata)
        metadata["content"] = [
            item
            for item in metadata.get("content", [])
            if item.get("editorial_date") != brief["date"]
        ]

    metadata["theme"] = theme
    metadata["daily_editorial"] = brief
    metadata["content"] = metadata.get("content", []) + packages
    write_json_file(metadata_path, metadata)
    return metadata_path


def cleanup_stale_editorial_outputs(theme, paths, date_key, packages):
    output_dir = paths["final_videos_path"]
    keep_files = {
        os.path.normcase(os.path.normpath(os.path.abspath(package["video_file"])))
        for package in packages
        if package.get("video_file")
    }
    prefixes = [
        f"{date_key}_{theme}_countdown_",
        f"{date_key}_{theme}_daily_scan_",
        f"{date_key}_{theme}_popular_",
        f"{date_key}_{theme}_full_daily_recap",
    ]

    if not os.path.isdir(output_dir):
        return

    for filename in os.listdir(output_dir):
        if not filename.endswith("_upload.mp4"):
            continue

        if not any(filename.startswith(prefix) for prefix in prefixes):
            continue

        filepath = os.path.abspath(os.path.join(output_dir, filename))
        compare_path = os.path.normcase(os.path.normpath(filepath))

        if compare_path in keep_files:
            continue

        try:
            os.remove(filepath)
        except OSError:
            pass


def run_daily_editorial_for_theme(theme_name=DEFAULT_THEME):
    start = time.time()
    paths = ensure_theme(theme_name)
    theme = paths["theme"]
    date_key = os.getenv("SHORTFORM_EDITORIAL_DATE", datetime.now().strftime("%Y-%m-%d"))
    print(f"=== Generating ranked countdown for theme: {theme} ({date_key}) ===")

    rendered_clips = load_rendered_clip_reviews(paths["metadata_path"])

    if not rendered_clips:
        print("No rendered ranked clips found for editorial generation.\n")
        return 0

    countdown_count = min(DAILY_TOPIC_COUNT, EDITORIAL_COUNTDOWN_SIZE)
    topic_groups = group_clips_by_topic(rendered_clips)[:countdown_count]

    if not topic_groups:
        print("No topic groups found for editorial generation.\n")
        return 0

    packages = []
    countdown_packages = []
    brief_items = []
    popular_brief_items = []
    rejected_items = []
    reel_adjective = take_next_adjectives(theme, 1)[0]
    context = build_countdown_context(theme, paths, rendered_clips, topic_groups, reel_adjective)
    attach_countdown_context(topic_groups, context)
    print(
        f"Countdown setup: watched {format_hours_phrase(context.get('watched_hours', 0))} "
        f"across {context.get('source_count', 0)} {theme} interviews; angle: {reel_adjective}"
    )

    for index, topic_item in enumerate(topic_groups, start=1):
        adjective = reel_adjective
        print(f"Rendering countdown short #{topic_item['_countdown_slot']}: {adjective} - {topic_item['topic']}")
        package = render_editorial_short(
            theme=theme,
            topic_item=topic_item,
            rank=index,
            adjective=adjective,
            date_key=date_key,
            paths=paths,
        )

        if not package_is_upload_ready(package):
            rejected_items.append({
                "type": "countdown",
                "countdown_slot": topic_item["_countdown_slot"],
                "topic": topic_item["topic"],
                "rejection_reasons": (package.get("render_qc") or {}).get("rejection_reasons", []),
            })
            print(f"Skipping rejected countdown short #{topic_item['_countdown_slot']} from upload metadata.")
            continue

        packages.append(package)
        countdown_packages.append(package)
        brief_items.append({
            "rank": index,
            "countdown_slot": topic_item["_countdown_slot"],
            "adjective": adjective,
            "topic": topic_item["topic"],
            "score": topic_item.get("score"),
            "sources": sorted(topic_item.get("sources", []))[:5],
            "output_file": package["video_file"],
            "script": package.get("editorial_script", ""),
            "visual_style": package.get("visual_style", ""),
            "clips_in_short": package.get("clips_in_short", 1),
            "watched_hours": package.get("watched_hours", 0),
        })

    recap_package = None

    if RENDER_RECAP_COMPILATION and countdown_packages:
        print("Rendering full daily recap compilation...")
        recap_package = render_recap_compilation(theme, date_key, countdown_packages, paths)

        if recap_package and package_is_upload_ready(recap_package):
            packages.append(recap_package)
        elif recap_package:
            rejected_items.append({
                "type": "recap",
                "rejection_reasons": (recap_package.get("render_qc") or {}).get("rejection_reasons", []),
            })
            print("Skipping rejected daily recap from upload metadata.")

    if RENDER_POPULAR_SEGMENT_SHORTS:
        popular_items = popular_segment_items(theme, paths, rendered_clips)

        if popular_items:
            print(f"Rendering {len(popular_items)} most replayed/popular segment shorts...")

        for index, item in enumerate(popular_items, start=1):
            print(
                f"Rendering popular segment #{index}: "
                f"{item.get('channel_label', 'Podcast Channel')} - {item.get('source_title', '')}"
            )
            package = render_popular_segment_short(
                theme=theme,
                item=item,
                index=index,
                date_key=date_key,
                paths=paths,
            )

            if not package_is_upload_ready(package):
                rejected_items.append({
                    "type": "popular_segment",
                    "rank": index,
                    "source_title": item.get("source_title", ""),
                    "rejection_reasons": (package.get("render_qc") or {}).get("rejection_reasons", []),
                })
                print(f"Skipping rejected popular segment #{index} from upload metadata.")
                continue

            packages.append(package)
            popular_brief_items.append({
                "rank": index,
                "source_title": item.get("source_title", ""),
                "channel_label": item.get("channel_label", ""),
                "source_video_url": item.get("source_video_url", ""),
                "popularity_score": item.get("popularity_score", 0),
                "output_file": package["video_file"],
                "script": package.get("editorial_script", ""),
                "content_signal": package.get("content_signal", {}),
            })
        if not popular_items:
            print("No replay/popularity-backed source segments found for popular segment shorts.")

    brief = {
        "theme": theme,
        "date": date_key,
        "topic_count": len(brief_items),
        "popular_segment_count": len(popular_brief_items),
        "rejected_count": len(rejected_items),
        "format": "ranked_countdown_reel_with_popular_segments",
        "content_strategy": "watched-hours countdown plus one-source popular/replayed segment shorts with restrained premium overlays and full source audio",
        "items": brief_items,
        "popular_segments": popular_brief_items,
        "rejected_items": rejected_items,
        "adjective_rotation": {
            "used": [reel_adjective],
            "rotation_file": ADJECTIVE_ROTATION_FILE,
        },
        "source_scan": {
            "watched_hours": context.get("watched_hours", 0),
            "hours_phrase": format_hours_phrase(context.get("watched_hours", 0)),
            "source_count": context.get("source_count", 0),
        },
        "recap_file": recap_package["video_file"] if recap_package else "",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    brief_dir = os.path.join(paths["metadata_path"], "editorial", date_key)
    os.makedirs(brief_dir, exist_ok=True)
    brief_file = os.path.join(brief_dir, "daily_brief.json")
    write_json_file(brief_file, brief)
    cleanup_stale_editorial_outputs(theme, paths, date_key, packages)
    metadata_file = save_editorial_metadata(theme, paths, packages, brief)

    print(f"Daily brief: {brief_file}")
    print(f"Upload metadata: {metadata_file}")
    print(f"Editorial outputs ready: {len(packages)}")
    print(f"Daily editorial finished in {time.time() - start:.2f} seconds\n")
    return len(packages)


def run_daily_editorial(theme=None):
    if theme:
        return run_daily_editorial_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_daily_editorial_for_theme(requested_theme)

    total = 0

    for theme_name in discover_themes():
        total += run_daily_editorial_for_theme(theme_name)

    return total


if __name__ == "__main__":
    run_daily_editorial()
