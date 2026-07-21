import os
FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

import csv
import calendar
import hashlib
import json
import math
import subprocess
import time
import re
import wave
from dataclasses import asdict, dataclass, field, replace
import yt_dlp
import cv2
import mediapipe as mp
import numpy as np
from yt_dlp.utils import download_range_func
import ytdlp_auth
import runtime_budget
from media_encoding import encoder_label, video_encoder_args
from theme_config import (
    BASE_DIR,
    DEFAULT_THEME,
    EXECUTED_FILE,
    PULLED_FILE,
    assert_theme_allowed_for_active_run,
    discover_themes,
    ensure_theme,
    load_json_file,
    mark_stage,
    utc_timestamp,
    write_json_file,
)
from theme_profile import (
    get_clip_rules,
    get_metadata_style,
    get_risk_controls,
    get_scoring_weights,
    get_theme_signals,
    load_theme_profile,
    source_guard_disqualification,
    theme_keyword_weights,
    theme_topic_tags as profile_theme_topic_tags,
)
from theme_signals import score_theme_signals
from analytics.feedback_prior import score_analytics_feedback_prior
from metadata_generation import generate_description, generate_hashtags, generate_title, score_title_quality, title_passes_publishable_bar
from metadata_generation.titles import TITLE_STOPWORDS, polish_headline_title
from popularity_signals import (
    build_popularity_profile_from_info,
    build_youtube_data_api_profile,
    load_cached_popularity_profile,
    merge_popularity_profiles,
    save_popularity_profile,
    score_comment_topic_match,
    score_popularity_for_window,
)

try:
    cv2.ocl.setUseOpenCL(False)
except Exception:
    pass


# =========================
# Base directories and paths
# =========================

base_dir = BASE_DIR

CURRENT_THEME = None
FRAME_QC_VERSION = "2026-06-dense-speaker-qc-v1"

videos_path = None
audio_path = None
transcriptions_path = None
clips_path = None
metadata_path = None
_TRANSCRIBE_MODEL = None
_TRANSCRIBE_MODEL_SETTINGS = None


def configure_theme(theme_name):
    global CURRENT_THEME
    global videos_path, audio_path, transcriptions_path, clips_path, metadata_path

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    videos_path = theme_paths["videos_path"]
    audio_path = theme_paths["audio_path"]
    transcriptions_path = theme_paths["transcriptions_path"]
    clips_path = theme_paths["clips_path"]
    metadata_path = theme_paths["metadata_path"]

    return theme_paths


# Keep this on while tuning reframing; turn it off for resume runs that should reuse completed clips.
REGENERATE_EXISTING_CLIPS = os.getenv("SHORTFORM_REGENERATE_EXISTING_CLIPS", "0") != "0"
SPEED_PROFILE = os.getenv("SHORTFORM_SPEED_PROFILE", "production").strip().lower()


def speed_profile_default(key, production, debug=None, premium=None):
    if key in os.environ:
        return os.getenv(key)

    if SPEED_PROFILE in {"debug", "fast", "tiny"}:
        return debug if debug is not None else production

    if SPEED_PROFILE in {"premium", "deep", "quality"}:
        return premium if premium is not None else production

    return production


def parse_theme_float_map(value):
    parsed = {}

    for item in str(value or "").split(","):
        if "=" not in item:
            continue

        key, raw_value = item.split("=", 1)
        key = key.strip().lower().replace("-", "_")

        try:
            parsed[key] = float(raw_value.strip())
        except ValueError:
            continue

    return parsed


def parse_theme_int_map(value):
    parsed = {}

    for key, raw_value in parse_theme_float_map(value).items():
        parsed[key] = max(0, int(round(raw_value)))

    return parsed


MIN_CLIP_DURATION = 30
MAX_CLIP_DURATION = 60
CANDIDATE_CLIP_DURATIONS = [35, 45, 55]
CANDIDATE_STRIDE_SECONDS = 4
MIN_SELECTED_CLIP_SCORE = 0.27
MIN_WORDS_PER_CANDIDATE = 30
MIN_CLIP_SPACING_SECONDS = 2
MAX_TOPIC_SIMILARITY = 0.58
SCORING_MODEL_VERSION = "2026-06-30-v71-source-trust-engagement-first"
MIN_CLIP_READINESS_SCORE = float(os.getenv("SHORTFORM_MIN_CLIP_READINESS_SCORE", "0.62"))
UNLIMITED_BACKLOG_MIN_SELECTED_SCORE = float(os.getenv("SHORTFORM_UNLIMITED_BACKLOG_MIN_SELECTED_SCORE", "0.60"))
UNLIMITED_BACKLOG_MIN_READINESS_SCORE = float(os.getenv("SHORTFORM_UNLIMITED_BACKLOG_MIN_READINESS_SCORE", "0.70"))
UNLIMITED_BACKLOG_MIN_TEXT_SCORE = float(os.getenv("SHORTFORM_UNLIMITED_BACKLOG_MIN_TEXT_SCORE", "0.20"))
MIN_FINISHED_TARGET = max(1, int(os.getenv("SHORTFORM_MIN_FINISHED_PER_THEME", "10")))
PREFERRED_FINISHED_TARGET = max(MIN_FINISHED_TARGET, int(os.getenv("SHORTFORM_PREFERRED_FINISHED_PER_THEME", "10")))
DAILY_UPLOAD_READY_TARGET = max(0, int(os.getenv("SHORTFORM_UPLOAD_READY_TARGET_PER_THEME", "15")))
DAILY_RESERVE_TARGET = max(0, int(os.getenv(
    "SHORTFORM_RESERVE_TARGET_PER_THEME",
    str(max(0, PREFERRED_FINISHED_TARGET - DAILY_UPLOAD_READY_TARGET)),
)))
DAILY_FINAL_PACKAGE_TARGET = PREFERRED_FINISHED_TARGET
DAILY_RENDER_ACCEPTED_BUFFER_MULTIPLIER = max(1.0, float(os.getenv("SHORTFORM_RENDER_ACCEPTED_BUFFER_MULTIPLIER", "1.0")))
DAILY_RENDER_ACCEPTED_TARGET = max(0, int(os.getenv(
    "SHORTFORM_DAILY_RENDER_ACCEPTED_TARGET",
    str(math.ceil(DAILY_FINAL_PACKAGE_TARGET * DAILY_RENDER_ACCEPTED_BUFFER_MULTIPLIER)),
)))
DAILY_RENDER_ACCEPTED_TARGET_GLOBAL_OVERRIDE = "SHORTFORM_DAILY_RENDER_ACCEPTED_TARGET" in os.environ
MIN_PRE_RENDER_COPY_SCORE = float(os.getenv("SHORTFORM_MIN_PRE_RENDER_COPY_SCORE", "0.52"))
THEME_EDITORIAL_SUCCESS_RATE_OVERRIDES = parse_theme_float_map(
    os.getenv("SHORTFORM_THEME_EDITORIAL_SUCCESS_RATES", "")
)
THEME_RENDER_ACCEPTED_TARGET_OVERRIDES = parse_theme_int_map(
    os.getenv("SHORTFORM_THEME_RENDER_ACCEPTED_TARGETS", "")
)
MAX_THEME_RENDER_ACCEPTED_TARGET = max(
    DAILY_RENDER_ACCEPTED_TARGET,
    int(os.getenv("SHORTFORM_MAX_THEME_RENDER_ACCEPTED_TARGET", "120")),
)
DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER = max(1, int(os.getenv("SHORTFORM_DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER", "2")))
DAILY_RENDER_POOL_MIN_ATTEMPTS = max(0, int(os.getenv("SHORTFORM_DAILY_RENDER_POOL_MIN_ATTEMPTS", "20")))
CONFIGURED_SOURCE_THEME_SIGNAL_FLOOR = float(os.getenv("SHORTFORM_CONFIGURED_SOURCE_THEME_SIGNAL_FLOOR", "0.50"))
CONFIGURED_SOURCE_THEME_WEIGHT_CAP = float(os.getenv("SHORTFORM_CONFIGURED_SOURCE_THEME_WEIGHT_CAP", "0.07"))
MIN_SOURCE_DURATION_SECONDS = float(os.getenv("SHORTFORM_MIN_SOURCE_DURATION_SECONDS", "600"))
MAX_SOURCE_DURATION_SECONDS = float(os.getenv("SHORTFORM_MAX_SOURCE_DURATION_SECONDS", str(4 * 60 * 60)))
RECENT_BLOCKED_RETRY_SECONDS = float(os.getenv("SHORTFORM_RECENT_BLOCKED_RETRY_SECONDS", str(6 * 60 * 60)))
SKIP_BROADCAST_VOD_SOURCES = os.getenv("SHORTFORM_SKIP_BROADCAST_VOD_SOURCES", "1") != "0"
ENABLE_PERSON_FALLBACK = os.getenv("SHORTFORM_ENABLE_PERSON_FALLBACK") == "1"
ENABLE_ALTERNATE_FRAMING_RETRY = os.getenv("SHORTFORM_ENABLE_ALTERNATE_FRAMING_RETRY", "1") != "0"
ALLOW_FACELESS_CENTER_SAFE = os.getenv("SHORTFORM_ALLOW_FACELESS_CENTER_SAFE", "1") == "1"
RENDER_PREROLL_SECONDS = max(0.0, float(os.getenv("SHORTFORM_RENDER_PREROLL_SECONDS", "0.75")))
RENDER_POSTROLL_SECONDS = max(0.0, float(os.getenv("SHORTFORM_RENDER_POSTROLL_SECONDS", "0.25")))
RENDER_EXTRA_DURATION_TOLERANCE = max(0.0, float(os.getenv("SHORTFORM_RENDER_EXTRA_DURATION_TOLERANCE", "1.25")))
FRAME_RETRY_SCORE_THRESHOLD = float(os.getenv("SHORTFORM_FRAME_RETRY_SCORE_THRESHOLD", "0.68"))
MAX_CROP_SECONDS_PER_MINUTE = float(os.getenv("SHORTFORM_MAX_CROP_SECONDS_PER_MINUTE", "180"))
MAX_CROP_WALL_SECONDS = float(os.getenv("SHORTFORM_MAX_CROP_WALL_SECONDS", "180"))
MAX_CROP_FRAME_MULTIPLIER = float(os.getenv("SHORTFORM_MAX_CROP_FRAME_MULTIPLIER", "1.12"))
FRAME_AUDIT_SAMPLE_COUNT = max(8, int(os.getenv("SHORTFORM_FRAME_AUDIT_SAMPLE_COUNT", "10")))
BLACK_FRAME_SAMPLE_COUNT = max(6, int(os.getenv("SHORTFORM_BLACK_FRAME_SAMPLE_COUNT", "8")))
FINAL_FRAME_PATH_SAMPLE_COUNT = max(8, int(os.getenv("SHORTFORM_FINAL_FRAME_PATH_SAMPLE_COUNT", "10")))
PREFLIGHT_FRAME_SAMPLE_COUNT = max(8, int(os.getenv("SHORTFORM_PREFLIGHT_FRAME_SAMPLE_COUNT", "10")))
FACE_TARGET_SAMPLE_COUNT = max(16, int(os.getenv("SHORTFORM_FACE_TARGET_SAMPLE_COUNT", "16")))
CREATE_RENDER_CONTACT_SHEETS = os.getenv("SHORTFORM_CREATE_RENDER_CONTACT_SHEETS", "0") == "1"
GROUP_FACE_CONFIDENCE_THRESHOLD = float(os.getenv("SHORTFORM_GROUP_FACE_CONFIDENCE_THRESHOLD", "0.25"))
HARD_REJECT_BAD_RENDERS = os.getenv("SHORTFORM_HARD_REJECT_BAD_RENDERS", "1") != "0"
MIN_ACCEPTED_RENDER_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_ACCEPTED_RENDER_VISUAL_QUALITY", "0.56"))
DEAD_FRAME_RATIO_THRESHOLD = float(os.getenv("SHORTFORM_DEAD_FRAME_RATIO_THRESHOLD", "0.22"))
MIN_ALIVE_FRAME_RATE = float(os.getenv("SHORTFORM_MIN_ALIVE_FRAME_RATE", "0.68"))
MIN_FINAL_SPEAKER_FACE_PRESENCE = float(os.getenv("SHORTFORM_MIN_FINAL_SPEAKER_FACE_PRESENCE", "0.40"))
MAX_FINAL_ALIVE_NO_FACE_RATIO = float(os.getenv("SHORTFORM_MAX_FINAL_ALIVE_NO_FACE_RATIO", "0.36"))
MAX_FINAL_NO_FACE_RUN_RATIO = float(os.getenv("SHORTFORM_MAX_FINAL_NO_FACE_RUN_RATIO", "0.30"))
MAX_FINAL_AVG_FACE_CENTER_OFFSET = float(os.getenv("SHORTFORM_MAX_FINAL_AVG_FACE_CENTER_OFFSET", "0.34"))
MAX_FINAL_SPEAKER_LOW_INFORMATION_RATIO = float(os.getenv("SHORTFORM_MAX_FINAL_SPEAKER_LOW_INFORMATION_RATIO", "0.05"))
MAX_FINAL_SPEAKER_BLANK_BACKGROUND_RATIO = float(os.getenv("SHORTFORM_MAX_FINAL_SPEAKER_BLANK_BACKGROUND_RATIO", "0.04"))
MIN_FINAL_FACE_PLAUSIBILITY = float(os.getenv("SHORTFORM_MIN_FINAL_FACE_PLAUSIBILITY", "0.37"))
MIN_FINAL_FACE_HEIGHT_RATIO = float(os.getenv("SHORTFORM_MIN_FINAL_FACE_HEIGHT_RATIO", "0.085"))
MIN_FINAL_TINY_FACE_LOCK_HEIGHT_RATIO = float(os.getenv("SHORTFORM_MIN_FINAL_TINY_FACE_LOCK_HEIGHT_RATIO", "0.070"))
CLIP_TRANSCRIBE_MODEL_SIZE = speed_profile_default(
    "SHORTFORM_CLIP_TRANSCRIBE_MODEL",
    production="base",
    debug="tiny",
    premium="small",
).strip() or "base"
CLIP_TRANSCRIBE_BEAM_SIZE = max(1, int(speed_profile_default(
    "SHORTFORM_CLIP_TRANSCRIBE_BEAM_SIZE",
    production="1",
    debug="1",
    premium="5",
)))
CLIP_TRANSCRIBE_BEST_OF = max(1, int(speed_profile_default(
    "SHORTFORM_CLIP_TRANSCRIBE_BEST_OF",
    production=str(CLIP_TRANSCRIBE_BEAM_SIZE),
    debug="1",
    premium=str(CLIP_TRANSCRIBE_BEAM_SIZE),
)))
ENABLE_THEME_GLOBAL_RANKING = os.getenv("SHORTFORM_ENABLE_THEME_GLOBAL_RANKING", "1") != "0"
THEME_CLIP_BUDGET = max(0, int(os.getenv("SHORTFORM_THEME_CLIP_BUDGET", "0")))
ENFORCE_THEME_CLIP_BUDGET = os.getenv("SHORTFORM_ENFORCE_THEME_CLIP_BUDGET", "0") == "1"
ALLOW_THEME_CLIP_CAP = os.getenv("SHORTFORM_ALLOW_THEME_CLIP_CAP", "0") == "1"
THEME_CANDIDATES_PER_VIDEO = max(1, int(os.getenv("SHORTFORM_THEME_CANDIDATES_PER_VIDEO", "24")))
SOURCE_CANDIDATE_CAP = max(0, int(os.getenv("SHORTFORM_SOURCE_CANDIDATE_CAP", "12")))
RESPECT_LEGACY_THEME_CANDIDATES_PER_VIDEO = os.getenv(
    "SHORTFORM_RESPECT_LEGACY_THEME_CANDIDATES_PER_VIDEO",
    "0",
) == "1"
CLIP_SCORE_CACHE_CANDIDATE_LIMIT = max(0, int(os.getenv("SHORTFORM_CLIP_SCORE_CACHE_CANDIDATE_LIMIT", "48")))
CLIP_REVIEW_REPORT_CANDIDATE_LIMIT = max(0, int(os.getenv("SHORTFORM_CLIP_REVIEW_REPORT_CANDIDATE_LIMIT", "60")))
RECONSIDER_UNSELECTED_SOURCES = os.getenv("SHORTFORM_RECONSIDER_UNSELECTED", "0") == "1"
REUSE_CACHED_CLIP_SCORES = os.getenv("SHORTFORM_REUSE_CACHED_CLIP_SCORES", "1") != "0"
INITIAL_AUDIO_PREFETCH_SOURCES_PER_THEME = max(1, int(os.getenv("SHORTFORM_INITIAL_AUDIO_PREFETCH_SOURCES_PER_THEME", "4")))
MIN_SCORED_SOURCES_PER_THEME = max(1, int(os.getenv("SHORTFORM_MIN_SCORED_SOURCES_PER_THEME", "4")))
MAX_UNSCORED_SOURCES_PER_THEME = max(
    MIN_SCORED_SOURCES_PER_THEME,
    int(os.getenv("SHORTFORM_MAX_UNSCORED_SOURCES_PER_THEME", "6")),
)
TARGET_PUBLISHABLE_CANDIDATES_PER_THEME = max(
    PREFERRED_FINISHED_TARGET,
    int(os.getenv("SHORTFORM_TARGET_PUBLISHABLE_CANDIDATES_PER_THEME", "20")),
)
ENABLE_POPULARITY_SCORING = os.getenv("SHORTFORM_ENABLE_POPULARITY_SCORING", "1") != "0"
POPULARITY_SCORE_WEIGHT = float(os.getenv("SHORTFORM_POPULARITY_SCORE_WEIGHT", "0.16"))
GUEST_RECOGNIZABILITY_MAX_ADJUSTMENT = float(os.getenv("SHORTFORM_GUEST_RECOGNIZABILITY_MAX_ADJUSTMENT", "0.018"))
GUEST_RECOGNIZABILITY_THEMES = {
    "sports",
    "finance",
    "technology_ai",
    "popculture",
}
FETCH_COMMENT_TIMESTAMP_SIGNALS = os.getenv("SHORTFORM_FETCH_COMMENT_TIMESTAMP_SIGNALS", "1") != "0"
COMMENT_TIMESTAMP_REFRESH_DAYS = float(os.getenv("SHORTFORM_COMMENT_TIMESTAMP_REFRESH_DAYS", "5"))
YOUTUBE_DATA_API_KEY = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
ENABLE_YOUTUBE_DATA_API_SIGNALS = os.getenv("SHORTFORM_ENABLE_YOUTUBE_DATA_API_SIGNALS", "1") != "0"
YOUTUBE_DATA_API_COMMENT_PAGES = max(1, int(os.getenv("SHORTFORM_YOUTUBE_DATA_API_COMMENT_PAGES", "1")))
SLOW_SOURCE_REVIEW_SECONDS = float(os.getenv("SHORTFORM_SLOW_SOURCE_REVIEW_SECONDS", "1800"))
ENABLE_SCORING_WINDOW_CAPS = os.getenv("SHORTFORM_ENABLE_SCORING_WINDOW_CAPS", "1") != "0"
FULL_SOURCE_SCAN_MAX_SECONDS = max(60, int(speed_profile_default(
    "SHORTFORM_FULL_SOURCE_SCAN_MAX_SECONDS",
    production="3600",
    debug="1200",
    premium="21600",
)))
MAX_SCORING_START_POINTS = max(40, int(speed_profile_default(
    "SHORTFORM_MAX_SCORING_START_POINTS",
    production="72",
    debug="180",
    premium="1600",
)))
SCORING_SIGNAL_WINDOW_RADIUS_SECONDS = max(10, int(os.getenv("SHORTFORM_SCORING_SIGNAL_WINDOW_RADIUS_SECONDS", "60")))
ENABLE_SIGNAL_WINDOW_TRANSCRIPTION = os.getenv("SHORTFORM_ENABLE_SIGNAL_WINDOW_TRANSCRIPTION", "1") != "0"
SIGNAL_TRANSCRIPT_FULL_MAX_SECONDS = max(300, int(speed_profile_default(
    "SHORTFORM_SIGNAL_TRANSCRIPT_FULL_MAX_SECONDS",
    production="900",
    debug="600",
    premium="3600",
)))
SIGNAL_TRANSCRIPT_MAX_WINDOWS = max(4, int(speed_profile_default(
    "SHORTFORM_SIGNAL_TRANSCRIPT_MAX_WINDOWS",
    production="4",
    debug="6",
    premium="40",
)))
SIGNAL_TRANSCRIPT_WINDOW_RADIUS_SECONDS = max(20, int(os.getenv(
    "SHORTFORM_SIGNAL_TRANSCRIPT_WINDOW_RADIUS_SECONDS",
    str(max(60, min(75, SCORING_SIGNAL_WINDOW_RADIUS_SECONDS))),
)))
ANALYSIS_AUDIO_MAX_ABR = max(48, int(os.getenv("SHORTFORM_ANALYSIS_AUDIO_MAX_ABR", "96")))


def active_theme_name(theme_name=None):
    return theme_name or CURRENT_THEME or DEFAULT_THEME


def active_theme_profile(theme_name=None):
    return load_theme_profile(active_theme_name(theme_name))


def active_clip_rules(theme_name=None):
    return get_clip_rules(active_theme_name(theme_name))


def rule_number(name, fallback, theme_name=None, cast=float):
    rules = active_clip_rules(theme_name)
    value = rules.get(name, fallback)

    try:
        return cast(value)
    except (TypeError, ValueError):
        return cast(fallback)


def rule_list(name, fallback, theme_name=None):
    value = active_clip_rules(theme_name).get(name, fallback)

    if not isinstance(value, list) or not value:
        return list(fallback)

    return value


def active_min_clip_duration(theme_name=None):
    return rule_number("min_clip_duration", MIN_CLIP_DURATION, theme_name=theme_name, cast=int)


def active_max_clip_duration(theme_name=None):
    return rule_number("max_clip_duration", MAX_CLIP_DURATION, theme_name=theme_name, cast=int)


def active_candidate_durations(theme_name=None):
    durations = [
        int(duration)
        for duration in rule_list("candidate_durations", CANDIDATE_CLIP_DURATIONS, theme_name=theme_name)
        if int(duration) > 0
    ]
    return durations or list(CANDIDATE_CLIP_DURATIONS)


def active_min_selected_score(theme_name=None):
    return rule_number("min_selected_score", MIN_SELECTED_CLIP_SCORE, theme_name=theme_name, cast=float)


def active_publishable_min_selected_score(theme_name=None):
    base = active_min_selected_score(theme_name)

    if active_theme_clip_limit(theme_name) is None:
        return max(base, UNLIMITED_BACKLOG_MIN_SELECTED_SCORE)

    return base


def active_min_readiness_score(theme_name=None):
    return rule_number("min_readiness_score", MIN_CLIP_READINESS_SCORE, theme_name=theme_name, cast=float)


def active_max_topic_similarity(theme_name=None):
    return rule_number("max_topic_similarity", MAX_TOPIC_SIMILARITY, theme_name=theme_name, cast=float)


def active_theme_clip_budget(theme_name=None):
    return max(0, rule_number("theme_clip_budget", THEME_CLIP_BUDGET, theme_name=theme_name, cast=int))


def active_theme_clip_limit(theme_name=None):
    if not (ENFORCE_THEME_CLIP_BUDGET and ALLOW_THEME_CLIP_CAP):
        return None

    budget = active_theme_clip_budget(theme_name)

    if budget <= 0:
        return None

    return budget


def active_theme_candidates_per_video(theme_name=None):
    if SOURCE_CANDIDATE_CAP > 0:
        return SOURCE_CANDIDATE_CAP

    if not RESPECT_LEGACY_THEME_CANDIDATES_PER_VIDEO:
        return None

    configured = rule_number(
        "theme_candidates_per_video",
        THEME_CANDIDATES_PER_VIDEO,
        theme_name=theme_name,
        cast=int,
    )
    return max(1, configured)


def ranked_candidate_window(candidates, limit=None):
    ranked = sorted(candidates or [], key=candidate_ranking_key, reverse=True)

    if limit is None:
        return ranked

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return ranked

    if limit <= 0:
        return ranked

    return ranked[:limit]


def active_candidate_stride(theme_name=None):
    return max(1, rule_number("candidate_stride_seconds", CANDIDATE_STRIDE_SECONDS, theme_name=theme_name, cast=int))


def keyword_in_text(text, keyword):
    key = str(keyword or "").strip().lower()
    if not key:
        return False

    haystack = f" {str(text or '').lower()} "
    if " " in key:
        return key in haystack

    return re.search(rf"\b{re.escape(key)}\b", haystack) is not None


def source_disqualified_by_theme(source_record, theme_name=None):
    return source_guard_disqualification(active_theme_profile(theme_name), source_record)


def source_duration_from_record(source_record):
    source_record = source_record or {}
    durations = []

    for key in ("duration", "duration_seconds", "source_duration"):
        try:
            value = float(source_record.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0

        if value > 0:
            durations.append(value)

    metrics = source_record.get("_processing_metrics") or {}
    window_policy = metrics.get("candidate_window_policy") or {}

    try:
        value = float(window_policy.get("source_duration_seconds") or 0.0)
    except (TypeError, ValueError):
        value = 0.0

    if value > 0:
        durations.append(value)

    return max(durations) if durations else 0.0


BROADCAST_VOD_TITLE_PATTERNS = [
    r"\blive\s+from\b.*\b(day|night)\s+(one|two|three|four|\d+)\b",
    r"\bfull\s+(match|game|stream|event|broadcast|trial)\b",
    r"\b(entire|complete)\s+(trial|hearing|case|testimony|deposition|proceeding)s?\b",
    r"\b(opening\s+to\s+sentencing|closing\s+arguments?\s+to\s+verdict)\b",
    r"\bfull\s+(court|hearing|testimony|deposition|proceeding)s?\b",
    r"\b(game|map)\s*0?\d+\b.*\b(vs\.?|versus)\b",
    r"\b(vs\.?|versus)\b.*\b(game|map)\s*0?\d+\b",
    r"\b(msi|major|tournament|playoffs?|finals?)\b.*\b(game|map)\s*0?\d+\b",
    r"\b(winners?|losers?|grand)\s+finals?\b",
    r"\bmajor\s+[ivx\d]+\s+tournament\b",
]


def source_looks_like_broadcast_vod(source_record):
    if not SKIP_BROADCAST_VOD_SOURCES:
        return False, []

    title = str((source_record or {}).get("title") or "")
    normalized = re.sub(r"\s+", " ", title).strip().lower()

    if not normalized:
        return False, []

    hits = [
        pattern
        for pattern in BROADCAST_VOD_TITLE_PATTERNS
        if re.search(pattern, normalized, flags=re.I)
    ]

    if hits:
        return True, [f"broadcast/live-event vod:{title[:120]}"]

    return False, []


def source_quality_disqualification(source_record):
    duration = source_duration_from_record(source_record)

    if duration and duration < MIN_SOURCE_DURATION_SECONDS:
        return True, [f"source too short for long-form clipping:{duration:.0f}s"]

    if MAX_SOURCE_DURATION_SECONDS > 0 and duration and duration > MAX_SOURCE_DURATION_SECONDS:
        return True, [f"source too long for daily clipping:{duration:.0f}s"]

    broadcast_disqualified, broadcast_hits = source_looks_like_broadcast_vod(source_record)

    if broadcast_disqualified:
        return True, broadcast_hits

    return False, []


def parse_countish_value(value):
    if isinstance(value, (int, float)):
        return int(max(0, value))

    text = str(value or "").strip().lower().replace(",", "")
    if not text:
        return 0

    multiplier = 1
    if "b" in text:
        multiplier = 1_000_000_000
    elif "m" in text:
        multiplier = 1_000_000
    elif "k" in text:
        multiplier = 1_000

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 0

    return int(float(match.group(1)) * multiplier)


def title_has_named_guest_shape(title):
    title = str(title or "").strip()

    if not title:
        return False

    if re.search(r"\b(with|w/|ft\.?|featuring)\s+[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){0,3}", title):
        return True

    if re.search(r"[|:-]\s*[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3}\b", title):
        return True

    name_like_phrases = re.findall(r"\b[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3}\b", title)
    ignore = {"Joe Rogan Experience", "The Diary", "This Past", "The Megyn Kelly Show"}
    return any(phrase not in ignore and len(phrase.split()) <= 4 for phrase in name_like_phrases)


def guest_recognizability_signal(theme_name, source_record, popularity_profile, readiness_score, arc_details, first_second_qc, transformation):
    theme = active_theme_name(theme_name)
    profile_name = str((active_theme_profile(theme).get("profile") or theme)).lower()
    eligible_theme = theme in GUEST_RECOGNIZABILITY_THEMES or profile_name in {
        "sports",
        "finance",
        "technology",
        "popculture",
    }
    min_readiness = max(0.66, active_min_readiness_score(theme))
    standalone_score = float((arc_details or {}).get("arc_standalone_score") or 0.0)
    transformation_score = float((transformation or {}).get("transformation_score") or 0.0)
    source_record = source_record or {}
    popularity_profile = popularity_profile or {}
    api_stats = (popularity_profile.get("youtube_data_api") or {}).get("stats") or {}
    source_tier = str(source_record.get("source_tier") or "legacy").lower()
    view_count = max(
        parse_countish_value(api_stats.get("view_count")),
        parse_countish_value(source_record.get("view_count")),
        parse_countish_value(source_record.get("views")),
    )
    comment_count = max(
        parse_countish_value(api_stats.get("comment_count")),
        parse_countish_value(source_record.get("comment_count")),
        parse_countish_value(source_record.get("comments")),
    )
    source_title = source_record.get("title") or popularity_profile.get("title") or ""
    reasons = []
    raw_score = 0.0

    if source_tier == "priority":
        raw_score += 0.34
        reasons.append("priority_source")
    elif source_tier == "secondary":
        raw_score += 0.16
        reasons.append("secondary_source")

    if source_record.get("routing_override_matches"):
        raw_score += 0.08
        reasons.append("episode_routing_match")

    if title_has_named_guest_shape(source_title):
        raw_score += 0.20
        reasons.append("named_guest_title_shape")

    if view_count > 0:
        raw_score += min(0.24, math.log10(view_count + 1) / 7.0 * 0.24)
        reasons.append("public_view_count")

    if comment_count > 0:
        raw_score += min(0.10, math.log10(comment_count + 1) / 5.0 * 0.10)
        reasons.append("public_comment_count")

    raw_score = max(0.0, min(1.0, raw_score))
    first_second_passed = not first_second_qc or first_second_qc.get("passed", True)
    standalone_confirmed = (
        float(readiness_score or 0.0) >= min_readiness
        and standalone_score >= 0.48
        and first_second_passed
        and transformation_score >= 0.50
    )
    adjustment = raw_score * GUEST_RECOGNIZABILITY_MAX_ADJUSTMENT if eligible_theme and standalone_confirmed else 0.0

    return {
        "eligible_theme": bool(eligible_theme),
        "standalone_value_confirmed": bool(standalone_confirmed),
        "score": round(raw_score, 4),
        "adjustment": round(adjustment, 4),
        "max_adjustment": GUEST_RECOGNIZABILITY_MAX_ADJUSTMENT,
        "reasons": reasons[:8],
        "source_tier": source_tier,
        "view_count": int(view_count),
        "comment_count": int(comment_count),
        "named_guest_title_shape": title_has_named_guest_shape(source_title),
        "gates": {
            "readiness_score": round(float(readiness_score or 0.0), 4),
            "minimum_readiness": round(min_readiness, 4),
            "standalone_context": round(standalone_score, 4),
            "first_second_passed": bool(first_second_passed),
            "transformation_score": round(transformation_score, 4),
        },
    }


# =========================
# Executables
# =========================

FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


# =========================
# yt-dlp configuration
# =========================

YTDL_COMMON_OPTS = {
    "quiet": True,
    "no_warnings": True,
    **ytdlp_auth.youtube_js_runtime_options(),
    "ignoreerrors": True,
    "continuedl": True,
    "retries": int(os.getenv("SHORTFORM_YTDLP_RETRIES", "6")),
    "fragment_retries": int(os.getenv("SHORTFORM_YTDLP_FRAGMENT_RETRIES", "6")),
    "extractor_retries": int(os.getenv("SHORTFORM_YTDLP_EXTRACTOR_RETRIES", "2")),
    "file_access_retries": int(os.getenv("SHORTFORM_YTDLP_FILE_RETRIES", "2")),
    "socket_timeout": int(os.getenv("SHORTFORM_YTDLP_SOCKET_TIMEOUT", "18")),
    "concurrent_fragment_downloads": int(os.getenv("SHORTFORM_YTDLP_FRAGMENTS", "8")),
    "throttledratelimit": int(os.getenv("SHORTFORM_YTDLP_THROTTLED_RATE", str(80 * 1024))),
    "http_chunk_size": int(os.getenv("SHORTFORM_YTDLP_HTTP_CHUNK_SIZE", str(10 * 1024 * 1024))),
    "noplaylist": True,
}

SOURCE_MAX_HEIGHT = int(os.getenv("SHORTFORM_SOURCE_MAX_HEIGHT", "1080"))
REQUIRE_MEDIAPIPE_FACE_VERIFY = os.getenv("SHORTFORM_REQUIRE_MEDIAPIPE_FACE_VERIFY", "1") != "0"
MEDIAPIPE_FACE_CONFIDENCE = float(os.getenv("SHORTFORM_MEDIAPIPE_FACE_CONFIDENCE", "0.56"))
MAX_CONSECUTIVE_NETWORK_FAILURES = int(os.getenv("SHORTFORM_MAX_NETWORK_FAILURES", "2"))
HALT_ON_RESTRICTED_DOWNLOAD_FAILURE = os.getenv("SHORTFORM_HALT_ON_RESTRICTED_DOWNLOAD_FAILURE", "1") != "0"
ALLOW_FULL_SOURCE_FALLBACK = os.getenv("SHORTFORM_ALLOW_FULL_SOURCE_FALLBACK", "0") == "1"
MAX_AUDIO_DOWNLOAD_BYTES = int(
    os.getenv("SHORTFORM_MAX_AUDIO_DOWNLOAD_BYTES", str(300 * 1024 * 1024))
)

AUDIO_STREAM_COPY_EXTENSIONS = {
    "aac": ".m4a",
    "alac": ".m4a",
    "mp3": ".mp3",
    "opus": ".opus",
    "vorbis": ".ogg",
    "flac": ".flac",
}
AUDIO_PACKAGE_EXTENSIONS = [".m4a", ".opus", ".ogg", ".mp3", ".flac", ".wav", ".webm"]
VIDEO_SECTION_PADDING_SECONDS = float(os.getenv("SHORTFORM_VIDEO_SECTION_PADDING_SECONDS", "1.25"))
DOWNLOAD_VIDEO_SECTIONS = os.getenv("SHORTFORM_DOWNLOAD_VIDEO_SECTIONS", "1") != "0"
CLEANUP_VIDEO_SECTIONS = os.getenv("SHORTFORM_CLEANUP_VIDEO_SECTIONS", "1") != "0"


def get_cookie_browser_candidates():
    return ytdlp_auth.get_cookie_browser_candidates()


def cookie_browser_to_tuple(candidate):
    return ytdlp_auth.cookie_browser_to_tuple(candidate)


def build_ytdl_opts(extra_opts=None, use_cookies=False):
    opts = {**YTDL_COMMON_OPTS}

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(base_dir, "cookies.txt"),
    )
    cookie_browsers = get_cookie_browser_candidates()

    if use_cookies:
        if (
            ytdlp_auth.browser_cookie_fallback_enabled()
            and cookie_browsers
            and ytdlp_auth.browser_cookie_fallback_ready()
        ):
            opts["cookiesfrombrowser"] = cookie_browser_to_tuple(cookie_browsers[0])
        elif os.path.exists(cookies_file):
            opts["cookiefile"] = cookies_file
        elif cookie_browsers:
            opts["cookiesfrombrowser"] = cookie_browser_to_tuple(cookie_browsers[0])

    if os.getenv("SHORTFORM_FORCE_IPV4", "1") == "1":
        opts["source_address"] = "0.0.0.0"

    if extra_opts:
        opts.update(extra_opts)

    return opts


def is_cookie_load_error(error):
    return ytdlp_auth.is_cookie_load_error(error)


def run_ytdlp_with_cookie_fallback(ydl_opts, operation):
    return ytdlp_auth.run_ytdlp_authenticated(ydl_opts, operation)


def run_ytdlp_then_retry_with_cookies(ydl_opts, operation, auth_required=False, reason="YouTube media"):
    return ytdlp_auth.run_ytdlp_with_auth_retry(
        ydl_opts,
        operation,
        auth_required=auth_required,
        reason=reason,
    )


def popularity_cache_dir():
    directory = os.path.join(metadata_path or base_dir, "_popularity")
    os.makedirs(directory, exist_ok=True)
    return directory


def load_or_fetch_popularity_profile(video_url, cleaned_title):
    if not ENABLE_POPULARITY_SCORING or not video_url:
        return {}

    cache_dir = popularity_cache_dir()
    cached = load_cached_popularity_profile(cache_dir, video_url, cleaned_title)
    api_signals_requested = bool(
        ENABLE_YOUTUBE_DATA_API_SIGNALS
        and YOUTUBE_DATA_API_KEY
    )

    if cached is not None:
        fetched_with_comments = bool(cached.get("fetched_with_comments"))
        fetched_with_youtube_data_api = bool(cached.get("fetched_with_youtube_data_api"))
        cached_at = cached.get("fetched_at_unix", 0)
        cache_age_days = (time.time() - float(cached_at or 0)) / 86400 if cached_at else 9999
        comment_signals_satisfied = (
            not FETCH_COMMENT_TIMESTAMP_SIGNALS
            or fetched_with_comments
        )
        api_signals_satisfied = (
            not api_signals_requested
            or fetched_with_youtube_data_api
        )

        if comment_signals_satisfied and api_signals_satisfied and cache_age_days < COMMENT_TIMESTAMP_REFRESH_DAYS:
            return cached

        print(" -> Refreshing popularity profile to include richer comment interaction signals.")

    if cached is not None and not FETCH_COMMENT_TIMESTAMP_SIGNALS:
        return cached

    try:
        extra_opts = {"skip_download": True}

        if FETCH_COMMENT_TIMESTAMP_SIGNALS:
            extra_opts["getcomments"] = True

        info = run_ytdlp_then_retry_with_cookies(
            build_ytdl_opts(extra_opts, use_cookies=True),
            lambda ydl: ydl.extract_info(video_url, download=False),
            auth_required=ytdlp_auth.media_download_auth_required(),
            reason="popularity signal lookup",
        )
        profile = build_popularity_profile_from_info(info or {})
        profile["fetched_with_comments"] = bool(FETCH_COMMENT_TIMESTAMP_SIGNALS)
        profile["fetched_with_youtube_data_api"] = False
        profile["fetched_at_unix"] = time.time()
    except Exception as error:
        print(f" -> Popularity signal lookup unavailable: {error}")
        profile = {
            "video_id": "",
            "title": cleaned_title,
            "duration": 0,
            "heatmap": [],
            "timestamp_markers": [],
            "chapters": [],
            "sources": [],
            "fetched_with_comments": bool(FETCH_COMMENT_TIMESTAMP_SIGNALS),
            "fetched_with_youtube_data_api": False,
            "fetched_at_unix": time.time(),
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

            sampled = (profile.get("youtube_data_api") or {}).get("comment_count_sampled", 0)
            markers = (profile.get("youtube_data_api") or {}).get("comment_timestamp_marker_count", 0)
            print(
                " -> YouTube Data API signals found: "
                f"{sampled} comments sampled, {markers} timestamp markers."
            )
        except Exception as error:
            profile["fetched_with_youtube_data_api"] = False
            profile["youtube_data_api_error"] = str(error)[:300]
            print(f" -> YouTube Data API signal lookup unavailable: {error}")

    save_popularity_profile(cache_dir, video_url, profile, cleaned_title)

    if profile.get("sources"):
        print(f" -> Popularity signals found: {', '.join(profile['sources'])}")
    else:
        print(" -> No public popularity signals found for this source.")

    return profile


# =========================
# Helpers
# =========================

def run_subprocess(cmd, label):
    """
    Runs a subprocess and prints useful FFmpeg errors instead of hiding them.
    """
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


def try_subprocess(cmd, label):
    """
    Runs a subprocess and returns the completed result without raising.
    Used for fast-path commands that have a safe fallback.
    """
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print(f" -> {label} fast path failed; falling back.")
        print(result.stderr[-1200:])

    return result


def get_first_audio_codec(media_path):
    result = subprocess.run(
        [
            FFPROBE_EXE,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
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
        return ""

    return result.stdout.strip().splitlines()[0].lower() if result.stdout.strip() else ""


def get_audio_package_candidates(cleaned_title):
    return [
        os.path.join(audio_path, f"{cleaned_title}{extension}")
        for extension in AUDIO_PACKAGE_EXTENSIONS
    ]


def find_existing_audio_package(cleaned_title):
    existing = [
        filepath
        for filepath in get_audio_package_candidates(cleaned_title)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0
    ]

    if not existing:
        return ""

    return max(existing, key=os.path.getmtime)


def audio_window_manifest_path(audio_filename):
    stem, _extension = os.path.splitext(os.path.abspath(audio_filename))
    return stem + ".windows.json"


def load_audio_window_manifest(audio_filename):
    manifest_path = audio_window_manifest_path(audio_filename)

    if not os.path.exists(manifest_path):
        return {}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}

    windows = payload.get("windows") if isinstance(payload, dict) else None

    if not isinstance(windows, list) or not windows:
        return {}

    if any(not os.path.exists(str(item.get("file") or "")) for item in windows if isinstance(item, dict)):
        return {}

    return payload


def audio_window_file_for(analysis_windows, manifest, index):
    items = manifest.get("windows") if isinstance(manifest, dict) else []

    if index <= 0 or index > len(items or []):
        return ""

    item = items[index - 1]
    path = str(item.get("file") or "") if isinstance(item, dict) else ""
    return path if path and os.path.exists(path) else ""


def remove_empty_or_partial_file(filepath):
    try:
        if os.path.exists(filepath) and os.path.getsize(filepath) <= 0:
            os.remove(filepath)
    except Exception:
        pass


def find_downloaded_file_by_prefix(folder, prefix, extensions):
    if not os.path.isdir(folder):
        return ""

    candidates = []

    for filename in os.listdir(folder):
        stem, extension = os.path.splitext(filename)

        if stem != prefix or extension.lower() not in extensions:
            continue

        filepath = os.path.join(folder, filename)

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            candidates.append(filepath)

    if not candidates:
        return ""

    return max(candidates, key=os.path.getmtime)


def cleanup_download_remnants(folder, prefix):
    if not os.path.isdir(folder):
        return

    for filename in os.listdir(folder):
        if not filename.startswith(f"{prefix}."):
            continue

        filepath = os.path.join(folder, filename)
        lower_name = filename.lower()

        if lower_name.endswith(".part") or ".part-" in lower_name or lower_name.endswith(".ytdl"):
            try:
                os.remove(filepath)
            except OSError:
                pass


def is_supported_youtube_video_url(video_url):
    value = str(video_url or "").strip().lower()
    return (
        "youtube.com/watch?" in value
        or "youtube.com/shorts/" in value
        or "youtu.be/" in value
    )


def clean_title_for_filename(title):
    cleaned = "".join(
        char for char in title
        if char.isalnum() or char in [" ", ".", "_", "-"]
    ).replace(" ", "_")

    # Avoid absurdly long Windows paths
    return cleaned[:140].strip("._-") or "Unknown_Video"


def assert_file_exists(filepath, label):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        raise FileNotFoundError(f"{label} was not created or is empty: {filepath}")


class SkippableVideoError(RuntimeError):
    pass


def bytes_label(value):
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        size = 0.0

    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.2f} GiB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MiB"
    if size >= 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{int(size)} B"


def audio_download_size_guard(cleaned_title):
    def guard(status):
        if not isinstance(status, dict) or status.get("status") != "downloading":
            return

        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        downloaded = status.get("downloaded_bytes") or 0

        try:
            total = int(total or 0)
        except (TypeError, ValueError):
            total = 0

        try:
            downloaded = int(downloaded or 0)
        except (TypeError, ValueError):
            downloaded = 0

        if total > MAX_AUDIO_DOWNLOAD_BYTES:
            raise SkippableVideoError(
                "audio package too large for daily scoring: "
                f"{cleaned_title} estimated {bytes_label(total)} "
                f"(cap {bytes_label(MAX_AUDIO_DOWNLOAD_BYTES)})"
            )

        if downloaded > MAX_AUDIO_DOWNLOAD_BYTES:
            raise SkippableVideoError(
                "audio package exceeded daily scoring cap while downloading: "
                f"{cleaned_title} downloaded {bytes_label(downloaded)} "
                f"(cap {bytes_label(MAX_AUDIO_DOWNLOAD_BYTES)})"
            )

    return guard


def reject_oversized_audio_metadata(info, source_record, cleaned_title):
    if not isinstance(info, dict):
        return

    try:
        duration = float(info.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    if duration > 0 and isinstance(source_record, dict):
        source_record.setdefault("duration_seconds", duration)

    if MAX_SOURCE_DURATION_SECONDS > 0 and duration > MAX_SOURCE_DURATION_SECONDS:
        raise SkippableVideoError(
            "source too long for daily clipping:"
            f"{duration:.0f}s ({cleaned_title})"
        )

    audio_sizes = []
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue

        acodec = str(fmt.get("acodec") or "none").lower()
        vcodec = str(fmt.get("vcodec") or "none").lower()
        if acodec == "none" or vcodec != "none":
            continue

        try:
            size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
        except (TypeError, ValueError):
            size = 0

        if size > 0:
            audio_sizes.append(size)

    if audio_sizes and min(audio_sizes) > MAX_AUDIO_DOWNLOAD_BYTES:
        raise SkippableVideoError(
            "smallest available audio package is too large for daily scoring: "
            f"{cleaned_title} minimum {bytes_label(min(audio_sizes))} "
            f"(cap {bytes_label(MAX_AUDIO_DOWNLOAD_BYTES)})"
        )


def reject_audio_file_duration(audio_filename, source_record, cleaned_title):
    window_manifest = load_audio_window_manifest(audio_filename)
    duration = float(
        window_manifest.get("source_duration_seconds")
        or get_media_duration_seconds(audio_filename)
    )

    if duration > 0 and isinstance(source_record, dict):
        source_record.setdefault("duration_seconds", duration)

    if MAX_SOURCE_DURATION_SECONDS > 0 and duration > MAX_SOURCE_DURATION_SECONDS:
        raise SkippableVideoError(
            "source too long for daily clipping:"
            f"{duration:.0f}s ({cleaned_title})"
        )

    return duration


def is_skippable_video_error_message(message):
    return ytdlp_auth.is_unavailable_video_error(message)


def is_restricted_auth_error_message(message):
    return ytdlp_auth.is_auth_needed_error(message)


def raise_or_skip_download_error(error, video_url):
    if isinstance(error, ytdlp_auth.RestrictedVideoAuthError):
        raise error

    if is_restricted_auth_error_message(error):
        if HALT_ON_RESTRICTED_DOWNLOAD_FAILURE:
            raise ytdlp_auth.RestrictedVideoAuthError(
                f"restricted YouTube auth failed while downloading {video_url}: "
                f"{str(error).splitlines()[0][:300]}"
            ) from error

        raise SkippableVideoError(f"video requires sign-in: {video_url}") from error

    if is_skippable_video_error_message(error):
        raise SkippableVideoError(f"video is unavailable: {video_url}") from error

    raise error


def is_format_selection_error(error):
    return (
        ytdlp_auth.is_format_unavailable_error(error)
        or "format-selection problem" in str(error).lower()
        or "requested media format" in str(error).lower()
    )


def is_network_download_error(error):
    message = str(error).lower()
    network_markers = [
        "connectionreseterror",
        "connection broken",
        "read timed out",
        "timed out",
        "failed to resolve",
        "getaddrinfo failed",
        "temporary failure in name resolution",
        "httpsconnectionpool",
        "unable to download api page",
        "remote host",
        "network is unreachable",
        "download failed",
    ]
    return any(marker in message for marker in network_markers)


# =========================
# Download media
# =========================

def preflight_audio_source_for_download(video_url, cleaned_title, source_record=None):
    duration = source_duration_from_record(source_record)

    if MAX_SOURCE_DURATION_SECONDS > 0 and duration and duration > MAX_SOURCE_DURATION_SECONDS:
        raise SkippableVideoError(
            "source too long for daily clipping:"
            f"{duration:.0f}s ({cleaned_title})"
        )

    if duration or os.getenv("SHORTFORM_AUDIO_PREFLIGHT_METADATA", "1") == "0":
        return

    print(" -> Inspecting source metadata before audio download.")
    ydl_opts_probe = build_ytdl_opts({
        "skip_download": True,
        "ignoreerrors": False,
    }, use_cookies=True)

    try:
        info = run_ytdlp_then_retry_with_cookies(
            ydl_opts_probe,
            lambda ydl: ydl.extract_info(video_url, download=False),
            auth_required=ytdlp_auth.media_download_auth_required(),
            reason="audio scoring metadata preflight",
        )
        reject_oversized_audio_metadata(info or {}, source_record, cleaned_title)
    except SkippableVideoError:
        raise
    except Exception as error:
        raise_or_skip_download_error(error, video_url)


def download_audio_windows_for_scoring(video_url, cleaned_title, source_record=None):
    if os.getenv("SHORTFORM_DOWNLOAD_SCORING_AUDIO_WINDOWS", "1") == "0":
        return ""

    popularity_profile = load_or_fetch_popularity_profile(video_url, cleaned_title)
    duration = float(
        (popularity_profile or {}).get("duration")
        or source_duration_from_record(source_record)
        or 0.0
    )

    if duration <= SIGNAL_TRANSCRIPT_FULL_MAX_SECONDS:
        return ""

    windows = transcript_signal_windows(popularity_profile or {}, duration)

    if not windows:
        return ""

    print(
        "Downloading scoring audio windows only: "
        f"{len(windows)} windows covering "
        f"{sum(end - start for start, end in windows) / 60.0:.1f}m of a {duration / 3600.0:.1f}h source"
    )
    window_root = os.path.join(audio_path, "_scoring_windows", cleaned_title)
    os.makedirs(window_root, exist_ok=True)
    window_items = []

    for index, (window_start, window_end) in enumerate(windows, start=1):
        prefix = f"window_{index:02d}_{int(window_start)}_{int(window_end)}"
        existing = find_downloaded_file_by_prefix(
            window_root,
            prefix,
            set(AUDIO_PACKAGE_EXTENSIONS),
        )

        if not existing:
            output_template = os.path.join(window_root, f"{prefix}.%(ext)s")
            ydl_opts = build_ytdl_opts({
                "format": (
                    f"bestaudio[vcodec=none][abr<={ANALYSIS_AUDIO_MAX_ABR}]/"
                    "bestaudio[vcodec=none]/bestaudio/best"
                ),
                "outtmpl": output_template,
                "download_ranges": download_range_func(None, [(window_start, window_end)]),
                "ignoreerrors": False,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": str(ANALYSIS_AUDIO_MAX_ABR),
                }],
            }, use_cookies=True)

            try:
                run_ytdlp_then_retry_with_cookies(
                    ydl_opts,
                    lambda ydl: ydl.download([video_url]),
                    auth_required=ytdlp_auth.media_download_auth_required(),
                    reason="signal-window audio scoring download",
                )
            except Exception as error:
                if is_restricted_auth_error_message(error) or is_skippable_video_error_message(error):
                    raise_or_skip_download_error(error, video_url)
                print(
                    " -> Window-only audio acquisition failed; "
                    f"falling back to full audio ({str(error).splitlines()[0][:220]})."
                )
                return ""

            existing = find_downloaded_file_by_prefix(
                window_root,
                prefix,
                set(AUDIO_PACKAGE_EXTENSIONS),
            )

        if not existing:
            print(" -> A scoring audio window was not created; falling back to full audio.")
            return ""

        window_items.append({
            "file": os.path.abspath(existing),
            "source_start": float(window_start),
            "source_end": float(window_end),
        })

    combined_audio = os.path.join(audio_path, f"{cleaned_title}.m4a")
    input_args = []
    filters = []
    labels = []
    combined_cursor = 0.0

    for index, item in enumerate(window_items):
        input_args.extend(["-i", item["file"]])
        filters.append(
            f"[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
        )
        labels.append(f"[a{index}]")
        item["combined_start"] = combined_cursor
        combined_cursor += max(0.0, item["source_end"] - item["source_start"])
        item["combined_end"] = combined_cursor

    filters.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[a]")
    run_subprocess([
        FFMPEG_EXE,
        "-y",
        *input_args,
        "-filter_complex", ";".join(filters),
        "-map", "[a]",
        "-c:a", "aac",
        "-b:a", "128k",
        combined_audio,
    ], "Scoring audio window assembly")
    assert_file_exists(combined_audio, "Windowed scoring audio")
    manifest = {
        "version": 1,
        "source_video_url": video_url,
        "source_duration_seconds": duration,
        "combined_duration_seconds": combined_cursor,
        "windows": window_items,
        "created_at": utc_timestamp(),
    }
    write_json_file(audio_window_manifest_path(combined_audio), manifest)

    if isinstance(source_record, dict):
        source_record["duration_seconds"] = duration
        source_record["audio_scope"] = "signal_windows"
        source_record["audio_window_count"] = len(window_items)

    return combined_audio


def download_audio_for_scoring(video_url, cleaned_title, source_record=None):
    existing_audio_filename = find_existing_audio_package(cleaned_title)

    if existing_audio_filename:
        reject_audio_file_duration(existing_audio_filename, source_record, cleaned_title)
        print(f"Reusing existing audio-only package: {os.path.basename(existing_audio_filename)}")
        return existing_audio_filename

    preflight_audio_source_for_download(video_url, cleaned_title, source_record)

    windowed_audio = download_audio_windows_for_scoring(
        video_url,
        cleaned_title,
        source_record=source_record,
    )

    if windowed_audio:
        print(f" -> Window-only audio acquisition ready: {os.path.basename(windowed_audio)}\n")
        return windowed_audio

    print(f"Downloading audio-only package for scoring: {cleaned_title}")
    start_download = time.time()
    output_template = os.path.join(audio_path, f"{cleaned_title}.%(ext)s")
    audio_attempts = [
        {
            "label": "speech-optimized audio",
            "format": (
                f"bestaudio[vcodec=none][abr<={ANALYSIS_AUDIO_MAX_ABR}]/"
                f"bestaudio[vcodec=none][acodec^=mp4a][abr<={ANALYSIS_AUDIO_MAX_ABR}]"
            ),
        },
        {
            "label": "preferred audio",
            "format": (
                "bestaudio[vcodec=none][acodec^=mp4a]/"
                "bestaudio[vcodec=none][ext=m4a]/"
                "bestaudio[vcodec=none]"
            ),
        },
        {
            "label": "broad audio",
            "format": (
                "bestaudio*[vcodec=none]/"
                "bestaudio*[acodec!=none][vcodec=none]/"
                "bestaudio[vcodec=none]"
            ),
            "extract_audio": True,
        },
        {
            "label": "last chance audio-only fallback",
            "format": (
                "worstaudio[vcodec=none]/"
                "worst[acodec!=none][vcodec=none]/"
                "worstaudio/"
                "bestaudio[vcodec=none]"
            ),
            "extract_audio": True,
        },
    ]
    attempt_errors = []

    for attempt in audio_attempts:
        ydl_opts_audio = build_ytdl_opts({
            "format": attempt["format"],
            "outtmpl": output_template,
            "max_filesize": MAX_AUDIO_DOWNLOAD_BYTES,
            "progress_hooks": [audio_download_size_guard(cleaned_title)],
            "ignoreerrors": False,
        }, use_cookies=True)

        if attempt.get("extract_audio"):
            ydl_opts_audio["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }]

        try:
            run_ytdlp_then_retry_with_cookies(
                ydl_opts_audio,
                lambda ydl: ydl.download([video_url]),
                auth_required=ytdlp_auth.media_download_auth_required(),
                reason=f"audio scoring download ({attempt['label']})",
            )
        except Exception as error:
            attempt_errors.append(f"{attempt['label']}: {str(error).splitlines()[0][:260]}")

            if is_format_selection_error(error) and attempt != audio_attempts[-1]:
                cleanup_download_remnants(audio_path, cleaned_title)
                print(f" -> {attempt['label']} format unavailable; trying broader audio acquisition.")
                continue

            raise_or_skip_download_error(error, video_url)

        audio_filename = find_existing_audio_package(cleaned_title)

        if audio_filename:
            reject_audio_file_duration(audio_filename, source_record, cleaned_title)
            print(f" -> Audio-only acquisition took: {time.time() - start_download:.2f} seconds\n")
            return audio_filename

        attempt_errors.append(f"{attempt['label']}: no audio file was created")
        cleanup_download_remnants(audio_path, cleaned_title)

    audio_filename = find_existing_audio_package(cleaned_title)

    if not audio_filename:
        raise RuntimeError(
            f"audio-only download failed: audio file was not created for {video_url}; "
            f"attempts: {' | '.join(attempt_errors[-5:])}"
        )

    reject_audio_file_duration(audio_filename, source_record, cleaned_title)
    print(f" -> Audio-only acquisition took: {time.time() - start_download:.2f} seconds\n")
    return audio_filename


def video_section_prefix(cleaned_title, clip_number, clip):
    start_token = int(max(0, clip.start_time))
    end_token = int(max(start_token + 1, math.ceil(clip.end_time)))
    return f"{cleaned_title}_{clip_number}_section_{start_token}_{end_token}"


def download_video_section(video_url, cleaned_title, clip_number, clip):
    os.makedirs(videos_path, exist_ok=True)
    section_start = max(0.0, float(clip.start_time) - VIDEO_SECTION_PADDING_SECONDS)
    section_end = max(section_start + 1.0, float(clip.end_time) + VIDEO_SECTION_PADDING_SECONDS)
    prefix = video_section_prefix(cleaned_title, clip_number, clip)
    existing = find_downloaded_file_by_prefix(videos_path, prefix, {".mp4", ".mkv", ".webm", ".mov"})

    if existing:
        print(f"Reusing existing selected video section: {os.path.basename(existing)}")
        return existing, section_start

    print(
        "Downloading selected video section only: "
        f"{cleaned_title} {section_start:.1f}s-{section_end:.1f}s"
    )
    output_template = os.path.join(videos_path, f"{prefix}.%(ext)s")
    section_attempts = [
        {
            "label": "adaptive h264/aac mp4 section",
            "format": (
                f"bestvideo[height<={SOURCE_MAX_HEIGHT}][vcodec^=avc1][ext=mp4]+"
                "bestaudio[acodec^=mp4a][ext=m4a]/"
                f"bestvideo[height<={SOURCE_MAX_HEIGHT}][vcodec^=avc1]+"
                "bestaudio[acodec^=mp4a]/"
                f"best[height<={SOURCE_MAX_HEIGHT}][ext=mp4]"
            ),
            "merge_output_format": "mp4",
        },
        {
            "label": "adaptive 1080p-compatible mkv section",
            "format": (
                f"bestvideo[height<={SOURCE_MAX_HEIGHT}]+bestaudio/"
                f"best[height<={SOURCE_MAX_HEIGHT}]/best"
            ),
            "merge_output_format": "mkv",
        },
        {
            "label": "progressive mp4 section",
            "format": (
                f"best[height<={SOURCE_MAX_HEIGHT}][ext=mp4]/"
                f"best[height<={SOURCE_MAX_HEIGHT}]/best"
            ),
        },
    ]
    start_download = time.time()
    attempt_errors = []

    for attempt in section_attempts:
        cleanup_download_remnants(videos_path, prefix)
        print(f" -> Trying {attempt['label']}")
        ydl_opts_section = build_ytdl_opts({
            "format": attempt["format"],
            "outtmpl": output_template,
            "download_ranges": download_range_func(None, [(section_start, section_end)]),
            "ignoreerrors": False,
        }, use_cookies=True)

        if attempt.get("merge_output_format"):
            ydl_opts_section["merge_output_format"] = attempt["merge_output_format"]

        try:
            run_ytdlp_then_retry_with_cookies(
                ydl_opts_section,
                lambda ydl: ydl.download([video_url]),
                auth_required=ytdlp_auth.media_download_auth_required(),
                reason=f"selected video section download ({attempt['label']})",
            )
        except Exception as error:
            if (
                isinstance(error, (SkippableVideoError, ytdlp_auth.RestrictedVideoAuthError))
                or is_restricted_auth_error_message(error)
                or is_skippable_video_error_message(error)
            ):
                raise_or_skip_download_error(error, video_url)

            attempt_errors.append(
                f"{attempt['label']}: {str(error).splitlines()[0][:240]}"
            )
            continue

        section_file = find_downloaded_file_by_prefix(videos_path, prefix, {".mp4", ".mkv", ".webm", ".mov"})

        if section_file:
            print(f" -> Selected video section download took: {time.time() - start_download:.2f} seconds")
            return section_file, section_start

        attempt_errors.append(f"{attempt['label']}: no media file was created")

    cleanup_download_remnants(videos_path, prefix)
    details = "; ".join(attempt_errors[-3:]) if attempt_errors else "no attempt details"
    raise RuntimeError(f"selected video section download failed for {video_url}: {details}")


def download_media(video_url, cleaned_title):
    video_filename = os.path.join(videos_path, f"{cleaned_title}.mp4")

    ydl_opts_combined = build_ytdl_opts({
        "format": (
            f"bestvideo[height<={SOURCE_MAX_HEIGHT}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height<={SOURCE_MAX_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={SOURCE_MAX_HEIGHT}]+bestaudio/"
            f"best[height<={SOURCE_MAX_HEIGHT}]/"
            "best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": video_filename,
        "ignoreerrors": False,
    }, use_cookies=True)

    start_download = time.time()

    if os.path.exists(video_filename) and os.path.getsize(video_filename) > 0:
        print(f"Reusing existing video package: {cleaned_title}.mp4")
    else:
        print(f"Downloading media package: {cleaned_title}.mp4")

        try:
            run_ytdlp_then_retry_with_cookies(
                ydl_opts_combined,
                lambda ydl: ydl.download([video_url]),
                auth_required=ytdlp_auth.media_download_auth_required(),
                reason="source video download",
            )
        except Exception as error:
            raise_or_skip_download_error(error, video_url)

        if os.path.exists(video_filename) and os.path.getsize(video_filename) == 0:
            os.remove(video_filename)

        if not os.path.exists(video_filename) or os.path.getsize(video_filename) <= 0:
            raise RuntimeError(f"download failed: media file was not created for {video_url}")

    assert_file_exists(video_filename, "Downloaded video")

    existing_audio_filename = find_existing_audio_package(cleaned_title)

    if existing_audio_filename:
        print(f"Reusing existing audio package: {os.path.basename(existing_audio_filename)}")
        print(f"Total acquisition time: {time.time() - start_download:.2f} seconds\n")
        return video_filename, existing_audio_filename

    print("Extracting audio locally...")
    a_start = time.time()
    audio_codec = get_first_audio_codec(video_filename)
    copy_extension = AUDIO_STREAM_COPY_EXTENSIONS.get(audio_codec)

    if copy_extension:
        audio_filename = os.path.join(audio_path, f"{cleaned_title}{copy_extension}")
        print(f" -> Stream-copying {audio_codec} audio to {copy_extension} for transcript/scoring.")

        copy_cmd = [
            FFMPEG_EXE,
            "-y",
            "-i", video_filename,
            "-map", "0:a:0",
            "-vn",
            "-c:a", "copy",
        ]

        if copy_extension == ".m4a":
            copy_cmd.extend(["-movflags", "+faststart"])

        copy_cmd.append(audio_filename)

        copy_result = try_subprocess(copy_cmd, "Audio stream copy")

        if copy_result.returncode != 0:
            remove_empty_or_partial_file(audio_filename)
            audio_filename = ""
    else:
        audio_filename = ""

    if not audio_filename:
        audio_filename = os.path.join(audio_path, f"{cleaned_title}.wav")
        print(f" -> Transcoding audio to 16 kHz mono WAV ({audio_codec or 'unknown'} source fallback).")
        run_subprocess([
            FFMPEG_EXE,
            "-y",
            "-i", video_filename,
            "-map", "0:a:0",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            audio_filename,
        ], "Audio extraction")

    assert_file_exists(audio_filename, "Extracted audio")

    print(f" -> Local audio extraction took: {time.time() - a_start:.2f} seconds")
    print(f"Total acquisition time: {time.time() - start_download:.2f} seconds\n")

    return video_filename, audio_filename


# =========================
# OpenCV / YOLO reframing
# =========================

def load_face_cascades():
    cascade_dir = cv2.data.haarcascades
    cascade_files = [
        "haarcascade_frontalface_default.xml",
        "haarcascade_profileface.xml",
    ]
    cascades = []

    for cascade_file in cascade_files:
        cascade_path = os.path.join(cascade_dir, cascade_file)
        cascade = cv2.CascadeClassifier(cascade_path)

        if not cascade.empty():
            cascades.append(cascade)

    return cascades


def detect_faces(frame, face_cascades):
    if not face_cascades:
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    frame_width = gray.shape[1]
    faces = []

    for cascade in face_cascades:
        detections = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in detections:
            faces.append({
                "x": float(x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "center_x": float(x + w / 2),
                "area": float(w * h),
            })

        flipped = cv2.flip(gray, 1)
        flipped_detections = cascade.detectMultiScale(
            flipped,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in flipped_detections:
            real_x = frame_width - x - w
            faces.append({
                "x": float(real_x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "center_x": float(real_x + w / 2),
                "area": float(w * h),
            })

    deduped_faces = []

    for face in sorted(faces, key=lambda item: item["area"], reverse=True):
        duplicate = any(
            abs(face["center_x"] - existing["center_x"]) < max(face["w"], existing["w"]) * 0.35
            and abs(face["y"] - existing["y"]) < max(face["h"], existing["h"]) * 0.35
            for existing in deduped_faces
        )

        if not duplicate:
            deduped_faces.append(face)

    return deduped_faces


_MEDIAPIPE_FACE_DETECTOR = None


def mediapipe_face_detector():
    global _MEDIAPIPE_FACE_DETECTOR

    if mp is None or not hasattr(mp, "solutions"):
        return None

    if _MEDIAPIPE_FACE_DETECTOR is None:
        _MEDIAPIPE_FACE_DETECTOR = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=MEDIAPIPE_FACE_CONFIDENCE,
        )

    return _MEDIAPIPE_FACE_DETECTOR


def detect_mediapipe_faces(frame):
    detector = mediapipe_face_detector()

    if detector is None or frame is None:
        return []

    frame_height, frame_width = frame.shape[:2]

    try:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = detector.process(rgb)
    except Exception:
        return []

    faces = []

    for detection in getattr(results, "detections", []) or []:
        box = detection.location_data.relative_bounding_box
        x = max(0.0, float(box.xmin) * frame_width)
        y = max(0.0, float(box.ymin) * frame_height)
        w = min(float(box.width) * frame_width, frame_width - x)
        h = min(float(box.height) * frame_height, frame_height - y)

        if w <= 1 or h <= 1:
            continue

        score = 0.0

        if detection.score:
            score = float(detection.score[0])

        faces.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "center_x": float(x + w / 2),
            "area": float(w * h),
            "source": "mediapipe",
            "detector_confidence": score,
        })

    return faces


def face_iou(left, right):
    left_x2 = float(left["x"] + left["w"])
    left_y2 = float(left["y"] + left["h"])
    right_x2 = float(right["x"] + right["w"])
    right_y2 = float(right["y"] + right["h"])
    inter_x1 = max(float(left["x"]), float(right["x"]))
    inter_y1 = max(float(left["y"]), float(right["y"]))
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    union = float(left["area"]) + float(right["area"]) - inter_area
    return inter_area / max(1.0, union)


def face_center_close(left, right):
    dx = abs(float(left["center_x"]) - float(right["center_x"]))
    left_center_y = float(left["y"] + left["h"] / 2)
    right_center_y = float(right["y"] + right["h"] / 2)
    dy = abs(left_center_y - right_center_y)
    return (
        dx < max(float(left["w"]), float(right["w"])) * 0.62
        and dy < max(float(left["h"]), float(right["h"])) * 0.62
    )


def is_plausible_interview_face(face, frame_width, frame_height):
    aspect_ratio = face["w"] / max(1.0, face["h"])
    center_y = face["y"] + face["h"] / 2
    relative_height = face["h"] / max(1.0, frame_height)

    if aspect_ratio < 0.62 or aspect_ratio > 1.55:
        return False

    if relative_height < 0.055 or relative_height > 0.42:
        return False

    # Hands/notebooks often false-positive lower in the frame. Interview faces
    # should usually live in the upper/middle portion after the 1920px resize.
    if center_y > frame_height * 0.70:
        return False

    if face["center_x"] < frame_width * 0.04 or face["center_x"] > frame_width * 0.96:
        return False

    return True


def compute_frame_visual_features(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    scale = min(1.0, 640 / max(1, max(h, w)))
    analysis_gray = cv2.resize(
        gray,
        (max(1, int(w * scale)), max(1, int(h * scale))),
        interpolation=cv2.INTER_AREA,
    ) if scale < 1.0 else gray
    mean_luma = float(np.mean(analysis_gray))
    contrast = float(np.std(analysis_gray))
    laplacian_var = float(cv2.Laplacian(analysis_gray, cv2.CV_64F).var())
    edges = cv2.Canny(analysis_gray, 50, 150)
    edge_density = float(np.count_nonzero(edges) / max(1, edges.size))

    return {
        "mean_luma": mean_luma,
        "contrast": contrast,
        "laplacian_var": laplacian_var,
        "edge_density": edge_density,
        "is_black": mean_luma < 8.0,
        "is_low_information": (
            mean_luma < 18.0
            or contrast < 9.0
            or (edge_density < 0.010 and laplacian_var < 18.0)
        ),
        "is_blank_background": (
            (mean_luma < 26.0 and contrast < 12.0 and edge_density < 0.014)
            or (contrast < 14.0 and edge_density < 0.010)
            or (laplacian_var < 18.0 and edge_density < 0.012)
        ),
    }


def estimate_skin_tone_ratio(frame):
    if frame is None or frame.size <= 0:
        return 0.0

    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    y_channel, cr_channel, cb_channel = cv2.split(ycrcb)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    _, saturation, value = cv2.split(hsv)
    skin_mask = (
        (y_channel > 28)
        & (cr_channel >= 118)
        & (cr_channel <= 190)
        & (cb_channel >= 58)
        & (cb_channel <= 158)
        & (saturation >= 12)
        & (value >= 32)
    )

    return float(np.count_nonzero(skin_mask) / max(1, skin_mask.size))


RECENT_BLOCKED_SKIP_PATTERNS = (
    "premieres in",
    "premiere will begin",
    "this live event will begin",
    "video unavailable",
    "private video",
    "has been removed",
    "not available",
)


def utc_timestamp_age_seconds(timestamp):
    if not timestamp:
        return None

    try:
        parsed = time.strptime(str(timestamp), "%Y-%m-%dT%H:%M:%SZ")
        return max(0.0, time.time() - calendar.timegm(parsed))
    except (TypeError, ValueError, OverflowError):
        return None


def recent_blocked_skip_reason(record):
    if not isinstance(record, dict):
        return ""

    if str(record.get("last_clip_generation_error_type") or "").lower() != "blocked":
        return ""

    message = str(record.get("last_clip_generation_error_message") or "").strip()
    lower_message = message.lower()

    if not any(pattern in lower_message for pattern in RECENT_BLOCKED_SKIP_PATTERNS):
        return ""

    age_seconds = utc_timestamp_age_seconds(record.get("last_clip_generation_attempt_at"))

    if age_seconds is not None and age_seconds <= RECENT_BLOCKED_RETRY_SECONDS:
        return message[:180] or "recent blocked/unavailable source"

    return ""


def score_face_roi_plausibility(frame, face):
    h, w = frame.shape[:2]
    x1 = max(0, int(face["x"] - face["w"] * 0.12))
    y1 = max(0, int(face["y"] - face["h"] * 0.12))
    x2 = min(w, int(face["x"] + face["w"] * 1.12))
    y2 = min(h, int(face["y"] + face["h"] * 1.12))

    if x2 <= x1 or y2 <= y1:
        return 0.0

    roi = frame[y1:y2, x1:x2]

    if roi.size <= 0:
        return 0.0

    features = compute_frame_visual_features(roi)
    skin_tone_ratio = estimate_skin_tone_ratio(roi)
    aspect_ratio = face["w"] / max(1.0, face["h"])
    relative_height = face["h"] / max(1.0, h)
    center_y = (face["y"] + face["h"] / 2) / max(1.0, h)

    aspect_score = 1.0 - min(1.0, abs(aspect_ratio - 0.90) / 0.55)
    size_score = 1.0 - min(1.0, abs(relative_height - 0.16) / 0.18)
    vertical_score = 1.0 if center_y <= 0.56 else max(0.0, 1.0 - ((center_y - 0.56) / 0.18))
    texture_score = (
        clamp01((features["contrast"] - 8.0) / 24.0) * 0.40
        + clamp01((features["edge_density"] - 0.008) / 0.065) * 0.32
        + clamp01((features["laplacian_var"] - 10.0) / 95.0) * 0.28
    )
    skin_score = clamp01((skin_tone_ratio - 0.012) / 0.16)

    if features["is_black"] or features["contrast"] < 5.0:
        texture_score *= 0.25

    if skin_tone_ratio < 0.003:
        return 0.0

    if skin_tone_ratio < 0.007 and relative_height < 0.24:
        texture_score *= 0.28
        vertical_score *= 0.70

    if skin_tone_ratio < 0.010 and features["edge_density"] < 0.045:
        texture_score *= 0.62

    return clamp01(
        aspect_score * 0.26
        + size_score * 0.22
        + vertical_score * 0.18
        + texture_score * 0.26
        + skin_score * 0.08
    )


def filter_plausible_interview_faces(frame, face_cascades, min_plausibility=0.34):
    faces = []
    frame_height, frame_width = frame.shape[:2]
    mediapipe_faces = detect_mediapipe_faces(frame)
    raw_faces = detect_faces(frame, face_cascades)

    if REQUIRE_MEDIAPIPE_FACE_VERIFY and mediapipe_face_detector() is not None:
        if not mediapipe_faces:
            return []

        raw_faces = [
            face
            for face in raw_faces
            if any(face_iou(face, mp_face) >= 0.06 or face_center_close(face, mp_face) for mp_face in mediapipe_faces)
        ]

    combined_faces = raw_faces + mediapipe_faces
    deduped_combined = []

    for face in sorted(combined_faces, key=lambda item: item["area"], reverse=True):
        duplicate = any(
            face_iou(face, existing) >= 0.18 or face_center_close(face, existing)
            for existing in deduped_combined
        )

        if not duplicate:
            deduped_combined.append(face)

    for face in deduped_combined:
        if not is_plausible_interview_face(face, frame_width=frame_width, frame_height=frame_height):
            continue

        plausibility = score_face_roi_plausibility(frame, face)
        detector_confidence = float(face.get("detector_confidence") or 0.0)

        if face.get("source") == "mediapipe":
            plausibility = max(plausibility, min(0.92, 0.54 + detector_confidence * 0.34))

        if plausibility < min_plausibility:
            continue

        enriched = dict(face)
        enriched["plausibility"] = float(plausibility)
        center_y_ratio = (face["y"] + face["h"] / 2) / max(1.0, frame_height)
        height_ratio = face["h"] / max(1.0, frame_height)
        vertical_score = 1.0 - min(1.0, abs(center_y_ratio - 0.43) / 0.34)
        size_score = 1.0 - min(1.0, abs(height_ratio - 0.16) / 0.20)

        if center_y_ratio < 0.24 and height_ratio < 0.23:
            vertical_score *= 0.35

        if center_y_ratio > 0.72:
            vertical_score *= 0.45

        enriched["speaker_zone_score"] = clamp01(
            plausibility * 0.30
            + vertical_score * 0.52
            + size_score * 0.18
        )
        faces.append(enriched)

    if faces:
        best_speaker_zone = max(float(face.get("speaker_zone_score") or 0.0) for face in faces)

        if best_speaker_zone >= 0.56:
            faces = [
                face
                for face in faces
                if float(face.get("speaker_zone_score") or 0.0) >= max(0.28, best_speaker_zone - 0.44)
            ]

    return faces


def select_best_interview_face(faces, preferred_center_x=None):
    if not faces:
        return None

    def face_key(face):
        center_penalty = 0.0

        if preferred_center_x is not None:
            center_penalty = abs(float(face.get("scaled_center_x", face.get("center_x", 0.0))) - preferred_center_x)

        return (
            float(face.get("speaker_zone_score") or 0.0),
            float(face.get("plausibility") or 0.0),
            float(face.get("motion_score") or 0.0),
            -center_penalty,
            float(face.get("area") or 0.0),
        )

    return max(faces, key=face_key)


def classify_frame_visual_state(frame, faces=None):
    features = compute_frame_visual_features(frame)
    has_face = bool(faces)
    dead_visual = (
        features["is_black"]
        or features["is_low_information"]
        or (features["is_blank_background"] and not has_face)
    )

    return {
        **features,
        "has_face": has_face,
        "is_dead_visual": bool(dead_visual),
        "is_alive_visual": not dead_visual,
    }


def score_face_motion(current_gray, previous_gray, face):
    if previous_gray is None or current_gray is None:
        return 0.0

    height, width = current_gray.shape[:2]
    x1 = max(0, int(face["x"] + face["w"] * 0.18))
    x2 = min(width, int(face["x"] + face["w"] * 0.82))
    y1 = max(0, int(face["y"] + face["h"] * 0.48))
    y2 = min(height, int(face["y"] + face["h"] * 0.92))

    if x2 <= x1 or y2 <= y1:
        return 0.0

    current_roi = current_gray[y1:y2, x1:x2]
    previous_roi = previous_gray[y1:y2, x1:x2]

    if current_roi.shape != previous_roi.shape or current_roi.size == 0:
        return 0.0

    return float(np.mean(cv2.absdiff(current_roi, previous_roi)))


def clamp_center_x(center_x, resized_w, output_width):
    if resized_w >= output_width:
        return max(output_width / 2, min(center_x, resized_w - output_width / 2))

    return resized_w / 2


def estimate_stable_face_target(temp_subclip, face_cascades=None, max_samples=None):
    max_samples = max_samples or FACE_TARGET_SAMPLE_COUNT
    cap = cv2.VideoCapture(temp_subclip)
    output_height = 1920
    output_width = 1080
    result = {
        "center_x": None,
        "sampled_frames": 0,
        "face_samples": 0,
        "cluster_count": 0,
        "confidence": 0.0,
    }

    if not cap.isOpened():
        return result

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if frame_count <= 0:
        cap.release()
        return result

    face_cascades = face_cascades or load_face_cascades()
    face_observations = []
    sample_indices = np.linspace(
        0,
        max(0, frame_count - 1),
        num=min(max_samples, frame_count),
        dtype=int,
    )

    for frame_index in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        result["sampled_frames"] += 1
        h, w = frame.shape[:2]

        if h <= 0 or w <= 0:
            continue

        scale = output_height / h
        resized_w = max(1, int(w * scale))
        frame_resized = cv2.resize(
            frame,
            (resized_w, output_height),
            interpolation=cv2.INTER_AREA,
        )
        detection_scale = min(1.0, 640 / output_height)
        detection_w = max(1, int(resized_w * detection_scale))
        detection_frame = cv2.resize(
            frame_resized,
            (detection_w, int(output_height * detection_scale)),
            interpolation=cv2.INTER_AREA,
        )
        faces = filter_plausible_interview_faces(detection_frame, face_cascades)

        if not faces:
            continue

        result["face_samples"] += 1

        for face in faces:
            if float(face.get("speaker_zone_score") or 0.0) < 0.22:
                continue

            face_observations.append({
                "center_x": float(face["center_x"] / detection_scale),
                "area": float(face["area"]) * (0.35 + float(face.get("speaker_zone_score") or 0.0)),
            })

    cap.release()

    if not face_observations:
        return result

    observations = sorted(face_observations, key=lambda item: item["center_x"])
    cluster_width = output_width * 0.24
    clusters = []

    for observation in observations:
        if not clusters or abs(observation["center_x"] - clusters[-1]["center_x"]) > cluster_width:
            clusters.append({
                "center_x": observation["center_x"],
                "count": 1,
                "area_sum": observation["area"],
            })
            continue

        cluster = clusters[-1]
        cluster["center_x"] = (
            cluster["center_x"] * cluster["area_sum"]
            + observation["center_x"] * observation["area"]
        ) / max(1.0, cluster["area_sum"] + observation["area"])
        cluster["area_sum"] += observation["area"]
        cluster["count"] += 1

    best_cluster = max(
        clusters,
        key=lambda item: (item["count"], item["area_sum"]),
    )
    result["center_x"] = float(best_cluster["center_x"])
    result["cluster_count"] = int(best_cluster["count"])
    result["confidence"] = clamp01(
        (best_cluster["count"] / max(1, result["sampled_frames"])) * 1.15
    )
    return result


def estimate_group_face_target(temp_subclip, face_cascades=None, max_samples=None):
    max_samples = max_samples or FACE_TARGET_SAMPLE_COUNT
    cap = cv2.VideoCapture(temp_subclip)
    output_height = 1920
    output_width = 1080
    result = {
        "center_x": None,
        "sampled_frames": 0,
        "face_samples": 0,
        "cluster_count": 0,
        "selected_cluster_count": 0,
        "selected_span_px": 0.0,
        "confidence": 0.0,
    }

    if not cap.isOpened():
        return result

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if frame_count <= 0:
        cap.release()
        return result

    face_cascades = face_cascades or load_face_cascades()
    group_observations = []
    sample_indices = np.linspace(
        0,
        max(0, frame_count - 1),
        num=min(max_samples, frame_count),
        dtype=int,
    )

    for frame_index in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        result["sampled_frames"] += 1
        h, w = frame.shape[:2]

        if h <= 0 or w <= 0:
            continue

        scale = output_height / h
        resized_w = max(1, int(w * scale))
        frame_resized = cv2.resize(
            frame,
            (resized_w, output_height),
            interpolation=cv2.INTER_AREA,
        )
        detection_scale = min(1.0, 640 / output_height)
        detection_w = max(1, int(resized_w * detection_scale))
        detection_frame = cv2.resize(
            frame_resized,
            (detection_w, int(output_height * detection_scale)),
            interpolation=cv2.INTER_AREA,
        )
        faces = filter_plausible_interview_faces(detection_frame, face_cascades)

        if len(faces) < 2:
            if faces:
                result["face_samples"] += 1
            continue

        result["face_samples"] += 1

        speaker_faces = [
            face
            for face in faces
            if float(face.get("speaker_zone_score") or 0.0) >= 0.26
        ] or faces
        largest_faces = sorted(
            speaker_faces,
            key=lambda item: (
                float(item.get("speaker_zone_score") or 0.0),
                float(item.get("area") or 0.0),
            ),
            reverse=True,
        )[:3]
        centers = sorted(float(face["center_x"] / detection_scale) for face in largest_faces)
        left_center = centers[0]
        right_center = centers[-1]
        span = right_center - left_center

        if span < output_width * 0.26 or span > output_width * 1.05:
            continue

        group_observations.append({
            "center_x": float((left_center + right_center) / 2),
            "span": float(span),
            "count": len(largest_faces),
        })

    cap.release()

    if not group_observations:
        return result

    centers = np.asarray([item["center_x"] for item in group_observations], dtype=np.float32)
    spans = np.asarray([item["span"] for item in group_observations], dtype=np.float32)
    result["center_x"] = float(np.median(centers))
    result["cluster_count"] = len(group_observations)
    result["selected_cluster_count"] = int(round(float(np.mean([item["count"] for item in group_observations]))))
    result["selected_span_px"] = float(np.median(spans))
    result["confidence"] = clamp01(
        (len(group_observations) / max(1, result["sampled_frames"])) * 1.35
    )
    return result


def select_dual_speaker_pair(faces, output_width):
    if len(faces) < 2:
        return None

    candidates = []

    for face in faces:
        if float(face.get("speaker_zone_score") or 0.0) < 0.34:
            continue

        if float(face.get("plausibility") or 0.0) < 0.42:
            continue

        candidates.append(face)

    if len(candidates) < 2:
        return None

    best_pair = None
    best_score = -1.0

    for left_index, left_face in enumerate(candidates):
        for right_face in candidates[left_index + 1:]:
            left_center = float(left_face.get("scaled_center_x", left_face.get("center_x", 0.0)))
            right_center = float(right_face.get("scaled_center_x", right_face.get("center_x", 0.0)))
            separation = abs(right_center - left_center)

            if separation < output_width * 0.30:
                continue

            speaker_score = (
                float(left_face.get("speaker_zone_score") or 0.0)
                + float(right_face.get("speaker_zone_score") or 0.0)
            )
            plausibility_score = (
                float(left_face.get("plausibility") or 0.0)
                + float(right_face.get("plausibility") or 0.0)
            )
            motion_score = (
                float(left_face.get("motion_score") or 0.0)
                + float(right_face.get("motion_score") or 0.0)
            )
            separation_score = min(1.0, separation / max(1.0, output_width * 0.78))
            score = speaker_score * 1.35 + plausibility_score * 0.60 + motion_score * 0.08 + separation_score

            if score > best_score:
                ordered = sorted([left_face, right_face], key=lambda item: float(item.get("scaled_center_x", item.get("center_x", 0.0))))
                best_pair = ordered
                best_score = score

    return best_pair


def crop_resized_region(frame_resized, center_x, center_y, crop_width, crop_height):
    source_h, source_w = frame_resized.shape[:2]
    crop_width = min(int(crop_width), source_w)
    crop_height = min(int(crop_height), source_h)
    center_x = float(center_x)
    center_y = float(center_y)
    x1 = int(round(center_x - crop_width / 2))
    y1 = int(round(center_y - crop_height * 0.42))
    x1 = max(0, min(x1, max(0, source_w - crop_width)))
    y1 = max(0, min(y1, max(0, source_h - crop_height)))
    return frame_resized[y1:y1 + crop_height, x1:x1 + crop_width]


def render_dual_speaker_stack_frame(frame_resized, pair, output_width=1080, output_height=1920):
    pane_height = output_height // 2
    pane_width = output_width
    source_h, source_w = frame_resized.shape[:2]
    crop_width = min(source_w, max(pane_width, int(pane_height * 1.35)))
    crop_height = min(source_h, max(pane_height, int(crop_width * pane_height / pane_width)))
    panes = []

    for face in pair[:2]:
        center_x = float(face.get("scaled_center_x", face.get("center_x", source_w / 2)))
        center_y = float(face.get("scaled_center_y", face.get("center_y", source_h * 0.42)))
        region = crop_resized_region(frame_resized, center_x, center_y, crop_width, crop_height)

        if region is None or region.size == 0:
            return None

        panes.append(cv2.resize(region, (pane_width, pane_height), interpolation=cv2.INTER_AREA))

    stacked = np.vstack(panes)
    cv2.line(stacked, (0, pane_height), (output_width, pane_height), (255, 244, 184), 4)
    return stacked


def smart_crop_to_shorts(temp_subclip, temp_tracked_avi, model, face_cascades=None, strategy="face_locked"):
    """
    Converts a horizontal clip into 1080x1920 vertical format with a restrained
    face-first virtual camera. Interview footage should stay centered around
    the speaker's face, with YOLO person tracking only used as a fallback.

    Uses AVI/MJPG as an intermediate because OpenCV's mp4 writing can crash
    or silently fail on Windows depending on codec availability.
    """

    if strategy not in {"face_locked", "stable_face_lock", "group_face_lock", "center_safe", "dual_speaker_stack"}:
        raise ValueError(f"Unknown crop strategy: {strategy}")

    cap = cv2.VideoCapture(temp_subclip)

    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open subclip: {temp_subclip}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or np.isnan(fps) or fps <= 0:
        fps = 24

    source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    use_native_intermediate = (
        os.getenv("SHORTFORM_NATIVE_CROP_INTERMEDIATE", "1") != "0"
        and source_width > 0
        and source_height > 0
        and source_width / max(1, source_height) >= 9 / 16
    )

    if use_native_intermediate:
        output_height = max(2, min(1920, source_height))
        output_width = max(2, int(round(output_height * 9 / 16)))
        output_width -= output_width % 2
        output_height -= output_height % 2
    else:
        output_width = 1080
        output_height = 1920

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    out = cv2.VideoWriter(
        temp_tracked_avi,
        fourcc,
        fps,
        (output_width, output_height),
    )

    if not out.isOpened():
        cap.release()
        raise RuntimeError(f"OpenCV could not create output video: {temp_tracked_avi}")

    camera_center_x = None
    locked_speaker_center_x = None
    pending_speaker_center_x = None
    pending_speaker_hits = 0
    offcenter_hits = 0
    fallback_person_center_x = None
    source_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    source_duration = (source_frame_count / fps) if source_frame_count > 0 and fps > 0 else 0.0
    crop_timeout_seconds = max(
        45.0,
        min(
            MAX_CROP_WALL_SECONDS,
            (source_duration / 60.0) * MAX_CROP_SECONDS_PER_MINUTE,
        ),
    )
    max_processed_frames = None
    if source_frame_count > 0:
        max_processed_frames = max(
            1,
            int(math.ceil(source_frame_count * MAX_CROP_FRAME_MULTIPLIER)),
        )

    frame_count = 0
    detection_checks = 0
    face_detection_hits = 0
    person_detection_hits = 0
    target_switches = 0
    speaker_switches = 0
    offcenter_reframes = 0
    previous_detected_source = None
    previous_detection_gray = None
    camera_positions = []
    dual_speaker_pair = None
    dual_pair_age_frames = 0
    dual_stack_frames = 0
    dual_stack_fallback_frames = 0
    dual_stack_detection_hits = 0

    face_cascades = face_cascades or load_face_cascades()
    stable_face_target = None
    group_face_target = None

    detection_interval_seconds = 0.35
    skip_frames = max(1, int(round(fps * detection_interval_seconds)))
    detection_max_height = 640
    min_person_confidence = 0.35

    # Interview framing: hold a locked shot, then switch quickly when needed.
    material_offcenter_px = int(output_width * 0.24)
    fallback_dead_zone_px = int(output_width * 0.28)
    speaker_match_px = int(output_width * 0.26)
    speaker_switch_px = int(output_width * 0.32)
    switch_min_hits = 2
    offcenter_min_hits = 4
    motion_switch_margin = 3.0

    if strategy == "stable_face_lock":
        stable_face_target = estimate_stable_face_target(
            temp_subclip,
            face_cascades=face_cascades,
        )
        if stable_face_target.get("center_x") is not None and output_height != 1920:
            stable_face_target["center_x"] *= output_height / 1920.0
        detection_checks = int(stable_face_target.get("sampled_frames", 0) or 0)
        face_detection_hits = int(stable_face_target.get("face_samples", 0) or 0)
    elif strategy == "group_face_lock":
        group_face_target = estimate_group_face_target(
            temp_subclip,
            face_cascades=face_cascades,
        )
        if group_face_target.get("center_x") is not None and output_height != 1920:
            coordinate_scale = output_height / 1920.0
            group_face_target["center_x"] *= coordinate_scale
            group_face_target["selected_span_px"] = float(
                group_face_target.get("selected_span_px") or 0.0
            ) * coordinate_scale
        detection_checks = int(group_face_target.get("sampled_frames", 0) or 0)
        face_detection_hits = int(group_face_target.get("face_samples", 0) or 0)

    written_frames = 0
    crop_started_at = time.time()

    try:
        while True:
            if time.time() - crop_started_at > crop_timeout_seconds:
                raise TimeoutError(
                    f"{strategy} smart crop exceeded {crop_timeout_seconds:.1f}s "
                    f"for {source_duration:.1f}s clip"
                )
            if max_processed_frames is not None and frame_count > max_processed_frames:
                raise TimeoutError(
                    f"{strategy} smart crop processed too many frames "
                    f"({frame_count}>{max_processed_frames})"
                )

            ret, frame = cap.read()

            if not ret or frame is None:
                break

            h, w = frame.shape[:2]
            if h <= 0 or w <= 0:
                continue

            # Resize by height first so the frame is always 1920px tall
            scale = output_height / h
            resized_w = max(1, int(w * scale))

            frame_resized = cv2.resize(
                frame,
                (resized_w, output_height),
                interpolation=cv2.INTER_AREA,
            )

            requested_center_x = None
            detected_source = None
            force_recenter = False

            if camera_center_x is None:
                camera_center_x = resized_w / 2

            if strategy == "stable_face_lock" and stable_face_target and stable_face_target.get("center_x"):
                requested_center_x = float(stable_face_target["center_x"])
                detected_source = "stable_face"
                force_recenter = frame_count == 0
            elif (
                strategy == "group_face_lock"
                and group_face_target
                and group_face_target.get("center_x")
                and float(group_face_target.get("confidence") or 0.0) >= GROUP_FACE_CONFIDENCE_THRESHOLD
            ):
                requested_center_x = float(group_face_target["center_x"])
                detected_source = "group_face"
                force_recenter = frame_count == 0

            if (
                strategy == "dual_speaker_stack"
                and resized_w >= output_width
                and frame_count % skip_frames == 0
            ):
                detection_checks += 1
                detection_scale = min(1.0, detection_max_height / output_height)
                detection_w = max(1, int(resized_w * detection_scale))

                detection_frame = cv2.resize(
                    frame_resized,
                    (detection_w, int(output_height * detection_scale)),
                    interpolation=cv2.INTER_AREA,
                ) if detection_scale < 1.0 else frame_resized
                detection_gray = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2GRAY)
                faces = filter_plausible_interview_faces(detection_frame, face_cascades)

                for face in faces:
                    face["motion_score"] = score_face_motion(
                        detection_gray,
                        previous_detection_gray,
                        face,
                    )
                    face["scaled_center_x"] = face["center_x"] / detection_scale
                    face["scaled_center_y"] = (face["y"] + face["h"] / 2) / detection_scale

                pair = select_dual_speaker_pair(faces, output_width)

                if pair:
                    face_detection_hits += len(faces)
                    dual_stack_detection_hits += 1
                    dual_speaker_pair = pair
                    dual_pair_age_frames = 0
                else:
                    dual_speaker_pair = None
                    dual_pair_age_frames = 0

                previous_detection_gray = detection_gray

            if (
                strategy == "face_locked"
                and resized_w >= output_width
                and frame_count % skip_frames == 0
            ):
                detection_checks += 1
                detection_scale = min(1.0, detection_max_height / output_height)
                detection_w = max(1, int(resized_w * detection_scale))

                if detection_scale < 1.0:
                    detection_frame = cv2.resize(
                        frame_resized,
                        (detection_w, int(output_height * detection_scale)),
                        interpolation=cv2.INTER_AREA,
                    )
                else:
                    detection_frame = frame_resized

                detection_gray = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2GRAY)
                faces = filter_plausible_interview_faces(detection_frame, face_cascades)

                if faces:
                    face_detection_hits += 1

                    for face in faces:
                        face["motion_score"] = score_face_motion(
                            detection_gray,
                            previous_detection_gray,
                            face,
                        )
                        face["scaled_center_x"] = face["center_x"] / detection_scale

                    if len(faces) == 1:
                        selected_face = faces[0]
                    else:
                        if locked_speaker_center_x is not None:
                            current_face = min(
                                faces,
                                key=lambda item: abs(item["scaled_center_x"] - locked_speaker_center_x),
                            )
                        else:
                            current_face = None

                        motion_sorted = sorted(
                            faces,
                            key=lambda item: (
                                item["motion_score"],
                                float(item.get("speaker_zone_score") or 0.0),
                                float(item.get("plausibility") or 0.0),
                                item["area"],
                            ),
                            reverse=True,
                        )
                        selected_face = motion_sorted[0] or select_best_interview_face(faces)

                        if current_face is not None:
                            current_motion = current_face["motion_score"]
                            selected_motion = selected_face["motion_score"]
                            selected_is_different_speaker = (
                                abs(selected_face["scaled_center_x"] - locked_speaker_center_x)
                                > speaker_switch_px
                            )

                            if (
                                not selected_is_different_speaker
                                or selected_motion < current_motion + motion_switch_margin
                            ):
                                selected_face = current_face

                    selected_center_x = selected_face["scaled_center_x"]

                    if locked_speaker_center_x is None:
                        locked_speaker_center_x = selected_center_x
                        requested_center_x = selected_center_x
                        detected_source = "face"
                        force_recenter = True
                    else:
                        speaker_delta = abs(selected_center_x - locked_speaker_center_x)

                        if speaker_delta > speaker_switch_px and len(faces) > 1:
                            if (
                                pending_speaker_center_x is not None
                                and abs(selected_center_x - pending_speaker_center_x) <= speaker_match_px
                            ):
                                pending_speaker_hits += 1
                                pending_speaker_center_x = (
                                    pending_speaker_center_x * 0.55
                                    + selected_center_x * 0.45
                                )
                            else:
                                pending_speaker_center_x = selected_center_x
                                pending_speaker_hits = 1

                            if pending_speaker_hits >= switch_min_hits:
                                locked_speaker_center_x = pending_speaker_center_x
                                requested_center_x = locked_speaker_center_x
                                detected_source = "face"
                                force_recenter = True
                                target_switches += 1
                                speaker_switches += 1
                                pending_speaker_center_x = None
                                pending_speaker_hits = 0
                        else:
                            pending_speaker_center_x = None
                            pending_speaker_hits = 0
                            face_offset = abs(selected_center_x - camera_center_x)

                            if face_offset > material_offcenter_px:
                                offcenter_hits += 1
                            else:
                                offcenter_hits = 0

                            if offcenter_hits >= offcenter_min_hits:
                                locked_speaker_center_x = selected_center_x
                                requested_center_x = locked_speaker_center_x
                                detected_source = "face"
                                force_recenter = True
                                offcenter_reframes += 1
                                offcenter_hits = 0

                    previous_detection_gray = detection_gray

                elif ENABLE_PERSON_FALLBACK and locked_speaker_center_x is None and model is not None:
                    results = model.predict(
                        detection_frame,
                        verbose=False,
                        conf=min_person_confidence,
                    )

                    largest_area = 0
                    largest_box = None

                    for result in results:
                        if result.boxes is None:
                            continue

                        for box in result.boxes:
                            cls_id = int(box.cls.item())

                            # COCO class 0 = person
                            if cls_id == 0:
                                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                                confidence = float(box.conf.item()) if box.conf is not None else 0.0

                                if confidence < min_person_confidence:
                                    continue

                                box_width = max(0, x2 - x1)
                                box_height = max(0, y2 - y1)
                                area = box_width * box_height

                                if area > largest_area:
                                    largest_area = area
                                    largest_box = [x1, y1, x2, y2]

                    if largest_box is not None:
                        person_detection_hits += 1
                        raw_person_center_x = (
                            (largest_box[0] + largest_box[2]) / 2
                        ) / detection_scale

                        if fallback_person_center_x is None:
                            fallback_person_center_x = raw_person_center_x

                        requested_center_x = fallback_person_center_x
                        detected_source = "person"

            if requested_center_x is not None:
                if previous_detected_source and previous_detected_source != detected_source:
                    target_switches += 1

                previous_detected_source = detected_source
                requested_center_x = clamp_center_x(requested_center_x, resized_w, output_width)

                if force_recenter:
                    camera_center_x = requested_center_x
                elif abs(requested_center_x - camera_center_x) > fallback_dead_zone_px:
                    camera_center_x = requested_center_x

            camera_center_x = clamp_center_x(camera_center_x, resized_w, output_width)

            camera_positions.append(float(camera_center_x))

            cropped_frame = None

            if (
                strategy == "dual_speaker_stack"
                and dual_speaker_pair
                and dual_pair_age_frames <= skip_frames
            ):
                cropped_frame = render_dual_speaker_stack_frame(
                    frame_resized,
                    dual_speaker_pair,
                    output_width=output_width,
                    output_height=output_height,
                )

                if cropped_frame is not None:
                    dual_stack_frames += 1
                    dual_pair_age_frames += 1

            if cropped_frame is None:
                if strategy == "dual_speaker_stack":
                    dual_stack_fallback_frames += 1

                # Calculate crop window
                start_x = int(camera_center_x - output_width / 2)

                if resized_w >= output_width:
                    start_x = max(0, min(start_x, resized_w - output_width))
                    end_x = start_x + output_width
                    cropped_frame = frame_resized[:, start_x:end_x]
                else:
                    # Extremely narrow/tall video: resize to 1080x1920
                    cropped_frame = cv2.resize(
                        frame_resized,
                        (output_width, output_height),
                        interpolation=cv2.INTER_AREA,
                    )

            # Safety check before writing into OpenCV C++ layer
            if cropped_frame is None or cropped_frame.size == 0:
                frame_count += 1
                continue

            if cropped_frame.shape[:2] != (output_height, output_width):
                cropped_frame = cv2.resize(
                    cropped_frame,
                    (output_width, output_height),
                    interpolation=cv2.INTER_AREA,
                )

            cropped_frame = np.ascontiguousarray(cropped_frame, dtype=np.uint8)

            out.write(cropped_frame)
            written_frames += 1
            frame_count += 1

    finally:
        cap.release()
        out.release()

    if written_frames == 0:
        raise RuntimeError(f"No frames were written for: {temp_subclip}")

    assert_file_exists(temp_tracked_avi, "Tracked intermediate video")

    if len(camera_positions) > 1:
        camera_deltas = np.abs(np.diff(np.asarray(camera_positions, dtype=np.float32)))
        avg_camera_move = float(np.mean(camera_deltas))
        max_camera_jump = float(np.max(camera_deltas))
    else:
        avg_camera_move = 0.0
        max_camera_jump = 0.0

    face_detection_rate = face_detection_hits / detection_checks if detection_checks else 0.0
    person_detection_rate = person_detection_hits / detection_checks if detection_checks else 0.0
    camera_stability = max(0.0, min(1.0, 1.0 - (avg_camera_move / 7.0)))
    detection_quality = max(face_detection_rate, person_detection_rate * 0.65)

    if strategy == "stable_face_lock":
        detection_quality = max(
            detection_quality * 0.55,
            float((stable_face_target or {}).get("confidence") or 0.0),
        )
    elif strategy == "group_face_lock":
        group_confidence = float((group_face_target or {}).get("confidence") or 0.0)
        detection_quality = group_confidence if group_confidence >= GROUP_FACE_CONFIDENCE_THRESHOLD else 0.0
    elif strategy == "dual_speaker_stack":
        dual_stack_rate = dual_stack_frames / max(1, written_frames)
        detection_quality = clamp01(dual_stack_rate * 1.20)

    framing_score = max(0.0, min(1.0, 0.68 * camera_stability + 0.32 * detection_quality))

    return {
        "frames_written": int(written_frames),
        "detection_checks": int(detection_checks),
        "face_detection_rate": float(face_detection_rate),
        "person_detection_rate": float(person_detection_rate),
        "avg_camera_move_px": float(avg_camera_move),
        "max_camera_jump_px": float(max_camera_jump),
        "target_switches": int(target_switches),
        "speaker_switches": int(speaker_switches),
        "offcenter_reframes": int(offcenter_reframes),
        "framing_score": float(framing_score),
        "strategy": strategy,
        "stable_face_confidence": float((stable_face_target or {}).get("confidence") or 0.0),
        "group_face_confidence": float((group_face_target or {}).get("confidence") or 0.0),
        "group_face_span_px": float((group_face_target or {}).get("selected_span_px") or 0.0),
        "dual_stack_frame_rate": float(dual_stack_frames / max(1, written_frames)),
        "dual_stack_detection_rate": float(dual_stack_detection_hits / max(1, detection_checks)),
        "dual_stack_fallback_frame_rate": float(dual_stack_fallback_frames / max(1, written_frames)),
        "intermediate_width": int(output_width),
        "intermediate_height": int(output_height),
        "native_crop_intermediate": bool(use_native_intermediate),
    }


def probe_video_file(video_path):
    metadata = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "has_audio": False,
    }

    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        video_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            return metadata

        payload = json.loads(result.stdout or "{}")
    except Exception:
        return metadata

    format_info = payload.get("format", {})
    metadata["duration"] = float(format_info.get("duration") or 0.0)

    for stream in payload.get("streams", []):
        codec_type = stream.get("codec_type")

        if codec_type == "video" and not metadata["width"]:
            metadata["width"] = int(stream.get("width") or 0)
            metadata["height"] = int(stream.get("height") or 0)
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"

            try:
                numerator, denominator = rate.split("/")
                metadata["fps"] = float(numerator) / max(1.0, float(denominator))
            except Exception:
                metadata["fps"] = 0.0

        if codec_type == "audio":
            metadata["has_audio"] = True

    return metadata


def is_valid_existing_clip(video_path, min_size_bytes=1024 * 1024):
    if not os.path.exists(video_path):
        return False

    try:
        if os.path.getsize(video_path) < min_size_bytes:
            return False
    except OSError:
        return False

    probe = probe_video_file(video_path)
    return (
        probe.get("duration", 0.0) >= 3.0
        and probe.get("width") == 1080
        and probe.get("height") == 1920
        and bool(probe.get("has_audio"))
    )


def estimate_black_frame_ratio(video_path, max_samples=None):
    max_samples = max_samples or BLACK_FRAME_SAMPLE_COUNT
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return 1.0

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    samples = []

    if frame_count <= 0:
        cap.release()
        return 1.0

    for frame_index in np.linspace(0, max(0, frame_count - 1), num=min(max_samples, frame_count), dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        samples.append(float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))))

    cap.release()

    if not samples:
        return 1.0

    black_samples = sum(1 for value in samples if value < 8.0)
    return black_samples / len(samples)


def clamp01(value):
    return max(0.0, min(1.0, float(value)))


def get_frame_audit_dir():
    directory = os.path.join(metadata_path or base_dir, "frame_audits")
    os.makedirs(directory, exist_ok=True)
    return directory


def create_frame_audit_contact_sheet(video_path, audit_path, face_cascades=None, sample_count=None):
    sample_count = sample_count or FRAME_AUDIT_SAMPLE_COUNT
    cap = cv2.VideoCapture(video_path)
    result = {
        "path": os.path.abspath(audit_path),
        "sampled_frames": 0,
        "created": False,
        "error": "",
    }

    if not cap.isOpened():
        result["error"] = "could not open final render"
        return result

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

    if frame_count <= 0:
        cap.release()
        result["error"] = "no frames available"
        return result

    face_cascades = face_cascades or load_face_cascades()
    sample_indices = np.linspace(
        0,
        max(0, frame_count - 1),
        num=min(sample_count, frame_count),
        dtype=int,
    )
    tiles = []
    tile_width = 270
    tile_height = 480

    for frame_index in sample_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        result["sampled_frames"] += 1
        source_h, source_w = frame.shape[:2]
        tile = cv2.resize(frame, (tile_width, tile_height), interpolation=cv2.INTER_AREA)
        detection_scale = min(1.0, 720 / max(1, source_h))
        detection_frame = cv2.resize(
            frame,
            (max(1, int(source_w * detection_scale)), max(1, int(source_h * detection_scale))),
            interpolation=cv2.INTER_AREA,
        ) if detection_scale < 1.0 else frame
        faces = filter_plausible_interview_faces(detection_frame, face_cascades)
        frame_state = classify_frame_visual_state(frame, faces=faces)

        if frame_state["is_dead_visual"]:
            faces = []

        status_color = (64, 220, 120)
        status_text = "OK"

        if frame_state["is_black"]:
            status_color = (48, 48, 220)
            status_text = "BLACK"
        elif frame_state["is_dead_visual"]:
            status_color = (70, 70, 245)
            status_text = "DEAD"
        elif frame_state["is_low_information"]:
            status_color = (70, 70, 245)
            status_text = "LOW INFO"
        elif not faces:
            status_color = (70, 190, 245)
            status_text = "NO FACE"

        if faces:
            face = select_best_interview_face(faces)

        if faces and face:
            source_scale_x = tile_width / max(1, detection_frame.shape[1])
            source_scale_y = tile_height / max(1, detection_frame.shape[0])
            x1 = int(face["x"] * source_scale_x)
            y1 = int(face["y"] * source_scale_y)
            x2 = int((face["x"] + face["w"]) * source_scale_x)
            y2 = int((face["y"] + face["h"]) * source_scale_y)
            cv2.rectangle(tile, (x1, y1), (x2, y2), status_color, 2)

        cv2.line(tile, (tile_width // 2, 0), (tile_width // 2, tile_height), (255, 244, 184), 1)
        seconds = frame_index / fps if fps > 0 else 0.0
        cv2.rectangle(tile, (0, 0), (tile_width, 48), (0, 0, 0), -1)
        cv2.putText(
            tile,
            f"{seconds:05.1f}s",
            (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            status_text,
            (10, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            status_color,
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            tile,
            f"E{frame_state['edge_density']:.3f} L{frame_state['laplacian_var']:.0f}",
            (118, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (210, 230, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(tile, (0, 0), (tile_width - 1, tile_height - 1), status_color, 3)
        tiles.append(tile)

    cap.release()

    if not tiles:
        result["error"] = "no readable frames"
        return result

    columns = min(3, len(tiles))
    rows = int(math.ceil(len(tiles) / columns))
    sheet = np.zeros((rows * tile_height, columns * tile_width, 3), dtype=np.uint8)

    for index, tile in enumerate(tiles):
        row = index // columns
        column = index % columns
        y1 = row * tile_height
        x1 = column * tile_width
        sheet[y1:y1 + tile_height, x1:x1 + tile_width] = tile

    os.makedirs(os.path.dirname(audit_path), exist_ok=True)
    result["created"] = bool(cv2.imwrite(audit_path, sheet))

    if not result["created"]:
        result["error"] = "failed to write contact sheet"

    return result


def analyze_final_frame_path(video_path, face_cascades=None, max_samples=None):
    max_samples = max_samples or FINAL_FRAME_PATH_SAMPLE_COUNT
    cap = cv2.VideoCapture(video_path)
    result = {
        "frame_qc_version": FRAME_QC_VERSION,
        "sampled_frames": 0,
        "black_frame_ratio": 1.0,
        "low_information_frame_ratio": 1.0,
        "dead_frame_ratio": 1.0,
        "alive_frame_rate": 0.0,
        "blank_background_frame_ratio": 1.0,
        "avg_edge_density": 0.0,
        "avg_laplacian_var": 0.0,
        "face_presence_rate": 0.0,
        "alive_no_face_frame_ratio": 1.0,
        "longest_no_face_run_ratio": 1.0,
        "avg_face_plausibility": 0.0,
        "avg_face_center_offset_ratio": 0.0,
        "max_face_center_offset_ratio": 0.0,
        "avg_face_height_ratio": 0.0,
        "flat_skin_false_face_ratio": 0.0,
        "flat_skin_false_face_ratio_of_faces": 0.0,
        "small_face_frame_ratio_of_faces": 0.0,
        "center_jitter_ratio": 0.0,
        "visual_cut_ratio": 0.0,
        "continuity_center_jitter_ratio": 0.0,
        "avg_sample_visual_change": 0.0,
        "visual_quality_score": 0.0,
        "flags": [],
    }

    if not cap.isOpened():
        result["flags"].append("could not open final render")
        return result

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if frame_count <= 0:
        cap.release()
        result["flags"].append("no final render frames")
        return result

    face_cascades = face_cascades or load_face_cascades()
    black_frames = 0
    low_information_frames = 0
    dead_frames = 0
    blank_background_frames = 0
    edge_density_values = []
    laplacian_values = []
    face_offsets = []
    face_heights = []
    face_centers = []
    continuity_face_deltas = []
    sample_visual_changes = []
    visual_cuts = 0
    previous_analysis_gray = None
    previous_face_center = None
    face_plausibilities = []
    flat_skin_false_face_frames = 0
    alive_no_face_frames = 0
    current_no_face_run = 0
    longest_no_face_run = 0

    for frame_index in np.linspace(0, max(0, frame_count - 1), num=min(max_samples, frame_count), dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        result["sampled_frames"] += 1

        h, w = frame.shape[:2]
        scale = min(1.0, 720 / max(1, h))
        detection_frame = cv2.resize(
            frame,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        ) if scale < 1.0 else frame
        faces = filter_plausible_interview_faces(detection_frame, face_cascades)
        frame_state = classify_frame_visual_state(frame, faces=faces)
        edge_density_values.append(frame_state["edge_density"])
        laplacian_values.append(frame_state["laplacian_var"])
        analysis_gray = cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
            (96, 170),
            interpolation=cv2.INTER_AREA,
        )
        visual_change = None

        if previous_analysis_gray is not None:
            visual_change = float(np.mean(cv2.absdiff(analysis_gray, previous_analysis_gray)) / 255.0)
            sample_visual_changes.append(visual_change)

            if visual_change > 0.145:
                visual_cuts += 1

        if frame_state["is_black"]:
            black_frames += 1

        if frame_state["is_low_information"]:
            low_information_frames += 1

        if frame_state["is_blank_background"]:
            blank_background_frames += 1

        if frame_state["is_dead_visual"]:
            dead_frames += 1
            current_no_face_run += 1
            longest_no_face_run = max(longest_no_face_run, current_no_face_run)
            previous_analysis_gray = analysis_gray
            continue

        if not faces:
            alive_no_face_frames += 1
            current_no_face_run += 1
            longest_no_face_run = max(longest_no_face_run, current_no_face_run)
            previous_analysis_gray = analysis_gray
            continue

        current_no_face_run = 0
        face = select_best_interview_face(faces)

        if not face:
            continue

        center_offset = abs(face["center_x"] - detection_frame.shape[1] / 2) / max(1, detection_frame.shape[1] / 2)
        face_offsets.append(float(center_offset))
        face_height_ratio = float(face["h"] / max(1, detection_frame.shape[0]))
        face_heights.append(face_height_ratio)
        normalized_face_center = float(face["center_x"] / max(1, detection_frame.shape[1]))
        face_centers.append(normalized_face_center)

        roi_x1 = max(0, int(face["x"] - face["w"] * 0.12))
        roi_y1 = max(0, int(face["y"] - face["h"] * 0.12))
        roi_x2 = min(detection_frame.shape[1], int(face["x"] + face["w"] * 1.12))
        roi_y2 = min(detection_frame.shape[0], int(face["y"] + face["h"] * 1.12))

        if roi_x2 > roi_x1 and roi_y2 > roi_y1:
            face_roi = detection_frame[roi_y1:roi_y2, roi_x1:roi_x2]
            face_roi_features = compute_frame_visual_features(face_roi)
            face_skin_tone_ratio = estimate_skin_tone_ratio(face_roi)

            if (
                face_height_ratio >= 0.14
                and face_skin_tone_ratio > 0.82
                and face_roi_features["edge_density"] < 0.04
            ):
                flat_skin_false_face_frames += 1

        if (
            previous_face_center is not None
            and visual_change is not None
            and visual_change <= 0.145
        ):
            continuity_face_deltas.append(abs(normalized_face_center - previous_face_center))

        previous_face_center = normalized_face_center
        face_plausibilities.append(float(face.get("plausibility", 0.0)))
        previous_analysis_gray = analysis_gray

    cap.release()

    if result["sampled_frames"] <= 0:
        result["flags"].append("no readable final frames")
        return result

    result["black_frame_ratio"] = black_frames / result["sampled_frames"]
    result["low_information_frame_ratio"] = low_information_frames / result["sampled_frames"]
    result["dead_frame_ratio"] = dead_frames / result["sampled_frames"]
    result["alive_frame_rate"] = 1.0 - result["dead_frame_ratio"]
    result["blank_background_frame_ratio"] = blank_background_frames / result["sampled_frames"]
    result["face_presence_rate"] = len(face_offsets) / result["sampled_frames"]
    result["alive_no_face_frame_ratio"] = alive_no_face_frames / result["sampled_frames"]
    result["longest_no_face_run_ratio"] = longest_no_face_run / result["sampled_frames"]
    result["visual_cut_ratio"] = visual_cuts / max(1, result["sampled_frames"] - 1)
    result["avg_sample_visual_change"] = float(np.mean(sample_visual_changes)) if sample_visual_changes else 0.0
    result["avg_edge_density"] = float(np.mean(edge_density_values)) if edge_density_values else 0.0
    result["avg_laplacian_var"] = float(np.mean(laplacian_values)) if laplacian_values else 0.0

    if face_offsets:
        result["avg_face_center_offset_ratio"] = float(np.mean(face_offsets))
        result["max_face_center_offset_ratio"] = float(np.max(face_offsets))
        result["avg_face_height_ratio"] = float(np.mean(face_heights))
        result["avg_face_plausibility"] = float(np.mean(face_plausibilities)) if face_plausibilities else 0.0
        result["flat_skin_false_face_ratio"] = flat_skin_false_face_frames / result["sampled_frames"]
        result["flat_skin_false_face_ratio_of_faces"] = flat_skin_false_face_frames / len(face_offsets)
        result["small_face_frame_ratio_of_faces"] = sum(1 for height in face_heights if height < 0.12) / len(face_heights)

    if len(face_centers) > 1:
        result["center_jitter_ratio"] = float(np.percentile(np.abs(np.diff(face_centers)), 90))

    if continuity_face_deltas:
        result["continuity_center_jitter_ratio"] = float(np.percentile(continuity_face_deltas, 90))

    if result["black_frame_ratio"] > 0.04:
        result["flags"].append("final render has black frames")

    if result["low_information_frame_ratio"] > 0.16:
        result["flags"].append("final render has low-information frames")

    intermittent_background_miss = (
        result["low_information_frame_ratio"] > MAX_FINAL_SPEAKER_LOW_INFORMATION_RATIO
        or result["blank_background_frame_ratio"] > MAX_FINAL_SPEAKER_BLANK_BACKGROUND_RATIO
    ) and (
        result["face_presence_rate"] < 0.98
        or result["alive_no_face_frame_ratio"] > 0.10
        or result["longest_no_face_run_ratio"] > 0.12
    )

    if intermittent_background_miss:
        result["flags"].append("intermittent low-information/background speaker miss")

    if result["dead_frame_ratio"] > DEAD_FRAME_RATIO_THRESHOLD:
        result["flags"].append("final render has dead visual frames")

    if result["alive_frame_rate"] < MIN_ALIVE_FRAME_RATE:
        result["flags"].append("low final alive-frame rate")

    if result["face_presence_rate"] < MIN_FINAL_SPEAKER_FACE_PRESENCE:
        result["flags"].append("low final face presence")

    if face_offsets and (
        result["avg_face_center_offset_ratio"] > MAX_FINAL_AVG_FACE_CENTER_OFFSET
        or result["max_face_center_offset_ratio"] > 0.64
    ):
        result["flags"].append("subject off-center in final crop")

    if face_offsets and result["max_face_center_offset_ratio"] > 0.78:
        result["flags"].append("subject severely off-center in final crop")

    if result["alive_no_face_frame_ratio"] > MAX_FINAL_ALIVE_NO_FACE_RATIO:
        result["flags"].append("alive frames often miss speaker")

    if result["longest_no_face_run_ratio"] > MAX_FINAL_NO_FACE_RUN_RATIO:
        result["flags"].append("extended no-speaker run in final crop")

    if face_plausibilities and result["avg_face_plausibility"] < MIN_FINAL_FACE_PLAUSIBILITY:
        result["flags"].append("weak final face plausibility")

    if face_offsets and result["avg_face_height_ratio"] < MIN_FINAL_FACE_HEIGHT_RATIO:
        tiny_lock_suspected = (
            result["avg_face_height_ratio"] < MIN_FINAL_TINY_FACE_LOCK_HEIGHT_RATIO
            or result["avg_face_center_offset_ratio"] > max(MAX_FINAL_AVG_FACE_CENTER_OFFSET, 0.32)
            or result["max_face_center_offset_ratio"] > 0.62
            or result["avg_face_plausibility"] < MIN_FINAL_FACE_PLAUSIBILITY + 0.08
            or result["face_presence_rate"] < 0.68
        )

        if tiny_lock_suspected:
            result["flags"].append("probable tiny/background face lock")
        else:
            result["flags"].append("tiny final speaker framing")

    if face_offsets:
        picture_in_picture_lock_suspected = (
            result["avg_face_height_ratio"] < 0.10
            and (
                result["face_presence_rate"] < 0.34
                or result["alive_no_face_frame_ratio"] > 0.50
                or result["longest_no_face_run_ratio"] > 0.40
            )
            and (
                result["max_face_center_offset_ratio"] > 0.48
                or result["longest_no_face_run_ratio"] > 0.52
                or (
                    result["avg_face_height_ratio"] < 0.075
                    and result["longest_no_face_run_ratio"] > 0.48
                )
            )
        )

        if picture_in_picture_lock_suspected:
            result["flags"].append("probable picture-in-picture/background lock")

    if (
        result["flat_skin_false_face_ratio"] > 0.42
        and result["face_presence_rate"] > 0.55
        and result["avg_face_height_ratio"] < 0.24
        and result["visual_cut_ratio"] < 0.18
    ):
        result["flags"].append("probable flat-surface false face lock")

    if (
        result["small_face_frame_ratio_of_faces"] > 0.55
        and result["face_presence_rate"] > 0.50
        and result["avg_face_height_ratio"] < 0.13
    ):
        result["flags"].append("probable small-object/background face lock")

    if (
        result["avg_face_height_ratio"] > 0.0
        and result["avg_face_height_ratio"] < 0.13
        and result["visual_cut_ratio"] > 0.32
        and result["avg_sample_visual_change"] > 0.10
        and (
            result["small_face_frame_ratio_of_faces"] > 0.45
            or result["face_presence_rate"] < 0.78
            or result["continuity_center_jitter_ratio"] > 0.18
        )
    ):
        result["flags"].append("probable broadcast/b-roll montage instead of speaker clip")

    if (
        result["face_presence_rate"] < 0.24
        and result["alive_no_face_frame_ratio"] > 0.48
        and result["avg_edge_density"] >= 0.018
    ):
        result["flags"].append("probable background lock instead of speaker")

    if result["continuity_center_jitter_ratio"] > 0.20:
        result["flags"].append("unstable final subject position")
    elif result["center_jitter_ratio"] > 0.20 and result["visual_cut_ratio"] < 0.24:
        result["flags"].append("unstable final subject position")

    quality_score = 1.0
    quality_score -= result["black_frame_ratio"] * 0.55
    quality_score -= result["low_information_frame_ratio"] * 0.40
    quality_score -= result["dead_frame_ratio"] * 0.44
    quality_score -= max(0.0, MIN_ALIVE_FRAME_RATE - result["alive_frame_rate"]) * 0.45
    quality_score -= max(0.0, 0.018 - result["avg_edge_density"]) * 4.2
    quality_score -= max(0.0, 0.42 - result["face_presence_rate"]) * 0.52
    quality_score -= max(0.0, 0.42 - result["avg_face_plausibility"]) * 0.12
    quality_score -= result["alive_no_face_frame_ratio"] * 0.20
    quality_score -= result["longest_no_face_run_ratio"] * 0.16
    quality_score -= result["avg_face_center_offset_ratio"] * 0.18
    quality_score -= max(0.0, result["max_face_center_offset_ratio"] - 0.55) * 0.22
    quality_score -= max(0.0, MIN_FINAL_FACE_HEIGHT_RATIO - result["avg_face_height_ratio"]) * 0.42
    if "probable picture-in-picture/background lock" in result["flags"]:
        quality_score -= 0.24
    if "probable flat-surface false face lock" in result["flags"]:
        quality_score -= 0.28
    if "probable small-object/background face lock" in result["flags"]:
        quality_score -= 0.26
    if "probable broadcast/b-roll montage instead of speaker clip" in result["flags"]:
        quality_score -= 0.30
    jitter_penalty_basis = (
        result["continuity_center_jitter_ratio"]
        if result["continuity_center_jitter_ratio"] > 0
        else result["center_jitter_ratio"] * max(0.18, 1.0 - result["visual_cut_ratio"] * 1.85)
    )
    quality_score -= jitter_penalty_basis * 0.35
    result["visual_quality_score"] = clamp01(quality_score)

    return result


def build_render_qc(video_path, crop_stats, expected_duration, face_cascades=None, audit_path=None):
    probe = probe_video_file(video_path)
    black_frame_ratio = estimate_black_frame_ratio(video_path)
    frame_path_qc = analyze_final_frame_path(video_path, face_cascades=face_cascades)
    audit_result = None

    if audit_path and CREATE_RENDER_CONTACT_SHEETS:
        audit_result = create_frame_audit_contact_sheet(
            video_path,
            audit_path,
            face_cascades=face_cascades,
        )
    flags = []

    if probe["width"] != 1080 or probe["height"] != 1920:
        flags.append("unexpected resolution")

    if not probe["has_audio"]:
        flags.append("missing audio")

    duration_tolerance = max(4.0, min(9.0, float(expected_duration or 0) * 0.14))

    if expected_duration and abs(probe["duration"] - expected_duration) > duration_tolerance:
        flags.append("duration drift")

    if black_frame_ratio > 0.08:
        flags.append("possible black frames")

    if crop_stats.get("framing_score", 1.0) < 0.55:
        flags.append("low framing confidence")

    flags.extend(frame_path_qc.get("flags", []))

    intentional_reframes = (
        crop_stats.get("speaker_switches", 0)
        + crop_stats.get("offcenter_reframes", 0)
    )

    if crop_stats.get("max_camera_jump_px", 0.0) > 22 and intentional_reframes == 0:
        flags.append("noticeable camera jump")

    return {
        "frame_qc_version": frame_path_qc.get("frame_qc_version", FRAME_QC_VERSION),
        **probe,
        "black_frame_ratio": float(black_frame_ratio),
        "frame_path": frame_path_qc,
        "visual_quality_score": float(frame_path_qc.get("visual_quality_score", 0.0)),
        "frame_audit": audit_result or {},
        "frame_audit_file": (audit_result or {}).get("path", ""),
        "crop": crop_stats,
        "flags": flags,
        "passed": not flags,
    }


def preflight_clip_visual_qc(temp_subclip, face_cascades, max_samples=None):
    max_samples = max_samples or PREFLIGHT_FRAME_SAMPLE_COUNT
    cap = cv2.VideoCapture(temp_subclip)
    result = {
        "sampled_frames": 0,
        "face_frames": 0,
        "black_frame_ratio": 1.0,
        "low_information_frame_ratio": 1.0,
        "dead_frame_ratio": 1.0,
        "alive_frame_rate": 0.0,
        "avg_edge_density": 0.0,
        "avg_laplacian_var": 0.0,
        "face_presence_rate": 0.0,
        "alive_no_face_frame_ratio": 1.0,
        "longest_no_face_run_ratio": 1.0,
        "avg_face_height_ratio": 0.0,
        "avg_face_plausibility": 0.0,
        "flat_skin_false_face_ratio": 0.0,
        "small_face_ratio_of_faces": 0.0,
        "visual_cut_ratio": 0.0,
        "avg_sample_visual_change": 0.0,
        "passed": False,
        "flags": [],
    }

    if not cap.isOpened():
        result["flags"].append("could not open preflight clip")
        return result

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if frame_count <= 0:
        cap.release()
        result["flags"].append("no frames for preflight")
        return result

    black_frames = 0
    low_information_frames = 0
    dead_frames = 0
    alive_no_face_frames = 0
    current_no_face_run = 0
    longest_no_face_run = 0
    flat_skin_false_face_frames = 0
    face_heights = []
    face_plausibilities = []
    edge_density_values = []
    laplacian_values = []
    sample_visual_changes = []
    visual_cuts = 0
    previous_analysis_gray = None

    for frame_index in np.linspace(0, max(0, frame_count - 1), num=min(max_samples, frame_count), dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        result["sampled_frames"] += 1
        h, w = frame.shape[:2]
        scale = min(1.0, 640 / max(1, h))
        detection_frame = cv2.resize(
            frame,
            (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        ) if scale < 1.0 else frame
        faces = filter_plausible_interview_faces(detection_frame, face_cascades)
        frame_state = classify_frame_visual_state(frame, faces=faces)
        edge_density_values.append(frame_state["edge_density"])
        laplacian_values.append(frame_state["laplacian_var"])
        analysis_gray = cv2.resize(
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
            (96, 170),
            interpolation=cv2.INTER_AREA,
        )

        if previous_analysis_gray is not None:
            visual_change = float(np.mean(cv2.absdiff(analysis_gray, previous_analysis_gray)) / 255.0)
            sample_visual_changes.append(visual_change)

            if visual_change > 0.145:
                visual_cuts += 1

        if frame_state["is_black"]:
            black_frames += 1

        if frame_state["is_low_information"]:
            low_information_frames += 1

        if frame_state["is_dead_visual"]:
            dead_frames += 1
            current_no_face_run += 1
            longest_no_face_run = max(longest_no_face_run, current_no_face_run)
            previous_analysis_gray = analysis_gray
            continue

        if not faces:
            alive_no_face_frames += 1
            current_no_face_run += 1
            longest_no_face_run = max(longest_no_face_run, current_no_face_run)
            previous_analysis_gray = analysis_gray
            continue

        face = select_best_interview_face(faces)

        if not face:
            alive_no_face_frames += 1
            current_no_face_run += 1
            longest_no_face_run = max(longest_no_face_run, current_no_face_run)
            previous_analysis_gray = analysis_gray
            continue

        current_no_face_run = 0
        result["face_frames"] += 1
        face_height_ratio = float(face["h"] / max(1, detection_frame.shape[0]))
        face_heights.append(face_height_ratio)
        face_plausibilities.append(float(face.get("plausibility", 0.0)))

        roi_x1 = max(0, int(face["x"] - face["w"] * 0.12))
        roi_y1 = max(0, int(face["y"] - face["h"] * 0.12))
        roi_x2 = min(detection_frame.shape[1], int(face["x"] + face["w"] * 1.12))
        roi_y2 = min(detection_frame.shape[0], int(face["y"] + face["h"] * 1.12))

        if roi_x2 > roi_x1 and roi_y2 > roi_y1:
            face_roi = detection_frame[roi_y1:roi_y2, roi_x1:roi_x2]
            face_roi_features = compute_frame_visual_features(face_roi)
            face_skin_tone_ratio = estimate_skin_tone_ratio(face_roi)

            if (
                face_height_ratio >= 0.14
                and face_skin_tone_ratio > 0.82
                and face_roi_features["edge_density"] < 0.04
            ):
                flat_skin_false_face_frames += 1

        previous_analysis_gray = analysis_gray

    cap.release()

    if result["sampled_frames"] <= 0:
        result["flags"].append("no readable preflight frames")
        return result

    result["black_frame_ratio"] = black_frames / result["sampled_frames"]
    result["low_information_frame_ratio"] = low_information_frames / result["sampled_frames"]
    result["dead_frame_ratio"] = dead_frames / result["sampled_frames"]
    result["alive_frame_rate"] = 1.0 - result["dead_frame_ratio"]
    result["alive_no_face_frame_ratio"] = alive_no_face_frames / result["sampled_frames"]
    result["longest_no_face_run_ratio"] = longest_no_face_run / result["sampled_frames"]
    result["avg_edge_density"] = float(np.mean(edge_density_values)) if edge_density_values else 0.0
    result["avg_laplacian_var"] = float(np.mean(laplacian_values)) if laplacian_values else 0.0
    result["visual_cut_ratio"] = visual_cuts / max(1, result["sampled_frames"] - 1)
    result["avg_sample_visual_change"] = float(np.mean(sample_visual_changes)) if sample_visual_changes else 0.0
    result["face_presence_rate"] = result["face_frames"] / result["sampled_frames"]

    if face_heights:
        result["avg_face_height_ratio"] = float(np.mean(face_heights))
        result["avg_face_plausibility"] = float(np.mean(face_plausibilities)) if face_plausibilities else 0.0
        result["flat_skin_false_face_ratio"] = flat_skin_false_face_frames / result["sampled_frames"]
        result["small_face_ratio_of_faces"] = sum(1 for height in face_heights if height < 0.12) / len(face_heights)

    if result["black_frame_ratio"] > 0.10:
        result["flags"].append("preflight black frames")

    if result["low_information_frame_ratio"] > 0.22:
        result["flags"].append("preflight low-information frames")

    if result["dead_frame_ratio"] > 0.30:
        result["flags"].append("preflight dead visual frames")

    if result["face_presence_rate"] < 0.20:
        result["flags"].append("low preflight face presence")

    if result["alive_no_face_frame_ratio"] > 0.52 and result["avg_edge_density"] >= 0.018:
        result["flags"].append("preflight likely misses speaker")

    if (
        result["avg_face_height_ratio"] > 0.0
        and result["avg_face_height_ratio"] < 0.10
        and (
            result["face_presence_rate"] < 0.34
            or result["alive_no_face_frame_ratio"] > 0.50
            or result["longest_no_face_run_ratio"] > 0.40
        )
    ):
        result["flags"].append("preflight probable picture-in-picture/background lock")

    if (
        result["flat_skin_false_face_ratio"] > 0.42
        and result["face_presence_rate"] > 0.50
        and result["avg_face_height_ratio"] < 0.24
    ):
        result["flags"].append("preflight probable flat-surface false face lock")

    if (
        result["small_face_ratio_of_faces"] > 0.55
        and result["face_presence_rate"] > 0.50
        and result["avg_face_height_ratio"] < 0.13
    ):
        result["flags"].append("preflight probable small-object/background face lock")

    if (
        result["avg_face_height_ratio"] > 0.0
        and result["avg_face_height_ratio"] < 0.13
        and result["visual_cut_ratio"] > 0.32
        and result["avg_sample_visual_change"] > 0.10
    ):
        result["flags"].append("preflight probable broadcast/b-roll montage")

    result["passed"] = not result["flags"]
    return result


def preflight_allows_center_safe_render(preflight_qc):
    if not ALLOW_FACELESS_CENTER_SAFE or not active_theme_allows_non_speaker_visual():
        return False

    if not isinstance(preflight_qc, dict):
        return False

    flags = set(preflight_qc.get("flags") or [])
    if not flags or flags - {"low preflight face presence"}:
        return False

    return (
        int(preflight_qc.get("face_frames") or 0) == 0
        and float(preflight_qc.get("alive_frame_rate") or 0.0) >= 0.88
        and float(preflight_qc.get("dead_frame_ratio") or 0.0) <= 0.12
        and float(preflight_qc.get("black_frame_ratio") or 0.0) <= 0.05
        and float(preflight_qc.get("avg_edge_density") or 0.0) >= 0.015
    )


def preflight_allows_partial_face_render(preflight_qc):
    if not isinstance(preflight_qc, dict):
        return False

    flags = set(preflight_qc.get("flags") or [])
    if not flags or flags - {"low preflight face presence"}:
        return False

    return (
        int(preflight_qc.get("face_frames") or 0) > 0
        and float(preflight_qc.get("alive_frame_rate") or 0.0) >= 0.82
        and float(preflight_qc.get("dead_frame_ratio") or 0.0) <= 0.15
        and float(preflight_qc.get("black_frame_ratio") or 0.0) <= 0.05
    )


def render_attempt_quality_score(render_qc):
    frame_score = float(render_qc.get("visual_quality_score", 0.0) or 0.0)
    frame_path = render_qc.get("frame_path", {}) or {}
    crop = render_qc.get("crop", {}) or {}
    crop_score = float(crop.get("framing_score", 0.0) or 0.0)
    flag_penalty = min(0.35, len(render_qc.get("flags", [])) * 0.08)
    passed_bonus = 0.12 if render_qc.get("passed") else 0.0
    strategy_penalty = 0.0
    dead_penalty = float(frame_path.get("dead_frame_ratio") or 0.0) * 0.22
    alive_bonus = max(0.0, float(frame_path.get("alive_frame_rate") or 0.0) - MIN_ALIVE_FRAME_RATE) * 0.08

    if (
        crop.get("strategy") == "group_face_lock"
        and float(crop.get("group_face_confidence") or 0.0) < GROUP_FACE_CONFIDENCE_THRESHOLD
    ):
        strategy_penalty += 0.035

    return clamp01(
        frame_score * 0.74
        + crop_score * 0.18
        + passed_bonus
        + alive_bonus
        - flag_penalty
        - strategy_penalty
        - dead_penalty
    )


def active_theme_allows_non_speaker_visual():
    profile_name = str((active_theme_profile() or {}).get("profile") or active_theme_name()).lower()
    return profile_name in {"politics", "truecrime", "sports", "gaming", "popculture", "technology_ai"}


def render_qc_non_speaker_visual_candidate(render_qc):
    if not active_theme_allows_non_speaker_visual():
        return False

    frame_path = render_qc.get("frame_path", {}) or {}
    flags = set(render_qc.get("flags", []) or [])
    visual_score = float(render_qc.get("visual_quality_score", 0.0) or 0.0)
    low_information = float(frame_path.get("low_information_frame_ratio") or 0.0)
    dead_frames = float(frame_path.get("dead_frame_ratio") or 0.0)
    black_frames = float(frame_path.get("black_frame_ratio") or 0.0)
    no_face_run = float(frame_path.get("longest_no_face_run_ratio") or 0.0)
    alive_no_face = float(frame_path.get("alive_no_face_frame_ratio") or 0.0)

    return (
        visual_score >= 0.58
        and low_information <= 0.18
        and dead_frames <= 0.02
        and black_frames <= 0.02
        and no_face_run <= 0.62
        and alive_no_face <= 0.72
        and not {
            "probable background lock instead of speaker",
            "probable tiny/background face lock",
            "probable picture-in-picture/background lock",
            "probable flat-surface false face lock",
            "probable small-object/background face lock",
            "subject severely off-center in final crop",
        } & flags
    )


def render_attempt_selection_score(render_qc):
    frame_path = render_qc.get("frame_path", {}) or {}
    flags = set(render_qc.get("flags", []) or [])
    score = float(render_qc.get("attempt_quality_score", 0.0) or 0.0)
    non_speaker_visual_ok = render_qc_non_speaker_visual_candidate(render_qc)
    continuity_jitter = float(frame_path.get("continuity_center_jitter_ratio") or 0.0)
    center_jitter = float(frame_path.get("center_jitter_ratio") or 0.0)
    visual_cut_ratio = float(frame_path.get("visual_cut_ratio") or 0.0)
    alive_no_face = float(frame_path.get("alive_no_face_frame_ratio") or 0.0)
    no_face_run = float(frame_path.get("longest_no_face_run_ratio") or 0.0)
    center_offset = float(frame_path.get("avg_face_center_offset_ratio") or 0.0)
    max_center_offset = float(frame_path.get("max_face_center_offset_ratio") or 0.0)
    face_height = float(frame_path.get("avg_face_height_ratio") or 0.0)
    face_plausibility = float(frame_path.get("avg_face_plausibility") or 0.0)

    # Prefer a slightly lower scoring but stable crop over a face-lock that is
    # actually chasing false positives on curtains, logos, or background edges.
    score -= max(0.0, continuity_jitter - 0.15) * 1.10
    score -= max(0.0, center_jitter - 0.28) * 0.45
    if non_speaker_visual_ok:
        score -= max(0.0, alive_no_face - 0.68) * 0.12
        score -= max(0.0, no_face_run - 0.58) * 0.18
    else:
        score -= max(0.0, alive_no_face - 0.34) * 0.35
        score -= max(0.0, no_face_run - 0.22) * 0.55
    score -= max(0.0, center_offset - 0.32) * 0.25
    score -= max(0.0, max_center_offset - 0.58) * 0.34
    score -= max(0.0, MIN_FINAL_FACE_HEIGHT_RATIO - face_height) * 1.30

    if face_plausibility:
        score -= max(0.0, (MIN_FINAL_FACE_PLAUSIBILITY + 0.08) - face_plausibility) * 0.24

    if "unstable final subject position" in flags:
        score -= 0.16

    if "subject off-center in final crop" in flags:
        score -= 0.15

    if "subject severely off-center in final crop" in flags:
        score -= 0.32

    if "probable background lock instead of speaker" in flags:
        score -= 0.34

    if "probable tiny/background face lock" in flags:
        score -= 0.42

    if "probable picture-in-picture/background lock" in flags:
        score -= 0.46

    if "probable flat-surface false face lock" in flags:
        score -= 0.48

    if "probable small-object/background face lock" in flags:
        score -= 0.44

    if "probable broadcast/b-roll montage instead of speaker clip" in flags and not non_speaker_visual_ok:
        score -= 0.52

    if "tiny final speaker framing" in flags:
        score -= 0.14

    if (
        render_qc.get("render_strategy") == "stable_face_lock"
        and continuity_jitter > 0.18
        and visual_cut_ratio > 0.30
    ):
        score -= 0.22

    return score


def fallback_framing_strategies():
    profile = active_theme_profile()
    profile_name = str(profile.get("profile") or "").lower()
    framing_style = str((profile.get("packaging") or {}).get("framing_style") or "").lower()
    rich_fallback_profiles = {"comedy", "sports", "gaming", "popculture"}
    standard_fallbacks = ["stable_face_lock", "center_safe"]

    if os.getenv("SHORTFORM_ENABLE_EXPENSIVE_FRAMING_FALLBACKS", "0") != "1":
        return standard_fallbacks

    if profile_name in rich_fallback_profiles or "reaction" in framing_style or "debate" in framing_style:
        return ["stable_face_lock", "dual_speaker_stack", "group_face_lock", "center_safe"]

    return standard_fallbacks


def primary_framing_strategy(preflight_qc=None):
    profile = active_theme_profile()
    profile_name = str(profile.get("profile") or "").lower()
    framing_style = str((profile.get("packaging") or {}).get("framing_style") or "").lower()
    reaction_profiles = {"comedy", "sports", "gaming", "popculture", "finance"}
    primary_face_strategy = os.getenv("SHORTFORM_PRIMARY_FACE_STRATEGY", "stable_face_lock").strip()

    if primary_face_strategy not in {"face_locked", "stable_face_lock"}:
        primary_face_strategy = "stable_face_lock"

    if preflight_allows_partial_face_render(preflight_qc):
        return primary_face_strategy

    if preflight_allows_center_safe_render(preflight_qc):
        return "center_safe"

    if profile_name in reaction_profiles or "reaction" in framing_style or "debate" in framing_style:
        return primary_face_strategy

    face_presence = 0.0
    if isinstance(preflight_qc, dict):
        face_presence = float(preflight_qc.get("face_presence_rate") or 0.0)

    if face_presence >= 0.35 or "speaker" in framing_style:
        return "stable_face_lock"

    return "center_safe"


def should_try_alternate_framing(render_qc):
    if not ENABLE_ALTERNATE_FRAMING_RETRY:
        return False

    flags = set(render_qc.get("flags", []))
    profile = active_theme_profile()
    profile_name = str(profile.get("profile") or "").lower()
    framing_style = str((profile.get("packaging") or {}).get("framing_style") or "").lower()
    rich_retry_profiles = {"comedy", "sports", "gaming", "popculture", "finance"}
    needs_reaction_retry = (
        profile_name in rich_retry_profiles
        or "reaction" in framing_style
        or "debate" in framing_style
    )
    no_speaker_flags = {
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "low final face presence",
    }
    universal_retry_flags = {
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "subject off-center in final crop",
        "subject severely off-center in final crop",
        "tiny final speaker framing",
        "final render has dead visual frames",
        "low final alive-frame rate",
    }

    if flags & no_speaker_flags and not needs_reaction_retry and not (flags & universal_retry_flags):
        return False

    visual_score = float(render_qc.get("visual_quality_score", 0.0) or 0.0)
    retry_flags = {
        "low final face presence",
        "subject off-center in final crop",
        "unstable final subject position",
        "noticeable camera jump",
        "low framing confidence",
        "final render has dead visual frames",
        "low final alive-frame rate",
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "weak final face plausibility",
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "subject severely off-center in final crop",
        "tiny final speaker framing",
        "intermittent low-information/background speaker miss",
    }

    return visual_score < FRAME_RETRY_SCORE_THRESHOLD or bool(flags & retry_flags)


def render_rejection_reasons(render_qc):
    if not HARD_REJECT_BAD_RENDERS:
        return []

    flags = set(render_qc.get("flags", []))
    visual_score = float(render_qc.get("visual_quality_score", 0.0) or 0.0)
    frame_path = render_qc.get("frame_path") or {}
    profile_name = str((active_theme_profile() or {}).get("profile") or active_theme_name()).lower()
    low_information = float(frame_path.get("low_information_frame_ratio") or 0.0)
    dead_frames = float(frame_path.get("dead_frame_ratio") or 0.0)
    black_frames = float(frame_path.get("black_frame_ratio") or 0.0)
    documentary_disqualifying_flags = {
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "subject severely off-center in final crop",
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
    }
    if active_theme_allows_non_speaker_visual():
        documentary_disqualifying_flags.discard(
            "probable broadcast/b-roll montage instead of speaker clip"
        )
    non_speaker_visual_ok = (
        active_theme_allows_non_speaker_visual()
        and visual_score >= 0.58
        and low_information <= 0.18
        and dead_frames <= 0.02
        and black_frames <= 0.02
        and not (flags & documentary_disqualifying_flags)
    )
    face_hard_flags = {
        "low final face presence",
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "weak final face plausibility",
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "intermittent low-information/background speaker miss",
    }
    hard_flags = {
        "could not open final render",
        "no final render frames",
        "no readable final frames",
        "unexpected resolution",
        "missing audio",
        "possible black frames",
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
        "low final face presence",
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "weak final face plausibility",
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "subject severely off-center in final crop",
        "intermittent low-information/background speaker miss",
    }

    if non_speaker_visual_ok:
        hard_flags -= face_hard_flags

    reasons = sorted(flags & hard_flags)

    face_presence = float(frame_path.get("face_presence_rate") or 0.0)
    alive_no_face = float(frame_path.get("alive_no_face_frame_ratio") or 0.0)
    no_face_run = float(frame_path.get("longest_no_face_run_ratio") or 0.0)
    center_offset = float(frame_path.get("avg_face_center_offset_ratio") or 0.0)
    max_center_offset = float(frame_path.get("max_face_center_offset_ratio") or 0.0)
    face_height = float(frame_path.get("avg_face_height_ratio") or 0.0)
    plausibility = float(frame_path.get("avg_face_plausibility") or 0.0)

    if not non_speaker_visual_ok and face_presence and face_presence < MIN_FINAL_SPEAKER_FACE_PRESENCE:
        reasons.append(
            f"speaker face presence below threshold ({face_presence:.2f} < {MIN_FINAL_SPEAKER_FACE_PRESENCE:.2f})"
        )

    if not non_speaker_visual_ok and alive_no_face > MAX_FINAL_ALIVE_NO_FACE_RATIO:
        reasons.append(
            f"alive no-speaker frames above threshold ({alive_no_face:.2f} > {MAX_FINAL_ALIVE_NO_FACE_RATIO:.2f})"
        )

    if not non_speaker_visual_ok and no_face_run > MAX_FINAL_NO_FACE_RUN_RATIO:
        reasons.append(
            f"no-speaker run above threshold ({no_face_run:.2f} > {MAX_FINAL_NO_FACE_RUN_RATIO:.2f})"
        )

    blank_background = float(frame_path.get("blank_background_frame_ratio") or 0.0)
    if (
        not non_speaker_visual_ok
        and (
            low_information > MAX_FINAL_SPEAKER_LOW_INFORMATION_RATIO
            or blank_background > MAX_FINAL_SPEAKER_BLANK_BACKGROUND_RATIO
        )
        and (
            face_presence < 0.98
            or alive_no_face > 0.10
            or no_face_run > 0.12
        )
    ):
        reasons.append(
            "speaker crop intermittently lands on low-information/background frames "
            f"(low_info={low_information:.2f}, blank={blank_background:.2f})"
        )

    if non_speaker_visual_ok:
        render_qc["documentary_non_face_ok"] = True
        render_qc["non_speaker_visual_ok"] = True
    elif center_offset > 0.42:
        reasons.append(
            f"speaker center offset is severe ({center_offset:.2f} > 0.42)"
        )
    elif face_presence < 0.90 and center_offset > MAX_FINAL_AVG_FACE_CENTER_OFFSET:
        reasons.append(
            f"speaker center offset above threshold ({center_offset:.2f} > {MAX_FINAL_AVG_FACE_CENTER_OFFSET:.2f})"
        )

    if face_presence < 0.55 and plausibility and plausibility < MIN_FINAL_FACE_PLAUSIBILITY:
        reasons.append(
            f"face plausibility below threshold ({plausibility:.2f} < {MIN_FINAL_FACE_PLAUSIBILITY:.2f})"
        )

    if not non_speaker_visual_ok and face_presence >= 0.30 and face_height and face_height < MIN_FINAL_FACE_HEIGHT_RATIO:
        reasons.append(
            f"speaker face too small for reliable crop ({face_height:.2f} < {MIN_FINAL_FACE_HEIGHT_RATIO:.2f})"
        )

    if (
        not non_speaker_visual_ok
        and face_height
        and face_height < 0.10
        and (
            face_presence < 0.34
            or alive_no_face > 0.50
            or no_face_run > 0.40
        )
        and (
            max_center_offset > 0.48
            or no_face_run > 0.52
            or (face_height < 0.075 and no_face_run > 0.48)
        )
    ):
        reasons.append("probable picture-in-picture or background crop lock")

    if not non_speaker_visual_ok and max_center_offset > 0.78:
        reasons.append(
            f"speaker max center offset is severe ({max_center_offset:.2f} > 0.78)"
        )

    if visual_score < MIN_ACCEPTED_RENDER_VISUAL_QUALITY and not non_speaker_visual_ok:
        reasons.append(
            f"visual quality below threshold ({visual_score:.2f} < {MIN_ACCEPTED_RENDER_VISUAL_QUALITY:.2f})"
        )

    return sorted(set(reasons))


def audit_existing_final_clip(video_path, expected_duration=0.0, face_cascades=None, audit_path=None):
    probe = probe_video_file(video_path)
    frame_qc = analyze_final_frame_path(video_path, face_cascades=face_cascades)
    audit_result = None

    if audit_path and CREATE_RENDER_CONTACT_SHEETS:
        audit_result = create_frame_audit_contact_sheet(
            video_path,
            audit_path,
            face_cascades=face_cascades,
        )

    render_qc = {
        "frame_qc_version": frame_qc.get("frame_qc_version", FRAME_QC_VERSION),
        "passed": True,
        "flags": list(frame_qc.get("flags") or []),
        "visual_quality_score": frame_qc.get("visual_quality_score", 0.0),
        "attempt_quality_score": frame_qc.get("visual_quality_score", 0.0),
        "render_strategy": "existing_file_audit",
        "crop": {
            "strategy": "existing_file_audit",
            "framing_score": frame_qc.get("visual_quality_score", 0.0),
            "face_detection_rate": frame_qc.get("face_presence_rate", 0.0),
            "speaker_switches": 0,
            "offcenter_reframes": 0,
        },
        "frame_path": frame_qc,
        "probe": probe,
        "reused_existing_file": True,
    }

    if audit_result and audit_result.get("created"):
        render_qc["frame_audit_file"] = audit_result.get("path", "")
        render_qc["frame_path"]["audit_file"] = audit_result.get("path", "")

    duration = float(probe.get("duration") or 0.0)
    expected_duration = float(expected_duration or 0.0)

    if expected_duration > 0:
        duration_delta = abs(duration - expected_duration)
        duration_tolerance = max(1.2, min(3.0, expected_duration * 0.08))

        if duration_delta > duration_tolerance:
            render_qc["flags"].append(
                f"existing clip duration mismatch ({duration:.2f}s vs expected {expected_duration:.2f}s)"
            )

    rejection_reasons = render_rejection_reasons(render_qc)

    if rejection_reasons:
        render_qc["passed"] = False
        render_qc["rejected"] = True
        render_qc["rejection_reasons"] = rejection_reasons
        render_qc["flags"] = sorted(set(render_qc.get("flags", []) + rejection_reasons))
    else:
        render_qc["rejected"] = False
        render_qc["rejection_reasons"] = []
        render_qc["flags"] = sorted(set(render_qc.get("flags", [])))

    return render_qc


def render_crop_attempt(
    temp_subclip,
    temp_tracked_avi,
    final_filename,
    strategy,
    model,
    face_cascades,
    expected_duration,
    audit_path,
):
    start_step2 = time.time()

    def failed_attempt(error, elapsed_seconds):
        message = str(error).splitlines()[0][:300]
        flag = "crop timeout" if isinstance(error, TimeoutError) else "crop attempt failed"
        crop_stats = {
            "strategy": strategy,
            "framing_score": 0.0,
            "face_detection_rate": 0.0,
            "speaker_switches": 0,
            "offcenter_reframes": 0,
        }
        render_qc = {
            "passed": False,
            "flags": [flag, message],
            "visual_quality_score": 0.0,
            "render_strategy": strategy,
            "attempt_quality_score": 0.0,
            "crop": crop_stats,
            "frame_path": {},
        }
        print(f" -> Step 2 ({strategy} smart crop) failed after {elapsed_seconds:.2f} seconds: {message}")
        return {
            "strategy": strategy,
            "output_file": "",
            "tracked_file": temp_tracked_avi,
            "crop_stats": crop_stats,
            "render_qc": render_qc,
            "step2_seconds": elapsed_seconds,
            "step3_seconds": 0.0,
        }

    try:
        crop_stats = smart_crop_to_shorts(
            temp_subclip=temp_subclip,
            temp_tracked_avi=temp_tracked_avi,
            model=model,
            face_cascades=face_cascades,
            strategy=strategy,
        )
    except Exception as error:
        return failed_attempt(error, time.time() - start_step2)

    step2_seconds = time.time() - start_step2
    print(f" -> Step 2 ({strategy} smart crop) took: {step2_seconds:.2f} seconds")

    start_step3 = time.time()

    try:
        mux_command = [
            FFMPEG_EXE,
            "-y",
            "-i", temp_tracked_avi,
            "-i", temp_subclip,
            "-map", "0:v:0",
            "-map", "1:a?",
            "-vf", "scale=1080:1920:flags=lanczos",
        ]
        mux_command.extend(video_encoder_args(quality=20, software_preset="fast"))
        mux_command.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            final_filename,
        ])
        run_subprocess(mux_command, f"FFmpeg audio muxing ({encoder_label()})")

        assert_file_exists(final_filename, "Final clip attempt")
    except Exception as error:
        return failed_attempt(error, step2_seconds + (time.time() - start_step3))

    render_qc = build_render_qc(
        video_path=final_filename,
        crop_stats=crop_stats,
        expected_duration=expected_duration,
        face_cascades=face_cascades,
        audit_path=audit_path,
    )
    render_qc["render_strategy"] = strategy
    render_qc["attempt_quality_score"] = render_attempt_quality_score(render_qc)

    step3_seconds = time.time() - start_step3
    print(f" -> Step 3 ({strategy} audio mux + audit) took: {step3_seconds:.2f} seconds")

    return {
        "strategy": strategy,
        "output_file": final_filename,
        "tracked_file": temp_tracked_avi,
        "crop_stats": crop_stats,
        "render_qc": render_qc,
        "step2_seconds": step2_seconds,
        "step3_seconds": step3_seconds,
    }


# =========================
# Viral clip scoring
# =========================

@dataclass
class CandidateClip:
    start_time: float
    end_time: float
    score: float
    audio_score: float
    text_score: float
    opening_score: float
    comment_score: float
    popularity_score: float
    arc_score: float
    readiness_score: float
    pacing_score: float
    duration_score: float
    boundary_score: float
    diversity_score: float
    theme_signal_score: float = 0.0
    theme_signals: dict = field(default_factory=dict)
    first_second_qc: dict = field(default_factory=dict)
    transformation_score: float = 0.0
    reused_content_risk: float = 0.0
    experiment: dict = field(default_factory=dict)
    rank_signals: dict = field(default_factory=dict)
    transcript_excerpt: str = ""
    hook_reason: str = ""
    topic_fingerprint: list = field(default_factory=list)
    suggested_title: str = ""
    suggested_caption: str = ""
    suggested_description: str = ""
    hashtags: list = field(default_factory=list)
    render_qc: dict = field(default_factory=dict)
    output_file: str = ""
    source_state_key: str = ""
    source_video_url: str = ""
    source_title: str = ""


VIRAL_KEYWORD_WEIGHTS = {
    # Conflict, stakes, and controversy
    "scam": 3.0,
    "fraud": 3.0,
    "lie": 2.5,
    "lying": 2.5,
    "wrong": 2.0,
    "mistake": 1.8,
    "problem": 1.7,
    "danger": 2.2,
    "risk": 1.8,
    "debt": 2.2,
    "broke": 2.2,
    "bankrupt": 2.5,
    "tax": 1.6,
    "lawsuit": 2.5,
    "illegal": 2.6,
    "controversial": 2.4,
    "exposed": 2.8,
    "truth": 2.0,
    "secret": 2.4,
    "insane": 2.2,
    "crazy": 2.0,
    "shocking": 2.4,
    "death threat": 3.2,
    "default": 2.2,
    "defaults": 2.2,
    "evil": 2.0,
    "victim": 1.8,
    "victims": 1.8,
    "offended": 1.8,
    "angry": 1.8,
    "terrifying": 2.3,
    "scary": 2.1,
    "panic": 2.1,
    "crisis": 2.4,
    "collapse": 2.2,
    "destroy": 2.1,
    "ruin": 2.1,
    "failure": 1.8,
    "trap": 2.2,
    "predatory": 2.6,

    # Strong positive/negative emotion
    "amazing": 1.6,
    "best": 1.5,
    "love": 1.5,
    "hate": 1.8,
    "terrible": 1.8,
    "awful": 1.8,
    "fear": 1.8,
    "angry": 1.8,
    "sad": 1.5,
    "happy": 1.2,
    "excited": 1.5,
    "passion": 1.5,
    "brutal": 2.0,
    "embarrassing": 1.9,
    "humiliating": 2.0,
    "regret": 1.8,
    "obsessed": 1.5,
    "hilarious": 1.6,
    "wild": 1.8,

    # Mainstream topics that often travel well
    "money": 2.0,
    "million": 2.0,
    "billion": 2.2,
    "rich": 1.7,
    "poor": 1.7,
    "business": 1.4,
    "ai": 2.0,
    "artificial intelligence": 2.4,
    "crypto": 2.0,
    "bitcoin": 2.0,
    "government": 1.8,
    "politics": 1.8,
    "war": 2.3,
    "crime": 2.2,
    "health": 1.5,
    "diet": 1.4,
    "addiction": 2.0,
    "dating": 1.8,
    "marriage": 1.7,
    "celebrity": 1.8,
    "credit card": 2.2,
    "credit cards": 2.2,
    "student loan": 2.2,
    "student loans": 2.2,
    "interest rate": 1.8,
    "car payment": 1.9,
    "electric car": 1.7,
    "housing": 1.7,
    "rent": 1.5,
    "job": 1.3,
    "jobs": 1.3,
    "college": 1.7,
    "degree": 1.6,
    "degrees": 1.6,
    "wealth gap": 2.0,
    "gender wealth gap": 2.4,
    "minimum payment": 1.8,
    "porsche": 1.5,
    "audi": 1.4,
}

HOOK_PATTERNS = [
    r"\bhere'?s why\b",
    r"\bthe reason\b",
    r"\bwhat people don'?t understand\b",
    r"\bnobody talks about\b",
    r"\byou have to understand\b",
    r"\bthe truth is\b",
    r"\bthis is why\b",
    r"\bthink about\b",
    r"\bhow do you\b",
    r"\bwhy would\b",
    r"\bwhat if\b",
    r"\byou won'?t believe\b",
    r"\bthis is the part\b",
    r"\bmost people\b",
    r"\beveryone thinks\b",
    r"\bthe biggest\b",
    r"\bthe problem is\b",
    r"\bfirst of all\b",
    r"\blook at this\b",
    r"\bthat'?s crazy\b",
    r"\bthat'?s insane\b",
    r"\bthe actual reality\b",
]

TOPIC_KEYWORDS = {
    "money", "debt", "credit", "loan", "loans", "college", "job", "jobs",
    "ai", "government", "politics", "tax", "crime", "health", "dating",
    "marriage", "business", "crypto", "bitcoin", "housing",
    "rent", "wealth", "income", "car", "cars", "porsche", "audi",
}

EMOTION_KEYWORDS = {
    "crazy", "insane", "shocking", "scary", "terrifying", "brutal", "angry",
    "offended", "hate", "love", "amazing", "awful", "terrible", "evil",
    "hilarious", "wild", "embarrassing", "humiliating", "regret", "fear",
}

CONFLICT_KEYWORDS = {
    "wrong", "problem", "lie", "lying", "scam", "fraud", "illegal", "risk",
    "danger", "lawsuit", "death", "threat", "default", "defaults", "victim",
    "victims", "predatory", "trap", "failure", "mistake", "destroy", "ruin",
}

FILLER_WORDS = {
    "yeah", "okay", "like", "just", "really", "actually", "basically", "kind",
    "sort", "stuff", "thing", "things", "know", "mean", "right", "well",
    "um", "uh", "you", "i", "we",
}

LOW_VALUE_TOPIC_WORDS = {
    "about", "after", "again", "also", "anything", "around", "back", "because",
    "can", "come", "comes", "coming", "didnt", "didn't", "doesnt", "doesn't",
    "doing", "done", "dude", "even", "ever", "every", "everything", "feel",
    "feels", "felt", "first", "gonna", "good", "got", "get", "gets", "getting",
    "give", "gives", "goes", "going", "guy", "guys", "here", "heres", "here's",
    "his", "kind", "last", "little",
    "look", "looks", "lot", "love", "make", "makes", "maybe", "much", "need",
    "never", "new", "now", "old", "one", "ones", "out", "over", "part", "people", "person", "pretty", "put", "said",
    "same", "say", "says", "see", "seen", "show", "shows", "something", "start", "started",
    "still", "some", "talk", "talking", "tell", "thank", "thanks", "there", "theres", "there's",
    "thing", "things", "thought", "time", "take", "takes", "taken", "taking",
    "two", "wanna", "want", "wanted", "wants",
    "way", "went", "whats", "what's", "whoa", "willing", "work", "world",
    "could", "couldve", "could've", "would", "wouldve", "would've", "youll", "you'll",
}

COMMENT_TRIGGER_WORDS = {
    "should", "shouldn't", "wrong", "right", "why", "how", "what", "agree",
    "disagree", "crazy", "insane", "scary", "evil", "victim", "victims",
    "default", "defaults", "debt", "money", "rich", "poor", "government",
    "college", "tax", "illegal", "fraud", "scam", "fair", "unfair",
    "freedom", "problem", "truth", "reality", "angry", "offended",
}

WEAK_START_WORDS = {
    "and", "but", "so", "because", "then", "that", "this", "those", "these",
    "they", "them", "their", "he", "she", "his", "her", "him", "it", "its",
    "we", "you", "i", "there", "which", "who", "when", "where",
}

FILLER_OPENERS = {
    "yeah", "yes", "no", "okay", "well", "like", "um", "uh", "right",
    "actually", "basically", "literally", "honestly",
}

SPONSOR_READ_PATTERNS = [
    r"\b(use|enter|apply)\s+(code|promo code|coupon code)\b",
    r"\b(code|promo code|coupon code)\s+[a-z0-9_-]{3,}\b",
    r"\blink\s+in\s+(the\s+)?description\b",
    r"\b(description|bio)\s+below\b",
    r"\b\d{1,2}\s*%\s+off\b",
    r"\bpercent\s+off\b",
    r"\bfree\s+(shipping|returns|trial|month|months)\b",
    r"\bglobal\s+shipping\b",
    r"\bsponsored\s+by\b",
    r"\b(today'?s|this)\s+sponsor\b",
    r"\bthanks?\s+to\s+(our\s+)?sponsor\b",
    r"\bhead\s+to\s+[a-z0-9.-]+\b",
    r"\bgo\s+to\s+the\s+link\b",
    r"\bcheck\s+out\s+the\s+link\b",
    r"\bclick\s+the\s+link\b",
    r"\b(show\s+notes|description)\s+to\s+learn\s+more\b",
    r"\blearn\s+more\s+in\s+the\s+(show\s+notes|description)\b",
    r"\bconference\s+in\s+[a-z]+(?:\s+\d{4})?\b",
    r"\bworld\s+congress\b",
    r"\bmodern\s+wisdom\b",
    r"\bsurfshark\b",
    r"\bhellofresh\b",
    r"\bhello\s*fresh\b",
    r"\bhomemade\s+meals?\b",
    r"\bglobal\s+recipes?\b",
    r"\b\d{1,3}\s*\+?\s*(global\s+)?recipes?\b",
    r"\bfree\s+meals?\b",
    r"\b[a-z0-9_-]+\s+dot\s+com\s+slash\b",
]

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that",
    "this", "these", "those", "is", "are", "was", "were", "be", "been",
    "being", "to", "of", "for", "with", "in", "on", "at", "by", "from",
    "as", "it", "its", "i", "you", "we", "they", "he", "she", "them",
    "him", "her", "my", "your", "our", "their", "me", "us", "do", "does",
    "did", "have", "has", "had", "not", "so", "just", "like", "know",
    "think", "really", "right", "yeah", "well", "what", "when", "where",
    "why", "how",
    "all", "okay", "ok", "yes", "no",
    "it's", "im", "i'm", "dont", "don't", "thats", "that's", "hes", "he's",
    "shes", "she's", "youre", "you're", "were", "we're", "theyre", "they're",
    "ive", "i've", "youve", "you've", "isnt", "isn't", "wasnt", "wasn't",
    "cant", "can't", "couldnt", "couldn't", "wouldnt", "wouldn't",
}

HASHTAG_KEYWORDS = {
    "money": "#money",
    "debt": "#debt",
    "credit": "#credit",
    "college": "#college",
    "business": "#business",
    "ai": "#ai",
    "crypto": "#crypto",
    "bitcoin": "#bitcoin",
    "government": "#politics",
    "politics": "#politics",
    "health": "#health",
    "dating": "#dating",
    "marriage": "#relationships",
    "crime": "#truecrime",
    "job": "#career",
    "jobs": "#career",
}

THEME_SCORING_PROFILES = {
    "comedy": {
        "keywords": {
            "funny": 2.2,
            "joke": 2.2,
            "laugh": 2.0,
            "hilarious": 2.1,
            "comedy": 2.2,
            "standup": 1.9,
            "story": 1.6,
            "roast": 1.8,
            "ridiculous": 1.7,
            "awkward": 1.6,
            "wild": 1.5,
        },
        "hashtags": ["#comedy", "#funny", "#jokes", "#standup", "#shorts"],
        "topic_tags": {
            "funny": "#funny",
            "joke": "#jokes",
            "comedy": "#comedy",
            "standup": "#standup",
            "roast": "#roast",
            "story": "#storytime",
        },
    },
    "sports": {
        "keywords": {
            "championship": 2.2,
            "playoffs": 2.0,
            "draft": 1.9,
            "trade": 1.8,
            "locker room": 2.0,
            "coach": 1.5,
            "quarterback": 1.8,
            "nba": 1.8,
            "nfl": 1.8,
            "legacy": 1.7,
            "rivalry": 2.0,
        },
        "hashtags": ["#sports", "#nfl", "#nba", "#podcast", "#shorts"],
        "topic_tags": {
            "nfl": "#nfl",
            "nba": "#nba",
            "draft": "#draft",
            "playoffs": "#playoffs",
            "quarterback": "#football",
            "trade": "#sportsnews",
        },
    },
    "finance": {
        "keywords": {
            "cash flow": 2.1,
            "investing": 1.9,
            "portfolio": 1.7,
            "valuation": 2.0,
            "startup": 1.8,
            "founder": 1.6,
            "market": 1.5,
            "recession": 2.2,
            "inflation": 2.0,
            "interest rates": 2.0,
            "net worth": 2.1,
        },
        "hashtags": ["#finance", "#money", "#investing", "#business", "#shorts"],
        "topic_tags": {
            "investing": "#investing",
            "startup": "#startups",
            "founder": "#founders",
            "market": "#markets",
            "inflation": "#inflation",
            "valuation": "#business",
        },
    },
    "politics": {
        "keywords": {
            "election": 2.2,
            "policy": 1.8,
            "border": 2.0,
            "congress": 1.8,
            "senate": 1.7,
            "president": 1.8,
            "media": 1.7,
            "corruption": 2.4,
            "democrat": 1.7,
            "republican": 1.7,
        },
        "hashtags": ["#politics", "#news", "#government", "#podcast", "#shorts"],
        "topic_tags": {
            "election": "#election",
            "policy": "#policy",
            "border": "#border",
            "congress": "#congress",
            "media": "#media",
            "corruption": "#politics",
        },
    },
    "self_improvement": {
        "keywords": {
            "discipline": 2.0,
            "habits": 1.9,
            "mindset": 1.8,
            "confidence": 1.6,
            "purpose": 1.7,
            "anxiety": 1.8,
            "focus": 1.6,
            "motivation": 1.4,
            "health": 1.5,
            "sleep": 1.6,
            "dopamine": 1.7,
        },
        "hashtags": ["#selfimprovement", "#mindset", "#motivation", "#growth", "#shorts"],
        "topic_tags": {
            "discipline": "#discipline",
            "habits": "#habits",
            "mindset": "#mindset",
            "confidence": "#confidence",
            "anxiety": "#mentalhealth",
            "sleep": "#health",
            "focus": "#productivity",
        },
    },
}

CLAIM_PATTERNS = [
    r"\bmost people (are|think|get|miss|don'?t)\b",
    r"\bthe reason (is|why)\b",
    r"\bthis is why\b",
    r"\bthat'?s why\b",
    r"\bthe truth is\b",
    r"\bthe problem is\b",
    r"\byou should never\b",
    r"\byou have to\b",
    r"\bwhat people don'?t understand\b",
    r"\bno one talks about\b",
    r"\bnobody talks about\b",
]

PAYOFF_PATTERNS = [
    r"\bbecause\b",
    r"\bthat means\b",
    r"\bwhich means\b",
    r"\bas a result\b",
    r"\bso the answer\b",
    r"\bthe answer is\b",
    r"\bwhat happens is\b",
    r"\bthat'?s the point\b",
]

HOOK_TYPE_PATTERNS = [
    ("disagreement", r"\b(i disagree|you'?re wrong|that'?s wrong|not true|push back)\b"),
    ("confession", r"\b(i realized|i learned|i regret|i was wrong|honestly)\b"),
    ("prediction", r"\b(will happen|going to happen|in the future|next decade|prediction)\b"),
    ("warning", r"\b(be careful|danger|risk|warning|terrifying|scary|trap)\b"),
    ("money_or_numbers", r"\$\s?\d+|\b\d+[\d,.]*%?\b|\bmillion\b|\bbillion\b"),
    ("belief_vs_truth", r"\b(everyone thinks|most people think|the truth is|actual reality)\b"),
    ("question", r"\?"),
]


def normalize_array(values):
    values = np.asarray(values, dtype=np.float32)

    if values.size == 0:
        return values

    low = float(np.percentile(values, 5))
    high = float(np.percentile(values, 95))

    if high <= low:
        return np.zeros_like(values, dtype=np.float32)

    return np.clip((values - low) / (high - low), 0, 1)


def saturating_score(value, scale):
    if value <= 0:
        return 0.0

    return float(1 - np.exp(-value / scale))


def get_theme_profile(theme_name=None):
    return active_theme_profile(theme_name)


def combined_keyword_weights(theme_name=None):
    profile = get_theme_profile(theme_name)
    return {
        **VIRAL_KEYWORD_WEIGHTS,
        **profile.get("keywords", {}),
        **theme_keyword_weights(active_theme_name(theme_name)),
    }


def theme_topic_tags(theme_name=None):
    return {
        **HASHTAG_KEYWORDS,
        **profile_theme_topic_tags(active_theme_name(theme_name)),
    }


def clean_transcript_text(text):
    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()
    cleaned_tokens = []

    for token in tokens:
        normalized = re.sub(r"[^a-zA-Z0-9']", "", token).lower()
        previous = ""

        if cleaned_tokens:
            previous = re.sub(r"[^a-zA-Z0-9']", "", cleaned_tokens[-1]).lower()

        if normalized and normalized == previous:
            continue

        cleaned_tokens.append(token)

    text = " ".join(cleaned_tokens)
    text = re.sub(r"\b(i'?m)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(you know|i mean|sort of|kind of)\b(?:,?\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)
    return text.strip()


def words_from_text(text):
    return re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", text.lower())


def first_spoken_word(text):
    words = words_from_text(text)
    return words[0] if words else ""


def compact_text(text, max_chars=90):
    text = re.sub(r"\s+", " ", text).strip(" -._")

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip(" -._")
    return shortened or text[:max_chars].strip(" -._")


def extract_topic_fingerprint(text, max_terms=10):
    words = words_from_text(text)
    weighted_terms = {}
    keyword_weights = combined_keyword_weights()

    for word in words:
        normalized_word = word.replace("'", "")

        if (
            word in STOPWORDS
            or normalized_word in STOPWORDS
            or word in FILLER_WORDS
            or normalized_word in FILLER_WORDS
            or word in LOW_VALUE_TOPIC_WORDS
            or normalized_word in LOW_VALUE_TOPIC_WORDS
            or len(normalized_word) < 3
        ):
            continue

        weight = 1.0

        if word in TOPIC_KEYWORDS:
            weight += 2.0
        if word in EMOTION_KEYWORDS or word in CONFLICT_KEYWORDS:
            weight += 1.4
        if word in COMMENT_TRIGGER_WORDS:
            weight += 0.8

        weighted_terms[word] = weighted_terms.get(word, 0.0) + weight

    for phrase, weight in keyword_weights.items():
        if " " in phrase and phrase in text.lower():
            weighted_terms[phrase.replace(" ", "_")] = weighted_terms.get(phrase.replace(" ", "_"), 0.0) + weight

    return [
        term
        for term, _ in sorted(weighted_terms.items(), key=lambda item: item[1], reverse=True)[:max_terms]
    ]


def is_meaningful_topic_term(term):
    normalized = str(term or "").replace("_", " ").replace("'", "").strip().lower()

    return bool(
        normalized
        and normalized not in STOPWORDS
        and normalized not in FILLER_WORDS
        and normalized not in LOW_VALUE_TOPIC_WORDS
        and len(normalized) >= 3
    )


TITLE_SUPPORT_ALIASES = {
    "nascar": {"nascar", "race", "racing", "racer", "cars", "car", "track", "horsepower", "stock"},
    "racing": {"race", "racing", "racer", "cars", "car", "track", "horsepower", "nascar"},
    "amino": {"amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine", "protein", "grams"},
    "acids": {"amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine", "protein", "grams"},
    "protein": {"protein", "amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine"},
    "abs": {"abs", "core", "hip", "hips", "flexor", "flexors", "physio", "ball", "range", "motion"},
    "strength": {"strength", "training", "lift", "lifts", "squat", "bench", "deadlift", "press", "row", "reps"},
    "lifts": {"strength", "training", "lift", "lifts", "squat", "bench", "deadlift", "press", "row", "reps"},
}

THEME_RELEVANCE_WORDS = {
    "health_fitness": {
        "health", "fitness", "wellness", "training", "exercise", "workout", "protein",
        "amino", "acid", "eaa", "eaas", "leucine", "lucine", "range", "motion",
        "hip", "hips", "flexor", "physio", "ball", "body", "abs", "core",
        "muscle", "sleep", "stress", "fertility", "metabolism", "nutrition",
    },
    "sports": {
        "sports", "game", "team", "coach", "athlete", "race", "racing", "nascar",
        "car", "cars", "track", "horsepower", "titans", "steelers", "pittsburgh",
        "practice", "practicing", "play", "season", "locker", "nba", "nfl",
    },
    "finance": {
        "market", "markets", "money", "debt", "rates", "inflation", "investor",
        "investors", "stock", "stocks", "fund", "funds", "hedge", "mutual",
        "cash", "flow", "revenue", "business", "rental", "rent", "valuation",
        "economy", "economic", "home", "homes", "house", "housing", "property",
        "properties", "mortgage", "price", "prices", "median", "affordability",
        "affordable", "payment", "income",
    },
    "technology_ai": {
        "ai", "agent", "agents", "model", "models", "openai", "claude", "code",
        "coding", "developer", "developers", "software", "startup", "founder",
        "product", "data", "machine", "learning", "robot", "chip", "security",
        "eval", "builder", "tech", "technology", "training", "paradigm",
    },
}

CROSS_THEME_MISMATCH_WORDS = {
    "health_fitness": {
        "stock", "stocks", "fund", "funds", "hedge", "mutual", "equity",
        "investor", "investors", "revenue", "market", "markets",
    },
    "technology_ai": {
        "steam", "fortnite", "gta", "dota", "skins", "skin", "gaming", "game",
        "games", "grand", "theft", "fortnight",
    },
}

SOURCE_CONTEXT_WORDS = {
    "show", "episode", "podcast", "interview", "guest", "channel", "archive",
    "take", "story", "moment", "detail", "debate", "fight", "room",
}


def normalize_support_word(word):
    word = str(word or "").lower().strip("'")
    word = word.replace("'s", "").replace("’s", "")

    if len(word) > 3 and word.endswith("s"):
        word = word[:-1]

    return word


def support_word_set(text):
    words = set()

    for word in words_from_text(text):
        normalized = normalize_support_word(word)

        if (
            not normalized
            or normalized in STOPWORDS
            or normalized in FILLER_WORDS
            or normalized in LOW_VALUE_TOPIC_WORDS
            or normalized in SOURCE_CONTEXT_WORDS
            or len(normalized) < 3
        ):
            continue

        words.add(normalized)

    return words


def title_support_details(title, transcript_text, source_title="", topic_terms=None):
    title_words = support_word_set(title)
    transcript_words = support_word_set(transcript_text)
    source_words = support_word_set(source_title)
    topic_words = support_word_set(" ".join(str(term).replace("_", " ") for term in topic_terms or []))
    non_source_title_words = title_words - source_words
    exact_support = title_words & transcript_words
    topic_support = non_source_title_words & topic_words & transcript_words
    alias_support = set()

    for word in non_source_title_words:
        aliases = TITLE_SUPPORT_ALIASES.get(word, set())

        if aliases and transcript_words & {normalize_support_word(alias) for alias in aliases}:
            alias_support.add(word)

    supported_title_words = exact_support | topic_support | alias_support
    checked_words = non_source_title_words or title_words
    support_ratio = len(supported_title_words & checked_words) / max(1, len(checked_words))

    return {
        "title_words": sorted(title_words),
        "transcript_words": sorted(transcript_words),
        "source_words": sorted(source_words),
        "checked_words": sorted(checked_words),
        "exact_support": sorted(exact_support),
        "topic_support": sorted(topic_support),
        "alias_support": sorted(alias_support),
        "support_ratio": float(support_ratio),
    }


def title_supported_by_clip(title, transcript_text, source_title="", topic_terms=None):
    title = compact_text(clean_transcript_text(title), 96)

    if not title:
        return False

    details = title_support_details(title, transcript_text, source_title, topic_terms)
    checked_words = set(details["checked_words"])

    if not checked_words:
        return False

    exact_count = len(details["exact_support"])
    alias_count = len(details["alias_support"])
    topic_count = len(details["topic_support"])

    if exact_count >= 2:
        return True

    if exact_count >= 1 and len(checked_words) <= 3:
        return True

    if exact_count >= 1 and details["support_ratio"] >= 0.34:
        return True

    if alias_count >= 1 and exact_count + topic_count + alias_count >= 2:
        return True

    return False


def transcript_has_theme_relevance(theme, text):
    theme = str(theme or "").strip().lower()
    words = support_word_set(text)
    positive_words = THEME_RELEVANCE_WORDS.get(theme, set())

    if not positive_words:
        return True

    positive_hits = words & {normalize_support_word(word) for word in positive_words}
    mismatch_hits = words & {normalize_support_word(word) for word in CROSS_THEME_MISMATCH_WORDS.get(theme, set())}

    if len(mismatch_hits) >= 2:
        if theme == "technology_ai" and positive_hits <= {"machine", "product"}:
            return False
        if not positive_hits:
            return False

    if positive_hits:
        return True

    if len(mismatch_hits) >= 2:
        return False

    return False


def transcript_specific_title_for_theme(theme, text):
    theme = str(theme or "").strip().lower()
    lower = clean_transcript_text(text).lower()

    if theme == "comedy":
        if "embarrassing story" in lower and "sidetrack" in lower:
            return "The Embarrassing UFC Sidetrack Story"

        if "born in italy" in lower and ("colorado" in lower or "army" in lower or "base" in lower):
            return "The Italy Childhood Story"

        if ("john benet" in lower or "jonbenet" in lower) and "jazz singer" in lower:
            return "The JonBenet Jazz Singer Joke"

        if "switch me out" in lower and ("voice" in lower or "trailer" in lower or "animation" in lower):
            return "Tony Hale's Toy Story Voice Panic"

        if "raw milk" in lower and ("pasteurized" in lower or "homogenized" in lower or "shelf" in lower):
            return "The Raw Milk Debate Gets Weird"

        if "cleaning lady" in lower:
            return "Cleaning For The Cleaning Lady"

        if "like a rolling stone" in lower and ("quiz" in lower or "check it out" in lower):
            return "The Rolling Stone Quiz Bit"

        if "mobbed" in lower and ("ellis" in lower or "kenny" in lower or "larry" in lower):
            return "Getting Mobbed By Fans"

        if "out into song" in lower or ("singing" in lower and "set-up" in lower):
            return "Amy Adams' Singing Setup"

        if "banned from the chicago theater" in lower or ("madison square garden" in lower and "ass crack" in lower):
            return "Thomas Lennon's Banned Theater Story"

    if theme == "health_fitness":
        if re.search(r"\b(eaa|eaas|leucine|lucine)\b", lower):
            return "EAAs And Leucine Matter"

        if "range of motion" in lower and ("physio ball" in lower or "hip" in lower or "feet" in lower):
            return "The Range Of Motion People Miss"

    if theme == "sports":
        if ("cooper flag" in lower or "cooper flagg" in lower) and ("five of 21" in lower or "field" in lower or "debut" in lower):
            return "Cooper Flagg's Rough Debut"

        if "brandon aiyuk" in lower or ("niners" in lower and ("bad mouthing" in lower or "last rodeo" in lower)):
            return "Brandon Aiyuk's 49ers Problem"

        if "supplemental draft" in lower or ("bookie" in lower and "nfl" in lower):
            return "The NFL Supplemental Draft Question"

        if ("mikal" in lower or "mikhail" in lower) and ("knicks" in lower or "championship" in lower):
            return "Mikal Bridges' Knicks Championship Moment"

        if "titans" in lower and "covid" in lower and re.search(r"\b(practic|positive|pittsburgh|steelers)\b", lower):
            return "The Titans COVID Practice Problem"

        if "nascar" in lower and ("horsepower" in lower or "stock car" in lower or "dirt track" in lower):
            return "NASCAR Horsepower Changes The Race"

    if theme == "finance":
        if "value stock is simply one that looks cheap" in lower:
            return "What Makes A Stock A Value Stock"

        if "short memories" in lower and ("must-own stock" in lower or "palantir" in lower):
            return "Investors Forget Must-Own Stocks Fast"

        if "post tax income" in lower and ("save 30%" in lower or "take-home pay" in lower or "saving" in lower):
            return "The Savings Rate Math People Miss"

        if "corporate stocks" in lower and ("mutual funds" in lower or "hedge funds" in lower):
            return "Institutional Investors Control The Market"

        if (
            ("rent" in lower or "rental" in lower)
            and ("home price" in lower or "median home" in lower or "cash flow" in lower or "afford" in lower)
        ):
            return "Home Prices Change The Rental Math"

    if theme == "popculture":
        if "methadone clinic" in lower and "jackass" in lower:
            return "How The Jackass Crew Actually Met"

        if "candy tier list" in lower:
            return "The Candy Tier List Went Sideways"

        if "sleeper pick" in lower and ("four" in lower or "jackass" in lower):
            return "Jackass 4 Became The Sleeper Pick"

        if "k-pop idol" in lower and ("south korea" in lower or "moved alone" in lower):
            return "Yunjin Moved To Korea Alone For K-Pop"

        if "google trends" in lower and ("career" in lower or "searching" in lower):
            return "Yunjin Reacts To Her Google Searches"

        if "out into song" in lower or ("singing" in lower and "set-ups" in lower):
            return "Amy Adams Keeps Turning Setups Into Songs"

        if "beef with soccer" in lower:
            return "The Soccer Take That Started A Debate"

        if "put in a pause on this fight" in lower or ("floyd" in lower and "fight" in lower and "pause" in lower):
            return "Why Floyd's Fight Got Put On Pause"

        if "virtual reality" in lower and ("augmented reality" in lower or "2014" in lower):
            return "Zuckerberg's VR Bet Started In 2014"

        if "2012 represents a country" in lower or ("career" in lower and "2012" in lower and "competition" in lower):
            return "Roberto Carlos' 2012 Career Moment"

        if "pull it" in lower and ("workin" in lower or "workout" in lower):
            return "The Yard Workout Bit Got Weird"

    if theme == "technology_ai":
        if any(term in lower for term in ["steam machine", "fortnite", "grand theft", "gta", "dota"]):
            return ""

    return ""


def merge_title_topics(topic_terms, title, max_terms=10, source_text=""):
    title_terms = [
        word
        for word in words_from_text(title)
        if is_meaningful_topic_term(word)
    ]
    source_words = support_word_set(source_text)
    merged = []

    for term in list(topic_terms or []) + title_terms:
        key = str(term or "").strip()

        if not key:
            continue

        normalized_key = key.lower()

        if normalized_key in {item.lower() for item in merged}:
            continue

        if not is_meaningful_topic_term(key):
            continue

        if source_text and key in title_terms and normalize_support_word(key) not in source_words:
            continue

        merged.append(key)

        if len(merged) >= max_terms:
            break

    return merged


def topic_similarity(left_terms, right_terms):
    left = set(left_terms)
    right = set(right_terms)

    if not left or not right:
        return 0.0

    return len(left & right) / len(left | right)


def candidate_external_signal_score(candidate):
    signals = candidate.rank_signals or {}
    return max(
        float(getattr(candidate, "popularity_score", 0.0) or 0.0),
        float(signals.get("comment_topic_score") or 0.0) * 0.82,
    )


def candidate_theme_signal_payload(candidate):
    signals = candidate.rank_signals or {}
    payload = signals.get("theme_signals") or {}
    return payload if isinstance(payload, dict) else {}


def candidate_theme_positive_hits(candidate):
    payload = candidate_theme_signal_payload(candidate)
    theme_key = active_theme_name()
    profile_key = (active_theme_profile() or {}).get("profile", "")
    preferred_keys = {
        "positive_keyword_hits",
        "theme_hits",
        f"{theme_key}_hits",
        f"{profile_key}_hits",
        "finance_hits",
        "comedy_hits",
        "sports_hits",
        "health_fitness_hits",
        "culture_hits",
        "truecrime_hits",
        "gaming_hits",
    }
    hits = []

    for key, value in payload.items():
        key_text = str(key or "")
        if key_text not in preferred_keys:
            continue
        if any(blocked in key_text for blocked in ("negative", "risk", "review")):
            continue
        if isinstance(value, (list, tuple, set)):
            hits.extend(str(item).strip().lower() for item in value if str(item).strip())
        elif value:
            hits.append(str(value).strip().lower())

    return sorted(set(hits))


def candidate_theme_negative_hits(candidate):
    payload = candidate_theme_signal_payload(candidate)
    hits = []

    for key in ("negative_keyword_hits",):
        value = payload.get(key) or []
        if isinstance(value, (list, tuple, set)):
            hits.extend(str(item).strip().lower() for item in value if str(item).strip())
        elif value:
            hits.append(str(value).strip().lower())

    return sorted(set(hits))


def configured_source_tier(value):
    return str(value or "").strip().lower() in {"priority", "secondary", "legacy"}


def trust_configured_source_relevance():
    return os.getenv("SHORTFORM_TRUST_CONFIGURED_SOURCE_RELEVANCE", "1") != "0"


def candidate_from_configured_source(candidate):
    signals = candidate.rank_signals or {}
    return configured_source_tier(signals.get("source_tier"))


def candidate_theme_fit_ready(candidate):
    if trust_configured_source_relevance() and candidate_from_configured_source(candidate):
        return True

    signal_config = get_theme_signals(active_theme_name())

    if not signal_config.get("penalize_missing_theme_signal", True):
        return True

    theme_signal_score = float(getattr(candidate, "theme_signal_score", 0.0) or 0.0)
    positive_hits = candidate_theme_positive_hits(candidate)
    negative_hits = candidate_theme_negative_hits(candidate)
    concerns = {
        str(item).lower()
        for item in (candidate.rank_signals or {}).get("theme_signal_concerns", []) or []
    }
    external_signal = candidate_external_signal_score(candidate)
    min_signal = float(os.getenv("SHORTFORM_MIN_THEME_SIGNAL_SELECTION_SCORE", "0.24"))

    if negative_hits and len(positive_hits) < 2:
        return False

    if "weak theme-specific signal" in concerns and theme_signal_score < 0.34:
        return False

    if not positive_hits and theme_signal_score < max(0.40, min_signal):
        return False

    if theme_signal_score < min_signal and external_signal < 0.48:
        return False

    return True


def candidate_title_publishable_ready(candidate):
    return candidate_pre_render_copy_ready(candidate)


def candidate_pre_render_copy_review(candidate):
    title = str(getattr(candidate, "suggested_title", "") or "").strip()
    topic_terms = getattr(candidate, "topic_fingerprint", []) or []
    transcript = str(getattr(candidate, "transcript_excerpt", "") or "")
    source_title = str(getattr(candidate, "source_title", "") or "")
    signals = getattr(candidate, "rank_signals", {}) or {}
    try:
        quality = score_title_quality(active_theme_name(), title, topic_terms=topic_terms)
    except Exception:
        quality = {}

    if isinstance(signals, dict):
        signals["title_quality"] = dict(quality)

    min_specificity = 0.42 if active_theme_clip_limit() is None else 0.35

    try:
        publishable_bar = title_passes_publishable_bar(
            active_theme_name(),
            title,
            topic_terms=topic_terms,
            min_specificity=min_specificity,
        )
    except Exception:
        publishable_bar = False

    supported = bool(
        title
        and title_supported_by_clip(title, transcript, source_title, topic_terms)
    )
    too_close_to_source = title_too_close_to_source_title(title, source_title)
    severe_flags = [
        flag
        for flag in (
            "keyword_soup_title",
            "source_only_title",
            "machine_label_title",
            "source_title_like",
        )
        if quality.get(flag)
    ]
    soft_flags = [
        flag
        for flag in (
            "generic_title",
            "mechanical_title",
            "repetitive_title",
            "weak_template_title",
            "raw_dialogue_fragment",
            "overlong_title",
            "dangling_title",
            "asr_sentence_title",
        )
        if quality.get(flag)
    ]
    meaningful_title_words = normalized_title_compare_tokens(title)
    meaningful_transcript_words = {
        word
        for word in words_from_text(transcript)
        if word not in TITLE_STOPWORDS and len(word) > 3
    }
    topic_word_count = sum(
        1
        for term in topic_terms
        for word in words_from_text(str(term).replace("_", " "))
        if word not in TITLE_STOPWORDS and len(word) > 3
    )
    fallback_potential = clamp01(
        0.45 * min(1.0, len(meaningful_transcript_words) / 18.0)
        + 0.35 * min(1.0, topic_word_count / 8.0)
        + 0.20 * float(getattr(candidate, "text_score", 0.0) or 0.0)
    )
    specificity = float(quality.get("specificity", 0.0) or quality.get("specificity_score", 0.0) or 0.0)
    honesty = float(quality.get("honesty", 0.0) or 0.0)
    not_clickbait = 1.0 if quality.get("not_clickbait", True) else 0.0
    distinct_title = 0.0 if too_close_to_source else min(1.0, len(meaningful_title_words) / 5.0)
    score = (
        specificity * 0.28
        + honesty * 0.20
        + (1.0 if supported else 0.0) * 0.17
        + (1.0 if publishable_bar else 0.0) * 0.14
        + distinct_title * 0.09
        + not_clickbait * 0.05
        + fallback_potential * 0.07
    )
    score -= 0.15 * len(severe_flags)
    score -= 0.06 * len(soft_flags)

    if title and not supported:
        score -= 0.08

    if too_close_to_source:
        score -= 0.12

    if not title:
        score = max(score, fallback_potential * 0.58)

    score = clamp01(score)
    ready = score >= MIN_PRE_RENDER_COPY_SCORE and not (
        len(severe_flags) >= 2 and fallback_potential < 0.68
    )
    review = {
        "score": round(score, 4),
        "ready": bool(ready),
        "publishable_bar": bool(publishable_bar),
        "supported_by_clip": bool(supported),
        "specificity": round(specificity, 4),
        "honesty": round(honesty, 4),
        "fallback_potential": round(fallback_potential, 4),
        "too_close_to_source": bool(too_close_to_source),
        "severe_flags": severe_flags,
        "soft_flags": soft_flags,
        "minimum_score": MIN_PRE_RENDER_COPY_SCORE,
    }

    try:
        candidate.rank_signals = candidate.rank_signals or {}
        candidate.rank_signals["pre_render_copy_review"] = review
    except Exception:
        pass

    return review


def candidate_pre_render_copy_ready(candidate):
    review = candidate_pre_render_copy_review(candidate)

    if review.get("ready"):
        return True

    transcript = str(getattr(candidate, "transcript_excerpt", "") or "")
    fallback_words = [word for word in words_from_text(transcript) if len(word) > 2]
    fallback_available = len(fallback_words) >= 8

    try:
        candidate.rank_signals = candidate.rank_signals or {}
        candidate.rank_signals["title_quality_advisory_only"] = True
        candidate.rank_signals["title_fallback_available"] = fallback_available
    except Exception:
        pass

    return fallback_available


def normalized_title_compare_tokens(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", str(text or "").lower())
    return [
        word.replace("'", "")
        for word in words
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]


def normalized_title_compare_text(text):
    return " ".join(normalized_title_compare_tokens(text))


def title_too_close_to_source_title(title, source_title):
    title_clean = normalized_title_compare_text(title)
    source_clean = normalized_title_compare_text(source_title)

    if not title_clean or not source_clean:
        return False

    if title_clean == source_clean:
        return True

    if len(title_clean) >= 24 and title_clean in source_clean:
        return True

    title_tokens = set(title_clean.split())
    source_tokens = set(source_clean.split())

    if len(title_tokens) >= 4 and title_tokens:
        overlap = len(title_tokens & source_tokens) / len(title_tokens)
        if overlap >= 0.86:
            return True

    return False


def candidate_selection_ready(candidate):
    signals = candidate.rank_signals or {}
    tier = signals.get("readiness_tier", "")
    readiness = float(getattr(candidate, "readiness_score", 0.0) or 0.0)
    external_signal = candidate_external_signal_score(candidate)
    hard_failures = signals.get("readiness_hard_failures", []) or []
    min_readiness = active_min_readiness_score()

    if tier == "reject" and external_signal < 0.34:
        return False

    if any("sponsor/ad-read" in str(item).lower() for item in hard_failures):
        return False

    if not candidate_theme_fit_ready(candidate):
        return False

    if not candidate_title_publishable_ready(candidate):
        return False

    if (
        not trust_configured_source_relevance()
        or not candidate_from_configured_source(candidate)
    ) and not transcript_has_theme_relevance(active_theme_name(), candidate.transcript_excerpt):
        return False

    if hard_failures and readiness < min_readiness and external_signal < 0.42:
        return False

    if readiness < min_readiness and (external_signal < 0.38 or readiness < 0.54):
        return False

    if active_theme_clip_limit() is None:
        backlog_min_readiness = max(min_readiness, UNLIMITED_BACKLOG_MIN_READINESS_SCORE)
        if trust_configured_source_relevance() and candidate_from_configured_source(candidate):
            backlog_min_readiness = min(backlog_min_readiness, min_readiness)
            backlog_external_threshold = 0.46
        else:
            backlog_external_threshold = 0.62

        if readiness < backlog_min_readiness and external_signal < backlog_external_threshold:
            return False

        text_score = float(getattr(candidate, "text_score", 0.0) or 0.0)
        if text_score < UNLIMITED_BACKLOG_MIN_TEXT_SCORE:
            if (
                text_score < UNLIMITED_BACKLOG_MIN_TEXT_SCORE * 0.75
                or readiness < backlog_min_readiness + 0.06
                or external_signal < (0.42 if candidate_from_configured_source(candidate) else 0.58)
            ):
                return False

    if candidate.first_second_qc and not candidate.first_second_qc.get("passed", True):
        intro_mode = (candidate.rank_signals or {}).get("recommended_intro_mode", "")

        if intro_mode == "cold_open":
            return False

    if candidate.reused_content_risk >= 0.42 and get_risk_controls(active_theme_name()).get("requires_claim_context"):
        return False

    return True


def candidate_fast_visual_risk(candidate):
    """Cheap prior for render failure risk; final acceptance still comes from frame QC."""
    signals = getattr(candidate, "rank_signals", {}) or {}
    first_second_qc = getattr(candidate, "first_second_qc", {}) or {}
    source_title = str(getattr(candidate, "source_title", "") or "").lower()
    excerpt = str(getattr(candidate, "transcript_excerpt", "") or "").lower()
    haystack = f"{source_title} {excerpt}"
    risk = 0.0

    if first_second_qc and not first_second_qc.get("passed", True):
        risk += 0.10

    if signals.get("recommended_intro_mode") == "cold_open":
        risk += 0.04

    for phrase, penalty in [
        ("bodycam", 0.08),
        ("body cam", 0.08),
        ("dashcam", 0.08),
        ("dash cam", 0.08),
        ("surveillance", 0.08),
        ("security camera", 0.08),
        ("cctv", 0.08),
        ("court audio", 0.10),
        ("911 call", 0.09),
        ("slideshow", 0.10),
        ("b-roll", 0.08),
        ("stock footage", 0.08),
        ("body language experts", 0.05),
    ]:
        if phrase in haystack:
            risk += penalty

    duration = max(0.0, float(getattr(candidate, "end_time", 0.0) or 0.0) - float(getattr(candidate, "start_time", 0.0) or 0.0))

    if duration >= active_max_clip_duration() - 2:
        risk += 0.03

    return clamp01(risk)


def candidate_copy_specificity_score(candidate):
    review = candidate_pre_render_copy_review(candidate)
    title = str(getattr(candidate, "suggested_title", "") or "")
    terms = getattr(candidate, "topic_fingerprint", []) or []
    quality = (getattr(candidate, "rank_signals", {}) or {}).get("title_quality") or {}

    if not isinstance(quality, dict) or not quality:
        try:
            quality = score_title_quality(active_theme_name(), title, topic_terms=terms)
        except Exception:
            quality = {}

    score = float(quality.get("specificity", 0.0) or quality.get("specificity_score", 0.0) or 0.0)

    if not score:
        meaningful_words = normalized_title_compare_tokens(title)
        score = min(1.0, len(meaningful_words) / 7.0)

    if quality.get("machine_label_title") or quality.get("source_only_title"):
        score *= 0.55

    if quality.get("dangling_title") or quality.get("asr_sentence_title"):
        score *= 0.72

    return clamp01(score * 0.72 + float(review.get("fallback_potential") or 0.0) * 0.28)


def candidate_render_priority_score(candidate):
    readiness = float(getattr(candidate, "readiness_score", 0.0) or 0.0)
    external = candidate_external_signal_score(candidate)
    boundary = float(getattr(candidate, "boundary_score", 0.0) or 0.0)
    arc = float(getattr(candidate, "arc_score", 0.0) or 0.0)
    text = float(getattr(candidate, "text_score", 0.0) or 0.0)
    opening = float(getattr(candidate, "opening_score", 0.0) or 0.0)
    pacing = float(getattr(candidate, "pacing_score", 0.0) or 0.0)
    duration = float(getattr(candidate, "duration_score", 0.0) or 0.0)
    specificity = candidate_copy_specificity_score(candidate)
    copy_review = candidate_pre_render_copy_review(candidate)
    copy_score = float(copy_review.get("score") or 0.0)
    visual_risk = candidate_fast_visual_risk(candidate)

    return clamp01(
        float(candidate.score) * 0.28
        + readiness * 0.18
        + external * 0.13
        + boundary * 0.09
        + arc * 0.08
        + text * 0.06
        + opening * 0.04
        + pacing * 0.03
        + duration * 0.02
        + specificity * 0.05
        + copy_score * 0.12
        - visual_risk * 0.16
    )


def candidate_ranking_key(candidate):
    return (
        candidate_render_priority_score(candidate),
        float(candidate.score),
        float(getattr(candidate, "readiness_score", 0.0) or 0.0),
        candidate_external_signal_score(candidate),
        float(getattr(candidate, "arc_score", 0.0) or 0.0),
        -candidate_fast_visual_risk(candidate),
    )


def apply_configured_source_theme_signal_floor(theme_signal_result, source_tier):
    result = dict(theme_signal_result or {})
    raw_score = float(result.get("theme_signal_score") or 0.0)

    if not trust_configured_source_relevance() or not configured_source_tier(source_tier):
        return result

    adjusted_score = max(raw_score, CONFIGURED_SOURCE_THEME_SIGNAL_FLOOR)
    result["theme_signal_score"] = adjusted_score
    signals = dict(result.get("signals") or {})
    signals["configured_source_relevance_trusted"] = True
    signals["raw_theme_signal_score"] = raw_score
    result["signals"] = signals
    concerns = [
        concern
        for concern in result.get("concerns", []) or []
        if str(concern).lower() != "weak theme-specific signal"
    ]
    result["concerns"] = concerns
    return result


def load_existing_theme_topic_fingerprints():
    fingerprints = []

    if not metadata_path or not os.path.isdir(metadata_path):
        return fingerprints

    for filename in os.listdir(metadata_path):
        if not filename.endswith("_clip_review.json"):
            continue

        try:
            with open(os.path.join(metadata_path, filename), "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        for clip in payload.get("selected", []):
            terms = clip.get("topic_fingerprint", [])

            if terms:
                fingerprints.append(terms)

    return fingerprints


def explain_hook(text, text_details, opening_score, audio_score):
    normalized_text = text.lower()

    if text_details.get("hook_type"):
        return f"{text_details['hook_type']} hook"

    for pattern in HOOK_PATTERNS:
        match = re.search(pattern, normalized_text)

        if match:
            return f"hook phrase: {match.group(0)}"

    if text.count("?"):
        return "question creates curiosity"

    for word in words_from_text(text):
        if word in CONFLICT_KEYWORDS:
            return f"conflict word: {word}"
        if word in EMOTION_KEYWORDS:
            return f"emotion word: {word}"
        if word in TOPIC_KEYWORDS:
            return f"mainstream topic: {word}"

    if text_details.get("specificity_score", 0) >= 0.45:
        return "specific numbers or money"

    if opening_score >= 0.65:
        return "strong opening"

    if audio_score >= 0.65:
        return "high audio energy"

    return "balanced interest signals"


def detect_hook_type(text):
    normalized_text = text.lower()

    for hook_type, pattern in HOOK_TYPE_PATTERNS:
        if re.search(pattern, normalized_text):
            return hook_type

    return ""


def score_boundary_quality(matching_segments, clip_start, clip_end):
    if not matching_segments:
        return 0.0, ["no transcript segments"]

    flags = []
    score = 1.0
    opening_word = first_spoken_word(matching_segments[0]["text"])
    closing_text = matching_segments[-1]["text"].strip()

    if opening_word in WEAK_START_WORDS:
        score -= 0.22
        flags.append(f"context opener: {opening_word}")

    if opening_word in FILLER_OPENERS:
        score -= 0.12
        flags.append(f"soft opener: {opening_word}")

    if closing_text and closing_text[-1] not in ".?!":
        score -= 0.10
        flags.append("ending may be mid-thought")

    duration = clip_end - clip_start

    if duration > 56:
        score -= 0.08
        flags.append("near max duration")

    if duration < 34:
        score -= 0.08
        flags.append("short context window")

    return max(0.0, min(1.0, score)), flags


def text_for_segment_slice(segments, start_time, end_time):
    return clean_transcript_text(" ".join(
        segment["text"]
        for segment in segments
        if segment["end"] > start_time and segment["start"] < end_time
    ))


def score_standalone_context(text, opening_word):
    words = words_from_text(text)

    if not words:
        return 0.0

    pronoun_hits = sum(1 for word in words[:55] if word in {"he", "she", "they", "them", "that", "this", "it", "those"})
    named_or_specific_hits = len(re.findall(r"\b[A-Z][a-z]{2,}\b|\b\d+[\d,.]*%?\b|\$\s?\d+", text))
    context_score = 0.72

    if opening_word in WEAK_START_WORDS:
        context_score -= 0.22

    if pronoun_hits >= 9 and named_or_specific_hits <= 1:
        context_score -= 0.22
    elif pronoun_hits >= 6 and named_or_specific_hits == 0:
        context_score -= 0.14

    if named_or_specific_hits >= 2:
        context_score += 0.13

    return max(0.0, min(1.0, context_score))


def score_retention_arc(text, matching_segments, clip_start, clip_end, text_details):
    duration = max(1.0, clip_end - clip_start)
    first_cut = clip_start + duration * 0.32
    second_cut = clip_start + duration * 0.70
    opening_text = text_for_segment_slice(matching_segments, clip_start, first_cut)
    middle_text = text_for_segment_slice(matching_segments, first_cut, second_cut)
    ending_text = text_for_segment_slice(matching_segments, second_cut, clip_end)
    normalized_full = text.lower()
    normalized_middle = middle_text.lower()
    normalized_ending = ending_text.lower()
    opening_word = first_spoken_word(text)

    hook_score = max(
        score_opening_text(opening_text or text[:360]),
        float(text_details.get("hook_score", 0.0)),
    )
    escalation_hits = len(re.findall(
        r"\b(but|however|actually|the problem|the truth|because|so|which means|that means|then|until|suddenly)\b",
        normalized_middle,
    ))
    escalation_score = saturating_score(escalation_hits, 2.4)
    payoff_hits = len(re.findall(
        r"\b(that'?s why|the answer|which means|that means|the point|so now|because|therefore|as a result|what happens)\b",
        normalized_ending,
    ))
    payoff_score = max(
        saturating_score(payoff_hits, 1.8),
        float(text_details.get("resolution_score", 0.0)) * 0.82,
    )
    curiosity_gap = 1.0 if re.search(r"\b(why|how|what if|the reason|nobody|most people|the problem|the truth)\b", normalized_full[:420]) else 0.0
    standalone_score = score_standalone_context(text, opening_word)
    sentence_score = float(text_details.get("sentence_completeness_score", 0.0))
    dialogue_score = float(text_details.get("dialogue_score", 0.0))

    if ending_text.strip() and ending_text.strip()[-1] in ".?!":
        payoff_score = min(1.0, payoff_score + 0.10)

    arc_score = (
        0.24 * hook_score
        + 0.19 * escalation_score
        + 0.21 * payoff_score
        + 0.15 * standalone_score
        + 0.10 * sentence_score
        + 0.06 * dialogue_score
        + 0.05 * curiosity_gap
    )

    flags = []
    if hook_score < 0.32:
        flags.append("weak opening hook")
    if payoff_score < 0.28:
        flags.append("weak payoff")
    if standalone_score < 0.45:
        flags.append("needs too much outside context")

    return max(0.0, min(1.0, arc_score)), {
        "arc_hook_score": float(hook_score),
        "arc_escalation_score": float(escalation_score),
        "arc_payoff_score": float(payoff_score),
        "arc_standalone_score": float(standalone_score),
        "arc_curiosity_gap": float(curiosity_gap),
        "arc_flags": flags,
    }


def repeated_ngram_ratio(words, n=3):
    if len(words) < n * 2:
        return 0.0

    grams = [
        tuple(words[index:index + n])
        for index in range(0, len(words) - n + 1)
    ]

    if not grams:
        return 0.0

    unique_count = len(set(grams))
    return max(0.0, min(1.0, 1.0 - unique_count / len(grams)))


def score_clip_readiness(
    text,
    matching_segments,
    clip_start,
    clip_end,
    text_details,
    arc_details,
    boundary_score,
    boundary_flags,
    opening_score,
    comment_score,
    popularity_score,
    comment_topic_score,
):
    words = words_from_text(text)
    word_count = len(words)
    duration = max(1.0, clip_end - clip_start)
    first_word = first_spoken_word(text)
    last_words = words[-5:]
    normalized_text = text.lower()
    sponsor_hits = [
        pattern
        for pattern in SPONSOR_READ_PATTERNS
        if re.search(pattern, normalized_text, flags=re.I)
    ]
    repetition_ratio = repeated_ngram_ratio(words, n=3)
    filler_ratio = float(text_details.get("filler_ratio") or 0.0)
    hook_score = max(
        float(arc_details.get("arc_hook_score") or 0.0),
        float(text_details.get("hook_score") or 0.0),
        float(opening_score or 0.0),
    )
    payoff_score = max(
        float(arc_details.get("arc_payoff_score") or 0.0),
        float(text_details.get("payoff_score") or 0.0),
        float(text_details.get("resolution_score") or 0.0),
    )
    context_score = float(arc_details.get("arc_standalone_score") or 0.0)
    completeness_score = float(text_details.get("sentence_completeness_score") or 0.0)
    clarity_score = float(text_details.get("clarity_score") or 0.0)
    specificity_score = float(text_details.get("specificity_score") or 0.0)
    claim_score = float(text_details.get("claim_score") or 0.0)
    conflict_score = float(text_details.get("conflict_score") or 0.0)
    emotion_score = float(text_details.get("emotion_score") or 0.0)
    dialogue_score = float(text_details.get("dialogue_score") or 0.0)
    signal_score = max(
        float(popularity_score or 0.0),
        float(comment_score or 0.0) * 0.74,
        float(comment_topic_score or 0.0) * 0.82,
    )
    substance_score = max(
        specificity_score * 0.72 + claim_score * 0.28,
        conflict_score * 0.58 + emotion_score * 0.42,
        signal_score,
    )
    duration_fit = score_duration(duration)
    pacing_fit = score_spoken_pacing(text, duration)
    weak_end = bool(last_words and last_words[-1] in {"and", "but", "because", "so", "if", "when", "that", "which"})
    quoted_or_named = bool(re.search(r"\b[A-Z][a-z]{2,}\b|\"|'", text))
    evidence_score = max(signal_score, substance_score, specificity_score, 0.16 if quoted_or_named else 0.0)

    readiness_score = (
        0.18 * hook_score
        + 0.17 * payoff_score
        + 0.15 * context_score
        + 0.13 * completeness_score
        + 0.10 * boundary_score
        + 0.09 * clarity_score
        + 0.08 * substance_score
        + 0.05 * pacing_fit
        + 0.03 * duration_fit
        + 0.02 * dialogue_score
    )

    concerns = []
    hard_failures = []

    if hook_score < 0.30:
        concerns.append("weak first-three-seconds hook")

    if payoff_score < 0.28:
        concerns.append("weak ending payoff")

    if context_score < 0.42:
        concerns.append("needs outside context")

    if completeness_score < 0.46:
        concerns.append("incomplete sentence arc")

    if boundary_score < 0.52:
        concerns.extend(boundary_flags[:2])

    if first_word in WEAK_START_WORDS or first_word in FILLER_OPENERS:
        concerns.append(f"soft or dependent opener: {first_word}")

    if weak_end:
        concerns.append("ending likely trails into next thought")

    if filler_ratio > 0.30:
        concerns.append("too much filler language")
        readiness_score -= min(0.12, (filler_ratio - 0.30) * 0.7)

    if repetition_ratio > 0.18:
        concerns.append("repetitive transcript language")
        readiness_score -= min(0.14, (repetition_ratio - 0.18) * 0.8)

    if word_count < 42:
        concerns.append("thin transcript context")
        readiness_score -= 0.05

    if evidence_score < 0.20:
        concerns.append("low evidence of why viewers would care")
        readiness_score -= 0.06

    if hook_score < 0.22 and signal_score < 0.24:
        hard_failures.append("no strong hook or external audience signal")

    if payoff_score < 0.18 and context_score < 0.48:
        hard_failures.append("no clean payoff and weak standalone context")

    if boundary_score < 0.38:
        hard_failures.append("bad transcript boundaries")

    if filler_ratio > 0.40 or repetition_ratio > 0.30:
        hard_failures.append("likely filler/repetition, not a clip")

    if sponsor_hits:
        concerns.append("sponsor/ad-read language")
        hard_failures.append("sponsor/ad-read segment")
        readiness_score -= 0.28

    readiness_score = max(0.0, min(1.0, readiness_score))

    if hard_failures:
        tier = "reject"
    elif readiness_score >= 0.84:
        tier = "elite"
    elif readiness_score >= 0.76:
        tier = "strong"
    elif readiness_score >= 0.66:
        tier = "usable"
    elif readiness_score >= 0.56:
        tier = "review"
    else:
        tier = "weak"

    return readiness_score, {
        "readiness_score": float(readiness_score),
        "readiness_tier": tier,
        "readiness_concerns": concerns[:8],
        "readiness_hard_failures": hard_failures,
        "sponsor_read_hits": sponsor_hits[:6],
        "readiness_repetition_ratio": float(repetition_ratio),
        "readiness_signal_score": float(signal_score),
        "readiness_substance_score": float(substance_score),
        "readiness_evidence_score": float(evidence_score),
        "readiness_hook_score": float(hook_score),
        "readiness_payoff_score": float(payoff_score),
        "readiness_context_score": float(context_score),
        "readiness_completeness_score": float(completeness_score),
        "readiness_clarity_score": float(clarity_score),
    }


def naturalize_clip_window(segments, provisional_start, duration, total_duration):
    window_end = min(provisional_start + duration, total_duration)
    window_segments = [
        segment
        for segment in segments
        if segment["end"] > provisional_start and segment["start"] < window_end
    ]

    if not window_segments:
        return None

    first_segment = next(
        (
            segment
            for segment in window_segments
            if segment["end"] > provisional_start + 0.25 and segment["text"].strip()
        ),
        window_segments[0],
    )
    first_index = segments.index(first_segment)
    opening_word = first_spoken_word(first_segment["text"])

    if opening_word in WEAK_START_WORDS or opening_word in FILLER_OPENERS:
        if first_index > 0:
            previous_segment = segments[first_index - 1]
            gap = float(first_segment["start"]) - float(previous_segment["end"])

            if gap <= 1.8 and float(first_segment["start"]) - float(previous_segment["start"]) <= 9:
                first_segment = previous_segment

    clip_start = max(0.0, float(first_segment["start"]) - 0.22)
    clip_end_limit = min(clip_start + duration, total_duration)
    matching_segments = [
        segment
        for segment in segments
        if segment["end"] > clip_start and segment["start"] < clip_end_limit
    ]

    completed_segments = [
        segment
        for segment in matching_segments
        if segment["end"] <= clip_end_limit
    ]

    if completed_segments:
        clip_end = min(total_duration, float(completed_segments[-1]["end"]) + 0.24)
    else:
        clip_end = clip_end_limit

    matching_segments = [
        segment
        for segment in matching_segments
        if segment["start"] < clip_end and segment["end"] <= clip_end + 0.05
    ]

    max_clip_duration = active_max_clip_duration()

    if clip_end - clip_start > max_clip_duration:
        clip_end = clip_start + max_clip_duration
        matching_segments = [
            segment
            for segment in matching_segments
            if segment["end"] <= clip_end + 0.05
        ]

    while matching_segments:
        closing_text = matching_segments[-1]["text"].strip()

        if closing_text and closing_text[-1] in ".?!":
            break

        next_segment = next(
            (
                segment
                for segment in segments
                if segment["start"] >= matching_segments[-1]["end"]
            ),
            None,
        )

        if not next_segment:
            break

        gap = float(next_segment["start"]) - float(matching_segments[-1]["end"])
        proposed_end = float(next_segment["end"]) + 0.18

        if gap > 1.4 or proposed_end - clip_start > max_clip_duration:
            break

        matching_segments.append(next_segment)
        clip_end = min(total_duration, proposed_end)

    return clip_start, clip_end, matching_segments


def build_suggested_copy(text, hook_reason, topic_terms, text_details=None, source_record=None):
    text = clean_transcript_text(text)
    text_details = text_details or {}
    source_record = source_record or {}
    archetype = text_details.get("theme_archetype") or text_details.get("hook_type", "") or "clip"
    clip_stub = {
        "transcript_excerpt": text[:900],
        "topic_fingerprint": topic_terms,
        "hook_reason": hook_reason,
        "duration": text_details.get("duration", 45),
        "source_title": source_record.get("title", ""),
    }
    generated_title = generate_title(
        active_theme_name(),
        archetype=archetype,
        clip=clip_stub,
        source_record=source_record,
        signals={"topic_terms": topic_terms},
    )
    transcript_title = transcript_specific_title_for_theme(active_theme_name(), text)
    title_quality = score_title_quality(active_theme_name(), generated_title, topic_terms=topic_terms)
    sentences = [
        compact_text(sentence, 78)
        for sentence in re.split(r"(?<=[.?!])\s+", text)
        if len(sentence.strip()) >= 18
    ]

    title = ""

    if transcript_title:
        transcript_title_quality = score_title_quality(active_theme_name(), transcript_title, topic_terms=topic_terms)

        if (
            transcript_title_quality["specificity"] >= 0.38
            and transcript_title_quality.get("honesty", 0.0) >= 0.70
            and not transcript_title_quality.get("generic_title")
            and not transcript_title_quality.get("mechanical_title")
            and not transcript_title_quality.get("repetitive_title")
            and transcript_title_quality.get("theme_native_title", True)
            and transcript_title_quality.get("not_clickbait", True)
            and title_supported_by_clip(transcript_title, text, source_record.get("title", ""), topic_terms)
        ):
            title = transcript_title

    if not title and (
            title_quality["specificity"] >= 0.38
            and title_quality.get("honesty", 0.0) >= 0.70
            and not title_quality.get("generic_title")
            and not title_quality.get("mechanical_title")
            and not title_quality.get("repetitive_title")
            and title_quality.get("theme_native_title", True)
            and title_quality.get("not_clickbait", True)
            and title_supported_by_clip(generated_title, text, source_record.get("title", ""), topic_terms)
    ):
        title = generated_title

    if not title:
        source_title = clean_transcript_text(source_record.get("title", ""))
        source_title = re.split(r"\s+\|\s+", source_title, maxsplit=1)[0]
        source_title = re.sub(r"(?i)\b(full show|full episode|video podcast|audio only|audio|podcast)\b", "", source_title)
        source_title = re.sub(r"(?i)\b(the rich eisen show|smartless|the breakfast club)\b", "", source_title)
        source_title = compact_text(source_title.strip(" -:|"), 76)
        source_quality = score_title_quality(active_theme_name(), source_title, topic_terms=topic_terms)

        if (
            source_title
            and len(words_from_text(source_title)) >= 4
            and source_quality.get("honesty", 0.0) >= 0.68
            and not source_quality.get("raw_dialogue_fragment")
            and not source_quality.get("generic_title")
            and not source_quality.get("mechanical_title")
            and source_quality.get("not_clickbait", True)
            and title_supported_by_clip(source_title, text, source_record.get("title", ""), topic_terms)
        ):
            title = source_title

    if not title:
        for sentence in sentences[:5]:
            sentence_terms = set(words_from_text(sentence))
            signal_terms = CONFLICT_KEYWORDS | EMOTION_KEYWORDS | TOPIC_KEYWORDS
            sentence_quality = score_title_quality(active_theme_name(), sentence, topic_terms=topic_terms)

            if (
                ("?" in sentence or bool(sentence_terms & signal_terms))
                and sentence_quality.get("honesty", 0.0) >= 0.70
                and not sentence_quality.get("raw_dialogue_fragment")
                and not sentence_quality.get("generic_title")
                and not sentence_quality.get("mechanical_title")
                and title_supported_by_clip(sentence, text, source_record.get("title", ""), topic_terms)
            ):
                title = sentence
                break

    if not title:
        fallback_options = [
            generated_title,
            f"The {str(archetype).replace('_', ' ').title()} Worth Rewatching",
            f"The {active_theme_name().replace('_', ' ').title()} Moment Worth Seeing",
        ]

        for fallback_title in fallback_options:
            fallback_title = compact_text(fallback_title, 78)
            fallback_quality = score_title_quality(active_theme_name(), fallback_title, topic_terms=topic_terms)

            if (
                fallback_title
                and fallback_quality.get("honesty", 0.0) >= 0.70
                and not fallback_quality.get("generic_title")
                and not fallback_quality.get("mechanical_title")
                and not fallback_quality.get("raw_dialogue_fragment")
                and fallback_quality.get("not_clickbait", True)
                and title_supported_by_clip(fallback_title, text, source_record.get("title", ""), topic_terms)
            ):
                title = fallback_title
                break

    if not title:
        title = "The Moment Worth Rewatching"

    if title and title[-1] not in ".?!":
        title = title.rstrip(",;:")

    title = polish_headline_title(title)

    hook_type = text_details.get("hook_type", "")
    hook_label = (
        hook_type.replace("_", " ")
        or hook_reason.replace("hook phrase: ", "").replace("mainstream topic: ", "")
    )
    caption = compact_text(f"{title} | {hook_label}", 140)
    description = generate_description(
        active_theme_name(),
        {**clip_stub, "suggested_title": title},
        transformation_notes=["theme-specific title", "source-context packaging"],
    )
    hashtags = generate_hashtags(active_theme_name(), archetype=archetype, topic_terms=topic_terms)

    return title, caption, hashtags[:7], description


def refresh_cached_candidate_copy(candidate, source_record=None):
    source_record = source_record or {}

    try:
        if candidate_title_is_publishable(candidate):
            return candidate
    except Exception:
        pass

    original_title = candidate.suggested_title
    text_details = {
        "duration": max(0.1, float(candidate.end_time) - float(candidate.start_time)),
        "theme_archetype": (candidate.rank_signals or {}).get("theme_archetype")
        or (candidate.rank_signals or {}).get("archetype")
        or (candidate.rank_signals or {}).get("hook_type")
        or "clip",
        "hook_type": (candidate.rank_signals or {}).get("hook_type", ""),
    }

    title, caption, hashtags, description = build_suggested_copy(
        candidate.transcript_excerpt,
        candidate.hook_reason,
        candidate.topic_fingerprint,
        text_details=text_details,
        source_record={
            **source_record,
            "title": source_record.get("title") or candidate.source_title,
        },
    )

    candidate.suggested_title = title
    candidate.suggested_caption = caption
    candidate.hashtags = hashtags
    candidate.suggested_description = description
    candidate.rank_signals = candidate.rank_signals or {}

    try:
        if candidate_title_is_publishable(candidate):
            if original_title and original_title != title:
                candidate.rank_signals["retitled_from_cache"] = True
                candidate.rank_signals["previous_suggested_title"] = original_title[:120]
            return candidate
    except Exception:
        pass

    candidate.rank_signals["retitle_attempted_from_cache"] = True
    return candidate


def candidate_to_dict(candidate):
    return asdict(candidate)


def clip_score_cache_path(cleaned_title):
    if not transcriptions_path:
        return ""

    return os.path.join(
        transcriptions_path,
        f"{cleaned_title}_clip_scores.json",
    )


def has_cached_clip_scores(cleaned_title):
    path = clip_score_cache_path(cleaned_title)
    return bool(path and os.path.exists(path))


def candidate_from_cached_dict(payload):
    fields = CandidateClip.__dataclass_fields__
    values = {
        key: payload[key]
        for key in fields
        if key in payload
    }
    return CandidateClip(**values)


def source_guard_empty_scored_source(cleaned_title, video_record, video_url, source_state_key, negative_hits, cache_status):
    negative_hits = [str(hit) for hit in (negative_hits or [])]
    video_record["_candidate_count"] = 0
    video_record["_theme_ranked_candidate_count"] = 0
    video_record["_last_cleaned_title"] = cleaned_title
    metrics = video_record.setdefault("_processing_metrics", {})
    metrics.update({
        "scoring_seconds": 0.0,
        "transcript_stage_seconds": 0.0,
        "audio_feature_stage_seconds": 0.0,
        "candidate_build_seconds": 0.0,
        "candidate_window_policy": {"mode": "source_disqualified"},
        "candidate_count": 0,
        "theme_ranked_candidate_count": 0,
        "slow_source_threshold_seconds": SLOW_SOURCE_REVIEW_SECONDS,
        "slow_source_review": False,
        "source_disqualified": True,
        "negative_source_signals": negative_hits,
        "cache_status": cache_status,
    })

    if cleaned_title and transcriptions_path:
        os.makedirs(transcriptions_path, exist_ok=True)
        scoring_filepath = clip_score_cache_path(cleaned_title)
        with open(scoring_filepath, "w", encoding="utf-8") as f:
            json.dump({
                "scoring_model_version": SCORING_MODEL_VERSION,
                "candidate_window_policy": {"mode": "source_disqualified"},
                "selected": [],
                "top_candidates": [],
                "source_disqualified": True,
                "negative_source_signals": negative_hits,
                "cache_status": cache_status,
            }, f, indent=4)
        write_clip_review_exports(cleaned_title, [], [])
        write_source_dossier(
            cleaned_title=cleaned_title,
            source_record=video_record,
            popularity_profile={},
            candidates=[],
            selected_clips=[],
        )

    print(
        " -> Source skipped by theme guard "
        f"(negative source signals: {', '.join(negative_hits) or 'source_guard'})"
    )

    return {
        "state_key": source_state_key,
        "record": video_record,
        "video_filename": "",
        "video_url": video_url,
        "audio_filename": "",
        "cleaned_title": cleaned_title,
        "candidates": [],
    }


def load_cached_scored_source(cleaned_title, video_record, video_url, source_state_key):
    if not REUSE_CACHED_CLIP_SCORES:
        return None

    scoring_filepath = clip_score_cache_path(cleaned_title)
    if not scoring_filepath or not os.path.exists(scoring_filepath):
        return None

    disqualified, negative_hits = source_disqualified_by_theme(video_record, active_theme_name())
    if not disqualified:
        disqualified, negative_hits = source_quality_disqualification(video_record)
    if disqualified:
        print(
            "Cached clip score ignored because current theme guard now blocks this source: "
            f"{scoring_filepath}"
        )
        return source_guard_empty_scored_source(
            cleaned_title=cleaned_title,
            video_record=video_record,
            video_url=video_url,
            source_state_key=source_state_key,
            negative_hits=negative_hits,
            cache_status="cached_source_guard_disqualified",
        )

    with open(scoring_filepath, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if payload.get("scoring_model_version") != SCORING_MODEL_VERSION:
        print(
            "Clip score cache was created with older editorial settings; regenerating: "
            f"{scoring_filepath}\n"
        )
        return None

    if payload.get("source_disqualified"):
        negative_hits = payload.get("negative_source_signals") or []
        return source_guard_empty_scored_source(
            cleaned_title=cleaned_title,
            video_record=video_record,
            video_url=video_url,
            source_state_key=source_state_key,
            negative_hits=negative_hits,
            cache_status="cached_source_disqualified",
        )

    candidates_payload = (
        payload.get("all_candidates")
        or payload.get("top_candidates")
        or payload.get("selected")
        or []
    )
    candidates = []
    for item in candidates_payload:
        try:
            candidate = candidate_from_cached_dict(item)
        except TypeError:
            continue

        candidate.source_state_key = candidate.source_state_key or source_state_key
        candidate.source_video_url = candidate.source_video_url or video_url
        candidate.source_title = candidate.source_title or video_record.get("title", "")
        candidate.rank_signals["source_state_key"] = candidate.source_state_key
        candidate.rank_signals["source_title"] = candidate.source_title
        candidate = refresh_cached_candidate_copy(candidate, video_record)
        candidates.append(candidate)

    if not candidates:
        return None

    top_candidates = ranked_candidate_window(candidates, active_theme_candidates_per_video())
    video_record["_candidate_count"] = int(len(candidates_payload))
    video_record["_theme_ranked_candidate_count"] = int(len(top_candidates))
    video_record["_last_cleaned_title"] = cleaned_title
    metrics = video_record.setdefault("_processing_metrics", {})
    metrics["score_cache_reused"] = True
    metrics["score_cache_path"] = scoring_filepath
    metrics["theme_ranked_candidate_count"] = len(top_candidates)

    print(
        "Reused cached clip scores: "
        f"{scoring_filepath} ({len(top_candidates)} kept for theme ranking; "
        f"source cap={active_theme_candidates_per_video() or 'unlimited'})\n"
    )

    return {
        "state_key": source_state_key,
        "record": video_record,
        "video_filename": "",
        "video_url": video_url,
        "audio_filename": "",
        "cleaned_title": cleaned_title,
        "candidates": top_candidates,
    }


def file_fingerprint(path, sample_bytes=1024 * 1024):
    if not path or not os.path.exists(path):
        return {}

    stat = os.stat(path)
    size = int(stat.st_size)
    digest = hashlib.sha256()
    digest.update(str(size).encode("utf-8"))
    digest.update(str(int(stat.st_mtime)).encode("utf-8"))

    with open(path, "rb") as f:
        first = f.read(sample_bytes)
        digest.update(first)

        if size > sample_bytes:
            f.seek(max(0, size - sample_bytes))
            digest.update(f.read(sample_bytes))

    return {
        "path": os.path.abspath(path),
        "size_bytes": size,
        "mtime_unix": float(stat.st_mtime),
        "fingerprint": digest.hexdigest(),
        "sample_bytes": int(sample_bytes),
    }


def candidate_archetypes(candidate):
    signals = candidate.rank_signals or {}
    archetypes = []

    if float(getattr(candidate, "popularity_score", 0.0) or 0.0) >= 0.22:
        archetypes.append("replay_or_timestamp_backed")
    if float(getattr(candidate, "comment_score", 0.0) or 0.0) >= 0.72:
        archetypes.append("comment_spark")
    if float(signals.get("comment_topic_score") or 0.0) >= 0.32:
        archetypes.append("comment_relevance_match")
    if float(getattr(candidate, "opening_score", 0.0) or 0.0) >= 0.72:
        archetypes.append("cold_open_hook")
    if float(getattr(candidate, "arc_score", 0.0) or 0.0) >= 0.72:
        archetypes.append("complete_retention_arc")
    if float(getattr(candidate, "readiness_score", 0.0) or 0.0) >= 0.72:
        archetypes.append("publish_ready_moment")
    if float(signals.get("payoff_score") or 0.0) >= 0.58 or float(signals.get("arc_payoff_score") or 0.0) >= 0.58:
        archetypes.append("payoff_or_reframe")
    if float(signals.get("specificity_score") or 0.0) >= 0.50 and float(signals.get("claim_score") or 0.0) >= 0.35:
        archetypes.append("explainer_or_takeaway")
    if float(signals.get("conflict_score") or 0.0) >= 0.45 or float(signals.get("dialogue_score") or 0.0) >= 0.45:
        archetypes.append("debate_or_exchange")
    if float(getattr(candidate, "audio_score", 0.0) or 0.0) >= 0.72:
        archetypes.append("high_energy")
    if signals.get("theme_archetype"):
        archetypes.insert(0, signals.get("theme_archetype"))

    if not archetypes:
        archetypes.append("general_quality")

    return archetypes


def compact_candidate_summary(candidate):
    signals = candidate.rank_signals or {}
    return {
        "start_time": round(float(candidate.start_time), 2),
        "end_time": round(float(candidate.end_time), 2),
        "duration": round(float(candidate.end_time - candidate.start_time), 2),
        "score": round(float(candidate.score), 4),
        "arc_score": round(float(getattr(candidate, "arc_score", 0.0)), 4),
        "readiness_score": round(float(getattr(candidate, "readiness_score", 0.0)), 4),
        "readiness_tier": signals.get("readiness_tier", ""),
        "readiness_concerns": signals.get("readiness_concerns", []),
        "readiness_hard_failures": signals.get("readiness_hard_failures", []),
        "popularity_score": round(float(getattr(candidate, "popularity_score", 0.0)), 4),
        "comment_score": round(float(getattr(candidate, "comment_score", 0.0)), 4),
        "comment_topic_score": round(float(signals.get("comment_topic_score") or 0.0), 4),
        "theme_signal_score": round(float(getattr(candidate, "theme_signal_score", 0.0) or 0.0), 4),
        "theme_signals": candidate.theme_signals,
        "guest_recognizability_score": round(float(signals.get("guest_recognizability_score") or 0.0), 4),
        "guest_recognizability_adjustment": round(float(signals.get("guest_recognizability_adjustment") or 0.0), 4),
        "guest_recognizability_reasons": (signals.get("guest_recognizability") or {}).get("reasons", []),
        "first_second_qc": candidate.first_second_qc,
        "transformation_score": round(float(getattr(candidate, "transformation_score", 0.0) or 0.0), 4),
        "reused_content_risk": round(float(getattr(candidate, "reused_content_risk", 0.0) or 0.0), 4),
        "recommended_intro_mode": signals.get("recommended_intro_mode", ""),
        "captionability_score": round(float(signals.get("captionability_score") or 0.0), 4),
        "audio_score": round(float(candidate.audio_score), 4),
        "opening_score": round(float(candidate.opening_score), 4),
        "boundary_score": round(float(candidate.boundary_score), 4),
        "hook_reason": candidate.hook_reason,
        "suggested_title": candidate.suggested_title,
        "topic_fingerprint": list(candidate.topic_fingerprint or []),
        "archetypes": candidate_archetypes(candidate),
        "comment_topic_matched_terms": signals.get("comment_topic_matched_terms", [])[:5],
        "arc_flags": signals.get("arc_flags", []),
        "transcript_excerpt": candidate.transcript_excerpt[:420],
    }


def build_candidate_inventory(candidates):
    if not candidates:
        return {}

    source_duration = max(float(candidate.end_time) for candidate in candidates)

    def zone_for(candidate):
        midpoint = (float(candidate.start_time) + float(candidate.end_time)) / 2
        ratio = midpoint / max(1.0, source_duration)

        if ratio < 0.20:
            return "opening"
        if ratio < 0.50:
            return "early_middle"
        if ratio < 0.80:
            return "late_middle"
        return "ending"

    inventory = {
        "source_duration_seconds": round(source_duration, 2),
        "total_candidates": len(candidates),
        "best_by_interview_zone": {
            "opening": [],
            "early_middle": [],
            "late_middle": [],
            "ending": [],
        },
        "best_by_signal": {
            "retention_arc": [],
            "publish_readiness": [],
            "public_popularity": [],
            "comment_timestamps": [],
            "comment_topic_relevance": [],
            "audio_energy": [],
            "clean_boundaries": [],
        },
        "best_by_archetype": {
            "replay_or_timestamp_backed": [],
            "comment_spark": [],
            "comment_relevance_match": [],
            "cold_open_hook": [],
            "complete_retention_arc": [],
            "publish_ready_moment": [],
            "payoff_or_reframe": [],
            "explainer_or_takeaway": [],
            "debate_or_exchange": [],
            "high_energy": [],
            "general_quality": [],
        },
    }

    for candidate in sorted(candidates, key=candidate_ranking_key, reverse=True):
        zone = zone_for(candidate)

        if len(inventory["best_by_interview_zone"][zone]) < 8:
            inventory["best_by_interview_zone"][zone].append(compact_candidate_summary(candidate))

    signal_rankings = {
        "retention_arc": lambda item: getattr(item, "arc_score", 0.0),
        "publish_readiness": lambda item: getattr(item, "readiness_score", 0.0),
        "public_popularity": lambda item: getattr(item, "popularity_score", 0.0),
        "comment_timestamps": lambda item: getattr(item, "comment_score", 0.0),
        "comment_topic_relevance": lambda item: (item.rank_signals or {}).get("comment_topic_score", 0.0),
        "audio_energy": lambda item: item.audio_score,
        "clean_boundaries": lambda item: item.boundary_score,
    }

    for signal_name, key_func in signal_rankings.items():
        ranked = sorted(
            candidates,
            key=lambda item: (key_func(item), item.score),
            reverse=True,
        )
        inventory["best_by_signal"][signal_name] = [
            compact_candidate_summary(candidate)
            for candidate in ranked[:8]
            if key_func(candidate) > 0
        ]

    for candidate in sorted(candidates, key=candidate_ranking_key, reverse=True):
        for archetype in candidate_archetypes(candidate):
            if len(inventory["best_by_archetype"].setdefault(archetype, [])) < 8:
                inventory["best_by_archetype"][archetype].append(compact_candidate_summary(candidate))

    return inventory


def build_topic_summary(candidates, limit=20):
    counts = {}

    for candidate in candidates or []:
        weight = float(getattr(candidate, "score", 0.0) or 0.0)

        for topic in candidate.topic_fingerprint or []:
            topic = str(topic or "").strip().lower()
            normalized_topic = topic.replace("_", " ").replace("'", "").strip()

            if not topic or not is_meaningful_topic_term(normalized_topic):
                continue

            counts[topic] = counts.get(topic, 0.0) + max(0.05, weight)

    return [
        {"topic": topic, "weight": round(weight, 4)}
        for topic, weight in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def clip_windows_overlap(left, right, padding=MIN_CLIP_SPACING_SECONDS):
    return (
        left.start_time < right.end_time + padding
        and left.end_time + padding > right.start_time
    )


def select_distinct_candidate_batch(candidates, predicate, limit=5, existing=None):
    selected = []
    existing = list(existing or [])

    for candidate in sorted(candidates or [], key=candidate_ranking_key, reverse=True):
        if not predicate(candidate):
            continue

        if any(clip_windows_overlap(candidate, other) for other in selected + existing):
            continue

        if any(topic_similarity(candidate.topic_fingerprint, other.topic_fingerprint) > 0.46 for other in selected + existing):
            continue

        selected.append(candidate)

        if len(selected) >= limit:
            break

    return selected


def build_source_clip_batch_plan(candidates, selected_clips=None, total_limit=24):
    selected_clips = selected_clips or []
    candidates = candidates or []
    batch_definitions = [
        (
            "already_selected",
            "Primary clips chosen by the current scorer.",
            lambda item: item in selected_clips,
            len(selected_clips) or 3,
        ),
        (
            "replay_backed",
            "Public replay, chapter, description, or comment timestamp signals point here.",
            lambda item: float(getattr(item, "popularity_score", 0.0) or 0.0) >= 0.18,
            5,
        ),
        (
            "comment_spark",
            "Likely to provoke comments, debate, agreement, or disagreement.",
            lambda item: float(getattr(item, "comment_score", 0.0) or 0.0) >= 0.64,
            5,
        ),
        (
            "comment_relevance",
            "Transcript matches names, topics, or phrases that commenters interacted with.",
            lambda item: float((item.rank_signals or {}).get("comment_topic_score") or 0.0) >= 0.24,
            5,
        ),
        (
            "clean_retention_arc",
            "Has a hook, standalone context, escalation, and payoff.",
            lambda item: float(getattr(item, "arc_score", 0.0) or 0.0) >= 0.68,
            6,
        ),
        (
            "publish_ready",
            "Clears the editor-style readiness check: hook, context, payoff, boundaries, and viewer evidence.",
            lambda item: (
                float(getattr(item, "readiness_score", 0.0) or 0.0) >= 0.62
                and (item.rank_signals or {}).get("readiness_tier") not in {"reject", "weak"}
            ),
            6,
        ),
        (
            "high_energy",
            "Audio movement suggests strong emphasis, laughter, heat, or pace.",
            lambda item: float(getattr(item, "audio_score", 0.0) or 0.0) >= 0.65,
            4,
        ),
        (
            "explainers",
            "Specific, claim-driven clips that can stand alone as takeaways.",
            lambda item: (
                float((item.rank_signals or {}).get("specificity_score") or 0.0) >= 0.42
                and float((item.rank_signals or {}).get("claim_score") or 0.0) >= 0.28
            ),
            4,
        ),
        (
            "late_payoffs",
            "Later moments that may be missed by only clipping the opening half.",
            lambda item: (
                float(item.start_time) >= max(candidate.end_time for candidate in candidates) * 0.55
                and float((item.rank_signals or {}).get("arc_payoff_score") or 0.0) >= 0.45
            ) if candidates else False,
            4,
        ),
    ]
    used = []
    batches = []

    for batch_name, goal, predicate, limit in batch_definitions:
        batch_candidates = selected_clips if batch_name == "already_selected" else candidates
        batch = select_distinct_candidate_batch(
            batch_candidates,
            predicate=predicate,
            limit=limit,
            existing=used,
        )
        used.extend(batch)
        batches.append({
            "batch": batch_name,
            "goal": goal,
            "clips": [compact_candidate_summary(candidate) for candidate in batch],
        })

        if len(used) >= total_limit:
            break

    full_order = []
    seen_keys = set()

    for batch in batches:
        for clip in batch["clips"]:
            key = (clip["start_time"], clip["end_time"], tuple(clip.get("topic_fingerprint", [])))

            if key in seen_keys:
                continue

            seen_keys.add(key)
            full_order.append({
                **clip,
                "batch": batch["batch"],
                "batch_goal": batch["goal"],
            })

            if len(full_order) >= total_limit:
                break

        if len(full_order) >= total_limit:
            break

    return {
        "total_recommended": len(full_order),
        "batches": batches,
        "full_interview_milking_order": full_order,
    }


def build_score_distribution(candidates):
    buckets = {
        "excellent_0_80_plus": 0,
        "strong_0_65_0_80": 0,
        "good_0_50_0_65": 0,
        "usable_0_35_0_50": 0,
        "weak_below_0_35": 0,
    }

    for candidate in candidates or []:
        score = float(getattr(candidate, "score", 0.0) or 0.0)

        if score >= 0.80:
            buckets["excellent_0_80_plus"] += 1
        elif score >= 0.65:
            buckets["strong_0_65_0_80"] += 1
        elif score >= 0.50:
            buckets["good_0_50_0_65"] += 1
        elif score >= 0.35:
            buckets["usable_0_35_0_50"] += 1
        else:
            buckets["weak_below_0_35"] += 1

    return buckets


def build_readiness_distribution(candidates):
    buckets = {
        "elite": 0,
        "strong": 0,
        "usable": 0,
        "review": 0,
        "weak": 0,
        "reject": 0,
        "selection_ready": 0,
    }

    for candidate in candidates or []:
        signals = candidate.rank_signals or {}
        tier = signals.get("readiness_tier") or "weak"
        buckets[tier] = buckets.get(tier, 0) + 1

        if candidate_selection_ready(candidate):
            buckets["selection_ready"] += 1

    return buckets


def top_popularity_markers(popularity_profile, limit=20):
    markers = sorted(
        popularity_profile.get("timestamp_markers", []) or [],
        key=lambda item: int(item.get("count") or 0),
        reverse=True,
    )

    return [
        {
            "time": round(float(marker.get("time") or 0), 2),
            "count": int(marker.get("count") or 0),
            "source_counts": marker.get("source_counts", {}),
        }
        for marker in markers[:limit]
    ]


def top_comment_topic_terms(popularity_profile, limit=30):
    return [
        {
            "term": term.get("term", ""),
            "weight": round(float(term.get("weight") or 0.0), 4),
            "count": int(term.get("count") or 0),
            "examples": term.get("examples", [])[:2],
        }
        for term in (popularity_profile.get("comment_topic_terms") or [])[:limit]
    ]


def source_dossier_dir():
    directory = os.path.join(metadata_path or base_dir, "source_dossiers")
    os.makedirs(directory, exist_ok=True)
    return directory


def write_source_dossier(cleaned_title, source_record, popularity_profile, candidates, selected_clips=None):
    candidates = candidates or []
    selected_clips = selected_clips or []
    popularity_profile = popularity_profile or {}
    youtube_data_api = popularity_profile.get("youtube_data_api") or {}
    stats = youtube_data_api.get("stats") or {}
    inventory = build_candidate_inventory(candidates)
    readiness_distribution = build_readiness_distribution(candidates)
    selected_clips = selected_clips or []
    selected_readiness = [
        float(getattr(clip, "readiness_score", 0.0) or 0.0)
        for clip in selected_clips
    ]
    selected_publish_ready = [
        clip
        for clip in selected_clips
        if (clip.rank_signals or {}).get("readiness_tier") in {"elite", "strong"}
    ]
    external_backed_candidates = [
        clip
        for clip in candidates
        if candidate_external_signal_score(clip) >= 0.18
    ]
    internally_discovered_candidates = [
        clip
        for clip in candidates
        if candidate_external_signal_score(clip) < 0.18
        and float(getattr(clip, "readiness_score", 0.0) or 0.0) >= active_min_readiness_score()
    ]
    processing = dict((source_record or {}).get("_processing_metrics", {}) or {})
    processing_runtime = float(
        processing.get("total_source_workflow_seconds")
        or processing.get("scoring_seconds")
        or 0.0
    )

    if processing_runtime > 0 and "selected_clips_per_hour_processed" not in processing:
        processing["selected_clips_per_hour_processed"] = round(
            len(selected_clips) / max(0.01, processing_runtime / 3600),
            4,
        )

    source_tier = "weak_source"

    if len(selected_publish_ready) >= 3 or int(readiness_distribution.get("elite") or 0) >= 12:
        source_tier = "primary_milk_source"
    elif len(selected_publish_ready) >= 1 or int(readiness_distribution.get("strong") or 0) >= 80:
        source_tier = "selective_source"
    elif int(readiness_distribution.get("usable") or 0) >= 400:
        source_tier = "thin_but_usable"

    dossier = {
        "source": {
            "cleaned_title": cleaned_title,
            "title": (source_record or {}).get("title", ""),
            "video_url": (source_record or {}).get("video_url", ""),
            "state_key": (source_record or {}).get("state_key", ""),
            "channel": stats.get("channel_title") or (source_record or {}).get("channel", ""),
            "published_at": stats.get("published_at") or (source_record or {}).get("published_at", ""),
            "source_tier": (source_record or {}).get("source_tier", ""),
            "origin_theme": (source_record or {}).get("origin_theme", ""),
            "routed_from_theme": (source_record or {}).get("routed_from_theme", ""),
            "route_targets": (source_record or {}).get("route_targets", []),
            "routing_status": (source_record or {}).get("routing_status", ""),
            "routing_override_matches": (source_record or {}).get("routing_override_matches", []),
        },
        "editorial_decision": {
            "source_tier": source_tier,
            "worth_clipping": source_tier in {"primary_milk_source", "selective_source"},
            "selected_clip_count": len(selected_clips),
            "selected_publish_ready_count": len(selected_publish_ready),
            "avg_selected_readiness": round(sum(selected_readiness) / len(selected_readiness), 4) if selected_readiness else None,
            "externally_backed_candidate_count": len(external_backed_candidates),
            "internally_discovered_publishable_count": len(internally_discovered_candidates),
            "slow_source_review": bool(processing.get("slow_source_review")),
        },
        "processing_metrics": processing,
        "signal_coverage": {
            "profile_sources": popularity_profile.get("sources", []),
            "has_heatmap": bool(popularity_profile.get("heatmap")),
            "has_chapters": bool(popularity_profile.get("chapters")),
            "timestamp_marker_count": len(popularity_profile.get("timestamp_markers") or []),
            "comment_topic_term_count": len(popularity_profile.get("comment_topic_terms") or []),
            "youtube_data_api_comments_sampled": int(youtube_data_api.get("comment_count_sampled") or 0),
            "youtube_data_api_timestamp_marker_count": int(youtube_data_api.get("comment_timestamp_marker_count") or 0),
            "youtube_data_api_comment_topic_term_count": int(youtube_data_api.get("comment_topic_term_count") or 0),
        },
        "youtube_stats": {
            "views": int(stats.get("view_count") or 0),
            "likes": int(stats.get("like_count") or 0),
            "comments": int(stats.get("comment_count") or 0),
        },
        "top_popularity_markers": top_popularity_markers(popularity_profile),
        "top_comment_topic_terms": top_comment_topic_terms(popularity_profile),
        "score_distribution": build_score_distribution(candidates),
        "readiness_distribution": readiness_distribution,
        "topic_summary": build_topic_summary(candidates),
        "candidate_inventory": inventory,
        "selected_clips": [compact_candidate_summary(clip) for clip in selected_clips],
        "clip_batch_plan": build_source_clip_batch_plan(candidates, selected_clips=selected_clips),
        "milking_plan": {
            "priority_order": [
                "selected_clips",
                "clip_batch_plan.full_interview_milking_order",
                "candidate_inventory.best_by_signal.publish_readiness",
                "candidate_inventory.best_by_signal.public_popularity",
                "candidate_inventory.best_by_signal.comment_timestamps",
                "candidate_inventory.best_by_signal.comment_topic_relevance",
                "candidate_inventory.best_by_signal.retention_arc",
                "candidate_inventory.best_by_interview_zone.ending",
                "candidate_inventory.best_by_interview_zone.opening",
            ],
            "rule": "Only produce multiple shorts from this interview when topic_fingerprint differs and the clip has a complete hook-context-payoff arc.",
        },
    }
    path = os.path.join(source_dossier_dir(), f"{cleaned_title}_source_dossier.json")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(dossier, f, indent=4)

    return path


def clip_review_candidate_key(payload):
    source_key = str(payload.get("source_state_key") or (payload.get("rank_signals") or {}).get("source_state_key") or "")

    try:
        start_time = round(float(payload.get("start_time") or 0.0), 2)
        end_time = round(float(payload.get("end_time") or 0.0), 2)
    except (TypeError, ValueError):
        start_time = 0.0
        end_time = 0.0

    return (source_key, start_time, end_time)


def write_clip_review_exports(cleaned_title, selected_clips, candidates=None, merge_existing_selected=False):
    review_json = os.path.join(metadata_path, f"{cleaned_title}_clip_review.json")
    review_csv = os.path.join(metadata_path, f"{cleaned_title}_clip_review.csv")

    selected_payload = [candidate_to_dict(clip) for clip in selected_clips]
    top_candidate_payload = []
    candidate_inventory = {}
    existing_selected_payload = []

    if candidates is not None:
        top_candidate_payload = [
            candidate_to_dict(clip)
            for clip in ranked_candidate_window(candidates, CLIP_REVIEW_REPORT_CANDIDATE_LIMIT)
        ]
        candidate_inventory = build_candidate_inventory(candidates)
    elif os.path.exists(review_json) and os.path.getsize(review_json) > 0:
        try:
            with open(review_json, "r", encoding="utf-8") as f:
                existing_payload = json.load(f)
                existing_selected_payload = existing_payload.get("selected", []) or []
                top_candidate_payload = existing_payload.get("top_candidates", [])
                candidate_inventory = existing_payload.get("candidate_inventory", {})
        except Exception:
            top_candidate_payload = []

    if merge_existing_selected and existing_selected_payload:
        merged = {}

        for item in existing_selected_payload:
            if not isinstance(item, dict):
                continue

            key = clip_review_candidate_key(item)
            if key[0]:
                merged[key] = item

        for item in selected_payload:
            key = clip_review_candidate_key(item)
            if key[0]:
                merged[key] = item

        selected_payload = sorted(
            merged.values(),
            key=lambda item: (
                str(item.get("source_state_key") or ""),
                float(item.get("start_time") or 0.0),
                float(item.get("end_time") or 0.0),
            ),
        )

    with open(review_json, "w", encoding="utf-8") as f:
        json.dump({
            "scoring_model_version": SCORING_MODEL_VERSION,
            "theme": active_theme_name(),
            "theme_profile": active_theme_profile(),
            "selected": selected_payload,
            "top_candidates": top_candidate_payload,
            "candidate_inventory": candidate_inventory,
        }, f, indent=4)

    columns = [
        "clip_number",
        "start_time",
        "end_time",
        "duration",
        "score",
        "text_score",
        "audio_score",
        "opening_score",
        "comment_score",
        "comment_topic_score",
        "theme_signal_score",
        "guest_recognizability_score",
        "guest_recognizability_adjustment",
        "guest_recognizability_reasons",
        "guest_standalone_gate",
        "theme_archetype",
        "intro_mode",
        "first_second_passed",
        "transformation_score",
        "reused_content_risk",
        "captionability_score",
        "popularity_score",
        "arc_score",
        "readiness_score",
        "readiness_tier",
        "readiness_concerns",
        "pacing_score",
        "duration_score",
        "boundary_score",
        "diversity_score",
        "hook_reason",
        "topic_fingerprint",
        "comment_topic_matched_terms",
        "suggested_title",
        "suggested_caption",
        "suggested_description",
        "hashtags",
        "output_file",
        "qc_passed",
        "qc_flags",
        "qc_rejected",
        "qc_rejection_reasons",
        "render_strategy",
        "visual_quality_score",
        "dead_frame_ratio",
        "alive_frame_rate",
        "face_presence_rate",
        "alive_no_face_frame_ratio",
        "longest_no_face_run_ratio",
        "visual_cut_ratio",
        "continuity_center_jitter_ratio",
        "avg_face_plausibility",
        "dual_stack_frame_rate",
        "dual_stack_detection_rate",
        "dual_stack_fallback_frame_rate",
        "avg_edge_density",
        "frame_audit_file",
        "transcript_excerpt",
    ]

    with open(review_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()

        for index, clip in enumerate(selected_clips, start=1):
            qc_flags = clip.render_qc.get("flags", []) if clip.render_qc else []
            frame_path = clip.render_qc.get("frame_path", {}) if clip.render_qc else {}
            crop_stats = clip.render_qc.get("crop", {}) if clip.render_qc else {}
            writer.writerow({
                "clip_number": index,
                "start_time": f"{clip.start_time:.2f}",
                "end_time": f"{clip.end_time:.2f}",
                "duration": f"{clip.end_time - clip.start_time:.2f}",
                "score": f"{clip.score:.4f}",
                "text_score": f"{clip.text_score:.4f}",
                "audio_score": f"{clip.audio_score:.4f}",
                "opening_score": f"{clip.opening_score:.4f}",
                "comment_score": f"{clip.comment_score:.4f}",
                "comment_topic_score": f"{(clip.rank_signals or {}).get('comment_topic_score', 0.0):.4f}",
                "theme_signal_score": f"{getattr(clip, 'theme_signal_score', 0.0):.4f}",
                "guest_recognizability_score": f"{(clip.rank_signals or {}).get('guest_recognizability_score', 0.0):.4f}",
                "guest_recognizability_adjustment": f"{(clip.rank_signals or {}).get('guest_recognizability_adjustment', 0.0):.4f}",
                "guest_recognizability_reasons": "; ".join((clip.rank_signals or {}).get("guest_recognizability", {}).get("reasons", [])),
                "guest_standalone_gate": (clip.rank_signals or {}).get("guest_recognizability", {}).get("standalone_value_confirmed", ""),
                "theme_archetype": (clip.rank_signals or {}).get("theme_archetype", ""),
                "intro_mode": (clip.rank_signals or {}).get("recommended_intro_mode", ""),
                "first_second_passed": (clip.first_second_qc or {}).get("passed", ""),
                "transformation_score": f"{getattr(clip, 'transformation_score', 0.0):.4f}",
                "reused_content_risk": f"{getattr(clip, 'reused_content_risk', 0.0):.4f}",
                "captionability_score": f"{(clip.rank_signals or {}).get('captionability_score', 0.0):.4f}",
                "popularity_score": f"{getattr(clip, 'popularity_score', 0.0):.4f}",
                "arc_score": f"{getattr(clip, 'arc_score', 0.0):.4f}",
                "readiness_score": f"{getattr(clip, 'readiness_score', 0.0):.4f}",
                "readiness_tier": (clip.rank_signals or {}).get("readiness_tier", ""),
                "readiness_concerns": "; ".join((clip.rank_signals or {}).get("readiness_concerns", [])),
                "pacing_score": f"{clip.pacing_score:.4f}",
                "duration_score": f"{clip.duration_score:.4f}",
                "boundary_score": f"{clip.boundary_score:.4f}",
                "diversity_score": f"{clip.diversity_score:.4f}",
                "hook_reason": clip.hook_reason,
                "topic_fingerprint": ", ".join(clip.topic_fingerprint),
                "comment_topic_matched_terms": ", ".join(
                    term.get("term", "")
                    for term in (clip.rank_signals or {}).get("comment_topic_matched_terms", [])[:6]
                ),
                "suggested_title": clip.suggested_title,
                "suggested_caption": clip.suggested_caption,
                "suggested_description": clip.suggested_description,
                "hashtags": " ".join(clip.hashtags),
                "output_file": clip.output_file,
                "qc_passed": clip.render_qc.get("passed", "") if clip.render_qc else "",
                "qc_flags": ", ".join(qc_flags),
                "qc_rejected": clip.render_qc.get("rejected", "") if clip.render_qc else "",
                "qc_rejection_reasons": ", ".join(clip.render_qc.get("rejection_reasons", [])) if clip.render_qc else "",
                "render_strategy": clip.render_qc.get("render_strategy", "") if clip.render_qc else "",
                "visual_quality_score": f"{clip.render_qc.get('visual_quality_score', 0.0):.4f}" if clip.render_qc else "",
                "dead_frame_ratio": f"{frame_path.get('dead_frame_ratio', 0.0):.4f}" if clip.render_qc else "",
                "alive_frame_rate": f"{frame_path.get('alive_frame_rate', 0.0):.4f}" if clip.render_qc else "",
                "face_presence_rate": f"{frame_path.get('face_presence_rate', 0.0):.4f}" if clip.render_qc else "",
                "alive_no_face_frame_ratio": f"{frame_path.get('alive_no_face_frame_ratio', 0.0):.4f}" if clip.render_qc else "",
                "longest_no_face_run_ratio": f"{frame_path.get('longest_no_face_run_ratio', 0.0):.4f}" if clip.render_qc else "",
                "visual_cut_ratio": f"{frame_path.get('visual_cut_ratio', 0.0):.4f}" if clip.render_qc else "",
                "continuity_center_jitter_ratio": f"{frame_path.get('continuity_center_jitter_ratio', 0.0):.4f}" if clip.render_qc else "",
                "avg_face_plausibility": f"{frame_path.get('avg_face_plausibility', 0.0):.4f}" if clip.render_qc else "",
                "dual_stack_frame_rate": f"{crop_stats.get('dual_stack_frame_rate', 0.0):.4f}" if clip.render_qc else "",
                "dual_stack_detection_rate": f"{crop_stats.get('dual_stack_detection_rate', 0.0):.4f}" if clip.render_qc else "",
                "dual_stack_fallback_frame_rate": f"{crop_stats.get('dual_stack_fallback_frame_rate', 0.0):.4f}" if clip.render_qc else "",
                "avg_edge_density": f"{frame_path.get('avg_edge_density', 0.0):.4f}" if clip.render_qc else "",
                "frame_audit_file": clip.render_qc.get("frame_audit_file", "") if clip.render_qc else "",
                "transcript_excerpt": clip.transcript_excerpt,
            })

    return review_json, review_csv


def get_media_duration_seconds(media_path):
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
        return max(0.0, float(result.stdout.strip() or 0))
    except ValueError:
        return 0.0


def merge_time_windows(windows, min_gap=12.0):
    merged = []

    for start, end in sorted(windows):
        start = max(0.0, float(start))
        end = max(start, float(end))

        if end <= start:
            continue

        if merged and start <= merged[-1][1] + min_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    return merged


def transcript_signal_windows(popularity_profile, total_duration):
    if not ENABLE_SIGNAL_WINDOW_TRANSCRIPTION:
        return []

    total_duration = float(total_duration or 0)

    if total_duration <= SIGNAL_TRANSCRIPT_FULL_MAX_SECONDS:
        return []

    signals = popularity_signal_times(popularity_profile or {}, total_duration)

    radius = SIGNAL_TRANSCRIPT_WINDOW_RADIUS_SECONDS
    windows = []

    if signals:
        selected_centers = []

        for signal_time, _source in signals[:SIGNAL_TRANSCRIPT_MAX_WINDOWS * 5]:
            if any(abs(signal_time - center) < radius * 1.65 for center in selected_centers):
                continue

            selected_centers.append(signal_time)
            windows.append((
                max(0.0, signal_time - radius),
                min(total_duration, signal_time + radius),
            ))

            if len(windows) >= SIGNAL_TRANSCRIPT_MAX_WINDOWS:
                break
    else:
        # First-pass triage for long sources with no public signals. This avoids
        # spending hours on a source before we know whether it has strong moments.
        sample_count = max(4, min(SIGNAL_TRANSCRIPT_MAX_WINDOWS, int(total_duration // 600) + 3))
        safe_start = min(total_duration, radius)
        safe_end = max(safe_start, total_duration - radius)

        for index in range(sample_count):
            ratio = index / max(1, sample_count - 1)
            center = safe_start + (safe_end - safe_start) * ratio
            windows.append((
                max(0.0, center - radius),
                min(total_duration, center + radius),
            ))

    return sorted(windows)[:SIGNAL_TRANSCRIPT_MAX_WINDOWS]


def extract_transcription_window(audio_filename, cleaned_title, start, end, index):
    window_dir = os.path.join(transcriptions_path, "_transcribe_windows")
    os.makedirs(window_dir, exist_ok=True)
    output_file = os.path.join(
        window_dir,
        f"{cleaned_title}_window_{index:02d}_{int(start)}_{int(end)}.wav",
    )

    if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
        return output_file

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-ss", f"{float(start):.3f}",
        "-to", f"{float(end):.3f}",
        "-i", audio_filename,
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        output_file,
    ], "Signal transcription window extraction")
    return output_file


def analysis_pcm_wav(media_file, cleaned_title, index):
    try:
        with wave.open(media_file, "rb") as wav_file:
            if (
                wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == 2
                and wav_file.getframerate() == 16000
            ):
                return media_file
    except (OSError, EOFError, wave.Error):
        pass

    analysis_dir = os.path.join(audio_path, "_analysis_windows")
    os.makedirs(analysis_dir, exist_ok=True)
    output_file = os.path.join(
        analysis_dir,
        f"{cleaned_title}_window_{int(index):02d}_16k.wav",
    )

    if os.path.exists(output_file) and os.path.getsize(output_file) > 44:
        try:
            with wave.open(output_file, "rb") as wav_file:
                if (
                    wav_file.getnchannels() == 1
                    and wav_file.getsampwidth() == 2
                    and wav_file.getframerate() == 16000
                    and os.path.getmtime(output_file) >= os.path.getmtime(media_file)
                ):
                    return output_file
        except (OSError, EOFError, wave.Error):
            pass

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-i", media_file,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        output_file,
    ], "Scoring-window PCM conversion")
    assert_file_exists(output_file, "Scoring-window analysis WAV")
    return output_file


def shared_transcription_model():
    global _TRANSCRIBE_MODEL, _TRANSCRIBE_MODEL_SETTINGS

    import torch
    from faster_whisper import WhisperModel

    if torch.cuda.is_available():
        device_type = "cuda"
        compute_type = "float16"
        device_label = "GPU Accelerated"
    else:
        device_type = "cpu"
        compute_type = "int8"
        device_label = "CPU int8"

    settings = (CLIP_TRANSCRIBE_MODEL_SIZE, device_type, compute_type)

    if _TRANSCRIBE_MODEL is not None and _TRANSCRIBE_MODEL_SETTINGS == settings:
        return _TRANSCRIBE_MODEL

    print(
        f"Initializing shared faster-whisper model "
        f"({CLIP_TRANSCRIBE_MODEL_SIZE} | {device_label})..."
    )
    _TRANSCRIBE_MODEL = WhisperModel(
        CLIP_TRANSCRIBE_MODEL_SIZE,
        device=device_type,
        compute_type=compute_type,
    )
    _TRANSCRIBE_MODEL_SETTINGS = settings
    return _TRANSCRIBE_MODEL


def transcribe_audio_segments(audio_filename, cleaned_title, lang_code="en", popularity_profile=None):
    window_manifest = load_audio_window_manifest(audio_filename)
    total_duration_hint = float(
        window_manifest.get("source_duration_seconds")
        or (popularity_profile or {}).get("duration")
        or 0
    )
    total_duration = total_duration_hint or get_media_duration_seconds(audio_filename)

    if window_manifest:
        signal_windows = [
            (float(item.get("source_start") or 0.0), float(item.get("source_end") or 0.0))
            for item in window_manifest.get("windows") or []
            if isinstance(item, dict)
        ]
    else:
        signal_windows = transcript_signal_windows(popularity_profile or {}, total_duration)
    transcript_suffix = "_segments_signal_windows.json" if signal_windows else "_segments.json"
    transcript_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}{transcript_suffix}",
    )
    audio_fingerprint = file_fingerprint(audio_filename)
    transcript_scope = {
        "mode": (
            "downloaded_signal_windows"
            if window_manifest
            else ("signal_windows" if signal_windows else "full_source")
        ),
        "source_duration_seconds": round(total_duration, 2),
        "full_source_max_seconds": SIGNAL_TRANSCRIPT_FULL_MAX_SECONDS,
        "window_count": len(signal_windows),
        "windows": [
            {"start": round(start, 2), "end": round(end, 2)}
            for start, end in signal_windows
        ],
    }

    if os.path.exists(transcript_filepath) and os.path.getsize(transcript_filepath) > 0:
        with open(transcript_filepath, "r", encoding="utf-8") as f:
            cached_payload = json.load(f)

        cached_fingerprint = (cached_payload.get("audio_fingerprint") or {}).get("fingerprint")
        cache_matches_settings = (
            cached_payload.get("model_size") == CLIP_TRANSCRIBE_MODEL_SIZE
            and int(cached_payload.get("beam_size", 0) or 0) == CLIP_TRANSCRIBE_BEAM_SIZE
            and int(cached_payload.get("best_of", 0) or 0) == CLIP_TRANSCRIBE_BEST_OF
            and (
                not cached_fingerprint
                or cached_fingerprint == audio_fingerprint.get("fingerprint")
            )
            and cached_payload.get("transcript_scope") == transcript_scope
        )

        if cache_matches_settings:
            print("Reusing segment-level transcript cache...")
            return cached_payload

        print("Transcript cache was created with older settings; regenerating...")

    model = shared_transcription_model()

    print(
        "Transcribing segment text only "
        f"(Language forced to: {lang_code}, beam={CLIP_TRANSCRIBE_BEAM_SIZE}, scope={transcript_scope['mode']})..."
    )
    start_transcribe = time.time()

    segments = []
    detected_language = lang_code

    if signal_windows:
        print(
            " -> Using signal-window transcription: "
            f"{len(signal_windows)} windows around public replay/chapter/comment signals "
            f"for {int(total_duration)}s source."
        )

        for index, (window_start, window_end) in enumerate(signal_windows, start=1):
            window_file = audio_window_file_for(signal_windows, window_manifest, index)

            if not window_file:
                window_file = extract_transcription_window(
                    audio_filename,
                    cleaned_title,
                    window_start,
                    window_end,
                    index,
                )
            segments_iter, info = model.transcribe(
                window_file,
                language=lang_code,
                beam_size=CLIP_TRANSCRIBE_BEAM_SIZE,
                best_of=CLIP_TRANSCRIBE_BEST_OF,
                vad_filter=True,
                word_timestamps=False,
                condition_on_previous_text=False,
            )
            detected_language = getattr(info, "language", detected_language)

            for segment in segments_iter:
                segments.append({
                    "start": float(segment.start) + window_start,
                    "end": float(segment.end) + window_start,
                    "text": segment.text.strip(),
                })
    else:
        segments_iter, info = model.transcribe(
            audio_filename,
            language=lang_code,
            beam_size=CLIP_TRANSCRIBE_BEAM_SIZE,
            best_of=CLIP_TRANSCRIBE_BEST_OF,
            vad_filter=True,
            word_timestamps=False,
            condition_on_previous_text=False,
        )
        detected_language = getattr(info, "language", detected_language)

        for segment in segments_iter:
            segments.append({
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text.strip(),
            })

    segments = sorted(
        [
            segment
            for segment in segments
            if segment.get("text")
        ],
        key=lambda segment: segment["start"],
    )

    payload = {
        "language": detected_language,
        "duration": float(total_duration or 0),
        "model_size": CLIP_TRANSCRIBE_MODEL_SIZE,
        "beam_size": CLIP_TRANSCRIBE_BEAM_SIZE,
        "best_of": CLIP_TRANSCRIBE_BEST_OF,
        "audio_fingerprint": audio_fingerprint,
        "transcript_scope": transcript_scope,
        "transcribed_at": utc_timestamp(),
        "transcription_seconds": round(time.time() - start_transcribe, 2),
        "segments": segments,
    }

    with open(transcript_filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f" -> Segment transcription took: {payload['transcription_seconds']:.2f} seconds\n")

    return payload


def analyze_audio_features(audio_filename, cleaned_title, analysis_windows=None, source_duration=None):
    features_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_audio_features.json",
    )
    analysis_windows = [
        (max(0.0, float(start)), max(0.0, float(end)))
        for start, end in (analysis_windows or [])
        if float(end) > float(start)
    ]
    window_manifest = load_audio_window_manifest(audio_filename)
    source_duration = max(0.0, float(
        source_duration
        or window_manifest.get("source_duration_seconds")
        or get_media_duration_seconds(audio_filename)
    ))
    analysis_scope = {
        "mode": "signal_windows" if analysis_windows else "full_source",
        "source_duration_seconds": round(source_duration, 2),
        "windows": [
            {"start": round(start, 2), "end": round(end, 2)}
            for start, end in analysis_windows
        ],
    }

    if os.path.exists(features_filepath) and os.path.getsize(features_filepath) > 0:
        with open(features_filepath, "r", encoding="utf-8") as f:
            cached_payload = json.load(f)

        cached_fingerprint = (cached_payload.get("audio_fingerprint") or {}).get("fingerprint")
        current_fingerprint = file_fingerprint(audio_filename).get("fingerprint")

        if (
            (not cached_fingerprint or cached_fingerprint == current_fingerprint)
            and cached_payload.get("analysis_scope", {"mode": "full_source"}) == analysis_scope
        ):
            print("Reusing audio feature cache...")
            return cached_payload

        print("Audio feature cache was created for different audio; regenerating...")

    print("Mapping audio energy and frequency movement...")
    start_audio = time.time()
    temporary_analysis_files = []

    if analysis_windows:
        wav_sources = []

        for index, (window_start, window_end) in enumerate(analysis_windows, start=1):
            window_file = audio_window_file_for(analysis_windows, window_manifest, index)

            if not window_file:
                window_file = extract_transcription_window(
                    audio_filename,
                    cleaned_title,
                    window_start,
                    window_end,
                    index,
                )

            wav_sources.append((
                analysis_pcm_wav(window_file, cleaned_title, index),
                window_start,
            ))
    else:
        analysis_wav = os.path.join(audio_path, f"{cleaned_title}_analysis_16k.wav")
        run_subprocess([
            FFMPEG_EXE,
            "-y",
            "-i", audio_filename,
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            analysis_wav,
        ], "Audio analysis WAV extraction")
        wav_sources = [(analysis_wav, 0.0)]
        temporary_analysis_files.append(analysis_wav)

    rms_values = []
    peak_values = []
    zcr_values = []
    centroid_values = []
    flux_values = []
    feature_times = []

    previous_magnitude = None

    for wav_path, time_offset in wav_sources:
        previous_magnitude = None

        with wave.open(wav_path, "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            chunk_size = sample_rate
            second_index = 0

            while True:
                raw = wav_file.readframes(chunk_size)

                if not raw:
                    break

                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                if samples.size == 0:
                    second_index += 1
                    continue

                rms = float(np.sqrt(np.mean(samples * samples)))
                peak = float(np.max(np.abs(samples)))
                zcr = float(np.mean(samples[:-1] * samples[1:] < 0)) if samples.size > 1 else 0.0

                windowed = samples * np.hanning(samples.size)
                magnitude = np.abs(np.fft.rfft(windowed))
                freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)
                mag_sum = float(np.sum(magnitude))
                centroid = float(np.sum(freqs * magnitude) / mag_sum) if mag_sum > 0 else 0.0

                if previous_magnitude is None:
                    flux = 0.0
                else:
                    shared = min(previous_magnitude.size, magnitude.size)
                    flux = float(np.mean(np.abs(magnitude[:shared] - previous_magnitude[:shared])))

                previous_magnitude = magnitude
                feature_times.append(max(0, int(round(time_offset + second_index))))
                rms_values.append(rms)
                peak_values.append(peak)
                zcr_values.append(zcr)
                centroid_values.append(centroid)
                flux_values.append(flux)
                second_index += 1

    for temporary_file in temporary_analysis_files:
        try:
            os.remove(temporary_file)
        except Exception:
            pass

    rms_norm = normalize_array(rms_values)
    peak_norm = normalize_array(peak_values)
    zcr_norm = normalize_array(zcr_values)
    centroid_norm = normalize_array(centroid_values)
    flux_norm = normalize_array(flux_values)
    rms_delta_norm = normalize_array(np.abs(np.diff(rms_norm, prepend=rms_norm[:1] if rms_norm.size else [0])))

    excitement = (
        0.38 * rms_norm
        + 0.20 * peak_norm
        + 0.22 * flux_norm
        + 0.12 * rms_delta_norm
        + 0.05 * centroid_norm
        + 0.03 * zcr_norm
    )

    dense_duration = max(
        1,
        int(math.ceil(source_duration)),
        (max(feature_times) + 1) if feature_times else 1,
    )
    dense_seconds = [
        {
            "time": index,
            "energy": 0.0,
            "peak": 0.0,
            "frequency_flux": 0.0,
            "tone_shift": 0.0,
            "excitement": 0.0,
        }
        for index in range(dense_duration)
    ]

    for value_index, absolute_second in enumerate(feature_times):
        if absolute_second >= len(dense_seconds):
            continue

        dense_seconds[absolute_second] = {
            "time": absolute_second,
            "energy": float(rms_norm[value_index]),
            "peak": float(peak_norm[value_index]),
            "frequency_flux": float(flux_norm[value_index]),
            "tone_shift": float(rms_delta_norm[value_index]),
            "excitement": float(excitement[value_index]),
        }

    payload = {
        "audio_fingerprint": file_fingerprint(audio_filename),
        "analysis_scope": analysis_scope,
        "analyzed_at": utc_timestamp(),
        "audio_feature_seconds": round(time.time() - start_audio, 2),
        "seconds": dense_seconds,
    }

    with open(features_filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f" -> Audio feature mapping took: {payload['audio_feature_seconds']:.2f} seconds\n")

    return payload


def split_transcript_sentences(text):
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.?!])\s+", clean_transcript_text(text))
        if sentence.strip()
    ]


def score_sentence_completeness(text, words):
    sentences = split_transcript_sentences(text)

    if not sentences or not words:
        return 0.0, 0

    terminal_sentences = [
        sentence
        for sentence in sentences
        if sentence[-1] in ".?!"
    ]
    terminal_ratio = len(terminal_sentences) / max(1, len(sentences))
    first_word = first_spoken_word(sentences[0])
    last_words = words[-4:]

    weak_open_penalty = 0.18 if first_word in WEAK_START_WORDS or first_word in FILLER_OPENERS else 0.0
    dangling_end_penalty = 0.20 if any(
        word in {"and", "but", "because", "so", "if", "when", "which", "that"}
        for word in last_words[-2:]
    ) else 0.0
    context_score = min(1.0, len(words) / 55)
    sentence_count_score = min(1.0, len(sentences) / 3)

    completeness_score = (
        0.42 * terminal_ratio
        + 0.30 * context_score
        + 0.28 * sentence_count_score
        - weak_open_penalty
        - dangling_end_penalty
    )

    return max(0.0, min(1.0, completeness_score)), len(sentences)


def score_dialogue_momentum(text, normalized_text):
    question_score = min(0.35, text.count("?") * 0.18)
    response_hits = len(re.findall(
        r"\b(so|because|but|actually|the reason|that means|here'?s why|what happens)\b",
        normalized_text,
    ))
    second_person_hits = len(re.findall(r"\b(you|your|people|everybody|nobody|someone)\b", normalized_text))
    first_person_hits = len(re.findall(r"\b(i|we|my|our)\b", normalized_text))
    exchange_score = 0.22 if first_person_hits and second_person_hits else 0.0

    raw_score = (
        question_score
        + min(0.30, response_hits * 0.08)
        + min(0.22, second_person_hits * 0.025)
        + exchange_score
    )

    return max(0.0, min(1.0, raw_score))


def score_text_window(text):
    text = clean_transcript_text(text)
    normalized_text = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", normalized_text)
    word_count = max(1, len(words))
    keyword_weights = combined_keyword_weights()

    weighted_keyword_total = 0.0

    for phrase, weight in keyword_weights.items():
        if " " in phrase:
            weighted_keyword_total += normalized_text.count(phrase) * weight
        else:
            weighted_keyword_total += words.count(phrase) * weight

    topic_hits = sum(1 for word in words if word in TOPIC_KEYWORDS)
    emotion_hits = sum(1 for word in words if word in EMOTION_KEYWORDS)
    conflict_hits = sum(1 for word in words if word in CONFLICT_KEYWORDS)
    filler_hits = sum(1 for word in words if word in FILLER_WORDS)

    hook_hits = sum(
        1
        for pattern in HOOK_PATTERNS
        if re.search(pattern, normalized_text)
    )

    question_hits = text.count("?")
    number_hits = len(re.findall(r"\b\d+[\d,.]*%?\b", text))
    money_hits = len(re.findall(r"\$\s?\d+|\b\d+[\d,.]*\s?(dollars?|bucks?)\b", text, re.IGNORECASE))
    percent_hits = len(re.findall(r"\b\d+[\d,.]*\s?%\b|\bpercent\b", normalized_text))
    specificity_hits = number_hits + money_hits + percent_hits

    payoff_hits = len(re.findall(
        r"\b(because|therefore|so that means|that means|the reason|that's why|this is why|which means|as a result)\b",
        normalized_text,
    ))
    contrast_hits = len(re.findall(r"\b(but|however|instead|actually|the problem is|the truth is)\b", normalized_text))
    claim_hits = sum(1 for pattern in CLAIM_PATTERNS if re.search(pattern, normalized_text))
    explicit_payoff_hits = sum(1 for pattern in PAYOFF_PATTERNS if re.search(pattern, normalized_text))
    hook_type = detect_hook_type(text)

    density_base = max(35, word_count)
    keyword_density = weighted_keyword_total * 100 / density_base
    topic_density = topic_hits * 100 / density_base
    emotion_density = emotion_hits * 100 / density_base
    conflict_density = conflict_hits * 100 / density_base

    first_words = " ".join(words[:28])
    opener_hook_hits = sum(
        1
        for pattern in HOOK_PATTERNS
        if re.search(pattern, first_words)
    )
    opener_question = 1 if "?" in text[:220] else 0

    hook_score = min(1.0, hook_hits * 0.24 + opener_hook_hits * 0.34 + opener_question * 0.16)
    keyword_score = saturating_score(keyword_density, 8.0)
    topic_score = saturating_score(topic_density, 5.5)
    emotion_score = saturating_score(emotion_density, 4.0)
    conflict_score = saturating_score(conflict_density, 4.3)
    specificity_score = saturating_score(specificity_hits, 3.2)
    payoff_score = saturating_score(payoff_hits + contrast_hits * 0.65, 3.0)
    claim_score = saturating_score(claim_hits + (1 if hook_type else 0), 2.4)
    resolution_score = saturating_score(explicit_payoff_hits + payoff_hits, 2.2)
    sentence_completeness_score, sentence_count = score_sentence_completeness(text, words)
    dialogue_score = score_dialogue_momentum(text, normalized_text)

    filler_ratio = filler_hits / word_count
    filler_penalty = min(0.35, max(0.0, filler_ratio - 0.22) * 1.8)
    clarity_score = max(0.0, 1.0 - filler_penalty)

    text_score = (
        0.14 * hook_score
        + 0.12 * keyword_score
        + 0.11 * conflict_score
        + 0.09 * emotion_score
        + 0.09 * topic_score
        + 0.09 * specificity_score
        + 0.12 * payoff_score
        + 0.08 * claim_score
        + 0.07 * resolution_score
        + 0.06 * sentence_completeness_score
        + 0.03 * dialogue_score
    )

    text_score = max(0.0, min(0.98, text_score * clarity_score))

    return {
        "score": float(text_score),
        "hook_score": float(hook_score),
        "keyword_score": float(keyword_score),
        "conflict_score": float(conflict_score),
        "emotion_score": float(emotion_score),
        "topic_score": float(topic_score),
        "specificity_score": float(specificity_score),
        "payoff_score": float(payoff_score),
        "claim_score": float(claim_score),
        "resolution_score": float(resolution_score),
        "sentence_completeness_score": float(sentence_completeness_score),
        "dialogue_score": float(dialogue_score),
        "clarity_score": float(clarity_score),
        "filler_ratio": float(filler_ratio),
        "word_count": int(word_count),
        "sentence_count": int(sentence_count),
        "hook_type": hook_type,
    }


def score_opening_text(text):
    if not text.strip():
        return 0.0

    details = score_text_window(text)
    normalized_text = text.lower()

    first_line_bonus = 0.0

    if re.search(r"\b(why|what|how|here'?s|look|first of all|the truth|the problem|nobody|most people)\b", normalized_text):
        first_line_bonus += 0.25

    if re.search(r"\b\d+[\d,.]*%?\b|\$\s?\d+", text):
        first_line_bonus += 0.15

    if any(word in normalized_text for word in ["crazy", "insane", "scary", "brutal", "wrong", "debt", "money"]):
        first_line_bonus += 0.18

    return min(1.0, details["score"] * 0.75 + details["hook_score"] * 0.25 + first_line_bonus)


def score_comment_potential(text):
    normalized_text = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", normalized_text)

    if not words:
        return 0.0

    trigger_hits = sum(1 for word in words if word in COMMENT_TRIGGER_WORDS)
    question_hits = text.count("?")
    contrast_hits = len(re.findall(r"\b(but|however|actually|instead|first of all|the truth is|the problem is)\b", normalized_text))
    absolute_hits = len(re.findall(r"\b(always|never|everyone|nobody|all|none|everybody|impossible|guaranteed)\b", normalized_text))
    money_or_number_hits = len(re.findall(r"\$\s?\d+|\b\d+[\d,.]*%?\b|\b\d+[\d,.]*\s?(dollars?|bucks?)\b", text, re.IGNORECASE))
    debate_phrase_hits = len(re.findall(
        r"\b(do you think|would you|should you|is it fair|is this fair|hot take|unpopular opinion|people don'?t understand)\b",
        normalized_text,
    ))

    raw_score = (
        trigger_hits * 0.22
        + question_hits * 0.55
        + contrast_hits * 0.30
        + absolute_hits * 0.28
        + money_or_number_hits * 0.16
        + debate_phrase_hits * 0.75
    )

    return min(1.0, saturating_score(raw_score, 2.6))


def score_spoken_pacing(text, duration):
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", text)

    if duration <= 0 or not words:
        return 0.0

    words_per_minute = len(words) / duration * 60

    if words_per_minute < 95:
        return max(0.0, words_per_minute / 95 * 0.65)

    if words_per_minute > 245:
        return max(0.2, 1.0 - ((words_per_minute - 245) / 180))

    return max(0.0, 1.0 - abs(words_per_minute - 170) / 120)


def score_duration(duration):
    min_clip_duration = active_min_clip_duration()
    max_clip_duration = active_max_clip_duration()

    if duration < min_clip_duration or duration > max_clip_duration:
        return 0.0

    durations = active_candidate_durations()
    ideal_duration = float(np.median(durations)) if durations else 42.0
    spread = max(18.0, max_clip_duration - min_clip_duration)
    return max(0.35, 1.0 - abs(duration - ideal_duration) / spread)


def analyze_first_second_qc(video_path, transcript_excerpt, intro_mode, theme_profile):
    first_word = first_spoken_word(transcript_excerpt)
    weak_first_word = first_word in WEAK_START_WORDS or first_word in FILLER_OPENERS
    words = words_from_text(transcript_excerpt)
    has_context_card = intro_mode in {"context_card", "voice_setup", "explain_then_clip", "editorial_countdown"}
    flags = []

    if not words:
        flags.append("no transcript in opening")

    if weak_first_word and not has_context_card:
        flags.append(f"weak first word: {first_word}")

    return {
        "audio_starts_fast": bool(words),
        "subtitle_starts_fast": bool(words),
        "visual_interest_score": 0.5 if has_context_card else 0.0,
        "weak_first_word": weak_first_word,
        "has_face_or_context_card": has_context_card,
        "dead_air_seconds": 0.0 if words else 1.0,
        "passed": not flags,
        "flags": flags,
    }


def score_captionability(text, duration):
    words = words_from_text(text)

    if not words or duration <= 0:
        return 0.0, {"flags": ["no words for captions"]}

    words_per_second = len(words) / max(1.0, duration)
    longest_word = max((len(word) for word in words), default=0)
    long_sentence_count = sum(
        1
        for sentence in re.split(r"(?<=[.?!])\s+", text)
        if len(words_from_text(sentence)) > 18
    )
    score = 1.0

    if words_per_second > 3.8:
        score -= min(0.28, (words_per_second - 3.8) * 0.12)

    if longest_word > 18:
        score -= 0.08

    if long_sentence_count:
        score -= min(0.20, long_sentence_count * 0.06)

    score = max(0.0, min(1.0, score))
    return score, {
        "words_per_second": float(words_per_second),
        "longest_word": int(longest_word),
        "long_caption_sentence_count": int(long_sentence_count),
        "flags": [
            flag
            for flag, condition in [
                ("too fast for clean captions", words_per_second > 4.2),
                ("long caption sentence", long_sentence_count > 0),
            ]
            if condition
        ],
    }


def score_transformation_candidate(
    theme_name,
    intro_mode,
    theme_signal_result,
    title_quality,
    popularity_score,
    source_tier="",
    readiness_score=0.0,
    arc_details=None,
):
    risk_controls = get_risk_controls(theme_name)
    transformation_notes = ["curated source selection", "vertical reframing", "caption packaging"]
    score = 0.24
    trusted_source = trust_configured_source_relevance() and configured_source_tier(source_tier)
    arc_details = arc_details or {}
    arc_quality = max(
        float(readiness_score or 0.0),
        (
            float(arc_details.get("arc_hook_score") or 0.0)
            + float(arc_details.get("arc_payoff_score") or arc_details.get("arc_resolution_score") or 0.0)
            + float(arc_details.get("arc_standalone_score") or 0.0)
        )
        / 3.0,
    )

    if intro_mode in {"context_card", "voice_setup", "explain_then_clip", "clip_then_takeaway"}:
        score += 0.18
        transformation_notes.append(f"{intro_mode} intro")

    if trusted_source and arc_quality >= 0.66:
        score += 0.14
        transformation_notes.append("trusted source with complete viewer arc")
    elif float(theme_signal_result.get("theme_signal_score") or 0.0) >= 0.32:
        score += 0.14
        transformation_notes.append("theme-specific editorial signal")

    if (
        title_quality.get("specificity", 0.0) >= 0.45
        and title_quality.get("theme_native_title", True)
        and not title_quality.get("generic_title")
        and not title_quality.get("mechanical_title")
        and not title_quality.get("repetitive_title")
    ):
        score += 0.12
        transformation_notes.append("specific title framing")
    elif title_quality.get("generic_title") or title_quality.get("mechanical_title"):
        score -= 0.05
        transformation_notes.append("title framing needs editorial rewrite")

    if popularity_score >= 0.18:
        score += 0.08
        transformation_notes.append("public replay/comment signal")

    if risk_controls.get("requires_claim_context"):
        score += 0.08 if intro_mode != "cold_open" else -0.08

    score = max(0.0, min(1.0, score))
    minimum = float(risk_controls.get("minimum_transformation_score") or 0.55)
    reused_content_risk = max(0.0, min(1.0, minimum + 0.20 - score))
    return {
        "transformation_score": score,
        "reused_content_risk": reused_content_risk,
        "minimum_transformation_score": minimum,
        "transformation_notes": transformation_notes,
    }


def theme_weighted_candidate_score(
    text_score,
    opening_score,
    arc_details,
    popularity_score,
    captionability_score,
    boundary_score,
    pacing_score,
    transformation_score,
    reused_content_risk,
    theme_signal_score,
    source_tier="",
):
    weights = get_scoring_weights(active_theme_name())
    hook_score = max(opening_score, float(arc_details.get("arc_hook_score") or 0.0))
    payoff_score = max(float(arc_details.get("arc_payoff_score") or 0.0), float(arc_details.get("arc_resolution_score") or 0.0))
    context_score = float(arc_details.get("arc_standalone_score") or 0.0)
    visual_proxy = max(0.0, min(1.0, boundary_score * 0.72 + captionability_score * 0.28))
    components = {
        "hook": hook_score,
        "payoff": payoff_score,
        "standalone_context": context_score,
        "theme_signal": theme_signal_score,
        "public_popularity": popularity_score,
        "captionability": captionability_score,
        "visual_quality": visual_proxy,
        "pacing": pacing_score,
        "transformation": transformation_score,
        "claim_safety": 1.0 - reused_content_risk,
    }
    active_weights = {
        key: float(value)
        for key, value in weights.items()
        if key in components and float(value) > 0
    }

    weighting_strategy = "theme_weighted"

    if trust_configured_source_relevance() and configured_source_tier(source_tier):
        original_theme_weight = float(active_weights.get("theme_signal") or 0.0)
        capped_theme_weight = min(original_theme_weight, CONFIGURED_SOURCE_THEME_WEIGHT_CAP)
        released_weight = max(0.0, original_theme_weight - capped_theme_weight)
        active_weights["theme_signal"] = capped_theme_weight

        for key, share in (
            ("hook", 0.24),
            ("payoff", 0.24),
            ("standalone_context", 0.18),
            ("public_popularity", 0.14),
            ("transformation", 0.12),
            ("captionability", 0.08),
        ):
            if key in components:
                active_weights[key] = float(active_weights.get(key) or 0.0) + released_weight * share

        if released_weight > 0:
            weighting_strategy = "configured_source_watchability"

    weight_total = sum(active_weights.values()) or 1.0
    score = sum(components[key] * value for key, value in active_weights.items()) / weight_total
    risk_penalty = reused_content_risk * (0.12 if get_risk_controls(active_theme_name()).get("requires_claim_context") else 0.07)
    components["effective_theme_signal_weight"] = round(float(active_weights.get("theme_signal") or 0.0), 4)
    components["theme_weighting_strategy"] = weighting_strategy
    return max(0.0, min(1.0, score - risk_penalty)), components


def aligned_start_point(value, stride, max_start):
    value = max(0, min(int(value), int(max_start)))
    stride = max(1, int(stride))
    return max(0, min(max_start, int(round(value / stride) * stride)))


def popularity_signal_times(popularity_profile, total_duration):
    signals = []
    total_duration = max(1, float(total_duration or 0))

    for marker in sorted(
        popularity_profile.get("heatmap") or [],
        key=lambda item: float(item.get("value") or item.get("score") or 0),
        reverse=True,
    )[:120]:
        start = float(marker.get("start_time", marker.get("start", marker.get("time", 0))) or 0)
        end = float(marker.get("end_time", marker.get("end", start + 12)) or start + 12)
        midpoint = max(0.0, min(total_duration, (start + end) / 2))
        signals.append((midpoint, "youtube_heatmap"))

    for marker in sorted(
        popularity_profile.get("timestamp_markers") or [],
        key=lambda item: int(item.get("count") or 1),
        reverse=True,
    )[:120]:
        marker_time = float(marker.get("time") or 0)

        if 0 <= marker_time <= total_duration:
            signals.append((marker_time, "timestamp_mentions"))

    for chapter in (popularity_profile.get("chapters") or [])[:80]:
        chapter_start = float(chapter.get("start_time", chapter.get("start", 0)) or 0)

        if 0 <= chapter_start <= total_duration:
            signals.append((chapter_start, "chapters"))

    return signals


def high_energy_start_points(seconds, stride, max_start, max_count):
    if max_count <= 0 or not seconds:
        return []

    step = max(stride, 10)
    window = 12
    scored = []

    for start in range(0, max(1, max_start + 1), step):
        end = min(len(seconds), start + window)
        values = [
            float(second.get("excitement") or 0)
            for second in seconds[start:end]
            if isinstance(second, dict)
        ]

        if not values:
            continue

        scored.append((float(np.mean(values)), aligned_start_point(start, stride, max_start)))

    ranked = sorted(scored, reverse=True)
    starts = []

    for _, start in ranked:
        if start not in starts:
            starts.append(start)

        if len(starts) >= max_count:
            break

    return starts


def evenly_spaced_start_points(max_start, stride, max_count):
    if max_count <= 0:
        return []

    if max_count == 1:
        return [0]

    starts = []

    for index in range(max_count):
        ratio = index / max(1, max_count - 1)
        starts.append(aligned_start_point(ratio * max_start, stride, max_start))

    return sorted(set(starts))


def candidate_start_points(total_duration, min_clip_duration, max_clip_duration, candidate_stride, seconds, popularity_profile):
    max_start = max(0, int(total_duration - min_clip_duration))
    all_starts = list(range(0, max(1, max_start + 1), candidate_stride))
    policy = {
        "enabled": ENABLE_SCORING_WINDOW_CAPS,
        "mode": "full_scan",
        "source_duration_seconds": int(total_duration),
        "full_scan_max_seconds": FULL_SOURCE_SCAN_MAX_SECONDS,
        "max_start_points": MAX_SCORING_START_POINTS,
        "available_start_points": len(all_starts),
        "selected_start_points": len(all_starts),
        "public_signal_count": 0,
        "high_energy_start_points": 0,
        "coverage_start_points": 0,
    }

    if (
        not ENABLE_SCORING_WINDOW_CAPS
        or len(all_starts) <= MAX_SCORING_START_POINTS
    ):
        return all_starts, policy

    signal_times = popularity_signal_times(popularity_profile or {}, total_duration)
    signal_starts = []
    radius = SCORING_SIGNAL_WINDOW_RADIUS_SECONDS

    for signal_time, _source in signal_times:
        for offset in [-radius, -max_clip_duration, -max_clip_duration / 2, 0, max_clip_duration / 2]:
            start = aligned_start_point(signal_time + offset, candidate_stride, max_start)

            if start not in signal_starts:
                signal_starts.append(start)

    max_signal_starts = max(40, int(MAX_SCORING_START_POINTS * 0.48))
    signal_starts = signal_starts[:max_signal_starts]
    remaining = max(0, MAX_SCORING_START_POINTS - len(signal_starts))
    energy_starts = high_energy_start_points(
        seconds=seconds,
        stride=candidate_stride,
        max_start=max_start,
        max_count=max(0, int(remaining * 0.45)),
    )
    selected = []

    for start in signal_starts + energy_starts:
        if start not in selected:
            selected.append(start)

    coverage_needed = max(0, MAX_SCORING_START_POINTS - len(selected))
    coverage_starts = evenly_spaced_start_points(max_start, candidate_stride, coverage_needed)

    for start in coverage_starts:
        if start not in selected:
            selected.append(start)

    selected = sorted(selected[:MAX_SCORING_START_POINTS])
    policy.update({
        "mode": "capped_two_pass",
        "selected_start_points": len(selected),
        "public_signal_count": len(signal_times),
        "public_signal_start_points": len(signal_starts),
        "high_energy_start_points": len(energy_starts),
        "coverage_start_points": len(coverage_starts),
    })
    return selected, policy


def build_candidate_clips(transcript_payload, audio_payload, popularity_profile=None, source_record=None):
    seconds = audio_payload.get("seconds", [])
    segments = transcript_payload.get("segments", [])
    popularity_profile = popularity_profile or {}
    source_record = source_record or {}
    theme_name = active_theme_name()
    theme_profile = active_theme_profile(theme_name)
    min_clip_duration = active_min_clip_duration(theme_name)
    max_clip_duration = active_max_clip_duration(theme_name)
    candidate_durations = active_candidate_durations(theme_name)
    candidate_stride = active_candidate_stride(theme_name)

    if not seconds:
        return []

    total_duration = len(seconds)
    candidates = []

    start_points, window_policy = candidate_start_points(
        total_duration=total_duration,
        min_clip_duration=min_clip_duration,
        max_clip_duration=max_clip_duration,
        candidate_stride=candidate_stride,
        seconds=seconds,
        popularity_profile=popularity_profile,
    )
    transcript_payload["_candidate_window_policy"] = window_policy

    print(
        " -> Candidate window policy: "
        f"{window_policy['mode']} "
        f"({window_policy['selected_start_points']}/{window_policy['available_start_points']} start points, "
        f"duration={window_policy['source_duration_seconds']}s)"
    )

    for start in start_points:
        for duration in candidate_durations:
            if duration > max_clip_duration:
                continue

            naturalized = naturalize_clip_window(
                segments=segments,
                provisional_start=start,
                duration=duration,
                total_duration=total_duration,
            )

            if naturalized is None:
                continue

            clip_start, clip_end, matching_segments = naturalized
            actual_duration = clip_end - clip_start

            if actual_duration < min_clip_duration or actual_duration > max_clip_duration or not matching_segments:
                continue

            text = clean_transcript_text(" ".join(segment["text"] for segment in matching_segments))
            words = re.findall(r"[a-zA-Z][a-zA-Z']+", text)

            if len(words) < MIN_WORDS_PER_CANDIDATE:
                continue

            opening_segments = [
                segment
                for segment in matching_segments
                if segment["start"] < clip_start + 12
            ]
            opening_text = clean_transcript_text(" ".join(segment["text"] for segment in opening_segments))

            start_index = max(0, int(clip_start))
            end_index = min(total_duration, max(start_index + 1, int(np.ceil(clip_end))))
            excitement_values = [
                second["excitement"]
                for second in seconds[start_index:end_index]
            ]
            tone_shift_values = [
                second["tone_shift"]
                for second in seconds[start_index:end_index]
            ]
            opening_audio_values = [
                second["excitement"]
                for second in seconds[start_index:min(end_index, start_index + 10)]
            ]

            mean_excitement = float(np.mean(excitement_values))
            peak_excitement = float(np.percentile(excitement_values, 90))
            tone_shift = float(np.percentile(tone_shift_values, 85))
            opening_audio = float(np.mean(opening_audio_values)) if opening_audio_values else mean_excitement

            audio_score = (
                0.42 * mean_excitement
                + 0.30 * peak_excitement
                + 0.18 * tone_shift
                + 0.10 * opening_audio
            )
            audio_score = max(0.0, min(1.0, audio_score))

            text_details = score_text_window(text)
            text_score = text_details["score"]
            opening_text_score = score_opening_text(opening_text or text[:320])
            opening_score = max(0.0, min(1.0, 0.68 * opening_text_score + 0.32 * opening_audio))
            comment_score = score_comment_potential(text)
            popularity_details = score_popularity_for_window(popularity_profile, clip_start, clip_end)
            popularity_score = float(popularity_details.get("score") or 0)
            comment_topic_details = score_comment_topic_match(popularity_profile, text)
            comment_topic_score = float(comment_topic_details.get("score") or 0)
            arc_score, arc_details = score_retention_arc(
                text=text,
                matching_segments=matching_segments,
                clip_start=clip_start,
                clip_end=clip_end,
                text_details=text_details,
            )
            pacing_score = score_spoken_pacing(text, actual_duration)
            duration_score = score_duration(actual_duration)
            boundary_score, boundary_flags = score_boundary_quality(
                matching_segments=matching_segments,
                clip_start=clip_start,
                clip_end=clip_end,
            )
            readiness_score, readiness_details = score_clip_readiness(
                text=text,
                matching_segments=matching_segments,
                clip_start=clip_start,
                clip_end=clip_end,
                text_details=text_details,
                arc_details=arc_details,
                boundary_score=boundary_score,
                boundary_flags=boundary_flags,
                opening_score=opening_score,
                comment_score=comment_score,
                popularity_score=popularity_score,
                comment_topic_score=comment_topic_score,
            )
            topic_terms = extract_topic_fingerprint(text)
            hook_reason = explain_hook(
                text=text,
                text_details=text_details,
                opening_score=opening_score,
                audio_score=audio_score,
            )
            suggested_title, suggested_caption, hashtags, suggested_description = build_suggested_copy(
                text=text,
                hook_reason=hook_reason,
                topic_terms=topic_terms,
                text_details={
                    **text_details,
                    "duration": actual_duration,
                },
                source_record=source_record,
            )
            topic_terms = merge_title_topics(topic_terms, suggested_title, source_text=text)
            source_tier = str((source_record or {}).get("source_tier") or "legacy").lower()
            theme_signal_result = score_theme_signals(
                theme_name=theme_name,
                text=text,
                segments=matching_segments,
                audio_path="",
                clip_start=clip_start,
                clip_end=clip_end,
                metadata={
                    "theme_profile": theme_profile,
                    "popularity_profile": popularity_profile,
                    "text_details": text_details,
                    "arc_details": arc_details,
                },
            )
            theme_signal_result = apply_configured_source_theme_signal_floor(theme_signal_result, source_tier)
            if theme_signal_result.get("archetype"):
                suggested_title, suggested_caption, hashtags, suggested_description = build_suggested_copy(
                    text=text,
                    hook_reason=hook_reason,
                    topic_terms=extract_topic_fingerprint(text),
                    text_details={
                        **text_details,
                        "duration": actual_duration,
                        "theme_archetype": theme_signal_result.get("archetype", ""),
                    },
                    source_record=source_record,
                )
                topic_terms = merge_title_topics(extract_topic_fingerprint(text), suggested_title, source_text=text)

            theme_signal_score = float(theme_signal_result.get("theme_signal_score") or 0.0)
            intro_mode = theme_signal_result.get("recommended_intro_mode") or (theme_profile.get("packaging") or {}).get("default_intro_mode", "context_card")
            first_second_qc = analyze_first_second_qc(
                video_path=None,
                transcript_excerpt=opening_text or text[:220],
                intro_mode=intro_mode,
                theme_profile=theme_profile,
            )
            captionability_score, captionability_details = score_captionability(text, actual_duration)
            title_quality = score_title_quality(theme_name, suggested_title, topic_terms=topic_terms)
            transformation = score_transformation_candidate(
                theme_name=theme_name,
                intro_mode=intro_mode,
                theme_signal_result=theme_signal_result,
                title_quality=title_quality,
                popularity_score=popularity_score,
                source_tier=source_tier,
                readiness_score=readiness_score,
                arc_details=arc_details,
            )
            score, score_components = theme_weighted_candidate_score(
                text_score=text_score,
                opening_score=opening_score,
                arc_details=arc_details,
                popularity_score=popularity_score,
                captionability_score=captionability_score,
                boundary_score=boundary_score,
                pacing_score=pacing_score,
                transformation_score=transformation["transformation_score"],
                reused_content_risk=transformation["reused_content_risk"],
                theme_signal_score=theme_signal_score,
                source_tier=source_tier,
            )
            quality_score = score
            popularity_boost = POPULARITY_SCORE_WEIGHT * popularity_score * (0.62 + 0.38 * boundary_score)
            readiness_multiplier = 0.82 + 0.22 * readiness_score

            if readiness_details.get("readiness_tier") == "reject":
                readiness_multiplier -= 0.10

            score = min(1.0, max(0.0, score * readiness_multiplier + popularity_boost))
            feedback_prior = score_analytics_feedback_prior(
                theme=theme_name,
                source_record=source_record,
                archetype=theme_signal_result.get("archetype", ""),
                intro_mode=intro_mode,
                caption_style=(theme_profile.get("packaging") or {}).get("caption_style", ""),
                content_format="raw_candidate",
                duration=actual_duration,
            )
            score = min(1.0, max(0.0, score + float(feedback_prior.get("score_adjustment") or 0.0)))
            score_components["analytics_feedback_adjustment"] = float(feedback_prior.get("score_adjustment") or 0.0)
            source_tier_adjustment = {
                "priority": 0.025,
                "secondary": 0.010,
                "legacy": 0.0,
            }.get(source_tier, 0.0)

            if (source_record or {}).get("routing_override_matches"):
                source_tier_adjustment += 0.005

            score = min(1.0, max(0.0, score + source_tier_adjustment))
            score_components["source_inventory_adjustment"] = round(source_tier_adjustment, 4)
            guest_signal = guest_recognizability_signal(
                theme_name=theme_name,
                source_record=source_record,
                popularity_profile=popularity_profile,
                readiness_score=readiness_score,
                arc_details=arc_details,
                first_second_qc=first_second_qc,
                transformation=transformation,
            )
            guest_adjustment = float(guest_signal.get("adjustment") or 0.0)
            score = min(1.0, max(0.0, score + guest_adjustment))
            score_components["guest_recognizability_adjustment"] = round(guest_adjustment, 4)

            candidates.append(CandidateClip(
                start_time=float(clip_start),
                end_time=float(clip_end),
                score=float(score),
                audio_score=float(audio_score),
                text_score=float(text_score),
                opening_score=float(opening_score),
                comment_score=float(comment_score),
                popularity_score=float(popularity_score),
                arc_score=float(arc_score),
                readiness_score=float(readiness_score),
                pacing_score=float(pacing_score),
                duration_score=float(duration_score),
                boundary_score=float(boundary_score),
                diversity_score=1.0,
                theme_signal_score=float(theme_signal_score),
                theme_signals=theme_signal_result,
                first_second_qc=first_second_qc,
                transformation_score=float(transformation["transformation_score"]),
                reused_content_risk=float(transformation["reused_content_risk"]),
                experiment={
                    "experiment_id": f"{theme_name}_intro_mode",
                    "variant": intro_mode,
                    "hypothesis": "Theme-aligned intro mode improves engaged view rate and retention.",
                },
                rank_signals={
                    **text_details,
                    **arc_details,
                    **readiness_details,
                    "boundary_flags": boundary_flags,
                    "quality_score": float(quality_score),
                    "theme_score_components": score_components,
                    "analytics_feedback_prior": feedback_prior,
                    "source_tier": source_tier,
                    "origin_theme": (source_record or {}).get("origin_theme", active_theme_name()),
                    "routed_from_theme": (source_record or {}).get("routed_from_theme", ""),
                    "route_targets": (source_record or {}).get("route_targets", []),
                    "routing_status": (source_record or {}).get("routing_status", "primary"),
                    "routing_override_matches": (source_record or {}).get("routing_override_matches", []),
                    "guest_recognizability": guest_signal,
                    "guest_recognizability_score": float(guest_signal.get("score") or 0.0),
                    "guest_recognizability_adjustment": guest_adjustment,
                    "theme_profile": theme_profile.get("profile", "generic"),
                    "theme_signal_score": float(theme_signal_score),
                    "theme_signals": theme_signal_result.get("signals", {}),
                    "theme_signal_concerns": theme_signal_result.get("concerns", []),
                    "theme_archetype": theme_signal_result.get("archetype", ""),
                    "recommended_intro_mode": intro_mode,
                    "first_second_qc": first_second_qc,
                    "captionability_score": float(captionability_score),
                    "captionability": captionability_details,
                    "transformation_score": float(transformation["transformation_score"]),
                    "reused_content_risk": float(transformation["reused_content_risk"]),
                    "transformation_notes": transformation.get("transformation_notes", []),
                    "title_quality": title_quality,
                    "popularity_score": float(popularity_score),
                    "popularity_heatmap_score": float(popularity_details.get("heatmap_score") or 0),
                    "popularity_timestamp_score": float(popularity_details.get("timestamp_score") or 0),
                    "popularity_chapter_score": float(popularity_details.get("chapter_score") or 0),
                    "popularity_source": popularity_details.get("source", ""),
                    "popularity_profile_sources": popularity_details.get("profile_sources", []),
                    "comment_topic_score": float(comment_topic_score),
                    "comment_topic_matched_terms": comment_topic_details.get("matched_terms", []),
                    "candidate_window_policy_mode": window_policy.get("mode", ""),
                    "candidate_window_policy": window_policy,
                },
                transcript_excerpt=text[:260].strip(),
                hook_reason=hook_reason,
                topic_fingerprint=topic_terms,
                suggested_title=suggested_title,
                suggested_caption=suggested_caption,
                suggested_description=suggested_description,
                hashtags=hashtags,
                source_title=resolve_record_title(source_record or {}),
                source_video_url=(source_record or {}).get("video_url", ""),
            ))

    return candidates


def select_non_overlapping_clips(candidates, max_clips=None, existing_fingerprints=None):
    selected = []
    existing_fingerprints = existing_fingerprints or []
    if max_clips is None:
        max_clips = active_theme_clip_limit()
    min_selected_score = active_publishable_min_selected_score()
    max_topic_similarity = active_max_topic_similarity()

    for candidate in sorted(candidates, key=candidate_ranking_key, reverse=True):
        if candidate.score < min_selected_score:
            continue

        if not candidate_selection_ready(candidate):
            continue

        overlaps = any(
            candidate.start_time < clip.end_time + MIN_CLIP_SPACING_SECONDS
            and candidate.end_time + MIN_CLIP_SPACING_SECONDS > clip.start_time
            for clip in selected
        )

        if overlaps:
            continue

        max_topic_overlap = max(
            (
                topic_similarity(candidate.topic_fingerprint, clip.topic_fingerprint)
                for clip in selected
            ),
            default=0.0,
        )
        max_existing_overlap = max(
            (
                topic_similarity(candidate.topic_fingerprint, fingerprint)
                for fingerprint in existing_fingerprints
            ),
            default=0.0,
        )
        max_total_overlap = max(max_topic_overlap, max_existing_overlap)
        candidate.diversity_score = float(1.0 - max_total_overlap)

        if max_total_overlap > max_topic_similarity:
            continue

        selected.append(candidate)

        if max_clips is not None and len(selected) >= max_clips:
            break

    return sorted(selected, key=lambda item: item.start_time)


def score_viral_candidates(audio_filename, cleaned_title, lang_code="en", popularity_profile=None, source_record=None):
    start_finding = time.time()
    source_record = source_record or {}
    disqualified, negative_hits = source_disqualified_by_theme(source_record, active_theme_name())
    if disqualified:
        print(
            " -> Source skipped by theme guard "
            f"(negative source signals: {', '.join(map(str, negative_hits))})"
        )
        source_record["_processing_metrics"] = {
            "scoring_seconds": 0.0,
            "transcript_stage_seconds": 0.0,
            "audio_feature_stage_seconds": 0.0,
            "candidate_build_seconds": 0.0,
            "candidate_window_policy": {"mode": "source_disqualified"},
            "candidate_count": 0,
            "slow_source_threshold_seconds": SLOW_SOURCE_REVIEW_SECONDS,
            "slow_source_review": False,
            "source_disqualified": True,
            "negative_source_signals": negative_hits,
        }
        scoring_filepath = os.path.join(
            transcriptions_path,
            f"{cleaned_title}_clip_scores.json",
        )
        with open(scoring_filepath, "w", encoding="utf-8") as f:
            json.dump({
                "scoring_model_version": SCORING_MODEL_VERSION,
                "candidate_window_policy": {"mode": "source_disqualified"},
                "selected": [],
                "top_candidates": [],
                "source_disqualified": True,
                "negative_source_signals": negative_hits,
            }, f, indent=4)
        write_clip_review_exports(cleaned_title, [], [])
        write_source_dossier(
            cleaned_title=cleaned_title,
            source_record=source_record,
            popularity_profile=popularity_profile or {},
            candidates=[],
            selected_clips=[],
        )
        return []

    start_transcript_stage = time.time()
    transcript_payload = transcribe_audio_segments(
        audio_filename,
        cleaned_title,
        lang_code,
        popularity_profile=popularity_profile,
    )
    transcript_stage_seconds = time.time() - start_transcript_stage
    transcript_scope = transcript_payload.get("transcript_scope") or {}
    analysis_windows = [
        (window.get("start", 0.0), window.get("end", 0.0))
        for window in transcript_scope.get("windows") or []
        if isinstance(window, dict)
    ]
    start_audio_stage = time.time()
    audio_payload = analyze_audio_features(
        audio_filename,
        cleaned_title,
        analysis_windows=analysis_windows,
        source_duration=transcript_payload.get("duration"),
    )
    audio_stage_seconds = time.time() - start_audio_stage
    start_candidate_stage = time.time()
    candidates = build_candidate_clips(
        transcript_payload,
        audio_payload,
        popularity_profile=popularity_profile,
        source_record=source_record,
    )
    candidate_stage_seconds = time.time() - start_candidate_stage
    candidate_window_policy = transcript_payload.get("_candidate_window_policy", {})
    scoring_seconds = time.time() - start_finding
    source_record["_processing_metrics"] = {
        "scoring_seconds": round(scoring_seconds, 2),
        "transcript_stage_seconds": round(transcript_stage_seconds, 2),
        "audio_feature_stage_seconds": round(audio_stage_seconds, 2),
        "candidate_build_seconds": round(candidate_stage_seconds, 2),
        "candidate_window_policy": candidate_window_policy,
        "candidate_count": len(candidates),
        "slow_source_threshold_seconds": SLOW_SOURCE_REVIEW_SECONDS,
        "slow_source_review": scoring_seconds > SLOW_SOURCE_REVIEW_SECONDS,
    }

    scoring_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_clip_scores.json",
    )

    with open(scoring_filepath, "w", encoding="utf-8") as f:
        json.dump({
            "scoring_model_version": SCORING_MODEL_VERSION,
            "candidate_window_policy": candidate_window_policy,
            "candidate_cache_mode": "all_candidates"
            if CLIP_SCORE_CACHE_CANDIDATE_LIMIT <= 0
            else f"top_{CLIP_SCORE_CACHE_CANDIDATE_LIMIT}",
            "selected": [],
            "all_candidates": [
                candidate_to_dict(clip)
                for clip in ranked_candidate_window(candidates, CLIP_SCORE_CACHE_CANDIDATE_LIMIT)
            ],
            "top_candidates": [
                candidate_to_dict(clip)
                for clip in ranked_candidate_window(candidates, CLIP_REVIEW_REPORT_CANDIDATE_LIMIT)
            ],
        }, f, indent=4)

    review_json, review_csv = write_clip_review_exports(cleaned_title, [], candidates)
    dossier_path = write_source_dossier(
        cleaned_title=cleaned_title,
        source_record=source_record,
        popularity_profile=popularity_profile or {},
        candidates=candidates,
        selected_clips=[],
    )

    if source_record["_processing_metrics"]["slow_source_review"]:
        print(
            " -> Slow source review flagged: "
            f"{scoring_seconds:.2f}s > {SLOW_SOURCE_REVIEW_SECONDS:.2f}s"
        )

    print(f" -> Viral clip scoring took: {scoring_seconds:.2f} seconds")
    print(f" -> Candidate clips scored: {len(candidates)}\n")
    print(f" -> Clip review JSON: {review_json}")
    print(f" -> Clip review CSV: {review_csv}\n")
    print(f" -> Source dossier: {dossier_path}\n")

    return candidates


def find_viral_clips(audio_filename, cleaned_title, lang_code="en", popularity_profile=None, source_record=None):
    candidates = score_viral_candidates(
        audio_filename,
        cleaned_title,
        lang_code,
        popularity_profile=popularity_profile,
        source_record=source_record,
    )
    existing_fingerprints = load_existing_theme_topic_fingerprints()
    clips = select_non_overlapping_clips(candidates, existing_fingerprints=existing_fingerprints)

    scoring_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_clip_scores.json",
    )

    with open(scoring_filepath, "w", encoding="utf-8") as f:
        json.dump({
            "scoring_model_version": SCORING_MODEL_VERSION,
            "candidate_window_policy": (
                candidates[0].rank_signals.get("candidate_window_policy")
                if candidates and isinstance(candidates[0].rank_signals, dict)
                else {}
            ),
            "candidate_cache_mode": "all_candidates"
            if CLIP_SCORE_CACHE_CANDIDATE_LIMIT <= 0
            else f"top_{CLIP_SCORE_CACHE_CANDIDATE_LIMIT}",
            "selected": [candidate_to_dict(clip) for clip in clips],
            "all_candidates": [
                candidate_to_dict(clip)
                for clip in ranked_candidate_window(candidates, CLIP_SCORE_CACHE_CANDIDATE_LIMIT)
            ],
            "top_candidates": [
                candidate_to_dict(clip)
                for clip in ranked_candidate_window(candidates, CLIP_REVIEW_REPORT_CANDIDATE_LIMIT)
            ],
        }, f, indent=4)

    review_json, review_csv = write_clip_review_exports(cleaned_title, clips, candidates)
    dossier_path = write_source_dossier(
        cleaned_title=cleaned_title,
        source_record=source_record or {},
        popularity_profile=popularity_profile or {},
        candidates=candidates,
        selected_clips=clips,
    )
    print(f" -> Selected {len(clips)} non-overlapping clips\n")
    print(f" -> Clip review JSON: {review_json}")
    print(f" -> Clip review CSV: {review_csv}\n")
    print(f" -> Source dossier: {dossier_path}\n")

    for index, clip in enumerate(clips, start=1):
        print(
            f"    Clip {index}: {clip.start_time:.1f}s-{clip.end_time:.1f}s "
            f"| score={clip.score:.3f} text={clip.text_score:.3f} "
            f"audio={clip.audio_score:.3f} opening={clip.opening_score:.3f} "
            f"comment={clip.comment_score:.3f} arc={clip.arc_score:.3f} "
            f"ready={clip.readiness_score:.3f} "
            f"boundary={clip.boundary_score:.3f} "
            f"diversity={clip.diversity_score:.3f}"
        )
        print(f"        Hook: {clip.hook_reason}")
        print(f"        Title: {clip.suggested_title}")

    if clips:
        print("")

    return clips


# =========================
# Process clips
# =========================

def render_selected_clips(video_filename, cleaned_title, source_record, source_state_key, clips, video_url=None, max_rendered=None):
    video_filename = os.path.abspath(video_filename) if video_filename else ""

    if video_filename:
        assert_file_exists(video_filename, "Video file")
    elif not video_url:
        raise RuntimeError("render_selected_clips requires either a video file or a video URL")
    elif not DOWNLOAD_VIDEO_SECTIONS:
        video_filename, _ = download_media(video_url, cleaned_title)
        video_filename = os.path.abspath(video_filename)
        assert_file_exists(video_filename, "Downloaded video")

    if not clips:
        print("No clips found for this video.\n")
        return 0

    for clip in clips:
        clip.source_state_key = source_state_key
        clip.source_video_url = source_record.get("video_url", "")
        clip.source_title = source_record.get("title", "")

    write_clip_review_exports(cleaned_title, clips, merge_existing_selected=True)

    model = None

    if ENABLE_PERSON_FALLBACK:
        print("Loading YOLO model for opt-in person fallback...")
        from ultralytics import YOLO

        model = YOLO("yolov9c.pt")
    else:
        print("YOLO person fallback disabled; framing will lock only to plausible faces.")

    face_cascades = load_face_cascades()
    allow_low_face_preflight = os.getenv("SHORTFORM_ALLOW_LOW_FACE_PREFLIGHT") == "1"
    clip_number = 1
    rendered_count = 0
    full_source_fallback_video = video_filename
    section_download_broken_for_source = False

    for clip in clips:
        if max_rendered is not None and rendered_count >= max_rendered:
            break

        if not runtime_budget.can_start_work(estimated_seconds=8 * 60, production=True):
            print(
                "Production time budget reached before starting another clip render; "
                "remaining ranked candidates are preserved for the next run.\n"
            )
            break

        source_duration = clip.end_time - clip.start_time

        if not (active_min_clip_duration() <= source_duration <= active_max_clip_duration()):
            continue

        input_video_filename = video_filename
        render_clip = clip
        downloaded_section_file = ""
        acquisition_notes = []

        if not input_video_filename and video_url and DOWNLOAD_VIDEO_SECTIONS:
            if section_download_broken_for_source and full_source_fallback_video:
                input_video_filename = full_source_fallback_video
                acquisition_notes.append("used full-source fallback after section download failed earlier")
            else:
                try:
                    downloaded_section_file, section_start = download_video_section(
                        video_url=video_url,
                        cleaned_title=cleaned_title,
                        clip_number=clip_number,
                        clip=clip,
                    )
                except Exception as section_err:
                    print(" -> Selected section download failed.")
                    print(f"    Section error: {section_err}")

                    if not ALLOW_FULL_SOURCE_FALLBACK:
                        clip.render_qc = {
                            "passed": False,
                            "flags": [
                                f"section download failed: {section_err}",
                                "full-source fallback disabled for production speed",
                            ],
                        }
                        print(
                            f" -> Skipping clip {clip_number}; full-source fallback is disabled. "
                            "Set SHORTFORM_ALLOW_FULL_SOURCE_FALLBACK=1 only for a targeted rerun.\n"
                        )
                        write_clip_review_exports(cleaned_title, clips, merge_existing_selected=True)
                        clip_number += 1
                        continue

                    section_download_broken_for_source = True
                    print(" -> Full-source fallback is enabled; downloading the source video.")

                    try:
                        if not full_source_fallback_video:
                            full_source_fallback_video, _ = download_media(video_url, cleaned_title)
                            full_source_fallback_video = os.path.abspath(full_source_fallback_video)

                        assert_file_exists(full_source_fallback_video, "Full source fallback video")
                        input_video_filename = full_source_fallback_video
                        acquisition_notes.append(
                            "section download failed; rendered from full-source fallback"
                        )
                    except Exception as fallback_err:
                        clip.render_qc = {
                            "passed": False,
                            "flags": [
                                f"section download failed: {section_err}",
                                f"full-source fallback failed: {fallback_err}",
                            ],
                        }
                        print(
                            f" -> Skipping clip {clip_number}; selected section and fallback both failed: "
                            f"{fallback_err}\n"
                        )
                        write_clip_review_exports(cleaned_title, clips, merge_existing_selected=True)
                        clip_number += 1
                        continue
                else:
                    input_video_filename = downloaded_section_file
                    render_clip = replace(
                        clip,
                        start_time=max(0.0, float(clip.start_time) - section_start),
                        end_time=max(0.1, float(clip.end_time) - section_start),
                    )
                    acquisition_notes.append("rendered from selected video section")

        if not input_video_filename:
            raise RuntimeError("No input video file available for selected clip rendering")

        if RENDER_PREROLL_SECONDS or RENDER_POSTROLL_SECONDS:
            padded_start = max(0.0, float(render_clip.start_time) - RENDER_PREROLL_SECONDS)
            padded_end = max(padded_start + 0.1, float(render_clip.end_time) + RENDER_POSTROLL_SECONDS)
            max_render_duration = active_max_clip_duration() + RENDER_EXTRA_DURATION_TOLERANCE

            if padded_end - padded_start > max_render_duration:
                padded_end = padded_start + max_render_duration

            if padded_start != render_clip.start_time or padded_end != render_clip.end_time:
                render_clip = replace(
                    render_clip,
                    start_time=padded_start,
                    end_time=padded_end,
                )
                acquisition_notes.append(
                    f"render window padded by {RENDER_PREROLL_SECONDS:.2f}s pre / {RENDER_POSTROLL_SECONDS:.2f}s post"
                )

        duration = render_clip.end_time - render_clip.start_time

        if not (active_min_clip_duration() <= duration <= active_max_clip_duration() + RENDER_EXTRA_DURATION_TOLERANCE):
            continue

        print(f"--- Processing Clip {clip_number} (Duration: {duration:.2f}s) ---")
        start_clip_total = time.time()

        temp_subclip = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}_sub.mp4",
        )

        # OpenCV writes more safely to AVI/MJPG first
        temp_tracked_avi = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}_tracked.avi",
        )

        final_filename = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}.mp4",
        )
        temporary_artifacts = [temp_subclip, temp_tracked_avi]

        if (
            not REGENERATE_EXISTING_CLIPS
            and is_valid_existing_clip(final_filename)
        ):
            existing_audit_path = os.path.join(
                get_frame_audit_dir(),
                f"{cleaned_title}_{clip_number}_existing_file_audit.jpg",
            )
            existing_qc = audit_existing_final_clip(
                final_filename,
                expected_duration=duration,
                face_cascades=face_cascades,
                audit_path=existing_audit_path,
            )
            clip.output_file = os.path.abspath(final_filename)
            clip.render_qc = existing_qc

            if existing_qc.get("passed"):
                print(f" -> Final clip already exists and passed current QC, skipping: {final_filename}\n")
                rendered_count += 1
                clip_number += 1
                continue

            print(
                " -> Existing final clip failed current QC; regenerating: "
                f"{final_filename} ({', '.join(existing_qc.get('rejection_reasons') or existing_qc.get('flags') or [])})"
            )
            clip.output_file = ""

            try:
                os.remove(final_filename)
            except OSError:
                pass
        elif not REGENERATE_EXISTING_CLIPS and os.path.exists(final_filename):
            print(f" -> Existing final clip is invalid; regenerating: {final_filename}")

        try:
            # STEP 1: Extract raw subclip using FFmpeg
            start_step1 = time.time()

            cut_command = [
                FFMPEG_EXE,
                "-y",
                "-ss", str(render_clip.start_time),
                "-i", input_video_filename,
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
            ]
            cut_command.extend(video_encoder_args(quality=18, software_preset="veryfast"))
            cut_command.extend([
                "-c:a", "aac",
                "-b:a", "192k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                temp_subclip,
            ])
            run_subprocess(cut_command, f"FFmpeg accurate cutting ({encoder_label()})")

            assert_file_exists(temp_subclip, "Temporary subclip")

            print(f" -> Step 1 (FFmpeg Cutting) took: {time.time() - start_step1:.2f} seconds")

            preflight_qc = preflight_clip_visual_qc(temp_subclip, face_cascades)

            if not preflight_qc.get("passed"):
                flags = preflight_qc.get("flags", [])
                print(f" -> Preflight visual QC warnings: {', '.join(flags)}")

                if preflight_allows_partial_face_render(preflight_qc):
                    print(" -> Continuing with face-lock render because partial speaker evidence exists.")
                elif preflight_allows_center_safe_render(preflight_qc):
                    print(" -> Continuing with center-safe render because the clip is visually active.")
                elif not allow_low_face_preflight:
                    clip.render_qc = {
                        "passed": False,
                        "rejected": True,
                        "flags": flags,
                        "rejection_reasons": flags,
                        "visual_quality_score": 0.0,
                        "attempt_quality_score": 0.0,
                        "render_strategy": "preflight_skip",
                        "preflight": preflight_qc,
                        "frame_path": preflight_qc,
                        "crop": {
                            "strategy": "preflight_skip",
                            "framing_score": 0.0,
                            "face_detection_rate": preflight_qc.get("face_presence_rate", 0.0),
                            "speaker_switches": 0,
                            "offcenter_reframes": 0,
                        },
                    }
                    print(" -> Skipping render because the clip does not have a reliable face target.")
                    continue

            # STEP 2/3: Render, audit, and optionally retry with safer framing.
            attempts = []
            audit_dir = get_frame_audit_dir()
            first_strategy = primary_framing_strategy(preflight_qc)
            face_audit_path = os.path.join(
                audit_dir,
                f"{cleaned_title}_{clip_number}_{first_strategy}.jpg",
            )

            first_attempt = render_crop_attempt(
                temp_subclip=temp_subclip,
                temp_tracked_avi=temp_tracked_avi,
                final_filename=final_filename,
                strategy=first_strategy,
                model=model,
                face_cascades=face_cascades,
                expected_duration=duration,
                audit_path=face_audit_path,
            )
            attempts.append(first_attempt)

            if should_try_alternate_framing(first_attempt["render_qc"]):
                first_qc = first_attempt["render_qc"]
                first_quality = float(first_qc.get("attempt_quality_score") or 0.0)
                fallback_accept_threshold = float(os.getenv("SHORTFORM_FALLBACK_ACCEPT_SCORE", "0.62"))
                first_has_output = bool(first_attempt.get("output_file") and os.path.exists(first_attempt["output_file"]))

                if (
                    first_has_output
                    and not render_rejection_reasons(first_qc)
                    and first_quality >= fallback_accept_threshold
                ):
                    print(
                        f" -> {first_strategy} framing has warnings but is usable "
                        f"(quality={first_quality:.2f}); accepting without extra fallbacks."
                    )
                else:
                    print(f" -> {first_strategy} framing looks risky; trying fallback crop strategies.")
                    fallback_strategies = fallback_framing_strategies()
                    first_flags = set(first_qc.get("flags", []))
                    timeout_recovery = "crop timeout" in first_flags

                    if timeout_recovery:
                        fallback_strategies = [
                            strategy
                            for strategy in ["stable_face_lock", "center_safe"]
                            if strategy in fallback_strategies and strategy != first_strategy
                        ]

                    for fallback_strategy in fallback_strategies:
                        if fallback_strategy == first_strategy:
                            continue

                        fallback_tracked_avi = os.path.join(
                            clips_path,
                            f"{cleaned_title}_{clip_number}_{fallback_strategy}.avi",
                        )
                        fallback_final_filename = os.path.join(
                            clips_path,
                            f"{cleaned_title}_{clip_number}_{fallback_strategy}.mp4",
                        )
                        temporary_artifacts.extend([fallback_tracked_avi, fallback_final_filename])
                        fallback_audit_path = os.path.join(
                            audit_dir,
                            f"{cleaned_title}_{clip_number}_{fallback_strategy}.jpg",
                        )
                        fallback_attempt = render_crop_attempt(
                            temp_subclip=temp_subclip,
                            temp_tracked_avi=fallback_tracked_avi,
                            final_filename=fallback_final_filename,
                            strategy=fallback_strategy,
                            model=model,
                            face_cascades=face_cascades,
                            expected_duration=duration,
                            audit_path=fallback_audit_path,
                        )
                        attempts.append(fallback_attempt)

                        fallback_qc = fallback_attempt["render_qc"]

                        fallback_quality = float(fallback_qc.get("attempt_quality_score") or 0.0)

                        if (
                            not render_rejection_reasons(fallback_qc)
                            and fallback_quality >= fallback_accept_threshold
                        ):
                            print(
                                " -> Fallback framing accepted early "
                                f"(strategy={fallback_strategy}, "
                                f"quality={fallback_qc.get('attempt_quality_score', 0.0):.2f})."
                            )
                            break

            valid_attempts = [
                attempt
                for attempt in attempts
                if attempt.get("output_file") and os.path.exists(attempt["output_file"])
            ]
            selected_attempt = max(
                valid_attempts or attempts,
                key=lambda item: render_attempt_selection_score(item["render_qc"]),
            )

            if not selected_attempt.get("output_file") or not os.path.exists(selected_attempt["output_file"]):
                clip.render_qc = selected_attempt["render_qc"]
                clip.render_qc["passed"] = False
                clip.render_qc["rejected"] = True
                clip.render_qc["rejection_reasons"] = ["all framing attempts failed"]
                clip.render_qc["all_framing_attempts"] = [
                    {
                        "strategy": attempt["strategy"],
                        "quality": attempt["render_qc"].get("attempt_quality_score", 0.0),
                        "selection_score": render_attempt_selection_score(attempt["render_qc"]),
                        "visual": attempt["render_qc"].get("visual_quality_score", 0.0),
                        "flags": attempt["render_qc"].get("flags", []),
                        "audit_file": attempt["render_qc"].get("frame_audit_file", ""),
                    }
                    for attempt in attempts
                ]
                print(" -> Rejecting render: all framing attempts failed")
                continue

            if selected_attempt["output_file"] != final_filename:
                if os.path.exists(final_filename):
                    os.remove(final_filename)
                os.replace(selected_attempt["output_file"], final_filename)

            for attempt in attempts:
                attempt_file = attempt["output_file"]
                if attempt_file != final_filename and os.path.exists(attempt_file):
                    os.remove(attempt_file)

            assert_file_exists(final_filename, "Final clip")
            clip.output_file = os.path.abspath(final_filename)
            clip.render_qc = selected_attempt["render_qc"]
            clip.render_qc["preflight"] = preflight_qc
            if acquisition_notes:
                clip.render_qc["media_acquisition"] = acquisition_notes[-1]
                clip.render_qc["flags"] = sorted(
                    set(clip.render_qc.get("flags", []) + acquisition_notes)
                )
            clip.render_qc["all_framing_attempts"] = [
                {
                    "strategy": attempt["strategy"],
                    "quality": attempt["render_qc"].get("attempt_quality_score", 0.0),
                    "selection_score": render_attempt_selection_score(attempt["render_qc"]),
                    "visual": attempt["render_qc"].get("visual_quality_score", 0.0),
                    "dead_frame_ratio": (
                        (attempt["render_qc"].get("frame_path") or {}).get("dead_frame_ratio", 0.0)
                    ),
                    "alive_frame_rate": (
                        (attempt["render_qc"].get("frame_path") or {}).get("alive_frame_rate", 0.0)
                    ),
                    "avg_face_plausibility": (
                        (attempt["render_qc"].get("frame_path") or {}).get("avg_face_plausibility", 0.0)
                    ),
                    "flags": attempt["render_qc"].get("flags", []),
                    "audit_file": attempt["render_qc"].get("frame_audit_file", ""),
                }
                for attempt in attempts
            ]
            rejection_reasons = render_rejection_reasons(clip.render_qc)

            if rejection_reasons:
                clip.render_qc["passed"] = False
                clip.render_qc["rejected"] = True
                clip.render_qc["rejection_reasons"] = rejection_reasons
                clip.render_qc["flags"] = sorted(set(clip.render_qc.get("flags", []) + rejection_reasons))

                try:
                    if os.path.exists(final_filename):
                        os.remove(final_filename)
                except OSError:
                    pass

                clip.output_file = ""
                print(f" -> Rejecting render: {', '.join(rejection_reasons)}")
                continue

            if clip.render_qc.get("documentary_non_face_ok"):
                clip.render_qc["passed"] = True
                clip.render_qc["rejected"] = False
                clip.render_qc["documentary_review_note"] = (
                    "Accepted for visually active non-speaker footage: "
                    "visual frames are alive even though face detection is unreliable."
                )

            rendered_count += 1

            if clip.render_qc.get("passed"):
                print(
                    " -> QC passed "
                    f"(strategy={clip.render_qc.get('render_strategy')}, "
                    f"quality={clip.render_qc.get('attempt_quality_score', 0.0):.2f}, "
                    f"framing={clip.render_qc['crop']['framing_score']:.2f}, "
                    f"face={clip.render_qc['crop']['face_detection_rate']:.2f})"
                )
            else:
                print(f" -> QC warnings: {', '.join(clip.render_qc.get('flags', []))}")

        except Exception as clip_err:
            clip.render_qc = {
                "passed": False,
                "flags": [f"processing failed: {clip_err}"],
            }
            print(f" -> Failed while processing clip {clip_number}: {clip_err}")

        finally:
            # Cleanup temporary processing files
            for temp_file in temporary_artifacts:
                try:
                    if temp_file != final_filename and os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass

            if downloaded_section_file and CLEANUP_VIDEO_SECTIONS:
                try:
                    if os.path.exists(downloaded_section_file):
                        os.remove(downloaded_section_file)
                except Exception:
                    pass

        print(f" -> Clip {clip_number} finished processing in: {time.time() - start_clip_total:.2f} seconds\n")
        write_clip_review_exports(cleaned_title, clips, merge_existing_selected=True)

        clip_number += 1

    return rendered_count


def process_clips(video_filename, audio_filename, cleaned_title, source_record, source_state_key, lang_code="en", video_url=None):
    audio_filename = os.path.abspath(audio_filename)
    assert_file_exists(audio_filename, "Audio file")
    popularity_profile = load_or_fetch_popularity_profile(video_url or source_record.get("video_url", ""), cleaned_title)

    print("Finding viral clips from audio + transcript scoring...")
    clips = find_viral_clips(
        audio_filename=audio_filename,
        cleaned_title=cleaned_title,
        lang_code=lang_code,
        popularity_profile=popularity_profile,
        source_record=source_record,
    )

    return render_selected_clips(
        video_filename=video_filename,
        video_url=video_url,
        cleaned_title=cleaned_title,
        source_record=source_record,
        source_state_key=source_state_key,
        clips=clips,
    )


# =========================
# Process one video
# =========================

def process_video(video_record):
    try:
        start_video_total = time.time()
        video_url = video_record["video_url"]
        video_record["_last_error_type"] = ""
        video_title = video_record.get("title") or ""

        if not is_supported_youtube_video_url(video_url):
            raise SkippableVideoError(f"unsupported non-video YouTube URL: {video_url}")

        if not video_title:
            info = run_ytdlp_then_retry_with_cookies(
                build_ytdl_opts(),
                lambda ydl: ydl.extract_info(video_url, download=False),
            )

            if info is None:
                print(f"Skipping unreadable/throttled video: {video_url}")
                return False

            video_title = info.get("title", "Unknown_Video")

        cleaned_title = clean_title_for_filename(video_title)

        audio_filename = download_audio_for_scoring(video_url, cleaned_title, source_record=video_record)
        assert_file_exists(audio_filename, "Extracted audio")

        rendered_count = process_clips(
            video_filename="",
            audio_filename=audio_filename,
            cleaned_title=cleaned_title,
            source_record=video_record,
            source_state_key=video_record["state_key"],
            lang_code="en",
            video_url=video_url,
        )

        video_record["_rendered_count"] = int(rendered_count)
        video_record["_last_cleaned_title"] = cleaned_title
        print(f"=== Total workflow duration for video: {time.time() - start_video_total:.2f} seconds ===\n")
        return bool(rendered_count)

    except Exception as e:
        video_record["_last_error_message"] = str(e).splitlines()[0][:500] if str(e) else e.__class__.__name__

        if (
            HALT_ON_RESTRICTED_DOWNLOAD_FAILURE
            and (
                isinstance(e, ytdlp_auth.RestrictedVideoAuthError)
                or is_restricted_auth_error_message(e)
            )
        ):
            video_record["_last_error_type"] = "blocked"
            print(f"Restricted YouTube auth failed for: {video_record.get('video_url')}\n{e}\n")
            if isinstance(e, ytdlp_auth.RestrictedVideoAuthError):
                raise

            raise ytdlp_auth.RestrictedVideoAuthError(
                f"restricted YouTube auth failed for {video_record.get('video_url')}: "
                f"{str(e).splitlines()[0][:300]}"
            ) from e

        if isinstance(e, (SkippableVideoError, ytdlp_auth.RestrictedVideoAuthError)) or is_skippable_video_error_message(e):
            video_record["_last_error_type"] = "blocked"
        elif is_network_download_error(e):
            video_record["_last_error_type"] = "network"
        else:
            video_record["_last_error_type"] = "processing"

        print(f"Failed to process video: {video_record.get('video_url')}\n{e}\n")
        return False


def theme_clip_records(pulled_data, executed_data):
    theme_records = [
        (state_key, record)
        for state_key, record in pulled_data.items()
        if (
            record.get("theme") == CURRENT_THEME
            and record.get("video_url")
            and not record.get("source_guard_disqualified")
            and is_supported_youtube_video_url(record.get("video_url"))
        )
    ]
    videos_to_process = [
        (state_key, record)
        for state_key, record in theme_records
        if (
            state_key not in executed_data
            and not record.get("clips_generated_at")
            and not record.get("stages", {}).get("clips_generated")
            and (
                RECONSIDER_UNSELECTED_SOURCES
                or not record.get("stages", {}).get("clips_ranked_not_selected")
            )
        )
    ]
    return theme_records, videos_to_process


def theme_records_for_global_ranking(theme_records, executed_data):
    unfinished_records = []

    for state_key, record in theme_records:
        stages = record.get("stages", {}) if isinstance(record.get("stages"), dict) else {}

        if state_key in executed_data:
            continue

        if (
            stages.get("subtitled")
            or stages.get("upload_ready")
            or stages.get("uploaded")
            or record.get("subtitle_status") == "complete"
            or record.get("upload_status") == "uploaded"
        ):
            continue

        unfinished_records.append((state_key, record))

    return unfinished_records


def source_view_count(record):
    raw = str((record or {}).get("views") or (record or {}).get("view_count") or "0")
    digits = re.sub(r"[^0-9]", "", raw)

    try:
        return int(digits or 0)
    except ValueError:
        return 0


def source_processing_priority(item):
    state_key, record = item
    title = str((record or {}).get("title") or "")
    cleaned_title = clean_title_for_filename(title) if title else ""
    has_score_cache = bool(cleaned_title and has_cached_clip_scores(cleaned_title))
    has_audio_cache = bool(cleaned_title and find_existing_audio_package(cleaned_title))
    stages = record.get("stages") if isinstance(record.get("stages"), dict) else {}
    tier_score = {
        "priority": 3,
        "secondary": 2,
        "legacy": 1,
    }.get(str(record.get("source_tier") or "").lower(), 0)
    duration = source_duration_from_record(record)
    duration_score = 1 if 10 * 60 <= duration <= 2.5 * 60 * 60 else 0
    return (
        1 if has_score_cache else 0,
        1 if stages.get("clips_scored") else 0,
        1 if has_audio_cache or stages.get("audio_prefetched") else 0,
        tier_score,
        duration_score,
        source_view_count(record),
        str(record.get("pulled_at") or ""),
        state_key,
    )


def prioritize_source_records(records):
    return sorted(records or [], key=source_processing_priority, reverse=True)


def resolve_record_title(video_record):
    video_url = video_record["video_url"]
    video_title = video_record.get("title") or ""

    if video_title:
        return video_title

    info = run_ytdlp_then_retry_with_cookies(
        build_ytdl_opts(),
        lambda ydl: ydl.extract_info(video_url, download=False),
    )

    if info is None:
        raise SkippableVideoError(f"unreadable/throttled video: {video_url}")

    video_title = info.get("title", "Unknown_Video")
    video_record["title"] = video_title
    return video_title


def prefetch_audio_for_record(video_record):
    video_url = video_record["video_url"]

    if not is_supported_youtube_video_url(video_url):
        raise SkippableVideoError(f"unsupported non-video YouTube URL: {video_url}")

    video_title = resolve_record_title(video_record)
    cleaned_title = clean_title_for_filename(video_title)
    disqualified, negative_hits = source_quality_disqualification(video_record)

    if disqualified:
        video_record["source_guard_disqualified"] = True
        video_record["source_quality_disqualified"] = True
        video_record["source_guard_negative_hits"] = negative_hits
        raise SkippableVideoError(
            "source quality disqualified before audio download: "
            + ", ".join(negative_hits)
        )

    audio_filename = download_audio_for_scoring(video_url, cleaned_title, source_record=video_record)
    assert_file_exists(audio_filename, "Extracted audio")
    video_record["_last_cleaned_title"] = cleaned_title
    return cleaned_title, audio_filename


def run_audio_prefetch(theme=None):
    if theme:
        return run_audio_prefetch_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_audio_prefetch_for_theme(requested_theme)

    for theme_name in discover_themes():
        run_audio_prefetch_for_theme(theme_name)


def run_audio_prefetch_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})
    executed_data = load_json_file(EXECUTED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    if not isinstance(executed_data, dict):
        executed_data = {}

    theme_records, videos_to_process = theme_clip_records(pulled_data, executed_data)
    videos_to_process = prioritize_source_records(videos_to_process)

    print(f"=== Prefetching audio for theme: {CURRENT_THEME} ===")
    print(f"Videos found: {len(theme_records)}")
    print(f"Videos needing scoring/rendering: {len(videos_to_process)}\n")

    prefetched = 0
    skipped = 0
    consecutive_network_failures = 0

    started_sources = 0

    for state_key, record in videos_to_process:
        video_title = str(record.get("title") or "")
        cleaned_title_hint = clean_title_for_filename(video_title) if video_title else ""
        has_audio_cache = bool(cleaned_title_hint and find_existing_audio_package(cleaned_title_hint))

        if not has_audio_cache and started_sources >= INITIAL_AUDIO_PREFETCH_SOURCES_PER_THEME:
            continue

        if not has_audio_cache and not runtime_budget.can_start_work(estimated_seconds=4 * 60, production=True):
            print(
                "Production time budget reached during audio prefetch; "
                "remaining sources stay pending for the next resumable run."
            )
            break

        record["state_key"] = state_key
        skip_reason = recent_blocked_skip_reason(record)

        if skip_reason:
            print(f"Skipping recently unavailable source: {record.get('video_url')} ({skip_reason})")
            continue

        record["_last_error_type"] = ""
        record["_last_error_message"] = ""

        try:
            if not has_audio_cache:
                started_sources += 1
            cleaned_title, audio_filename = prefetch_audio_for_record(record)
            prefetched += 1
            consecutive_network_failures = 0
            mark_stage(pulled_data[state_key], "audio_prefetched")
            pulled_data[state_key]["funnel_status"] = "audio_prefetched"
            pulled_data[state_key]["clip_prefix"] = cleaned_title
            pulled_data[state_key]["audio_filename"] = os.path.abspath(audio_filename)
            pulled_data[state_key].pop("last_clip_generation_error_type", None)
            pulled_data[state_key].pop("last_clip_generation_error_message", None)
            write_json_file(PULLED_FILE, pulled_data)
        except Exception as error:
            skipped += 1
            record["_last_error_message"] = str(error).splitlines()[0][:500] if str(error) else error.__class__.__name__

            if (
                HALT_ON_RESTRICTED_DOWNLOAD_FAILURE
                and (
                    isinstance(error, ytdlp_auth.RestrictedVideoAuthError)
                    or is_restricted_auth_error_message(error)
                )
            ):
                record["_last_error_type"] = "blocked"
                print(f"Restricted YouTube auth failed for: {record.get('video_url')}\n{error}\n")
                if isinstance(error, ytdlp_auth.RestrictedVideoAuthError):
                    raise

                raise ytdlp_auth.RestrictedVideoAuthError(
                    f"restricted YouTube auth failed for {record.get('video_url')}: "
                    f"{str(error).splitlines()[0][:300]}"
                ) from error

            if isinstance(error, (SkippableVideoError, ytdlp_auth.RestrictedVideoAuthError)) or is_skippable_video_error_message(error):
                record["_last_error_type"] = "blocked"
            elif is_network_download_error(error):
                record["_last_error_type"] = "network"
                consecutive_network_failures += 1
            else:
                record["_last_error_type"] = "processing"
                consecutive_network_failures = 0

            print(f"Failed to prefetch audio: {record.get('video_url')}\n{error}\n")
            update_failed_clip_generation_record(pulled_data, state_key, record)

            if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                print(
                    "Stopping audio prefetch after "
                    f"{consecutive_network_failures} consecutive network/download failures. "
                    "Check the internet/DNS connection and rerun; cached audio will be reused."
                )
                break

    print(
        f"Audio prefetch complete for {CURRENT_THEME}: "
        f"ready={prefetched}, skipped={skipped}, "
        f"elapsed={time.time() - run_start:.2f} seconds\n"
    )


def score_video_for_theme_ranking(video_record):
    try:
        start_video_total = time.time()
        video_url = video_record["video_url"]
        source_state_key = video_record["state_key"]
        video_record["_last_error_type"] = ""
        if not is_supported_youtube_video_url(video_url):
            raise SkippableVideoError(f"unsupported non-video YouTube URL: {video_url}")

        video_title = resolve_record_title(video_record)
        cleaned_title = clean_title_for_filename(video_title)
        disqualified, negative_hits = source_disqualified_by_theme(video_record, active_theme_name())
        if not disqualified:
            disqualified, negative_hits = source_quality_disqualification(video_record)
        if disqualified:
            return source_guard_empty_scored_source(
                cleaned_title=cleaned_title,
                video_record=video_record,
                video_url=video_url,
                source_state_key=source_state_key,
                negative_hits=negative_hits,
                cache_status="source_guard_disqualified_before_download",
            )

        cached_source = load_cached_scored_source(
            cleaned_title=cleaned_title,
            video_record=video_record,
            video_url=video_url,
            source_state_key=source_state_key,
        )
        if cached_source is not None:
            return cached_source

        audio_filename = download_audio_for_scoring(video_url, cleaned_title, source_record=video_record)

        assert_file_exists(audio_filename, "Extracted audio")
        popularity_profile = load_or_fetch_popularity_profile(video_url, cleaned_title)

        print("Scoring candidate clips for theme-wide ranking...")
        candidates = score_viral_candidates(
            audio_filename=os.path.abspath(audio_filename),
            cleaned_title=cleaned_title,
            lang_code="en",
            popularity_profile=popularity_profile,
            source_record=video_record,
        )

        top_candidates = ranked_candidate_window(candidates, active_theme_candidates_per_video())

        for clip in top_candidates:
            clip.source_state_key = source_state_key
            clip.source_video_url = video_record.get("video_url", "")
            clip.source_title = video_record.get("title", "")
            clip.rank_signals["source_state_key"] = source_state_key
            clip.rank_signals["source_title"] = video_record.get("title", "")

        video_record["_candidate_count"] = len(candidates)
        video_record["_theme_ranked_candidate_count"] = len(top_candidates)
        video_record["_last_cleaned_title"] = cleaned_title
        processing_metrics = video_record.setdefault("_processing_metrics", {})
        elapsed_video_seconds = time.time() - start_video_total
        processing_metrics["total_source_workflow_seconds"] = round(elapsed_video_seconds, 2)
        processing_metrics["theme_ranked_candidate_count"] = len(top_candidates)
        processing_metrics["selected_clips_per_hour_processed"] = round(
            len(top_candidates) / max(0.01, elapsed_video_seconds / 3600),
            4,
        )
        write_source_dossier(
            cleaned_title=cleaned_title,
            source_record=video_record,
            popularity_profile=popularity_profile or {},
            candidates=candidates,
            selected_clips=[],
        )
        print(
            f"=== Candidate scoring duration for video: {elapsed_video_seconds:.2f} seconds "
            f"({len(top_candidates)} kept for theme ranking) ===\n"
        )

        return {
            "state_key": source_state_key,
            "record": video_record,
            "video_filename": "",
            "video_url": video_url,
            "audio_filename": audio_filename,
            "cleaned_title": cleaned_title,
            "candidates": top_candidates,
        }

    except Exception as e:
        video_record["_last_error_message"] = str(e).splitlines()[0][:500] if str(e) else e.__class__.__name__

        if (
            HALT_ON_RESTRICTED_DOWNLOAD_FAILURE
            and (
                isinstance(e, ytdlp_auth.RestrictedVideoAuthError)
                or is_restricted_auth_error_message(e)
            )
        ):
            video_record["_last_error_type"] = "blocked"
            print(f"Restricted YouTube auth failed for: {video_record.get('video_url')}\n{e}\n")
            if isinstance(e, ytdlp_auth.RestrictedVideoAuthError):
                raise

            raise ytdlp_auth.RestrictedVideoAuthError(
                f"restricted YouTube auth failed for {video_record.get('video_url')}: "
                f"{str(e).splitlines()[0][:300]}"
            ) from e

        if isinstance(e, (SkippableVideoError, ytdlp_auth.RestrictedVideoAuthError)) or is_skippable_video_error_message(e):
            video_record["_last_error_type"] = "blocked"
        elif is_network_download_error(e):
            video_record["_last_error_type"] = "network"
        else:
            video_record["_last_error_type"] = "processing"

        print(f"Failed to score video: {video_record.get('video_url')}\n{e}\n")
        return None


def theme_candidate_overlaps(candidate, selected_clip):
    if candidate.source_state_key != selected_clip.source_state_key:
        return False

    return (
        candidate.start_time < selected_clip.end_time + MIN_CLIP_SPACING_SECONDS
        and candidate.end_time + MIN_CLIP_SPACING_SECONDS > selected_clip.start_time
    )


def candidate_title_fingerprint(candidate):
    text = " ".join([
        str(candidate.suggested_title or ""),
        " ".join(str(term) for term in candidate.topic_fingerprint or []),
    ])
    words = [
        word
        for word in words_from_text(text)
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]

    if not words:
        return ""

    return " ".join(words[:6])


def candidate_distinct_topic_terms(candidate):
    source_words = {
        word
        for word in words_from_text(getattr(candidate, "source_title", "") or "")
        if word not in TITLE_STOPWORDS and len(word) > 2
    }
    terms = []

    for term in candidate.topic_fingerprint or []:
        term_words = [
            word
            for word in words_from_text(str(term).replace("_", " "))
            if word not in TITLE_STOPWORDS and len(word) > 2
        ]

        if not term_words:
            continue

        if source_words and all(word in source_words for word in term_words):
            continue

        normalized = " ".join(term_words)

        if normalized not in terms:
            terms.append(normalized)

    return terms or list(candidate.topic_fingerprint or [])


def candidate_render_attempt_key(candidate):
    try:
        start_time = round(float(getattr(candidate, "start_time", 0.0) or 0.0), 2)
        end_time = round(float(getattr(candidate, "end_time", 0.0) or 0.0), 2)
    except (TypeError, ValueError):
        start_time = 0.0
        end_time = 0.0

    return (
        str(
            getattr(candidate, "source_state_key", "")
            or (getattr(candidate, "rank_signals", {}) or {}).get("source_state_key")
            or ""
        ),
        start_time,
        end_time,
    )


def load_attempted_render_candidate_keys(theme_name=None):
    if os.getenv("SHORTFORM_SKIP_RENDERED_CANDIDATES", "1") == "0":
        return set()

    if not metadata_path or not os.path.isdir(metadata_path):
        return set()

    attempted = set()

    for filename in os.listdir(metadata_path):
        if not filename.endswith("_clip_review.json"):
            continue

        path = os.path.join(metadata_path, filename)

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        for clip in payload.get("selected", []) or []:
            if not isinstance(clip, dict):
                continue

            has_render_attempt = bool(clip.get("output_file") or clip.get("render_qc"))

            if not has_render_attempt:
                continue

            key = clip_review_candidate_key(clip)

            if key[0]:
                attempted.add(key)

    return attempted


def select_theme_best_clips(candidates, max_clips=None, existing_fingerprints=None):
    selected = []
    selected_title_texts = set()
    selected_title_fingerprints = set()
    existing_fingerprints = existing_fingerprints or []
    min_selected_score = active_publishable_min_selected_score()
    max_topic_similarity = active_max_topic_similarity()

    for candidate in sorted(candidates, key=candidate_ranking_key, reverse=True):
        if candidate.score < min_selected_score:
            continue

        if not candidate_selection_ready(candidate):
            continue

        if any(theme_candidate_overlaps(candidate, selected_clip) for selected_clip in selected):
            continue

        if not candidate_pre_render_copy_ready(candidate):
            continue

        title_fingerprint = candidate_title_fingerprint(candidate)
        title_text_key = re.sub(r"\s+", " ", str(candidate.suggested_title or "").strip().lower())

        if title_text_key and title_text_key in selected_title_texts:
            continue

        if title_fingerprint and title_fingerprint in selected_title_fingerprints:
            continue

        max_topic_overlap = max(
            (
                topic_similarity(
                    candidate_distinct_topic_terms(candidate),
                    candidate_distinct_topic_terms(selected_clip),
                )
                for selected_clip in selected
            ),
            default=0.0,
        )
        max_existing_overlap = max(
            (
                topic_similarity(candidate.topic_fingerprint, fingerprint)
                for fingerprint in existing_fingerprints
            ),
            default=0.0,
        )
        max_total_overlap = max(max_topic_overlap, max_existing_overlap)
        candidate.diversity_score = float(1.0 - max_total_overlap)

        if max_total_overlap > max_topic_similarity:
            continue

        selected.append(candidate)
        if title_text_key:
            selected_title_texts.add(title_text_key)
        if title_fingerprint:
            selected_title_fingerprints.add(title_fingerprint)

        if max_clips is not None and len(selected) >= max_clips:
            break

    return selected


def candidate_title_is_publishable(candidate):
    title_quality = score_title_quality(
        active_theme_name(),
        candidate.suggested_title,
        topic_terms=candidate.topic_fingerprint,
    )

    return (
        title_passes_publishable_bar(
            active_theme_name(),
            candidate.suggested_title,
            topic_terms=candidate.topic_fingerprint,
            min_specificity=0.38,
        )
        and not title_quality.get("source_only_title")
        and title_quality.get("honesty", 0.0) >= 0.70
        and title_supported_by_clip(
            candidate.suggested_title,
            candidate.transcript_excerpt,
            candidate.source_title,
            candidate.topic_fingerprint,
        )
    )


def build_theme_render_pool(selected_clips, all_candidates, max_clips=None):
    if max_clips is None:
        available_count = len(all_candidates or selected_clips or [])
        pool_limit = min(available_count, daily_render_pool_attempt_limit())
    else:
        pool_limit = max(
            max_clips,
            min(
                48,
                max_clips * int(os.getenv("SHORTFORM_RENDER_POOL_MULTIPLIER", "4")),
            ),
        )

    if pool_limit <= 0:
        return []

    min_score = active_publishable_min_selected_score() * 0.92
    pool = []
    seen = set()
    seen_title_texts = set()

    for candidate in list(selected_clips or []) + sorted(all_candidates or [], key=candidate_ranking_key, reverse=True):
        key = (
            candidate.source_state_key or (candidate.rank_signals or {}).get("source_state_key") or "",
            round(float(candidate.start_time), 1),
            round(float(candidate.end_time), 1),
        )

        if key in seen:
            continue

        if candidate.score < min_score:
            continue

        if not candidate_selection_ready(candidate):
            continue

        if not candidate_pre_render_copy_ready(candidate):
            continue

        title_text_key = re.sub(r"\s+", " ", str(candidate.suggested_title or "").strip().lower())

        if title_text_key and title_text_key in seen_title_texts:
            continue

        if any(theme_candidate_overlaps(candidate, existing) for existing in pool):
            continue

        seen.add(key)
        if title_text_key:
            seen_title_texts.add(title_text_key)
        pool.append(candidate)

        if len(pool) >= pool_limit:
            break

    return pool


def print_theme_rankings(selected_clips):
    if not selected_clips:
        print("No clips survived theme-wide ranking.\n")
        return

    print(f"=== Theme-wide publishable clips selected: {len(selected_clips)} ===")

    for index, clip in enumerate(selected_clips, start=1):
        title = clip.source_title or clip.source_video_url
        print(
            f"{index:02d}. score={clip.score:.3f} "
            f"text={clip.text_score:.3f} opening={clip.opening_score:.3f} "
            f"comment={clip.comment_score:.3f} arc={clip.arc_score:.3f} "
            f"ready={clip.readiness_score:.3f} "
            f"popular={clip.popularity_score:.3f} "
            f"diversity={clip.diversity_score:.3f} "
            f"| {clip.start_time:.1f}s-{clip.end_time:.1f}s | {title}"
        )
        print(f"    Hook: {clip.hook_reason}")
        print(f"    Title: {clip.suggested_title}")

    print("")


def theme_editorial_success_rate(theme_name=None):
    theme_key = str(active_theme_name(theme_name) or "").strip().lower().replace("-", "_")

    if theme_key in THEME_EDITORIAL_SUCCESS_RATE_OVERRIDES:
        return max(0.05, min(1.0, THEME_EDITORIAL_SUCCESS_RATE_OVERRIDES[theme_key]))

    return 0.0


def daily_render_target(theme_name=None):
    if DAILY_RENDER_ACCEPTED_TARGET_GLOBAL_OVERRIDE:
        return max(0, DAILY_RENDER_ACCEPTED_TARGET)

    theme_key = str(active_theme_name(theme_name) or "").strip().lower().replace("-", "_")

    if theme_key in THEME_RENDER_ACCEPTED_TARGET_OVERRIDES:
        return max(0, min(MAX_THEME_RENDER_ACCEPTED_TARGET, THEME_RENDER_ACCEPTED_TARGET_OVERRIDES[theme_key]))

    return max(0, min(MAX_THEME_RENDER_ACCEPTED_TARGET, DAILY_RENDER_ACCEPTED_TARGET))


def daily_render_pool_attempt_limit(theme_name=None, selected_count=None):
    explicit_limit = os.getenv("SHORTFORM_RENDER_POOL_ATTEMPT_LIMIT", "").strip()

    if explicit_limit:
        try:
            limit = int(explicit_limit)
        except ValueError:
            limit = 0

        if limit > 0:
            return min(limit, selected_count) if selected_count is not None else limit

    target = daily_render_target(theme_name)

    if target <= 0:
        return selected_count if selected_count is not None else 0

    limit = max(DAILY_RENDER_POOL_MIN_ATTEMPTS, target * DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER)

    if selected_count is not None:
        return min(max(0, int(selected_count)), limit)

    return limit


def render_pool_metadata(theme_name, selected_count, render_pool_count):
    target = daily_render_target(theme_name)
    return {
        "upload_ready_target": DAILY_UPLOAD_READY_TARGET,
        "reserve_target": DAILY_RESERVE_TARGET,
        "final_package_target": DAILY_FINAL_PACKAGE_TARGET,
        "accepted_render_target": target,
        "estimated_editorial_success_rate": round(theme_editorial_success_rate(theme_name), 4),
        "accepted_render_buffer_multiplier": DAILY_RENDER_ACCEPTED_BUFFER_MULTIPLIER,
        "attempt_pool_limit": daily_render_pool_attempt_limit(theme_name, selected_count=selected_count),
        "attempt_multiplier": DAILY_RENDER_POOL_ATTEMPT_MULTIPLIER,
        "attempt_minimum": DAILY_RENDER_POOL_MIN_ATTEMPTS,
        "selected_available": selected_count,
        "render_pool_count": render_pool_count,
        "policy": "initial_batch_then_editorial_topup_until_package_target",
    }


def theme_selection_report_path(theme_name=None):
    theme_name = theme_name or CURRENT_THEME
    return os.path.join(metadata_path, f"{theme_name}_theme_selection.json")


def write_theme_selection_report(theme_name, selected_clips, all_candidates):
    report_path = theme_selection_report_path(theme_name)
    clip_limit = active_theme_clip_limit(theme_name)
    source_candidate_cap = active_theme_candidates_per_video(theme_name)
    render_pool = build_theme_render_pool(selected_clips, all_candidates, max_clips=clip_limit)
    payload = {
        "theme": theme_name,
        "scoring_model_version": SCORING_MODEL_VERSION,
        "selection_mode": "quality_threshold" if clip_limit is None else "budget_limited",
        "clip_limit": clip_limit,
        "publishable_min_selected_score": active_publishable_min_selected_score(theme_name),
        "publishable_min_readiness_score": (
            max(active_min_readiness_score(theme_name), UNLIMITED_BACKLOG_MIN_READINESS_SCORE)
            if clip_limit is None
            else active_min_readiness_score(theme_name)
        ),
        "publishable_min_text_score": (
            UNLIMITED_BACKLOG_MIN_TEXT_SCORE
            if clip_limit is None
            else None
        ),
        "source_candidate_cap": source_candidate_cap,
        "source_candidate_policy": "unlimited" if source_candidate_cap is None else f"top_{source_candidate_cap}_per_source",
        "review_report_candidate_limit": CLIP_REVIEW_REPORT_CANDIDATE_LIMIT or "unlimited",
        "legacy_clip_budget": active_theme_clip_budget(theme_name),
        "clip_rules": active_clip_rules(theme_name),
        "candidate_count": len(all_candidates),
        "selected_count": len(selected_clips),
        "render_pool_count": len(render_pool),
        "render_quota": render_pool_metadata(theme_name, len(selected_clips), len(render_pool)),
        "readiness_distribution": build_readiness_distribution(all_candidates),
        "selected": [candidate_to_dict(clip) for clip in selected_clips],
        "render_pool": [candidate_to_dict(clip) for clip in render_pool],
        "top_candidates": [
            candidate_to_dict(clip)
            for clip in sorted(all_candidates, key=candidate_ranking_key, reverse=True)[:75]
        ],
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f"Theme selection report: {report_path}\n")
    return report_path


def load_theme_selection_report(theme_name=None):
    report_path = theme_selection_report_path(theme_name)

    if not os.path.exists(report_path):
        raise FileNotFoundError(
            f"Theme selection report missing: {report_path}. "
            "Run the score stage before video-section acquisition or rendering."
        )

    with open(report_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise RuntimeError(f"Theme selection report is invalid: {report_path}")

    return payload


def selected_clips_by_source_from_report(report, pulled_data):
    groups = {}
    parsed_clips = []
    attempted_keys = load_attempted_render_candidate_keys(CURRENT_THEME)

    for item in report.get("render_pool") or report.get("selected") or []:
        try:
            clip = candidate_from_cached_dict(item)
        except TypeError:
            continue

        source_state_key = (
            clip.source_state_key
            or (clip.rank_signals or {}).get("source_state_key")
            or item.get("source_state_key")
            or ""
        )

        if not source_state_key:
            continue

        record = pulled_data.get(source_state_key, {})
        clip.source_state_key = source_state_key
        clip.source_video_url = clip.source_video_url or record.get("video_url", "")
        clip.source_title = clip.source_title or record.get("title", "")
        clip.rank_signals["source_state_key"] = clip.source_state_key
        clip.rank_signals["source_title"] = clip.source_title
        clip = refresh_cached_candidate_copy(clip, record)

        if candidate_render_attempt_key(clip) in attempted_keys:
            continue

        parsed_clips.append((clip, record))

    if os.getenv("SHORTFORM_RENDER_ALL_SELECTED", "0") != "1":
        pool_limit = daily_render_pool_attempt_limit(CURRENT_THEME, selected_count=len(parsed_clips))
        parsed_clips = sorted(parsed_clips, key=lambda item: candidate_ranking_key(item[0]), reverse=True)[:pool_limit]
    else:
        parsed_clips = sorted(parsed_clips, key=lambda item: candidate_ranking_key(item[0]), reverse=True)

    for clip, record in parsed_clips:
        source_state_key = clip.source_state_key
        groups.setdefault(source_state_key, {
            "record": record,
            "clips": [],
        })["clips"].append(clip)

    for group in groups.values():
        group["clips"] = sorted(group["clips"], key=candidate_ranking_key, reverse=True)

    return groups


def cleaned_title_for_source_record(record, clips=None):
    clips = clips or []
    title = record.get("title") or ""

    if not title and clips:
        title = clips[0].source_title or ""

    if not title and record.get("video_url"):
        title = resolve_record_title(record)

    return record.get("clip_prefix") or clean_title_for_filename(title or "Unknown_Video")


def update_failed_clip_generation_record(pulled_data, state_key, record):
    pulled_data[state_key]["last_clip_generation_attempt_at"] = utc_timestamp()
    pulled_data[state_key]["last_clip_generation_error_type"] = record.get("_last_error_type", "processing")
    if record.get("_last_error_message"):
        pulled_data[state_key]["last_clip_generation_error_message"] = str(record.get("_last_error_message"))[:500]
    write_json_file(PULLED_FILE, pulled_data)


def run_theme_global_ranked_scoring(records_for_ranking, pulled_data):
    clip_limit = active_theme_clip_limit()
    selection_description = (
        "every publishable clip that meets the quality threshold"
        if clip_limit is None
        else f"only the top {clip_limit} clips"
    )
    print(
        "Theme-wide ranking enabled: "
        f"scoring every source, then selecting {selection_description}.\n"
    )

    scored_sources = []
    consecutive_network_failures = 0
    uncached_score_attempts = 0

    records_for_ranking = prioritize_source_records(records_for_ranking)
    publishable_candidate_count = 0

    for state_key, record in records_for_ranking:
        record["state_key"] = state_key
        skip_reason = recent_blocked_skip_reason(record)

        if skip_reason:
            print(f"Skipping recently unavailable source: {record.get('video_url')} ({skip_reason})")
            continue

        video_title = record.get("title") or ""
        cleaned_title = clean_title_for_filename(video_title) if video_title else ""
        has_score_cache = bool(cleaned_title and has_cached_clip_scores(cleaned_title))

        if (
            MAX_UNSCORED_SOURCES_PER_THEME >= 0
            and not has_score_cache
            and uncached_score_attempts >= MAX_UNSCORED_SOURCES_PER_THEME
        ):
            print(
                "Skipping unscored source due to resume scoring cap "
                f"(SHORTFORM_MAX_UNSCORED_SOURCES_PER_THEME={MAX_UNSCORED_SOURCES_PER_THEME}): "
                f"{record.get('video_url')}"
            )
            continue

        if not has_score_cache:
            if not runtime_budget.can_start_work(estimated_seconds=12 * 60, production=True):
                print(
                    "Production time budget reached during source scoring; "
                    "unscored sources remain pending for the next run."
                )
                break
            uncached_score_attempts += 1

        scored_source = score_video_for_theme_ranking(record)

        if scored_source is None:
            if record.get("_last_error_type") == "network":
                consecutive_network_failures += 1
            else:
                consecutive_network_failures = 0

            update_failed_clip_generation_record(pulled_data, state_key, record)

            if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                print(
                    "Stopping this theme after "
                    f"{consecutive_network_failures} consecutive network/download failures. "
                    "Check the internet/DNS connection and rerun; completed videos will be skipped."
                )
                break

            continue

        consecutive_network_failures = 0
        scored_sources.append(scored_source)
        publishable_candidate_count += sum(
            1
            for candidate in scored_source.get("candidates") or []
            if candidate_selection_ready(candidate)
        )
        mark_stage(pulled_data[state_key], "clips_scored")
        pulled_data[state_key]["funnel_status"] = "clips_scored"
        pulled_data[state_key]["clip_prefix"] = record.get("_last_cleaned_title", "")
        pulled_data[state_key]["candidate_count"] = int(record.get("_candidate_count") or 0)
        pulled_data[state_key]["theme_ranked_candidate_count"] = int(record.get("_theme_ranked_candidate_count") or 0)
        pulled_data[state_key].pop("last_clip_generation_error_type", None)
        pulled_data[state_key].pop("last_clip_generation_error_message", None)
        write_json_file(PULLED_FILE, pulled_data)

        if (
            uncached_score_attempts >= MIN_SCORED_SOURCES_PER_THEME
            and publishable_candidate_count >= TARGET_PUBLISHABLE_CANDIDATES_PER_THEME
        ):
            print(
                "Adaptive scoring target reached: "
                f"{publishable_candidate_count} publishable candidates from "
                f"{uncached_score_attempts} newly scored source(s). "
                "Remaining source records stay available for a later run.\n"
            )
            break

    all_candidates = [
        candidate
        for scored_source in scored_sources
        for candidate in scored_source["candidates"]
    ]
    existing_fingerprints = load_existing_theme_topic_fingerprints()
    selected_clips = select_theme_best_clips(
        all_candidates,
        max_clips=active_theme_clip_limit(),
        existing_fingerprints=existing_fingerprints,
    )
    selected_by_source = {}

    for clip in selected_clips:
        selected_by_source.setdefault(clip.source_state_key, []).append(clip)

    print_theme_rankings(selected_clips)
    write_theme_selection_report(CURRENT_THEME, selected_clips, all_candidates)

    for scored_source in scored_sources:
        state_key = scored_source["state_key"]
        record = scored_source["record"]
        selected_for_source = sorted(
            selected_by_source.get(state_key, []),
            key=lambda item: item.start_time,
        )

        if not selected_for_source:
            mark_stage(pulled_data[state_key], "clips_ranked_not_selected")
            pulled_data[state_key]["funnel_status"] = "clips_ranked_not_selected"
            pulled_data[state_key]["clips_generated_count"] = 0
            pulled_data[state_key].pop("last_clip_generation_error_message", None)
            write_json_file(PULLED_FILE, pulled_data)
            continue

        mark_stage(pulled_data[state_key], "clips_selected")
        pulled_data[state_key]["funnel_status"] = "clips_selected"
        pulled_data[state_key]["selected_clips_count"] = len(selected_for_source)
        pulled_data[state_key].pop("last_clip_generation_error_type", None)
        pulled_data[state_key].pop("last_clip_generation_error_message", None)
        write_json_file(PULLED_FILE, pulled_data)

    return {
        "scored_sources": scored_sources,
        "selected_clips": selected_clips,
        "all_candidates": all_candidates,
    }


def prefetch_selected_video_sections_for_source(cleaned_title, source_record, source_state_key, clips, max_sections=None):
    if not clips:
        return 0

    if not DOWNLOAD_VIDEO_SECTIONS:
        print("Selected video section downloads disabled; render stage will use full-source fallback if configured.")
        return 0

    video_url = source_record.get("video_url") or clips[0].source_video_url

    if not video_url:
        raise RuntimeError(f"missing video URL for selected source {source_state_key}")

    fetched_count = 0

    for clip_number, clip in enumerate(clips, start=1):
        if max_sections is not None and fetched_count >= max_sections:
            break

        if not runtime_budget.can_start_work(estimated_seconds=2 * 60, production=True):
            print("Production time budget reached during selected-section prefetch.")
            break

        source_duration = clip.end_time - clip.start_time

        if not (active_min_clip_duration() <= source_duration <= active_max_clip_duration()):
            continue

        section_file, _section_start = download_video_section(
            video_url=video_url,
            cleaned_title=cleaned_title,
            clip_number=clip_number,
            clip=clip,
        )
        assert_file_exists(section_file, "Selected video section")
        fetched_count += 1

    return fetched_count


def run_selected_video_prefetch(theme=None):
    if theme:
        return run_selected_video_prefetch_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_selected_video_prefetch_for_theme(requested_theme)

    for theme_name in discover_themes():
        run_selected_video_prefetch_for_theme(theme_name)


def run_selected_video_prefetch_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    report = load_theme_selection_report(CURRENT_THEME)
    groups = selected_clips_by_source_from_report(report, pulled_data)
    print(f"=== Prefetching selected video sections for theme: {CURRENT_THEME} ===")
    print(f"Selected sources: {len(groups)}")
    print(f"Selected clips: {sum(len(group['clips']) for group in groups.values())}\n")

    fetched_total = 0
    failed_total = 0
    prefetch_target = max(
        MIN_FINISHED_TARGET,
        daily_render_target(CURRENT_THEME) + int(os.getenv("SHORTFORM_VIDEO_PREFETCH_BUFFER", "4")),
    )

    for source_state_key, group in groups.items():
        if fetched_total >= prefetch_target:
            print(
                f"Selected-section prefetch target reached ({fetched_total}/{prefetch_target}); "
                "additional ranked sections will download on demand only if a render top-up needs them."
            )
            break

        record = pulled_data.get(source_state_key) or group["record"]
        pulled_data.setdefault(source_state_key, record)
        record["state_key"] = source_state_key
        record["_last_error_type"] = ""
        clips = group["clips"]

        try:
            cleaned_title = cleaned_title_for_source_record(record, clips)
            fetched_count = prefetch_selected_video_sections_for_source(
                cleaned_title=cleaned_title,
                source_record=record,
                source_state_key=source_state_key,
                clips=clips,
                max_sections=max(0, prefetch_target - fetched_total),
            )
            fetched_total += fetched_count
            mark_stage(pulled_data[source_state_key], "video_sections_prefetched")
            pulled_data[source_state_key]["funnel_status"] = "video_sections_prefetched"
            pulled_data[source_state_key]["selected_video_sections_count"] = fetched_count
            pulled_data[source_state_key]["clip_prefix"] = cleaned_title
            pulled_data[source_state_key].pop("last_clip_generation_error_type", None)
            write_json_file(PULLED_FILE, pulled_data)
        except Exception as error:
            failed_total += 1

            if (
                HALT_ON_RESTRICTED_DOWNLOAD_FAILURE
                and (
                    isinstance(error, ytdlp_auth.RestrictedVideoAuthError)
                    or is_restricted_auth_error_message(error)
                )
            ):
                record["_last_error_type"] = "blocked"
                print(f"Restricted YouTube auth failed for: {record.get('video_url')}\n{error}\n")
                if isinstance(error, ytdlp_auth.RestrictedVideoAuthError):
                    raise

                raise ytdlp_auth.RestrictedVideoAuthError(
                    f"restricted YouTube auth failed for {record.get('video_url')}: "
                    f"{str(error).splitlines()[0][:300]}"
                ) from error

            if isinstance(error, (SkippableVideoError, ytdlp_auth.RestrictedVideoAuthError)) or is_skippable_video_error_message(error):
                record["_last_error_type"] = "blocked"
            elif is_network_download_error(error):
                record["_last_error_type"] = "network"
            else:
                record["_last_error_type"] = "processing"

            print(f"Failed to prefetch selected video sections: {record.get('video_url')}\n{error}\n")
            update_failed_clip_generation_record(pulled_data, source_state_key, record)

    print(
        f"Selected video section prefetch complete for {CURRENT_THEME}: "
        f"sections={fetched_total}, failed_sources={failed_total}, "
        f"elapsed={time.time() - run_start:.2f} seconds\n"
    )


def run_selected_clip_render(theme=None):
    if theme:
        return run_selected_clip_render_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_selected_clip_render_for_theme(requested_theme)

    total = 0

    for theme_name in discover_themes():
        total += int(run_selected_clip_render_for_theme(theme_name) or 0)

    return total


def run_selected_clip_render_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    report = load_theme_selection_report(CURRENT_THEME)
    groups = selected_clips_by_source_from_report(report, pulled_data)
    print(f"=== Rendering selected clips for theme: {CURRENT_THEME} ===")
    print(f"Selected sources: {len(groups)}")
    selected_clip_total = sum(len(group["clips"]) for group in groups.values())
    print(f"Selected clips: {selected_clip_total}\n")

    rendered_total = 0
    failed_sources = 0
    render_target_override = os.getenv("SHORTFORM_RENDER_TARGET_PER_THEME", "").strip()
    render_target = (
        max(0, int(render_target_override))
        if render_target_override
        else min(max(0, selected_clip_total), daily_render_target(CURRENT_THEME))
    )

    if not render_target:
        print(f"No selected clips to render for theme: {CURRENT_THEME}\n")
        return 0

    print(
        "Render quota: "
        f"target accepted clips={render_target} "
        f"(upload target={DAILY_UPLOAD_READY_TARGET}, reserve target={DAILY_RESERVE_TARGET}, "
        f"attempt pool={selected_clip_total})"
    )

    for source_state_key, group in groups.items():
        if rendered_total >= render_target:
            break

        record = pulled_data.get(source_state_key) or group["record"]
        pulled_data.setdefault(source_state_key, record)
        record["state_key"] = source_state_key
        record["_last_error_type"] = ""
        clips = group["clips"]
        cleaned_title = cleaned_title_for_source_record(record, clips)

        try:
            rendered_count = render_selected_clips(
                video_filename="",
                video_url=record.get("video_url") or (clips[0].source_video_url if clips else ""),
                cleaned_title=cleaned_title,
                source_record=record,
                source_state_key=source_state_key,
                clips=clips,
                max_rendered=max(0, render_target - rendered_total),
            )
            record["_rendered_count"] = int(rendered_count)
            rendered_total += int(rendered_count)

            if rendered_count:
                mark_stage(pulled_data[source_state_key], "clips_generated")
                pulled_data[source_state_key]["funnel_status"] = "clips_generated"
                pulled_data[source_state_key]["clips_generated_count"] = int(rendered_count)
                pulled_data[source_state_key]["clip_prefix"] = cleaned_title
                pulled_data[source_state_key].pop("last_clip_generation_error_type", None)
            else:
                pulled_data[source_state_key]["last_clip_generation_attempt_at"] = utc_timestamp()
                pulled_data[source_state_key]["last_clip_generation_error_type"] = "rendering"

            write_json_file(PULLED_FILE, pulled_data)
        except Exception as error:
            failed_sources += 1
            record["_last_error_type"] = "rendering"
            print(f"Failed to render selected clips: {record.get('video_url')}\n{error}\n")
            update_failed_clip_generation_record(pulled_data, source_state_key, record)

    print(
        f"Selected clip render complete for {CURRENT_THEME}: "
        f"rendered={rendered_total}, failed_sources={failed_sources}, "
        f"elapsed={time.time() - run_start:.2f} seconds\n"
    )
    return rendered_total


def run_theme_global_ranked_generation(records_for_ranking, pulled_data):
    run_theme_global_ranked_scoring(records_for_ranking, pulled_data)
    run_selected_video_prefetch_for_theme(CURRENT_THEME)
    run_selected_clip_render_for_theme(CURRENT_THEME)


def run_clip_scoring(theme=None):
    if theme:
        return run_clip_scoring_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_clip_scoring_for_theme(requested_theme)

    for theme_name in discover_themes():
        run_clip_scoring_for_theme(theme_name)


def run_clip_scoring_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})
    executed_data = load_json_file(EXECUTED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    if not isinstance(executed_data, dict):
        executed_data = {}

    theme_records, videos_to_process = theme_clip_records(pulled_data, executed_data)
    records_for_ranking = theme_records_for_global_ranking(theme_records, executed_data)

    print(f"=== Scoring clips for theme: {CURRENT_THEME} ===")
    print(f"Videos found: {len(theme_records)}")
    print(f"Unfinished videos available for ranking: {len(records_for_ranking)}")
    print(f"Videos left to score: {len(videos_to_process)}\n")

    if not ENABLE_THEME_GLOBAL_RANKING:
        raise RuntimeError("The separate score/video/render stages require SHORTFORM_ENABLE_THEME_GLOBAL_RANKING=1.")

    run_theme_global_ranked_scoring(records_for_ranking, pulled_data)
    print(f"Updated pulled registry: {PULLED_FILE}")
    print(f"Theme '{CURRENT_THEME}' scoring finished. Total run time: {time.time() - run_start:.2f} seconds\n")


# =========================
# Main batch runner
# =========================

def run_clip_generation(theme=None):
    if theme:
        return run_clip_generation_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_clip_generation_for_theme(requested_theme)

    for theme_name in discover_themes():
        run_clip_generation_for_theme(theme_name)


def run_clip_generation_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})
    executed_data = load_json_file(EXECUTED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    if not isinstance(executed_data, dict):
        executed_data = {}

    theme_records, videos_to_process = theme_clip_records(pulled_data, executed_data)
    records_for_ranking = theme_records_for_global_ranking(theme_records, executed_data)

    print(f"=== Generating clips for theme: {CURRENT_THEME} ===")
    print(f"Videos found: {len(theme_records)}")
    print(f"Already completed: {sum(1 for key in executed_data if key.startswith(CURRENT_THEME + '|'))}")
    print(
        "Clips already generated: "
        f"{sum(1 for _, record in theme_records if record.get('clips_generated_at') or record.get('stages', {}).get('clips_generated'))}"
    )
    print(f"Videos left to process: {len(videos_to_process)}\n")

    if ENABLE_THEME_GLOBAL_RANKING:
        run_theme_global_ranked_generation(records_for_ranking, pulled_data)
        print(f"Updated pulled registry: {PULLED_FILE}")
        print(f"Theme '{CURRENT_THEME}' finished. Total run time: {time.time() - run_start:.2f} seconds\n")
        return

    consecutive_network_failures = 0

    for state_key, record in videos_to_process:
        record["state_key"] = state_key
        processed = process_video(record)

        if processed:
            consecutive_network_failures = 0
            mark_stage(pulled_data[state_key], "clips_generated")
            pulled_data[state_key]["funnel_status"] = "clips_generated"
            pulled_data[state_key]["clips_generated_count"] = int(record.get("_rendered_count") or 0)
            pulled_data[state_key]["clip_prefix"] = record.get("_last_cleaned_title", "")
            pulled_data[state_key].pop("last_clip_generation_error_type", None)
            write_json_file(PULLED_FILE, pulled_data)
        else:
            if record.get("_last_error_type") == "network":
                consecutive_network_failures += 1
            else:
                consecutive_network_failures = 0

            update_failed_clip_generation_record(pulled_data, state_key, record)

            if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                print(
                    "Stopping this theme after "
                    f"{consecutive_network_failures} consecutive network/download failures. "
                    "Check the internet/DNS connection and rerun; completed videos will be skipped."
                )
                break

    print(f"Updated pulled registry: {PULLED_FILE}")
    print(f"Theme '{CURRENT_THEME}' finished. Total run time: {time.time() - run_start:.2f} seconds\n")


if __name__ == "__main__":
    run_clip_generation()
