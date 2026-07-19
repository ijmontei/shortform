import json
import math
import os
import argparse
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
from content_archive import dedupe_packages
from editorial_gates import evaluate_editorial_gates
from metadata_generation import score_title_quality, title_passes_publishable_bar
from metadata_generation.titles import polish_headline_title, source_context_title
from theme_config import BASE_DIR, DEFAULT_THEME, EXECUTED_FILE, PULLED_FILE, assert_theme_allowed_for_active_run, discover_themes, ensure_theme, load_json_file, mark_stage, utc_timestamp, write_json_file
from theme_profile import load_theme_profile, theme_hashtags, theme_tags
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
UPLOAD_READY_TARGET_PER_THEME = max(0, int(os.getenv("SHORTFORM_UPLOAD_READY_TARGET_PER_THEME", "15")))
RESERVE_TARGET_PER_THEME = max(0, int(os.getenv("SHORTFORM_RESERVE_TARGET_PER_THEME", "10")))
EDITORIAL_FINAL_PACKAGE_TARGET = max(1, int(os.getenv(
    "SHORTFORM_EDITORIAL_FINAL_PACKAGE_TARGET",
    str(UPLOAD_READY_TARGET_PER_THEME + RESERVE_TARGET_PER_THEME),
)))
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
    os.getenv("SHORTFORM_ELEVENLABS_VOICE_ID", "HAM2nE4sbHnPgMji6JqB"),
).strip()
ELEVENLABS_FALLBACK_VOICE_IDS = [
    voice_id.strip()
    for voice_id in os.getenv("SHORTFORM_ELEVENLABS_FALLBACK_VOICE_IDS", "").split(",")
    if voice_id.strip()
]
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3").strip()
ELEVENLABS_OUTPUT_FORMAT = os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_192").strip()
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.16"))
ELEVENLABS_SIMILARITY_BOOST = float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.94"))
ELEVENLABS_STYLE = float(os.getenv("ELEVENLABS_STYLE", "0.98"))
ELEVENLABS_SPEAKER_BOOST = os.getenv("ELEVENLABS_SPEAKER_BOOST", "1") != "0"
NARRATION_PITCH = float(os.getenv("SHORTFORM_NARRATION_PITCH", "1.0"))
NARRATION_BASS_GAIN = float(os.getenv("SHORTFORM_NARRATION_BASS_GAIN", "0.0"))
NARRATION_LOUDNESS_I = float(os.getenv("SHORTFORM_NARRATION_LOUDNESS_I", "-16.0"))
NARRATION_TARGET_SECONDS = float(os.getenv("SHORTFORM_NARRATION_TARGET_SECONDS", "3.40"))
NARRATION_LEAD_IN_SECONDS = max(0.0, float(os.getenv("SHORTFORM_NARRATION_LEAD_IN_SECONDS", "0.28")))
NARRATION_FADE_IN_SECONDS = max(0.0, float(os.getenv("SHORTFORM_NARRATION_FADE_IN_SECONDS", "0.07")))
NARRATION_TAIL_PAD_SECONDS = max(0.0, float(os.getenv("SHORTFORM_NARRATION_TAIL_PAD_SECONDS", "0.32")))
NARRATION_MAX_TEMPO = max(1.0, min(1.12, float(os.getenv("SHORTFORM_NARRATION_MAX_TEMPO", "1.0"))))
INTRO_AUDIO_SAFETY_PAD_SECONDS = max(0.18, float(os.getenv("SHORTFORM_INTRO_AUDIO_SAFETY_PAD_SECONDS", "0.45")))
INTRO_SOURCE_AUDIO_VOLUME = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_SOURCE_AUDIO_VOLUME", "0.025"))
CLIP_SOURCE_AUDIO_VOLUME = float(os.getenv("SHORTFORM_EDITORIAL_CLIP_AUDIO_VOLUME", "1.0"))
EDITORIAL_SOURCE_AUDIO_FADE_IN_SECONDS = max(0.0, float(os.getenv("SHORTFORM_EDITORIAL_SOURCE_AUDIO_FADE_IN_SECONDS", "0.24")))
EDITORIAL_INTRO_TARGET_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_SECONDS", "5.2"))
EDITORIAL_INTRO_MAX_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_INTRO_MAX_SECONDS", "6.25"))
EDITORIAL_INTRO_ABSOLUTE_MAX_SECONDS = max(
    EDITORIAL_INTRO_MAX_SECONDS,
    float(os.getenv("SHORTFORM_EDITORIAL_INTRO_ABSOLUTE_MAX_SECONDS", "7.25")),
)
EDITORIAL_TOTAL_MAX_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_TOTAL_MAX_SECONDS", "58.0"))
CURRENT_FRAME_QC_VERSION = "2026-06-broll-montage-v2"
EDITORIAL_TRANSITION_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_TRANSITION_SECONDS", "0.45"))
EDITORIAL_RANK_CARD_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_RANK_CARD_SECONDS", "0.0"))
EDITORIAL_CLIP_MIN_SECONDS = float(os.getenv("SHORTFORM_EDITORIAL_CLIP_MIN_SECONDS", "7.0"))
EDITORIAL_BURN_SOURCE_CAPTIONS = os.getenv("SHORTFORM_EDITORIAL_BURN_SOURCE_CAPTIONS", "1") != "0"
EDITORIAL_PERIOD_LABEL = os.getenv("SHORTFORM_EDITORIAL_PERIOD_LABEL", "this week").strip() or "this week"
EDITORIAL_BOARD_SOURCE_LIMIT = max(5, int(os.getenv("SHORTFORM_EDITORIAL_BOARD_SOURCE_LIMIT", "12")))
EDITORIAL_HARD_REJECT_BAD_OUTPUTS = os.getenv("SHORTFORM_EDITORIAL_HARD_REJECT_BAD_OUTPUTS", "1") != "0"
MIN_EDITORIAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_EDITORIAL_VISUAL_QUALITY", "0.60"))
STRICT_EDITORIAL_FACE_GATES = os.getenv("SHORTFORM_STRICT_EDITORIAL_FACE_GATES", "1") != "0"
MIN_EDITORIAL_SOURCE_FACE_PRESENCE = float(os.getenv("SHORTFORM_MIN_EDITORIAL_SOURCE_FACE_PRESENCE", "0.42"))
MAX_EDITORIAL_SOURCE_NO_FACE_RUN = float(os.getenv("SHORTFORM_MAX_EDITORIAL_SOURCE_NO_FACE_RUN", "0.30"))
MAX_EDITORIAL_SOURCE_ALIVE_NO_FACE = float(os.getenv("SHORTFORM_MAX_EDITORIAL_SOURCE_ALIVE_NO_FACE", "0.36"))
MAX_EDITORIAL_SOURCE_CENTER_OFFSET = float(os.getenv("SHORTFORM_MAX_EDITORIAL_SOURCE_CENTER_OFFSET", "0.30"))
MAX_EDITORIAL_SOURCE_MAX_CENTER_OFFSET = float(os.getenv("SHORTFORM_MAX_EDITORIAL_SOURCE_MAX_CENTER_OFFSET", "0.58"))
MIN_EDITORIAL_SOURCE_FACE_PLAUSIBILITY = float(os.getenv("SHORTFORM_MIN_EDITORIAL_SOURCE_FACE_PLAUSIBILITY", "0.37"))
MIN_EDITORIAL_OUTPUT_FACE_PRESENCE = float(os.getenv("SHORTFORM_MIN_EDITORIAL_OUTPUT_FACE_PRESENCE", "0.46"))
MAX_EDITORIAL_OUTPUT_NO_FACE_RUN = float(os.getenv("SHORTFORM_MAX_EDITORIAL_OUTPUT_NO_FACE_RUN", "0.24"))
MAX_EDITORIAL_OUTPUT_ALIVE_NO_FACE = float(os.getenv("SHORTFORM_MAX_EDITORIAL_OUTPUT_ALIVE_NO_FACE", "0.40"))
MIN_DOCUMENTARY_EDITORIAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_DOCUMENTARY_EDITORIAL_VISUAL_QUALITY", "0.60"))
MAX_DOCUMENTARY_EDITORIAL_NO_FACE_RUN = float(os.getenv("SHORTFORM_MAX_DOCUMENTARY_EDITORIAL_NO_FACE_RUN", "0.50"))
MAX_DOCUMENTARY_EDITORIAL_ALIVE_NO_FACE = float(os.getenv("SHORTFORM_MAX_DOCUMENTARY_EDITORIAL_ALIVE_NO_FACE", "0.62"))
ENABLE_SECONDARY_FINAL_FRAME_QC = os.getenv("SHORTFORM_ENABLE_SECONDARY_FINAL_FRAME_QC", "1") != "0"
SECONDARY_FINAL_FRAME_QC_MAX_FRAMES = max(6, int(os.getenv("SHORTFORM_SECONDARY_FINAL_FRAME_QC_MAX_FRAMES", "10")))
SECONDARY_FINAL_SOURCE_AVG_OFFSET_LIMIT = float(os.getenv("SHORTFORM_SECONDARY_FINAL_SOURCE_AVG_OFFSET_LIMIT", "0.30"))
SECONDARY_FINAL_SOURCE_SEVERE_OFFSET_LIMIT = float(os.getenv("SHORTFORM_SECONDARY_FINAL_SOURCE_SEVERE_OFFSET_LIMIT", "0.46"))
RELAX_THEME_RELEVANCE_GATES = os.getenv("SHORTFORM_RELAX_THEME_RELEVANCE_GATES", "1") != "0"
YOUTUBE_PRIVACY_STATUS = os.getenv("SHORTFORM_YOUTUBE_PRIVACY_STATUS", "public").strip().lower()
if YOUTUBE_PRIVACY_STATUS not in {"public", "unlisted", "private"}:
    YOUTUBE_PRIVACY_STATUS = "public"
RENDER_POPULAR_SEGMENT_SHORTS = os.getenv("SHORTFORM_RENDER_POPULAR_SEGMENTS", "1") != "0"
POPULAR_SEGMENTS_PER_THEME = max(0, int(os.getenv("SHORTFORM_POPULAR_SEGMENTS_PER_THEME", "0")))
POPULAR_SEGMENT_REQUIRE_SIGNAL = os.getenv("SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL", "1") != "0"
POPULAR_SEGMENT_MIN_SCORE = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_MIN_SCORE", "0.12"))
EXHAUST_RENDERED_EDITORIAL_CLIPS = os.getenv("SHORTFORM_EXHAUST_RENDERED_EDITORIAL_CLIPS", "0") == "1"
EXHAUST_RENDERED_MAX_CLIPS = max(0, int(os.getenv("SHORTFORM_EXHAUST_RENDERED_MAX_CLIPS", "0")))
POPULAR_SEGMENT_INTRO_SECONDS = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_INTRO_SECONDS", "2.85"))
POPULAR_SEGMENT_MAX_SECONDS = float(os.getenv("SHORTFORM_POPULAR_SEGMENT_MAX_SECONDS", "58.0"))
EDITORIAL_SUBTITLE_MODEL = None
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
THEME_STYLE_ADJECTIVES = {
    "comedy": [
        "funniest", "wildest", "strangest", "most unexpected", "sharpest",
        "most uncomfortable", "most surprising", "most debated", "most revealing",
        "coolest", "most underrated", "most chaotic", "best timed", "boldest",
        "most awkward", "biggest", "most quotable", "most savage", "most unfiltered",
        "most replayable",
    ],
    "finance": [
        "sharpest", "most important", "most revealing", "most useful", "most practical",
        "most overlooked", "smartest", "most debated", "most surprising", "biggest",
        "most urgent", "most actionable", "most contrarian", "most data-backed",
        "most tactical", "riskiest", "most timely", "clearest", "most expensive",
        "most misunderstood",
    ],
    "sports": [
        "most heated", "most debated", "biggest", "sharpest", "wildest",
        "most surprising", "most clutch", "most controversial", "most underrated",
        "most revealing", "most important", "boldest", "most replayable",
        "most competitive", "most tactical", "most unexpected", "most intense",
        "coolest", "most uncomfortable", "best",
    ],
    "technology_ai": [
        "sharpest", "most useful", "most surprising", "most important",
        "most practical", "smartest", "most revealing", "most overlooked",
        "biggest", "most debated", "most tactical", "most actionable",
        "most technical", "most futuristic", "most misunderstood", "clearest",
        "most urgent", "most controversial", "most unexpected", "most data-backed",
    ],
    "health_fitness": [
        "most useful", "most practical", "most important", "most surprising",
        "most overlooked", "clearest", "smartest", "most actionable",
        "most revealing", "most debated", "biggest", "most misunderstood",
        "most urgent", "most evidence-backed", "most tactical", "most relatable",
        "most unexpected", "sharpest", "most uncomfortable", "most grounded",
    ],
    "politics": [
        "most important", "most revealing", "most debated", "sharpest",
        "most consequential", "most overlooked", "most controversial",
        "most urgent", "most surprising", "clearest", "biggest",
        "most tactical", "most uncomfortable", "most misunderstood",
        "most timely", "most concrete", "most detailed", "most disputed",
        "most clarifying", "most serious",
    ],
    "popculture": [
        "wildest", "most surprising", "most revealing", "most debated",
        "funniest", "strangest", "biggest", "most unexpected", "sharpest",
        "most awkward", "most quotable", "most replayable", "coolest",
        "most uncomfortable", "most underrated", "most unfiltered", "boldest",
        "most interesting", "most viral", "best",
    ],
    "truecrime": [
        "most revealing", "most important", "most disturbing", "most overlooked",
        "sharpest", "most consequential", "most detailed", "most disputed",
        "most unexpected", "most clarifying", "most serious", "most unsettling",
        "most crucial", "most misunderstood", "most documented", "most urgent",
        "most concrete", "most credible", "most confusing", "biggest",
    ],
}
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
    "technology_ai": {
        "label": "tech ai",
        "hashtags": ["#ai", "#technology", "#builders", "#shorts"],
        "tags": ["artificial intelligence", "technology", "builders", "founder interviews", "tech podcast", "ai shorts"],
    },
    "health_fitness": {
        "label": "wellness",
        "hashtags": ["#wellness", "#psychology", "#health", "#shorts"],
        "tags": ["wellness", "psychology", "health", "self improvement", "behavior change", "wellness podcast"],
    },
    "politics": {
        "label": "politics",
        "hashtags": ["#politics", "#news", "#currentaffairs", "#shorts"],
        "tags": ["politics", "news", "current affairs", "political podcast", "policy", "politics shorts"],
    },
    "popculture": {
        "label": "pop culture",
        "hashtags": ["#popculture", "#celebrity", "#music", "#shorts"],
        "tags": ["pop culture", "celebrity interviews", "music culture", "entertainment", "culture podcast", "celebrity shorts"],
    },
    "truecrime": {
        "label": "crime legal",
        "hashtags": ["#truecrime", "#legal", "#interview", "#shorts"],
        "tags": ["true crime", "legal interviews", "confessional interview", "human stories", "courtroom", "crime podcast"],
    },
}

STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "could", "every",
    "from", "have", "just", "like", "really", "right", "that", "their", "there",
    "they", "this", "those", "what", "when", "where", "which", "with", "would",
    "your", "youre", "yeah", "thing", "things", "people", "going", "think",
    "podcast", "episode", "shorts", "short", "video", "clip", "clips",
}

WEAK_TOPIC_WORDS = STOPWORDS | {
    "actually", "almost", "always", "anything", "basically", "better", "came",
    "coming", "didnt", "doesnt", "dont", "everything", "felt", "gonna",
    "guess", "happen", "happened", "having", "heard", "kinda", "kind",
    "little", "maybe", "mean", "means", "messy", "might", "much", "never",
    "normally", "okay", "pretty", "probably", "said", "saying", "somebody",
    "someone", "something", "sorry", "sort", "stuff", "talk", "talking",
    "thought", "totally", "whatever", "whats", "whole", "youve", "spelled",
    "army", "gut", "educate", "level", "yourself", "there", "really",
    "bluchu", "called", "especially", "absolutely", "around", "here",
    "hiding", "quick", "silently", "inside", "context", "behind",
    "detail", "standout", "moment", "problem",
    "group", "lesson", "rule", "number", "true", "many", "hours", "days",
    "year", "years", "attorney", "phone", "college", "budget", "network",
    "enterprise", "thinking", "scary", "crazy", "sense", "times",
    "very", "government", "million", "parents", "caps", "overweight",
    "wealth", "destroy", "sentiment", "terror", "rooting", "country",
    "president", "express", "subjective", "hard", "panel", "working",
    "both",
}

GENERIC_TOPIC_PHRASES = {
    "clean explanation",
    "heated exchange",
    "player comparison",
    "business breakdown",
    "health mistake",
    "case detail",
    "celebrity moment",
    "says everything",
    "got personal",
    "investors should understand",
    "silently wrecking",
    "ai problem behind",
    "context behind",
    "standout moment",
    "locker room story",
    "debate clip with real context",
    "evidence detail worth rechecking",
    "case moment inside",
    "evidence question around",
    "pop culture detail people missed",
    "ai detail builders are debating",
    "health habit worth rethinking",
    "market detail investors should watch",
    "trial credit deny",
    "prime crime",
    "room credit deny",
    "crime tony early",
    "prison crime dakota",
    "evidence both passenger",
}

GENERIC_EDITORIAL_TITLE_PATTERNS = [
    r"^the\s+debate\s+clip\s+with\s+real\s+context$",
    r"^the\s+evidence\s+detail\s+worth\s+rechecking$",
    r"^the\s+case\s+moment\s+inside\b",
    r"^the\s+pop\s+culture\s+detail\s+people\s+missed$",
    r"^the\s+ai\s+detail\s+builders\s+are\s+debating$",
    r"^the\s+market\s+detail\s+investors\s+should\s+watch$",
    r"^the\s+health\s+habit\s+worth\s+rethinking$",
    r"\bevidence\s+question\s+around\b",
    r"\bthe\s+moment\s+inside\b",
    r"^trial\s+credit\s+deny$",
    r"^prime\s+crime$",
    r"^room\s+credit\s+deny$",
    r"^crime\s+tony\s+early$",
    r"^prison\s+crime\s+dakota$",
    r"^evidence\s+both\s+passenger\b",
    r"^why\s+don'?t\s+we\b",
    r"\bwas\s+somebody\s+who\b",
    r"\bcast\s+debate\s+the\s+movie\b",
    r"^everyone\s+who\s+stood\s+by\s+.+\s+the\s+crash$",
    r"\binside\s+joke\s+league\s+find\b",
    r"^(trying\s+games\s+left|call\s+post\s+block|career\s+zion\s+young|locker\s+jaylen\s+brown)\s+changed\s+the\s+game$",
]

TOPIC_ACTION_WORDS = {
    "admit", "admits", "admitted", "argue", "argues", "argued",
    "ask", "asks", "asked", "avoid", "avoids", "avoided", "ban",
    "banned", "beat", "beats", "became", "becomes", "break",
    "breaks", "broke", "changed", "changes", "challenge", "challenged",
    "confess", "confessed", "confront", "confronts", "debate", "debated",
    "deny", "denied", "explain", "explains", "explained", "fight",
    "fights", "found", "hit", "hits", "land", "landed", "lost",
    "miss", "missed", "panic", "question", "questions", "recover",
    "recovery", "rethink", "reveal", "reveals", "revealed", "risk",
    "save", "saved", "shift", "shifts", "split", "splits", "stand",
    "stood", "testimony", "trial", "verdict", "warning", "warns",
}

TOPIC_CONNECTOR_WORDS = {
    "after", "against", "before", "during", "over", "under", "versus",
    "without", "with", "vs", "inside", "because", "when", "why", "how",
}

NOUN_SOUP_WORDS = WEAK_TOPIC_WORDS | {
    "actions", "aired", "afternoon", "broadcasting", "charity",
    "christine", "dakota", "defense", "dom", "hard", "helen", "however",
    "jameson", "king", "nancy", "paris", "phoenix", "potty", "reason",
    "room", "ruin", "russo", "sears", "solid", "students", "subjective",
    "town", "van", "ways", "passenger", "passengers",
}

MOJIBAKE_REPLACEMENTS = {
    "вЂ™": "'",
    "вЂ": "'",
    "вЂњ": '"',
    "вЂќ": '"',
    "вЂ¦": "...",
    "вЂ\"": "-",
    "РІР‚в„ў": "'",
    "РІР‚В": "'",
    "РІР‚Сљ": '"',
    "РІР‚Сњ": '"',
    "РІР‚вЂњ": "-",
    "РІР‚вЂќ": "-",
    "РІР‚В¦": "...",
    "Г‚": "",
}


MOJIBAKE_REPLACEMENTS.update({
    "\u0432\u0402\u201c": "-",
    "\u0432\u0402\u201d": "-",
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u02dc": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\u009d": '"',
    "\u00e2\u20ac\u015d": '"',
    "\u00e2\u20ac\u201c": "-",
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u00a6": "...",
    "\u00c3\u201a": "",
})


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


def clean_viewer_text(text):
    cleaned = str(text or "")

    for bad, replacement in MOJIBAKE_REPLACEMENTS.items():
        cleaned = cleaned.replace(bad, replacement)

    cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    cleaned = cleaned.replace("\u2026", "...")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|._")
    return fix_topic_case(cleaned)


SPECIAL_TOPIC_CASE = {
    "ai": "AI",
    "ipo": "IPO",
    "nyc": "NYC",
    "nfl": "NFL",
    "nba": "NBA",
    "ufc": "UFC",
    "spacex": "SpaceX",
    "openai": "OpenAI",
    "nvidia": "NVIDIA",
    "palantir": "Palantir",
}


def fix_topic_case(text):
    cleaned = str(text or "")

    for lower, replacement in SPECIAL_TOPIC_CASE.items():
        cleaned = re.sub(rf"\b{re.escape(lower)}\b", replacement, cleaned, flags=re.I)

    return cleaned


def title_words(text):
    return re.findall(r"[a-zA-Z][a-zA-Z0-9']{1,}|\b\d+[\d,.]*%?\b", str(text or ""))


def editorial_title_has_generic_pattern(text):
    lowered = clean_viewer_text(text).lower()
    return any(re.search(pattern, lowered) for pattern in GENERIC_EDITORIAL_TITLE_PATTERNS)


def topic_phrase_is_keyword_soup(theme, phrase):
    cleaned = clean_viewer_text(phrase)
    lowered = cleaned.lower()

    if not cleaned:
        return True

    if editorial_title_has_generic_pattern(cleaned):
        return True

    words = [word.lower().strip("'") for word in title_words(cleaned)]
    meaningful = [
        word
        for word in words
        if word not in WEAK_TOPIC_WORDS and word not in SOURCE_TITLE_SHOW_WORDS and len(word) >= 3
    ]

    if len(words) >= 3 and len(meaningful) < 2:
        return True

    if len(meaningful) < 3:
        return False

    action_hits = {
        word
        for word in meaningful
        if word in TOPIC_ACTION_WORDS
        or (word.endswith("ed") and word not in NOUN_SOUP_WORDS)
        or (word.endswith("ing") and word not in NOUN_SOUP_WORDS)
    }
    connector_hit = any(word in TOPIC_CONNECTOR_WORDS for word in words)
    specific_anchor = (
        bool(re.search(r"\b\d+[\d,.]*%?\b", cleaned))
        or bool(re.search(r"[A-Za-z]['’]s\b", cleaned))
        or connector_hit
    )
    theme_words = THEME_RELEVANCE_WORDS.get(str(theme or "").strip().lower(), set())
    domain_hits = {word for word in meaningful if word in theme_words}
    soup_hits = {word for word in meaningful if word in NOUN_SOUP_WORDS}
    theme_key = str(theme or "").strip().lower()

    if theme_key == "technology_ai" and {"data", "black", "hole"}.issubset(set(words)):
        return False

    if (
        theme_key == "truecrime"
        and "evidence" in meaningful
        and set(words) & {
            "dna", "blood", "gun", "guns", "towel", "truck", "phone", "phones",
            "fingerprint", "fingerprints", "forensic", "forensics", "video",
            "surveillance", "custody", "testimony",
        }
    ):
        return False

    if (
        theme_key == "truecrime"
        and domain_hits
        and re.search(r"\b(life sentence|sentencing hearing|trial|verdict|testimony|custody decision)\b", lowered)
    ):
        return False

    if len(soup_hits) >= 2 and len(domain_hits) <= 1:
        return True

    if not action_hits and not specific_anchor and len(domain_hits) == 0:
        return True

    if len(meaningful) >= 4 and not action_hits and not specific_anchor and len(domain_hits) <= 1:
        return True

    return False


def looks_like_raw_dialogue_topic(text):
    cleaned = clean_viewer_text(text)
    lowered = cleaned.lower()
    words = [word.lower().strip("'") for word in title_words(cleaned)]

    if not cleaned or len(words) < 3:
        return True

    if any(phrase in lowered for phrase in GENERIC_TOPIC_PHRASES):
        return True

    if cleaned.endswith("?"):
        question_start = words[0] if words else ""

        if question_start not in {"why", "how"}:
            return True

        if {"you", "yourself", "we", "they", "i"} & set(words):
            return True

    weak_starts = {
        "i", "you", "we", "they", "he", "she", "it", "that", "this", "so",
        "and", "but", "then", "more", "sorry", "okay", "yeah", "or", "do",
        "can",
    }
    first_word = words[0] if words else ""

    if first_word in weak_starts and not re.search(r"\b(why|how|what|market|case|policy|story|joke|team|ai)\b", lowered):
        return True

    pronoun_count = sum(1 for word in words if word in {"i", "you", "we", "they", "he", "she", "it"})
    filler_hits = sum(
        1
        for phrase in ["kind of", "sort of", "you know", "i mean", "i think", "what do you think", "thats kind"]
        if phrase in lowered
    )

    if pronoun_count >= 3 or filler_hits >= 1:
        return True

    if re.search(r"\b(i|you|we|they|he|she)\s+(said|thought|think|mean|guess|dont|didnt)\b", lowered):
        return True

    meaningful = [
        word
        for word in words
        if word not in WEAK_TOPIC_WORDS and len(word) >= 4
    ]
    return len(meaningful) < 2


def short_topic_phrase_ok(text):
    cleaned = clean_viewer_text(text)
    lowered = cleaned.lower()
    words = [word.lower().strip("'") for word in title_words(cleaned)]

    if not cleaned or any(phrase in lowered for phrase in GENERIC_TOPIC_PHRASES):
        return False

    if topic_phrase_is_keyword_soup("", cleaned):
        return False

    if lowered in SPECIAL_TOPIC_CASE:
        return True

    if any(phrase in lowered for phrase in ["cash flow", "interest rates", "mortgage rates", "space x"]):
        return True

    if any(word in {"i", "you", "we", "they", "he", "she", "it"} for word in words):
        return False

    meaningful = [
        word
        for word in words
        if word not in WEAK_TOPIC_WORDS and len(word) >= 4
    ]
    return 1 <= len(meaningful) <= 4 and len(words) <= 5


def source_subject_from_title(source_title):
    source_title = clean_viewer_text(source_title)
    first_chunk = re.split(r"\s+\|\s+|\s+-\s+|:", source_title, maxsplit=1)[0]
    first_chunk = re.sub(r"\b(ep|episode|podcast|interview|show)\b\.?\s*#?\d*", " ", first_chunk, flags=re.I)
    first_chunk = re.sub(r"\s+", " ", first_chunk).strip(" -:|._")
    words = title_words(first_chunk)

    if 1 <= len(words) <= 5 and len(first_chunk) <= 44:
        return first_chunk

    return ""


def possessive_subject(subject):
    subject = clean_viewer_text(subject).strip(" .:-")

    if not subject:
        return ""

    return f"{subject}'" if subject.lower().endswith("s") else f"{subject}'s"


def strengthen_topic_with_source_subject(theme, topic, source_title):
    topic = editorial_title_topic(topic)
    subject = source_subject_from_title(source_title)

    if not topic or topic == "The Standout Moment" or not subject:
        return topic

    subject_words = {word.lower().strip("'") for word in title_words(subject)}
    topic_words = [word.lower().strip("'") for word in title_words(topic)]

    if not subject_words or subject_words & set(topic_words):
        return topic

    topic_without_article = re.sub(r"^(the|a|an)\s+", "", topic, flags=re.I).strip()

    if len(topic_words) <= 4 and (
        re.search(r"\b(story|take|debate|panic|mistake|warning|question|case|moment|clip)\b", topic, flags=re.I)
        or str(theme or "").strip().lower() in {"comedy", "sports", "popculture"}
    ):
        return compact_text(f"{possessive_subject(subject)} {topic_without_article}", 62)

    return topic


SOURCE_TITLE_SHOW_WORDS = {
    "daybreak", "weekend", "edition", "podcast", "show", "interview",
    "episode", "bonus", "clips", "clip", "archive", "bloomberg",
}


def source_title_topic(source_title, theme="", limit=7):
    cleaned = clean_viewer_text(source_title)
    lower = cleaned.lower()

    if theme == "finance" and "us jobs" in lower and "vietnam eco" in lower:
        return "US Jobs And Vietnam Economy"

    if theme == "finance" and "new strikes on iran" in lower:
        return "Iran Strikes And Fed Policy"

    if theme == "finance" and "socialists sweep nyc" in lower:
        return "NYC Socialists And AI Market Signals"

    if theme == "health_fitness" and "fertility" in lower and "wrecking" in lower:
        return "Fertility Habits Most People Miss"

    if theme == "health_fitness" and "ben askren" in lower and "brink" in lower:
        return "Ben Askren's Recovery After The Brink"

    if theme == "health_fitness" and "muscle building exercises" in lower:
        return "Muscle-Building Exercises People Skip"

    if theme == "health_fitness" and {"depression", "fatigue", "trauma"} <= set(title_words(lower)):
        return "Depression, Fatigue And Childhood Trauma"

    if theme == "sports" and "rams expectation" in lower:
        return "The Rams Super Bowl Debate"

    if theme == "sports" and "champ bailey" in lower and "qbs stopped throwing" in lower:
        return "Why QBs Stopped Testing Champ Bailey"

    if theme == "sports" and "dustin poirier" in lower and "arrest" in lower:
        return "Dustin Poirier's Plea After Arrest"

    if theme == "sports" and "college locker room" in lower and "shoe collection" in lower:
        return "Coen Carr's Locker Room Shoe Collection"

    if theme == "technology_ai" and "pre-training" in lower:
        return "Why Pre-Training Isn't Dead"

    if theme == "technology_ai" and "data black hole" in lower and "ai" in lower:
        return "The AI Data Black Hole"

    if theme == "technology_ai" and "india's moment" in lower and "global companies" in lower:
        return "India's Startup Founder Wave"

    if theme == "technology_ai" and "after coding is solved" in lower:
        return "What Happens After Coding Is Solved"

    if theme == "technology_ai" and "zynga founder" in lower:
        return "Why Consumer Startups Still Matter"

    if theme == "politics" and "social media advisor" in lower:
        return "Trump's Social Media Advisor"

    if theme == "politics" and "top admiral" in lower and "troops" in lower:
        return "Trump's Military Order Controversy"

    if theme == "politics" and "rose garden dinner" in lower and "farmers" in lower:
        return "Trump's Farm Relief Dinner"

    if theme == "politics" and "nancy guthrie" in lower and "ransom" in lower:
        return "The Nancy Guthrie Ransom Note Questions"

    if theme == "politics" and "did trump surrender" in lower:
        return "Did Trump Surrender To Iran"

    if theme == "politics" and "nicholas kristof" in lower and "israel" in lower:
        return "Nicholas Kristof's Israel Report Defense"

    if theme == "politics" and "warning to israel" in lower:
        return "JD Vance's Warning To Israel"

    if theme == "politics" and "jd vance" in lower and "impeachment" in lower:
        return "JD Vance And Impeachment Fear"

    if theme == "politics" and "ro to elon" in lower:
        return "Ro Khanna's Challenge To Elon"

    if theme == "politics" and "trump melts down" in lower:
        return "Trump's Bill Meltdown"

    if theme == "popculture" and "fictional dads" in lower:
        return "The Best Fictional Dads Debate"

    if theme == "popculture" and "aly raisman" in lower:
        return "Aly Raisman On Dating Again"

    if theme == "popculture" and "markiplier" in lower and "movie" in lower:
        return "Markiplier's Hollywood Movie Bet"

    if theme == "popculture" and "jackass" in lower and "searched" in lower:
        return "Jackass Cast's Most Searched Questions"

    if theme == "popculture" and "mark zuckerberg" in lower and "ai" in lower:
        return "Mark Zuckerberg's AI Job Impact"

    if theme == "popculture" and "yunjin" in lower and "pre-debut" in lower:
        return "Yunjin's Pre-Debut Story"

    if theme == "popculture" and "thierry henry" in lower and "roberto carlos" in lower:
        return "Thierry Henry And Roberto Carlos"

    if theme == "truecrime" and "matching towel" in lower and "missing gun" in lower:
        return "The Missing Gun And Mother's Testimony"

    if theme == "truecrime" and "nancy brophy" in lower:
        return "Nancy Brophy Trial Evidence"

    if theme == "truecrime" and "maxwell connection" in lower and "epstein" in lower:
        return "Robert Maxwell And Epstein's Zorro Ranch"

    if theme == "truecrime" and "dragging officer" in lower and "avoids prison" in lower:
        return "Woman Drags Officer Case"

    if theme == "truecrime" and "anna kepner" in lower and "cruise" in lower:
        return "Anna Kepner Cruise Case Details"

    if theme == "truecrime" and "hospital freakouts" in lower:
        return "Hospital Bodycam Confrontation"

    if theme == "truecrime" and "false prophet" in lower and "sam bateman" in lower:
        return "Sam Bateman Trial Details"

    if theme == "truecrime" and "football player" in lower and "girlfriend" in lower:
        return "Cocaine Evidence In The Ex-Football Player Case"

    if theme == "truecrime" and "sinning pastor" in lower:
        return "Pastor Spell's Neighbor Fight"

    if theme == "truecrime" and "most horrific murder" in lower:
        return "The Most Horrific Murder Case"

    if theme == "truecrime" and "verdict" in lower:
        return "The Military Wife Murder Verdict"

    if theme == "truecrime" and "yogurt shop" in lower:
        return "The Yogurt Shop Exonerations"

    if theme == "truecrime" and "ultimate betrayal" in lower:
        return "Jacob's Betrayal Case"

    chunks = [
        re.sub(r"\s+", " ", chunk).strip(" -:._!?")
        for chunk in re.split(r"\s+\|\s+|:|,", cleaned)
        if chunk.strip()
    ]

    if not chunks:
        return ""

    candidates = []

    for chunk in chunks[:5]:
        words = [
            word
            for word in title_words(chunk)
            if word.lower().strip("'") not in WEAK_TOPIC_WORDS
            and word.lower().strip("'") not in SOURCE_TITLE_SHOW_WORDS
        ]

        if len(words) < 2:
            continue

        normalized_words = [word.lower().strip("'") for word in words]
        domain_hits = sum(1 for word in normalized_words if word in {
            "jobs", "economy", "market", "markets", "company", "brands", "fertility",
            "depression", "fatigue", "trauma", "trump", "vance", "israel", "iran",
            "movie", "hollywood", "coach", "quarterback", "trial", "verdict",
            "testimony", "ai", "coding", "founder", "model",
        })
        show_penalty = sum(1 for word in normalized_words if word in SOURCE_TITLE_SHOW_WORDS)
        score = domain_hits * 3 + min(len(words), limit) - show_penalty * 2
        candidates.append((score, words[:limit]))

    if not candidates:
        return ""

    best_words = max(candidates, key=lambda item: item[0])[1]
    return compact_text(polish_headline_title(" ".join(best_words)), 62)


def topic_phrase_is_weak(phrase, theme=""):
    if topic_phrase_is_keyword_soup(theme, phrase):
        return True

    if short_topic_phrase_ok(phrase):
        return False

    words = [word.lower().strip("'") for word in title_words(phrase)]

    if len(words) < 3:
        return True

    weak_count = sum(1 for word in words if word in WEAK_TOPIC_WORDS)

    if weak_count / max(1, len(words)) >= 0.45:
        return True

    if words[0] in {"especially", "absolutely", "around", "here", "more", "this", "that"}:
        return True

    if len(phrase) > 52:
        return True

    return False


def public_editorial_topic_ok(theme, text, topic_terms=None, allow_short_topic=True):
    cleaned = compact_text(clean_viewer_text(text), 64).strip(" -:|.")
    lowered = cleaned.lower()

    if not cleaned:
        return False

    if lowered in {
        "the standout moment",
        "standout moment",
        "the big takeaway",
        "best moment from the scan",
        "the moment worth rewatching",
    }:
        return False

    if allow_short_topic and short_topic_phrase_ok(cleaned):
        return True

    if looks_like_raw_dialogue_topic(cleaned):
        return False

    terms = topic_terms or [cleaned]
    quality = score_title_quality(theme, cleaned, topic_terms=terms)

    if topic_phrase_is_weak(cleaned, theme=theme) and (
        quality.get("honesty", 0.0) < 0.82
        or quality.get("generic_title")
        or quality.get("raw_dialogue_fragment")
        or quality.get("keyword_soup_title")
    ):
        return False

    return (
        quality.get("honesty", 0.0) >= 0.70
        and not quality.get("generic_title")
        and not quality.get("raw_dialogue_fragment")
        and not quality.get("mechanical_title")
        and not quality.get("repetitive_title")
        and quality.get("not_clickbait", True)
        and (quality.get("theme_native_title", True) or len(words_from_text(cleaned)) >= 4)
    )


TOPIC_SUPPORT_ALIASES = {
    "nascar": {"nascar", "race", "racing", "racer", "cars", "car", "track", "horsepower", "stock"},
    "racing": {"race", "racing", "racer", "cars", "car", "track", "horsepower", "nascar"},
    "amino": {"amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine", "protein", "grams"},
    "acids": {"amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine", "protein", "grams"},
    "protein": {"protein", "amino", "acid", "acids", "eaa", "eaas", "leucine", "lucine"},
    "abs": {"abs", "core", "hip", "hips", "flexor", "flexors", "physio", "ball", "range", "motion"},
    "strength": {"strength", "training", "lift", "lifts", "squat", "bench", "deadlift", "press", "row", "reps"},
    "lifts": {"strength", "training", "lift", "lifts", "squat", "bench", "deadlift", "press", "row", "reps"},
}

TOPIC_CONTEXT_WORDS = {
    "show", "episode", "podcast", "interview", "guest", "channel", "archive",
    "take", "story", "moment", "detail", "debate", "fight", "room",
}

THEME_RELEVANCE_WORDS = {
    "comedy": {
        "comedy", "comic", "comedian", "joke", "jokes", "laugh", "laughs",
        "roast", "bit", "story", "setup", "punchline", "awkward", "riff",
        "crowd", "room", "funny", "weird", "wild",
    },
    "gaming": {
        "gaming", "game", "games", "esports", "creator", "streamer",
        "tournament", "team", "player", "pro", "ranked", "league",
        "valorant", "cod", "riot", "lcs", "studio", "developer",
        "console", "controller", "launch", "patch", "roster", "scrim",
        "optic", "thieves", "faze",
    },
    "health_fitness": {
        "health", "fitness", "wellness", "training", "exercise", "workout", "protein",
        "amino", "acid", "eaa", "leucine", "lucine", "range", "motion", "hip",
        "hips", "flexor", "physio", "ball", "body", "abs", "core", "muscle",
        "sleep", "stress", "fertility", "metabolism", "nutrition",
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
    "politics": {
        "politics", "policy", "election", "campaign", "court", "congress",
        "senate", "president", "border", "war", "media", "vote", "law",
        "hearing", "debate", "poll", "corruption", "foreign", "trump",
        "vance", "israel", "iran", "netanyahu", "hezbollah", "supreme",
    },
    "popculture": {
        "celebrity", "actor", "movie", "movies", "music", "song", "album",
        "hollywood", "culture", "artist", "dating", "fame", "career",
        "viral", "scene", "tour", "fan", "fans", "jackass", "amy",
        "adams", "markiplier",
    },
    "truecrime": {
        "crime", "case", "trial", "court", "confession", "witness",
        "victim", "testimony", "investigation", "detective", "prison",
        "jury", "verdict", "evidence", "lawyer", "legal", "survivor",
        "murder", "gun", "mother", "cruise", "epstein", "ranch",
        "harmony", "anna", "sam", "jacob",
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


def normalize_support_word(word):
    word = str(word or "").lower().strip("'")
    word = word.replace("'s", "").replace("’s", "")

    if len(word) > 3 and word.endswith("s"):
        word = word[:-1]

    return word


def support_words(text):
    result = set()

    for word in words_from_text(text):
        normalized = normalize_support_word(word)

        if (
            not normalized
            or normalized in WEAK_TOPIC_WORDS
            or normalized in TOPIC_CONTEXT_WORDS
            or len(normalized) < 3
        ):
            continue

        result.add(normalized)

    return result


def topic_support_details(topic, clip):
    clip = clip or {}
    topic_words = support_words(topic)
    transcript_words = support_words(clip.get("transcript_excerpt", ""))
    source_words = support_words(clip.get("source_title", ""))
    checked_words = topic_words - source_words or topic_words
    exact_support = topic_words & transcript_words
    alias_support = set()

    for word in checked_words:
        aliases = TOPIC_SUPPORT_ALIASES.get(word, set())

        if aliases and transcript_words & {normalize_support_word(alias) for alias in aliases}:
            alias_support.add(word)

    supported_words = (exact_support | alias_support) & checked_words
    support_ratio = len(supported_words) / max(1, len(checked_words))

    return {
        "topic_words": sorted(topic_words),
        "transcript_words": sorted(transcript_words),
        "source_words": sorted(source_words),
        "checked_words": sorted(checked_words),
        "exact_support": sorted(exact_support),
        "alias_support": sorted(alias_support),
        "support_ratio": float(support_ratio),
    }


def topic_supported_by_clip(topic, clip):
    cleaned = editorial_title_topic(topic)

    if not cleaned or cleaned == "The Standout Moment":
        return False

    details = topic_support_details(cleaned, clip)
    checked_words = set(details["checked_words"])

    if not checked_words:
        return False

    exact_count = len(details["exact_support"])
    alias_count = len(details["alias_support"])

    if exact_count >= 2:
        return True

    if exact_count >= 1 and len(checked_words) <= 3:
        return True

    if exact_count >= 1 and details["support_ratio"] >= 0.34:
        return True

    if alias_count >= 1 and exact_count + alias_count >= 2:
        return True

    return False


def clip_has_theme_relevance(theme, clip):
    theme = str(theme or clip_theme_key(clip)).strip().lower()
    source_tier = str(
        clip.get("source_tier")
        or (clip.get("rank_signals") or {}).get("source_tier")
        or ""
    ).strip().lower()

    if (
        os.getenv("SHORTFORM_TRUST_CONFIGURED_SOURCE_RELEVANCE", "1") != "0"
        and source_tier in {"priority", "secondary", "legacy"}
    ):
        return True

    words = support_words(clip.get("transcript_excerpt", ""))
    positive_words = THEME_RELEVANCE_WORDS.get(theme, set())

    if not positive_words:
        return True

    positive_hits = words & positive_words
    mismatch_hits = words & CROSS_THEME_MISMATCH_WORDS.get(theme, set())

    if len(mismatch_hits) >= 2:
        if theme == "technology_ai" and positive_hits <= {"machine", "product"}:
            return False
        if not positive_hits:
            return False

    if len(positive_hits) >= 1:
        return True

    if len(mismatch_hits) >= 2:
        return False

    return False


def transcript_topic_phrase(theme, clip):
    excerpt = clean_viewer_text(clip.get("transcript_excerpt", ""))
    lower = excerpt.lower()
    source_subject = source_subject_from_title(clip.get("source_title", ""))

    if theme == "finance" and "constellation" in lower and "turnaround" in lower:
        return "Constellation Brands Turnaround"

    if theme == "health_fitness":
        if re.search(r"\b(eaa|eaas|leucine|lucine)\b", lower):
            return "EAAs And Leucine Matter"

        if "range of motion" in lower and ("physio ball" in lower or "hip" in lower or "feet" in lower):
            return "The Range Of Motion People Miss"

        if "female physicians" in lower and "infertility" in lower:
            return "Female Physicians And Fertility Risk"

        if "five elements" in lower and "acupuncture" in lower:
            return "Five Elements Acupuncture"

        if "why was i hiding" in lower or "was i hiding" in lower:
            return "Why Ed O'Brien Was Hiding"

        if "not sustainable" in lower or "relentless" in lower:
            return "When Success Stops Feeling Sustainable"

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

    if theme == "technology_ai":
        if any(term in lower for term in ["steam machine", "fortnite", "grand theft", "gta", "dota"]):
            return ""

        if "ai advisor" in lower and ("coordination" in lower or "government" in lower or "everyone's fine" in lower):
            return "AI Advisors Make Coordination Harder"

        if "product variant" in lower and ("vision" in lower or "instinct" in lower):
            return "Product Vision Versus Product Variants"

        if "pre-training" in lower and "dead" in lower:
            return "Why Pre-Training Isn't Dead"

        if "coding is solved" in lower:
            return "What Happens After Coding Is Solved"

    if theme == "truecrime":
        if "jameson" in lower and "removed from his mother's care" in lower:
            return "Jameson Was Removed From His Mother's Care"

        if "harmony" in lower and "potty train" in lower:
            return "Harmony Montgomery Potty Trained Herself"

        if "prosecution's case is pretty airtight" in lower and "video" in lower:
            return "The Cruise Video Timeline Looked Airtight"

        if "enter the room" in lower and "deny it" in lower:
            return "The Room Entry He Planned To Deny"

        if "pardon" in lower and "prime minister" in lower:
            return "The Pardon Claim After The Murder Case"

        if ("matthew" in lower or "matt " in lower) and "sentencing" in lower and "kidnapping" in lower:
            return "Matthew Ponema Sentencing Hearing"

        if "life in prison" in lower and "dakota van patten" in lower:
            return "Dakota Van Patten's Life Sentence Trial"

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

    if source_subject and "wardrobe" in source_subject.lower():
        return "Bobby's Wardrobe Malfunction"

    return ""


def clip_topic_terms(clip, limit=5):
    source_title = clean_viewer_text(clip.get("source_title", ""))
    source_words = {word.lower() for word in title_words(source_title)}
    terms = []

    for term in clip.get("topic_fingerprint", []):
        cleaned = clean_viewer_text(str(term).replace("_", " ")).lower()
        cleaned = re.sub(r"[^a-z0-9\s%.-]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if not cleaned:
            continue

        words = [word for word in cleaned.split() if word not in WEAK_TOPIC_WORDS and len(word) >= 3]

        if not words:
            continue

        normalized = " ".join(words)

        if normalized in source_words and len(terms) >= 2:
            continue

        if normalized not in terms:
            terms.append(normalized)

        if len(terms) >= limit:
            break

    return terms


def phrase_from_topic_terms(theme, clip, terms):
    term_set = set(terms)
    source_subject = source_subject_from_title(clip.get("source_title", ""))

    if {"cleaning", "lady"} <= term_set:
        return "Cleaning For The Cleaning Lady"

    if {"sidetrack", "embarrassing"} <= term_set:
        return "The Embarrassing UFC Sidetrack Story"

    if {"born", "italy"} <= term_set or {"colorado", "italy"} <= term_set:
        if source_subject:
            suffix = "'" if source_subject.lower().endswith("s") else "'s"
            return f"{source_subject}{suffix} Italy Story"

        return "The Italy Childhood Story"

    if {"cooper", "flag"} <= term_set or {"cooper", "flagg"} <= term_set:
        return "Cooper Flagg's Rough Debut"

    if {"john", "benet", "jazz"} <= term_set or {"jonbenet", "jazz"} <= term_set:
        return "The JonBenet Jazz Singer Joke"

    if {"voice", "trailer"} <= term_set or {"voice", "animation"} <= term_set:
        return "Tony Hale's Toy Story Voice Panic"

    if {"raw", "milk"} <= term_set or {"milk", "pasteurized"} <= term_set:
        return "The Raw Milk Debate Gets Weird"

    if {"rolling", "stone"} <= term_set:
        return "The Rolling Stone Quiz Bit"

    if {"brandon", "aiyuk"} <= term_set or {"niners", "team"} <= term_set:
        return "Brandon Aiyuk's 49ers Problem"

    if {"supplemental", "draft"} <= term_set or {"nfl", "wrong"} <= term_set:
        return "The NFL Supplemental Draft Question"

    if {"mikal", "championship"} <= term_set or {"mikhail", "championship"} <= term_set:
        return "Mikal Bridges' Knicks Championship Moment"

    if {"word", "play"} <= term_set or "wordplay" in term_set:
        return "The Wordplay Backstory"

    if ("actor" in term_set or "acting" in term_set) and ({"reaction", "feeling", "instinct"} & term_set):
        return "Acting On Instinct"

    if {"singing", "song"} & term_set and {"setup", "set"} & term_set:
        return "The Singing Setup"

    if "mobbed" in term_set:
        return "Getting Mobbed By Fans"

    if theme == "comedy" and {"salt", "died"} & term_set and source_subject:
        return f"{source_subject} Standout Story"

    if not terms:
        return ""

    if len(terms) >= 3:
        phrase = " ".join(terms[:3])
    elif len(terms) == 2:
        phrase = " ".join(terms)
    else:
        subject = source_subject or ""
        phrase = f"{subject} {terms[0]}".strip()

    phrase = phrase.title()

    if theme == "comedy" and not re.search(r"\b(story|joke|roast|bit|payoff)\b", phrase, flags=re.I):
        phrase = f"{phrase} Story"

    return compact_text(phrase, 54)


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
    text = compact_text(clean_viewer_text(text), 180)
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
    profile = load_theme_profile(theme)
    brand = profile.get("brand") or {}
    packaging = profile.get("packaging", {}) or {}
    label = (
        brand.get("channel_name")
        or profile.get("metadata_style", {}).get("label")
        or theme.replace("_", " ")
    )
    default = {
        "label": label,
        "hashtags": ["#podcast", "#recap", "#shorts"],
        "tags": ["podcast", "recap", "shorts", theme.replace("_", " ")],
        "profile": profile.get("profile", "generic"),
        "packaging": packaging,
        "caption_style": packaging.get("caption_style", ""),
        "framing_style": packaging.get("framing_style", ""),
        "overlay_style": packaging.get("overlay_style", ""),
        "default_intro_mode": packaging.get("default_intro_mode", ""),
        "metadata_style": profile.get("metadata_style", {}),
    }
    return {
        **default,
        **THEME_TAGS.get(theme, {}),
        "label": label,
        "hashtags": theme_hashtags(theme) or default["hashtags"],
        "tags": theme_tags(theme) or default["tags"],
    }


def adjective_pool_for_theme(theme):
    theme_key = str(theme or "").strip().lower()
    pool = THEME_STYLE_ADJECTIVES.get(theme_key) or STYLE_ADJECTIVES
    return unique_sequence(pool)


def normalized_adjective_queue(queue, theme=None):
    allowed = adjective_pool_for_theme(theme)
    allowed_set = set(allowed)
    cleaned = unique_sequence(queue)
    cleaned = [item for item in cleaned if item in allowed_set]

    for adjective in allowed:
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
    queue = normalized_adjective_queue(theme_state.get("queue", adjective_pool_for_theme(theme)), theme=theme)
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

    output_file = clip.get("output_file", "")

    if isinstance(value, dict) and value:
        frame_path = value.get("frame_path") if isinstance(value.get("frame_path"), dict) else {}
        cached_version = value.get("frame_qc_version") or frame_path.get("frame_qc_version")

        if cached_version == CURRENT_FRAME_QC_VERSION:
            return value

        if not output_file or not os.path.exists(output_file):
            return value

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
            "frame_qc_version": frame_qc.get("frame_qc_version", ""),
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
    theme_key = str(clip.get("theme") or "").strip().lower()
    state_key = str(clip.get("source_state_key") or "")

    if not theme_key and "|" in state_key:
        theme_key = state_key.split("|", 1)[0].strip().lower()

    if not RELAX_THEME_RELEVANCE_GATES and not clip_has_theme_relevance(theme_key, clip):
        return False

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
        "probable tiny/background face lock",
        "probable background lock instead of speaker",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
    }
    frame_path = render_qc.get("frame_path") or {}
    face_presence = float(frame_path.get("face_presence_rate") or 0.0)
    no_face_run = float(frame_path.get("longest_no_face_run_ratio") or 0.0)
    alive_no_face = float(frame_path.get("alive_no_face_frame_ratio") or 0.0)
    center_offset = float(frame_path.get("avg_face_center_offset_ratio") or 0.0)
    max_center_offset = float(frame_path.get("max_face_center_offset_ratio") or 0.0)
    plausibility = float(frame_path.get("avg_face_plausibility") or 0.0)
    non_speaker_visual_ok = (
        theme_key in NON_SPEAKER_VISUAL_THEMES
        and (render_qc.get("documentary_non_face_ok") or render_qc.get("non_speaker_visual_ok"))
        and clip_visual_quality_score(clip) >= MIN_DOCUMENTARY_EDITORIAL_VISUAL_QUALITY
        and no_face_run <= max(MAX_DOCUMENTARY_EDITORIAL_NO_FACE_RUN, 0.62)
        and alive_no_face <= max(MAX_DOCUMENTARY_EDITORIAL_ALIVE_NO_FACE, 0.72)
        and "probable tiny/background face lock" not in flags
        and "probable background lock instead of speaker" not in flags
        and "probable picture-in-picture/background lock" not in flags
        and "probable flat-surface false face lock" not in flags
        and "probable small-object/background face lock" not in flags
    )

    if non_speaker_visual_ok:
        hard_flags.discard("probable broadcast/b-roll montage instead of speaker clip")

    if flags & hard_flags:
        return False

    if non_speaker_visual_ok:
        return True

    if STRICT_EDITORIAL_FACE_GATES:
        if face_presence and face_presence < MIN_EDITORIAL_SOURCE_FACE_PRESENCE:
            return False

        if no_face_run > MAX_EDITORIAL_SOURCE_NO_FACE_RUN:
            return False

        if alive_no_face > MAX_EDITORIAL_SOURCE_ALIVE_NO_FACE:
            return False

        if center_offset > 0.42:
            return False

        if face_presence < 0.90 and center_offset > MAX_EDITORIAL_SOURCE_CENTER_OFFSET:
            return False

        if max_center_offset > MAX_EDITORIAL_SOURCE_MAX_CENTER_OFFSET:
            return False

        if "subject off-center in final crop" in flags:
            return False

        if "unstable final subject position" in flags and (
            max_center_offset > 0.58 or alive_no_face > 0.30
        ):
            return False

        if face_presence < 0.55 and plausibility and plausibility < MIN_EDITORIAL_SOURCE_FACE_PLAUSIBILITY:
            return False

        if {
            "low final face presence",
            "alive frames often miss speaker",
            "extended no-speaker run in final crop",
            "weak final face plausibility",
            "probable tiny/background face lock",
            "probable background lock instead of speaker",
            "probable picture-in-picture/background lock",
            "probable flat-surface false face lock",
            "probable small-object/background face lock",
            "probable broadcast/b-roll montage instead of speaker clip",
        } & flags:
            return False

    return clip_visual_quality_score(clip) >= 0.58


def clip_is_popular_segment_usable(clip):
    render_qc = clip_render_qc(clip)

    if render_qc and not render_qc.get("passed", True):
        soft_flags = {"source playback ends without a strong face"}
        rejection_reasons = set(render_qc.get("rejection_reasons") or [])
        flags = set(render_qc.get("flags") or [])

        if not (rejection_reasons or flags):
            return False

        if (rejection_reasons or flags) - soft_flags:
            return False

    return clip_is_editorial_usable(clip)


def editorial_output_rejection_reasons(frame_qc, theme="", speaker_strict=True):
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
    speaker_hard_flags = {
        "probable picture-in-picture/background lock",
        "probable background lock instead of speaker",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
    }
    if speaker_strict:
        hard_flags |= speaker_hard_flags
    reasons = sorted(flags & hard_flags)
    visual_score = float(frame_qc.get("visual_quality_score") or 0.0)
    face_presence = float(frame_qc.get("face_presence_rate") or 0.0)
    no_face_run = float(frame_qc.get("longest_no_face_run_ratio") or 0.0)
    alive_no_face = float(frame_qc.get("alive_no_face_frame_ratio") or 0.0)
    max_center_offset = float(frame_qc.get("max_face_center_offset_ratio") or 0.0)
    low_information = float(frame_qc.get("low_information_frame_ratio") or 0.0)
    dead_frames = float(frame_qc.get("dead_frame_ratio") or 0.0)
    black_frames = float(frame_qc.get("black_frame_ratio") or 0.0)
    theme_key = str(theme or "").strip().lower()
    non_speaker_visual_ok = (
        theme_key in NON_SPEAKER_VISUAL_THEMES
        and visual_score >= MIN_DOCUMENTARY_EDITORIAL_VISUAL_QUALITY
        and low_information <= 0.18
        and dead_frames <= 0.02
        and black_frames <= 0.02
        and no_face_run <= max(MAX_DOCUMENTARY_EDITORIAL_NO_FACE_RUN, 0.62)
        and alive_no_face <= max(MAX_DOCUMENTARY_EDITORIAL_ALIVE_NO_FACE, 0.72)
        and not {
            "probable tiny/background face lock",
            "probable background lock instead of speaker",
            "probable picture-in-picture/background lock",
            "probable flat-surface false face lock",
            "probable small-object/background face lock",
        } & flags
    )

    if non_speaker_visual_ok and "probable broadcast/b-roll montage instead of speaker clip" in reasons:
        reasons.remove("probable broadcast/b-roll montage instead of speaker clip")

    if visual_score < MIN_EDITORIAL_VISUAL_QUALITY and not non_speaker_visual_ok:
        reasons.append(
            f"low editorial visual quality score ({visual_score:.2f} < {MIN_EDITORIAL_VISUAL_QUALITY:.2f})"
        )

    if not speaker_strict:
        return reasons

    if not non_speaker_visual_ok and face_presence and face_presence < MIN_EDITORIAL_OUTPUT_FACE_PRESENCE:
        reasons.append(
            f"low final package face presence ({face_presence:.2f} < {MIN_EDITORIAL_OUTPUT_FACE_PRESENCE:.2f})"
        )

    if not non_speaker_visual_ok and no_face_run > MAX_EDITORIAL_OUTPUT_NO_FACE_RUN:
        reasons.append(
            f"long final package no-speaker run ({no_face_run:.2f} > {MAX_EDITORIAL_OUTPUT_NO_FACE_RUN:.2f})"
        )

    if not non_speaker_visual_ok and alive_no_face > MAX_EDITORIAL_OUTPUT_ALIVE_NO_FACE:
        reasons.append(
            f"alive final package frames often miss speaker ({alive_no_face:.2f} > {MAX_EDITORIAL_OUTPUT_ALIVE_NO_FACE:.2f})"
        )

    if (
        not non_speaker_visual_ok
        and alive_no_face > 0.34
        and "alive frames often miss speaker" in flags
    ):
        reasons.append(
            f"alive final package repeatedly misses speaker ({alive_no_face:.2f} > 0.34)"
        )

    if (
        not non_speaker_visual_ok
        and alive_no_face > 0.25
        and max_center_offset > 0.70
        and (
            "subject off-center in final crop" in flags
            or "unstable final subject position" in flags
            or "probable tiny/background face lock" in flags
            or "probable picture-in-picture/background lock" in flags
            or "probable flat-surface false face lock" in flags
            or "probable small-object/background face lock" in flags
            or "probable broadcast/b-roll montage instead of speaker clip" in flags
        )
    ):
        reasons.append(
            f"final package likely locked to background ({max_center_offset:.2f} max face offset)"
        )

    return reasons


def editorial_audio_qc_for(output_file):
    try:
        import content_qc

        return content_qc.analyze_audio_start(output_file)
    except Exception as error:
        return {
            "flags": [f"final editorial audio QA failed: {error}"],
        }


def editorial_secondary_frame_qc_for(output_file, theme="", package=None):
    if not ENABLE_SECONDARY_FINAL_FRAME_QC:
        return {"skipped": True, "reason": "secondary final-frame QC disabled", "flags": []}

    try:
        import content_qc

        media = content_qc.ffprobe_media(output_file)
        package = package or {}
        intro_duration = float(package.get("intro_duration") or 0.0)
        rank_card_duration = float(package.get("rank_card_duration") or 0.0)
        source_play_duration = float(package.get("source_play_duration") or 0.0)
        sample_start = 0.0
        sample_end = float(media.get("duration") or 0.0)
        asset_type = "final_upload"

        if source_play_duration >= 3.0:
            sample_start = max(0.0, intro_duration + rank_card_duration)
            sample_end = min(sample_end, sample_start + source_play_duration)
            asset_type = "final_upload_source"

        interval_seconds = max(
            2.0,
            max(0.0, sample_end - sample_start) / max(1, SECONDARY_FINAL_FRAME_QC_MAX_FRAMES),
        )
        contact_sheet, frame_samples = content_qc.create_contact_sheet(
            output_file,
            str(theme or DEFAULT_THEME),
            asset_type,
            media,
            interval_seconds=interval_seconds,
            max_frames=SECONDARY_FINAL_FRAME_QC_MAX_FRAMES,
            start_seconds=sample_start,
            end_seconds=sample_end,
        )
        frame_qc = content_qc.summarize_frame_metrics(frame_samples, asset_type)
        frame_qc["contact_sheet"] = contact_sheet
        frame_qc["frame_qc_version"] = "content_qc_final_upload_v1"
        frame_qc["sample_asset_type"] = asset_type
        frame_qc["sample_start_seconds"] = round(sample_start, 3)
        frame_qc["sample_end_seconds"] = round(sample_end, 3)
        return frame_qc
    except Exception as error:
        return {
            "flags": [f"final editorial secondary frame QA failed: {error}"],
        }


def editorial_secondary_frame_rejection_reasons(frame_qc):
    flags = set((frame_qc or {}).get("flags") or [])
    reasons = []
    hard_flags = {
        "no sampled frames",
        "black/dead frames present",
        "too many low-information frames",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable small-object/background face lock",
        "probable flat-surface false face lock",
    }

    for flag in sorted(flags & hard_flags):
        reasons.append(f"secondary final-frame QC: {flag}")

    if any(flag.startswith("final editorial secondary frame QA failed") for flag in flags):
        reasons.append("secondary final-frame QC failed")

    return reasons


def editorial_secondary_frame_advisory_reasons(frame_qc):
    flags = set((frame_qc or {}).get("flags") or [])
    reasons = []
    asset_type = str((frame_qc or {}).get("sample_asset_type") or "")
    face_presence = float((frame_qc or {}).get("face_presence_rate") or 0.0)
    no_face_run = float((frame_qc or {}).get("longest_no_face_run_ratio") or 0.0)
    avg_offset = float((frame_qc or {}).get("avg_face_center_offset") or 0.0)
    max_offset = float((frame_qc or {}).get("max_face_center_offset") or 0.0)
    low_face_limit = 0.35 if asset_type == "final_upload_source" else 0.42
    avg_offset_limit = SECONDARY_FINAL_SOURCE_AVG_OFFSET_LIMIT if asset_type == "final_upload_source" else 0.26
    severe_offset_limit = SECONDARY_FINAL_SOURCE_SEVERE_OFFSET_LIMIT if asset_type == "final_upload_source" else 0.42

    if "low speaker/face presence" in flags and face_presence < low_face_limit:
        reasons.append(f"secondary final-frame QC advisory: low speaker presence ({face_presence:.2f} < {low_face_limit:.2f})")

    if "extended run without a strong face" in flags and no_face_run > 0.36:
        reasons.append(f"secondary final-frame QC advisory: extended weak-subject run ({no_face_run:.2f} > 0.36)")

    if "subject often off center" in flags and avg_offset > avg_offset_limit:
        reasons.append(f"secondary final-frame QC advisory: off-center subject ({avg_offset:.2f} > {avg_offset_limit:.2f})")

    if "severe off-center frames" in flags and max_offset > severe_offset_limit:
        reasons.append(f"secondary final-frame QC advisory: severe off-center frames ({max_offset:.2f} > {severe_offset_limit:.2f})")

    return reasons


def editorial_audio_rejection_reasons(audio_qc):
    flags = set((audio_qc or {}).get("flags") or [])
    hard_flags = {
        "audio start is empty",
        "no clear audio onset in first five seconds",
        "slow audio/narration start",
        "possible clipped/distorted intro audio",
    }
    return sorted(flags & hard_flags)


def finalize_editorial_package(package, label):
    output_file = package.get("video_file", "")

    if not output_file or not os.path.exists(output_file):
        package.setdefault("posting_status", {})["youtube_shorts"] = "failed"
        package.setdefault("review", {})["rejection_reason"] = "missing rendered editorial output"
        package["editorial_gates"] = evaluate_editorial_gates(package.get("theme", DEFAULT_THEME), package)
        return package

    try:
        import clip_generation

        frame_qc = clip_generation.analyze_final_frame_path(output_file, max_samples=24)
    except Exception as error:
        frame_qc = {
            "flags": [f"final editorial QA failed: {error}"],
            "visual_quality_score": 0.0,
        }

    audio_qc = editorial_audio_qc_for(output_file)
    secondary_frame_qc = editorial_secondary_frame_qc_for(output_file, package.get("theme", DEFAULT_THEME), package=package)
    rejection_reasons = editorial_output_rejection_reasons(
        frame_qc,
        package.get("theme", DEFAULT_THEME),
        speaker_strict=False,
    )
    rejection_reasons.extend(editorial_secondary_frame_rejection_reasons(secondary_frame_qc))
    rejection_reasons.extend(editorial_audio_rejection_reasons(audio_qc))
    rejection_reasons = sorted(set(rejection_reasons))
    advisory_reasons = sorted(set(editorial_secondary_frame_advisory_reasons(secondary_frame_qc)))
    package["render_qc"] = {
        "frame_qc_version": frame_qc.get("frame_qc_version", CURRENT_FRAME_QC_VERSION),
        "passed": not rejection_reasons,
        "flags": sorted(set(
            list(frame_qc.get("flags") or [])
            + list((secondary_frame_qc or {}).get("flags") or [])
            + list(audio_qc.get("flags") or [])
            + rejection_reasons
        )),
        "visual_quality_score": frame_qc.get("visual_quality_score", 0.0),
        "frame_path": frame_qc,
        "secondary_frame_path": secondary_frame_qc,
        "intro_audio": audio_qc,
        "rejected": bool(rejection_reasons),
        "rejection_reasons": rejection_reasons,
        "advisory_reasons": advisory_reasons,
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

    package["editorial_gates"] = evaluate_editorial_gates(package.get("theme", DEFAULT_THEME), package)
    return package


def package_is_upload_ready(package):
    editorial_gates = package.get("editorial_gates") or evaluate_editorial_gates(
        package.get("theme", DEFAULT_THEME),
        package,
    )
    captions_required = package.get("upload_ready_requires_burned_captions", True)
    return (
        bool(package.get("video_file"))
        and os.path.exists(package.get("video_file", ""))
        and (package.get("posting_status") or {}).get("youtube_shorts") == "ready"
        and (not captions_required or package.get("content_has_burned_captions"))
        and not (package.get("render_qc") or {}).get("rejected")
        and editorial_gates.get("passed", True)
    )


def editorial_clip_score(clip):
    base_score = float(clip.get("score") or 0)
    visual_score = clip_visual_quality_score(clip)
    readiness = float(clip.get("readiness_score") or 0.0)
    popularity = float(clip.get("popularity_score") or 0.0)
    comment = float(clip.get("comment_score") or 0.0)
    arc = float(clip.get("arc_score") or 0.0)
    boundary = float(clip.get("boundary_score") or 0.0)
    text = float(clip.get("text_score") or 0.0)
    render_qc = clip_render_qc(clip)
    penalty = 0.0

    if render_qc and not render_qc.get("passed", True):
        penalty += 0.05

    if "unstable final subject position" in set(render_qc.get("flags") or []):
        penalty += 0.035

    return (
        base_score * 0.42
        + readiness * 0.16
        + visual_score * 0.16
        + max(popularity, comment) * 0.10
        + boundary * 0.07
        + arc * 0.05
        + text * 0.04
        - penalty
    )


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


def clip_theme_key(clip):
    state_key = str(clip.get("source_state_key") or "")

    if "|" in state_key:
        return state_key.split("|", 1)[0]

    return str(clip.get("theme") or "").strip().lower()


def topic_label_from_clip(clip, theme=""):
    theme = (theme or clip_theme_key(clip)).strip().lower()
    suggested_title = compact_text(clean_viewer_text(clip.get("suggested_title", "")), 58).strip(" .")
    terms = clip_topic_terms(clip, limit=10)
    transcript_phrase = transcript_topic_phrase(theme, clip)

    if (
        transcript_phrase
        and topic_supported_by_clip(transcript_phrase, clip)
        and public_editorial_topic_ok(theme, transcript_phrase, topic_terms=terms)
    ):
        return compact_text(transcript_phrase, 54)

    if (
        suggested_title
        and len(words_from_text(suggested_title)) >= 4
        and len(suggested_title) <= 52
        and public_editorial_topic_ok(
            theme,
            suggested_title,
            topic_terms=clip.get("topic_fingerprint") or [suggested_title],
            allow_short_topic=False,
        )
        and topic_supported_by_clip(suggested_title, clip)
    ):
        return suggested_title

    phrase = phrase_from_topic_terms(theme, clip, terms)
    source_topic = source_title_topic(clip.get("source_title", ""), theme=theme)

    if theme == "comedy" and phrase:
        if topic_supported_by_clip(phrase, clip) and public_editorial_topic_ok(theme, phrase, topic_terms=terms):
            return compact_text(phrase, 54)

    if (
        source_topic
        and topic_supported_by_clip(source_topic, clip)
        and public_editorial_topic_ok(theme, source_topic, topic_terms=terms)
    ):
        return source_topic

    if phrase:
        if topic_supported_by_clip(phrase, clip) and public_editorial_topic_ok(theme, phrase, topic_terms=terms):
            return compact_text(phrase, 54)

    text = clean_viewer_text(clip.get("transcript_excerpt", ""))
    counts = {}

    for word in words_from_text(text):
        normalized = word.strip("'").replace("'", "")

        if normalized in WEAK_TOPIC_WORDS or len(normalized) < 4:
            continue

        counts[normalized] = counts.get(normalized, 0) + 1

    ranked = sorted(counts, key=lambda word: (-counts[word], word))

    if ranked:
        fallback = compact_text(" ".join(ranked[:3]).title(), 54)

        if topic_supported_by_clip(fallback, clip) and public_editorial_topic_ok(theme, fallback, topic_terms=terms):
            return fallback

    source_subject = source_subject_from_title(clip.get("source_title", ""))

    if (
        source_subject
        and topic_supported_by_clip(source_subject, clip)
        and public_editorial_topic_ok(theme, source_subject, topic_terms=terms)
    ):
        return compact_text(source_subject, 54)

    return "The Standout Moment"


def group_clips_by_topic(clips, theme=""):
    groups = {}

    for clip in clips:
        if not clip_is_editorial_usable(clip):
            continue

        topic = topic_label_from_clip(clip, theme=theme)

        if topic == "The Standout Moment" or not topic_supported_by_clip(topic, clip):
            continue

        if not public_editorial_topic_ok(
            theme,
            topic,
            topic_terms=clip.get("topic_fingerprint") or [topic],
            allow_short_topic=False,
        ):
            continue

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


def source_keys_from_clips(theme, clips):
    keys = []

    for clip in clips or []:
        key = clip_state_key(theme, clip)

        if key and key not in keys:
            keys.append(key)

    return keys


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


def popular_segment_publishable_copy(theme, item):
    title, topic, topic_terms = popular_segment_public_title(theme, item)
    script = build_popular_segment_script(theme, item)

    if not social_title_is_publishable(theme, title, topic_terms=topic_terms):
        return False

    if re.search(r"^needs\s+specific\s+", title, flags=re.I):
        return False

    if not public_hook_script_ok(script, topic):
        return False

    return True


def popular_segment_title_candidates(theme, topic, source_title, channel, clip, signal_source):
    transcript = clean_viewer_text(clip.get("transcript_excerpt", ""))
    transcript_l = transcript.lower()
    source_l = clean_viewer_text(source_title).lower()
    repaired_candidates = []

    if "kevin levrone" in (transcript_l + " " + source_l) and "training" in (transcript_l + " " + source_l):
        repaired_candidates.append("Exercise Scientist Reviews Kevin Levrone's Training")

    if "iran" in transcript_l and "nuclear weapon" in transcript_l and "has changed" in transcript_l:
        repaired_candidates.append("Trump's Iran Line Hasn't Changed")

    if "iran" in transcript_l and "un" in transcript_l and "clown show" in transcript_l:
        repaired_candidates.append("Iran's UN Seat Became the Clown Show")

    if "brad lander" in transcript_l and "district 10" in transcript_l:
        repaired_candidates.append("Brad Lander's NYC Upset Changed the Race")

    source_topic = source_title_topic(source_title, theme)
    source_subject = source_subject_from_title(source_title)
    topic_quality = score_title_quality(
        theme,
        topic,
        topic_terms=[topic, source_title, channel],
    )
    topic_candidates = [
        build_social_title(theme, topic, content_format="popular", signal_source=signal_source),
        topic,
    ]
    source_candidates = []

    if source_topic:
        source_candidates.extend([
            source_topic,
            build_social_title(theme, source_topic, content_format="popular", signal_source=signal_source),
        ])

    if source_subject:
        source_candidates.append(source_subject)

    if topic_quality.get("dangling_title") or re.search(r"^needs\s+specific\s+", topic, flags=re.I):
        candidates = repaired_candidates + source_candidates + topic_candidates
    else:
        candidates = repaired_candidates + topic_candidates + source_candidates

    return unique_sequence(candidate for candidate in candidates if candidate)


def popular_segment_public_title(theme, item):
    clip = item.get("clip") or {}
    source_title = item.get("source_title") or clip.get("source_title") or "Podcast interview"
    channel = item.get("channel_label") or "Podcast Channel"
    raw_topic = clip.get("suggested_title") or clip_summary(clip, source_title)
    topic = clean_headline_topic(
        theme,
        raw_topic,
        clip=clip,
        source_title=source_title,
        channel=channel,
    )
    signal_source = popular_segment_signal_source(item)
    topic_terms = unique_sequence(
        [topic, source_title, channel]
        + [str(term).replace("_", " ") for term in (clip.get("topic_fingerprint") or [])]
    )

    for candidate in popular_segment_title_candidates(theme, topic, source_title, channel, clip, signal_source):
        title = sanitize_social_title(
            theme,
            candidate,
            topic,
            clip=clip,
            source_title=source_title,
            channel=channel,
            content_format="popular",
        )

        if not re.search(r"^needs\s+specific\s+", title, flags=re.I) and social_title_is_publishable(
            theme,
            title,
            topic_terms=topic_terms,
        ):
            return title, topic, topic_terms

    fallback = source_title_topic(source_title, theme) or topic
    return sanitize_social_title(
        theme,
        fallback,
        fallback,
        clip=clip,
        source_title=source_title,
        channel=channel,
        content_format="popular",
    ), topic, topic_terms


def popular_segment_items(theme, paths, rendered_clips):
    records = load_theme_source_records(theme)
    records_by_key = {record_state_key(theme, record): record for record in records}
    records_by_url = {record.get("video_url", ""): record for record in records}
    grouped = {}

    for clip in rendered_clips:
        if not clip.get("output_file") or not os.path.exists(clip.get("output_file", "")):
            continue

        if not clip_is_popular_segment_usable(clip):
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

    items = [item for item in items if popular_segment_publishable_copy(theme, item)]
    items = sorted(items, key=lambda item: item["sort_score"], reverse=True)

    if POPULAR_SEGMENTS_PER_THEME > 0:
        items = items[:POPULAR_SEGMENTS_PER_THEME]

    return items


def exhaustive_rendered_segment_items(theme, paths, rendered_clips):
    records = load_theme_source_records(theme)
    records_by_key = {record_state_key(theme, record): record for record in records}
    records_by_url = {record.get("video_url", ""): record for record in records}
    items = []
    seen = set()

    for clip in rendered_clips:
        output_file = clip.get("output_file") or ""

        if not output_file or not os.path.exists(output_file):
            continue

        if not clip_is_popular_segment_usable(clip):
            continue

        key = (
            clip_state_key(theme, clip),
            round(float(clip.get("start_time") or 0.0), 2),
            round(float(clip.get("end_time") or 0.0), 2),
        )

        if key in seen:
            continue

        seen.add(key)
        source_key = clip_state_key(theme, clip)
        source_record = records_by_key.get(source_key) or records_by_url.get(clip.get("source_video_url", "")) or {}
        popularity_score = enrich_clip_popularity(theme, paths, clip)
        items.append({
            "source_state_key": source_key,
            "source_title": clip.get("source_title") or source_record.get("title") or "Podcast interview",
            "source_video_url": clip.get("source_video_url") or source_record.get("video_url", ""),
            "channel_label": channel_label_for_record(source_record),
            "clip": clip,
            "popularity_score": popularity_score,
            "sort_score": popular_sort_score(clip),
            "thumbnail_file": download_youtube_thumbnail(paths, clip.get("source_video_url") or source_record.get("video_url", "")),
        })

    items = sorted(items, key=lambda item: item["sort_score"], reverse=True)

    if EXHAUST_RENDERED_MAX_CLIPS > 0:
        items = items[:EXHAUST_RENDERED_MAX_CLIPS]

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
    topic_groups = group_clips_by_topic(clips, theme=theme)[:EDITORIAL_COUNTDOWN_SIZE] or [topic_item]
    context = build_countdown_context(theme, paths, clips, topic_groups, adjective)
    attach_countdown_context(topic_groups, context)
    return context


PROMPT_LANGUAGE_LINE_PATTERN = re.compile(
    r"^\s*(?:voice(?:over)?|delivery|direction|tone|pacing|style|read|say)\s*:\s*",
    re.IGNORECASE,
)
PROMPT_LANGUAGE_PHRASES = [
    "clear social video host",
    "natural voice",
    "energetic but understandable",
    "natural pacing",
    "crisp consonants",
    "crisp consanants",
    "confident conversational delivery",
    "confident delivery",
    "no rushed delivery",
    "no rush dialogue",
    "no-rush dialogue",
]


def sanitize_spoken_narration_text(text, fallback_hook="this moment"):
    text = clean_viewer_text(text)
    if not text:
        return f"Number 1: {fallback_hook}."

    text = re.sub(r"\[[^\]]*(?:voice|delivery|pacing|consonants?|consanants?|dialogue)[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\([^\)]*(?:voice|delivery|pacing|consonants?|consanants?|dialogue)[^\)]*\)", " ", text, flags=re.IGNORECASE)

    cleaned_lines = []
    for raw_line in re.split(r"[\r\n]+", text):
        line = raw_line.strip()
        if not line:
            continue
        if PROMPT_LANGUAGE_LINE_PATTERN.search(line):
            line = PROMPT_LANGUAGE_LINE_PATTERN.sub("", line).strip()
        lower_line = line.lower()
        if any(phrase in lower_line for phrase in PROMPT_LANGUAGE_PHRASES) and not re.search(r"\bnumber\s+\d+\b", lower_line):
            continue
        for phrase in PROMPT_LANGUAGE_PHRASES:
            line = re.sub(re.escape(phrase), " ", line, flags=re.IGNORECASE)
        line = re.sub(r"\s*,\s*,+", ", ", line)
        line = re.sub(r"^\s*[,;:\-.]+\s*", "", line).strip()
        if line:
            cleaned_lines.append(line)

    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text).strip(" ,;:-")
    if not text:
        return f"Number 1: {fallback_hook}."
    if text[-1] not in ".!?":
        text += "."
    return text


def elevenlabs_tts_text(text):
    return sanitize_spoken_narration_text(text)


def atempo_filter_chain(tempo):
    tempo = max(1.0, float(tempo or 1.0))
    filters = []

    while tempo > 2.0:
        filters.append("atempo=2.000")
        tempo /= 2.0

    if tempo > 1.01:
        filters.append(f"atempo={tempo:.3f}")

    return filters


def process_narration_audio(input_path, scratch_dir, date_key, theme, rank):
    pitch = max(0.55, min(1.15, NARRATION_PITCH))
    raw_duration = max(0.1, get_duration(input_path))
    target_ceiling = max(
        2.8,
        EDITORIAL_INTRO_MAX_SECONDS
        - NARRATION_LEAD_IN_SECONDS
        - NARRATION_TAIL_PAD_SECONDS
        - INTRO_AUDIO_SAFETY_PAD_SECONDS,
    )
    target_duration = max(2.6, min(target_ceiling, NARRATION_TARGET_SECONDS))
    tempo = max(1.0, min(NARRATION_MAX_TEMPO, raw_duration / target_duration))
    output_path = os.path.join(scratch_dir, f"{date_key}_{theme}_{rank:02d}_intro_mastered.wav")

    needs_intro_pad = (
        NARRATION_LEAD_IN_SECONDS > 0.001
        or NARRATION_FADE_IN_SECONDS > 0.001
        or NARRATION_TAIL_PAD_SECONDS > 0.001
    )

    if abs(pitch - 1.0) < 0.01 and abs(NARRATION_BASS_GAIN) < 0.1 and tempo <= 1.01 and not needs_intro_pad:
        return input_path

    audio_filters = ["aresample=44100"]

    if abs(pitch - 1.0) >= 0.01:
        audio_filters.append(f"rubberband=pitch={pitch:.3f}")

    audio_filters.extend(atempo_filter_chain(tempo))

    if abs(NARRATION_BASS_GAIN) >= 0.1:
        audio_filters.append(f"bass=g={NARRATION_BASS_GAIN:.2f}:f=110:w=0.65")

    audio_filters.extend([
        "treble=g=-0.6:f=4200:w=0.8",
        "alimiter=limit=0.94",
        f"loudnorm=I={NARRATION_LOUDNESS_I:.1f}:TP=-1.5:LRA=8",
    ])

    if NARRATION_LEAD_IN_SECONDS > 0.001:
        delay_ms = int(round(NARRATION_LEAD_IN_SECONDS * 1000))
        audio_filters.append(f"adelay={delay_ms}:all=1")

    if NARRATION_FADE_IN_SECONDS > 0.001:
        fade_duration = NARRATION_LEAD_IN_SECONDS + NARRATION_FADE_IN_SECONDS
        audio_filters.append(f"afade=t=in:st=0:d={fade_duration:.3f}")

    if NARRATION_TAIL_PAD_SECONDS > 0.001:
        audio_filters.append(f"apad=pad_dur={NARRATION_TAIL_PAD_SECONDS:.3f}")

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
        print(f" -> Narration pitch filter unavailable; trying fit-and-master fallback: {error}")

    fallback_filters = ["aresample=44100"]

    fallback_filters.extend(atempo_filter_chain(tempo))

    if abs(NARRATION_BASS_GAIN) >= 0.1:
        fallback_filters.append(f"bass=g={NARRATION_BASS_GAIN:.2f}:f=110:w=0.65")

    fallback_filters.extend([
        "treble=g=-0.6:f=4200:w=0.8",
        "alimiter=limit=0.94",
        f"loudnorm=I={NARRATION_LOUDNESS_I:.1f}:TP=-1.5:LRA=8",
    ])

    if NARRATION_LEAD_IN_SECONDS > 0.001:
        delay_ms = int(round(NARRATION_LEAD_IN_SECONDS * 1000))
        fallback_filters.append(f"adelay={delay_ms}:all=1")

    if NARRATION_FADE_IN_SECONDS > 0.001:
        fade_duration = NARRATION_LEAD_IN_SECONDS + NARRATION_FADE_IN_SECONDS
        fallback_filters.append(f"afade=t=in:st=0:d={fade_duration:.3f}")

    if NARRATION_TAIL_PAD_SECONDS > 0.001:
        fallback_filters.append(f"apad=pad_dur={NARRATION_TAIL_PAD_SECONDS:.3f}")

    try:
        run_subprocess([
            FFMPEG_EXE,
            "-y",
            "-i", input_path,
            "-af", ",".join(fallback_filters),
            "-ar", "44100",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            output_path,
        ], "Narration fit and mastering")
        return output_path
    except Exception as fallback_error:
        print(f" -> Narration mastering unavailable; using raw voiceover: {fallback_error}")
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
    text = sanitize_spoken_narration_text(text)

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


THEME_TITLE_NOUNS = {
    "comedy": "Comedy",
    "sports": "Sports",
    "gaming": "Gaming",
    "finance": "Business",
    "technology_ai": "AI",
    "health_fitness": "Wellness",
    "politics": "Politics",
    "truecrime": "True Crime",
    "popculture": "Culture",
}
NON_SPEAKER_VISUAL_THEMES = {"politics", "truecrime", "sports", "gaming", "popculture"}


def editorial_title_topic(topic):
    cleaned = compact_text(clean_viewer_text(topic).strip(" .!?"), 62)
    cleaned = re.sub(r"^(editor pick|timestamp-backed|viewers replayed)\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+from\s+[a-zA-Z0-9 ._-]{2,40}$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^watch\s*:\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^what\s+watch\s*:\s*", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^what\s+(.+?)\s+reveals\s+about\s+the\s+market$", r"\1", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^why\s+investors\s+are\s+watching\s+(.+)$", r"\1", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^the\s+business\s+risk\s+hidden\s+in\s+(.+)$", r"\1", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^what\s+(?=[A-Z])", "", cleaned).strip()
    cleaned = re.sub(r"\s+reveals(?:\s+market)?$", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"\btold the story behind.*$", "", cleaned, flags=re.I).strip()
    cleaned = cleaned.replace("'S", "'s").replace("’S", "'s")
    cleaned = re.sub(r"^(the\s+)?context\s+behind\s+", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^(the\s+)?ai\s+problem\s+behind\s+", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^(the\s+)?health\s+mistake\s+behind\s+", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"^why\s+(.+?)\s+matters(?:\s+for\s+your\s+body)?$", r"\1", cleaned, flags=re.I).strip()
    cleaned = re.sub(
        r":\s+the\s+(investor\s+takeaway|health\s+detail(?:\s+to\s+rethink)?|habit\s+to\s+rethink|builder\s+takeaway|builder\s+debate|story\s+people\s+will\s+debate|detail\s+that\s+changes\s+the\s+case|sports\s+debate)$",
        "",
        cleaned,
        flags=re.I,
    ).strip()
    cleaned = re.sub(r"\b(And|Or|But|With|For|On|To|From|Into|About|Behind|Inside)$", "", cleaned).strip(" -:,.")

    cleaned = fix_topic_case(cleaned)

    if not cleaned or (looks_like_raw_dialogue_topic(cleaned) and not short_topic_phrase_ok(cleaned)):
        return "The Standout Moment"

    return cleaned


def clean_headline_topic(theme, topic, clip=None, source_title="", channel=""):
    clip = clip or {}
    theme_key = str(theme or "").strip().lower()
    source_title = source_title or clip.get("source_title", "")
    channel = clean_viewer_text(channel)
    candidates = [
        topic,
        transcript_topic_phrase(theme, clip),
        phrase_from_topic_terms(theme, clip, clip_topic_terms(clip)),
        source_context_title(theme, source_title, clip, clip.get("topic_fingerprint") or []),
        source_title_topic(source_title, theme),
        clean_viewer_text(clip.get("suggested_title", "")),
        source_subject_from_title(source_title),
    ]

    for candidate in candidates:
        cleaned = editorial_title_topic(candidate)

        if channel:
            cleaned = re.sub(rf"\s+from\s+{re.escape(channel)}$", "", cleaned, flags=re.I).strip()

        cleaned = compact_text(cleaned.replace("'S", "'s").replace("’S", "'s"), 58)
        cleaned = strengthen_topic_with_source_subject(theme, cleaned, source_title)

        if theme_key == "politics":
            cleaned_l = cleaned.lower()

            if "ai spending" in cleaned_l or ("ai" in cleaned_l and "spending" in cleaned_l):
                return "AI Spending Becomes A Policy Fight"

        if (
            cleaned
            and cleaned != "The Standout Moment"
            and (not clip or topic_supported_by_clip(cleaned, clip))
            and public_editorial_topic_ok(
                theme,
                cleaned,
                topic_terms=clip.get("topic_fingerprint") or [cleaned],
            )
        ):
            return cleaned

    return "The Standout Moment"


def theme_specific_direct_title(theme_key, topic):
    topic = editorial_title_topic(topic)
    lower = topic.lower()

    if not topic or topic.lower() in {"the standout moment", "standout moment"}:
        return ""

    if topic_phrase_is_keyword_soup(theme_key, topic):
        return ""

    if theme_key == "comedy":
        if "magnus" in lower and "rivalry" in lower:
            return "Magnus Carlsen's Rivalry Story"
        if "magnus" in lower:
            return "Magnus Carlsen's Chess Story"

    if theme_key == "sports":
        if "kyle larson" in lower or "nascar" in lower:
            return "Kyle Larson's NASCAR Take"
        return topic if public_editorial_topic_ok("sports", topic, topic_terms=[topic], allow_short_topic=False) else ""

    if theme_key == "gaming":
        if "optic" in lower:
            return "OpTic's Gaming Room Take"
        if "valorant" in lower:
            return "The Valorant Take Players Will Debate"
        if "cod" in lower or "call of duty" in lower:
            return "The COD Take That Split The Desk"
        if public_editorial_topic_ok("gaming", topic, topic_terms=[topic], allow_short_topic=False):
            return topic

    if theme_key == "finance":
        if "rental cash flow" in lower:
            return "Rental Cash Flow Still Has A Catch"
        if "inflation floor" in lower:
            return "Inflation Floor Is Back In Focus"
        if "debt" in lower and "rates" in lower:
            return "Debt And Rates Are Back In Focus"
        if "spacex" in lower:
            return topic if public_editorial_topic_ok("finance", topic, topic_terms=[topic], allow_short_topic=False) else ""

    if theme_key == "technology_ai":
        if "steam machine" in lower:
            return "Steam Machine Splits The Builder Room"
        if "data black hole" in lower:
            return "The AI Data Black Hole"

    if theme_key == "health_fitness":
        if "aging slower" in lower:
            return "Aging Slower Habits Worth Knowing"
        if "amino" in lower:
            return "Essential Amino Acids Are The Missing Detail"
        if "strength training" in lower or "lifts" in lower:
            return "Strength Training Lifts Worth Rethinking"
        if "abs" in lower:
            return "The Abs Mistake Worth Rethinking"
        if "fertility" in lower:
            return "Fertility Warning Signs Worth Hearing"

    if theme_key == "popculture":
        if "jackass" in lower and "movie" in lower:
            return "The Jackass Movie Debate"
        if public_editorial_topic_ok("popculture", topic, topic_terms=[topic], allow_short_topic=False):
            return topic

    if theme_key == "truecrime":
        if public_editorial_topic_ok("truecrime", topic, topic_terms=[topic], allow_short_topic=False):
            return topic

    if public_editorial_topic_ok(theme_key, topic, topic_terms=[topic], allow_short_topic=False):
        quality = score_title_quality(theme_key, topic, topic_terms=[topic])

        if (
            quality.get("length_ok")
            and quality.get("honesty", 0.0) >= 0.70
            and quality.get("specificity", 0.0) >= 0.44
            and not quality.get("generic_title")
            and not quality.get("mechanical_title")
            and quality.get("theme_native_title", True)
            and quality.get("not_clickbait", True)
        ):
            return topic

    return ""


def build_social_title(theme, topic, content_format="countdown", signal_source=""):
    topic = editorial_title_topic(topic)
    theme_key = str(theme or "").strip().lower()
    popular = content_format == "popular"
    signal_is_external = signal_source and signal_source != "internal_quality_fallback"
    topic_words = title_words(topic)
    topic_terms = [topic]
    topic_l = topic.lower()

    if topic_phrase_is_keyword_soup(theme_key, topic):
        return "Needs Specific Editorial Title"

    if theme_key == "politics" and ("ai spending" in topic_l or ("ai" in topic_l and "spending" in topic_l)):
        return "AI Spending Becomes A Policy Fight"

    direct_title = theme_specific_direct_title(theme_key, topic)

    if direct_title:
        return compact_text(direct_title, 92)

    topic_quality = score_title_quality(theme, topic, topic_terms=topic_terms)

    if (
        len(topic_words) >= 3
        and public_editorial_topic_ok(theme, topic, topic_terms=topic_terms, allow_short_topic=False)
        and title_passes_publishable_bar(theme, topic, topic_terms=topic_terms, min_specificity=0.40)
        and topic_quality.get("honesty", 0.0) >= 0.72
        and not topic_quality.get("generic_title")
        and not topic_quality.get("mechanical_title")
        and not topic_quality.get("repetitive_title")
        and topic_quality.get("theme_native_title", True)
    ):
        return compact_text(topic, 92)

    if (
        theme_key == "finance"
        and len(topic_words) >= 4
        and re.search(r"\b(are|is|was|were|will|can|could|has|have)\b", topic, flags=re.I)
        and title_passes_publishable_bar(theme, topic, topic_terms=topic_terms, min_specificity=0.38)
    ):
        return compact_text(topic, 92)

    patterns = {
        "comedy": [
            "{topic} Gets Weird Fast",
            "{topic} Became The Punchline",
        ],
        "sports": [
            "{topic} Changed The Game",
            "{topic} Became The Locker Room Debate",
        ],
        "gaming": [
            "{topic} Has Gamers Arguing",
            "{topic} Became The Creator Debate",
        ],
        "finance": [
            "Why {topic} Changes The Math",
            "{topic} Is Back In Focus",
        ],
        "technology_ai": [
            "Why Builders Are Debating {topic}",
            "{topic} Is The AI Question",
        ],
        "health_fitness": [
            "Why {topic} Is Worth Rethinking",
            "{topic} Changes The Health Advice",
        ],
        "politics": [
            "{topic} Became The Policy Fight",
            "Why {topic} Has Everyone Arguing",
        ],
        "truecrime": [
            "Investigators Focused On {topic}",
            "Why {topic} Matters In The Case",
        ],
        "popculture": [
            "{topic} Took Over The Conversation",
            "Why Fans Are Talking About {topic}",
        ],
    }
    template_pool = patterns.get(theme_key, ["The Moment Inside {topic}"])

    if popular and signal_is_external:
        external_patterns = {
            "sports": "{topic}: The Take That Changed The Debate",
            "finance": "{topic}: The Catch Investors Should Hear",
            "gaming": "{topic}: The Take That Changed The Match",
            "technology_ai": "{topic}: The Limit Builders Should Hear",
            "truecrime": "{topic}: The Detail That Changes The Read",
        }
        template = external_patterns.get(theme_key)

        if template:
            title = compact_text(template.format(topic=topic), 92)

            if title_passes_publishable_bar(theme, title, topic_terms=topic_terms, min_specificity=0.38):
                return title

    for template in template_pool:
        if "{topic} {topic}" in template:
            continue

        title = compact_text(template.format(topic=topic), 92)

        if topic.lower() in {"the standout moment", "standout moment"}:
            continue

        if (
            not re.search(r"\b(split the room)\b.*\b(split the room)\b", title, flags=re.I)
            and title_passes_publishable_bar(theme, title, topic_terms=topic_terms, min_specificity=0.38)
        ):
            return title

    if public_editorial_topic_ok(theme, topic, topic_terms=topic_terms, allow_short_topic=False):
        return compact_text(topic, 92)

    theme_fallbacks = {
        "comedy": "Needs Specific Comedy Title",
        "sports": "Needs Specific Sports Title",
        "gaming": "Needs Specific Gaming Title",
        "finance": "Needs Specific Finance Title",
        "technology_ai": "Needs Specific AI Title",
        "health_fitness": "Needs Specific Health Title",
        "politics": "Needs Specific Politics Title",
        "truecrime": "Needs Specific True Crime Title",
        "popculture": "Needs Specific Culture Title",
    }
    return theme_fallbacks.get(theme_key, "Needs Specific Editorial Title")


def social_title_is_publishable(theme, title, topic_terms=None):
    title_text = clean_viewer_text(title)
    quality = score_title_quality(theme, title, topic_terms=topic_terms or [title])
    keyword_soup = topic_phrase_is_keyword_soup(theme, title_text)
    keyword_soup_ok = (
        keyword_soup
        and quality.get("honesty", 0.0) >= 0.82
        and quality.get("specificity", 0.0) >= 0.78
        and quality.get("theme_native_title", True)
        and not quality.get("generic_title")
        and not quality.get("raw_dialogue_fragment")
    )
    return (
        bool(title_text)
        and
        quality.get("length_ok", True)
        and quality.get("honesty", 0.0) >= 0.70
        and quality.get("specificity", 0.0) >= 0.40
        and not editorial_title_has_generic_pattern(title_text)
        and (not keyword_soup or keyword_soup_ok)
        and not re.search(r"\b(the|a|an)\s+(changes|missed|debating|watching)\s+(the|a|an)\b", title_text, flags=re.I)
        and not re.search(r"\bpop\s+culture\s+missed\b", title_text, flags=re.I)
        and not re.search(r"^the\s+builders\s+are\s+debating$", title_text, flags=re.I)
        and not quality.get("generic_title")
        and not quality.get("raw_dialogue_fragment")
        and not quality.get("mechanical_title")
        and not quality.get("repetitive_title")
        and not quality.get("weak_template_title")
        and not quality.get("keyword_soup_title")
        and not quality.get("overlong_title")
        and not quality.get("dangling_title")
        and not quality.get("asr_sentence_title")
        and quality.get("theme_native_title", True)
        and quality.get("not_clickbait", True)
        and not re.search(r"^needs\s+specific\s+", str(title or ""), flags=re.I)
    )


def sanitize_social_title(theme, title, topic, clip=None, source_title="", channel="", content_format="countdown"):
    clip = clip or {}
    theme_key = str(theme or "").strip().lower()
    topic = clean_headline_topic(theme, topic, clip=clip, source_title=source_title, channel=channel)
    topic_terms = unique_sequence(
        [topic, source_title, channel]
        + [str(term).replace("_", " ") for term in (clip.get("topic_fingerprint") or [])]
    )

    if social_title_is_publishable(theme, title, topic_terms=topic_terms):
        return compact_text(title, 92)

    candidates = []
    source_topic = source_title_topic(source_title, theme)
    source_subject = source_subject_from_title(source_title)

    if source_topic:
        candidates.extend([
            source_topic,
            build_social_title(theme, source_topic, content_format=content_format),
        ])

    if source_subject:
        candidates.append(source_subject)

    if topic and topic != "The Standout Moment":
        candidates.extend([
            topic,
            build_social_title(theme, topic, content_format=content_format),
        ])

    suggested_title = clean_viewer_text(clip.get("suggested_title", ""))
    if suggested_title:
        candidates.append(suggested_title)

    for candidate in unique_sequence(candidates):
        candidate = compact_text(clean_viewer_text(candidate), 92)

        if not candidate or re.search(r"^needs\s+specific\s+", candidate, flags=re.I):
            continue

        if social_title_is_publishable(theme, candidate, topic_terms=topic_terms + [candidate]):
            return candidate

    fallback_label = THEME_TITLE_NOUNS.get(theme_key, "Editorial")
    return f"Needs Specific {fallback_label} Title"


def social_title_key(title):
    words = [
        word
        for word in re.findall(r"[a-zA-Z0-9]+", clean_viewer_text(title).lower())
        if word and word not in {"the", "a", "an"}
    ]
    return " ".join(words)


def package_youtube_title(package):
    youtube = (package.get("platforms") or {}).get("youtube_shorts") or {}
    return clean_viewer_text(youtube.get("title") or package.get("title") or "")


def set_package_public_title(package, title):
    title = compact_text(clean_viewer_text(title), 100)
    package["title"] = title
    package.setdefault("platforms", {}).setdefault("youtube_shorts", {})["title"] = title[:100]
    package["title_quality"] = score_title_quality(
        package.get("theme", ""),
        title,
        topic_terms=[
            ((package.get("content_signal") or {}).get("topic") or title),
            package.get("source_title", ""),
            package.get("source_channel", ""),
        ],
    )
    package.setdefault("rank_signals", {})["title_quality"] = package["title_quality"]
    return package


def package_title_alternatives(theme, package):
    signal = package.get("content_signal") or {}
    topic = clean_headline_topic(
        theme,
        signal.get("topic") or package.get("caption") or package.get("title", ""),
        clip={
            "suggested_title": package.get("title", ""),
            "source_title": package.get("source_title", ""),
            "source_channel": package.get("source_channel", ""),
            "topic_fingerprint": package.get("tags", []),
            "transcript_excerpt": package.get("transcript_excerpt", ""),
        },
        source_title=package.get("source_title", ""),
        channel=package.get("source_channel", ""),
    )
    source_title = package.get("source_title", "")
    source_topic = source_title_topic(source_title, theme)
    source_subject = source_subject_from_title(source_title)
    content_format = "popular" if package.get("content_format") == "popular_segment_short" else "countdown"
    candidates = [
        package_youtube_title(package),
        topic,
        build_social_title(theme, topic, content_format=content_format),
        source_topic,
        build_social_title(theme, source_topic, content_format=content_format) if source_topic else "",
    ]

    if source_subject and topic and source_subject.lower() not in topic.lower():
        candidates.extend([
            compact_text(f"{source_subject}: {topic}", 92),
            compact_text(f"{possessive_subject(source_subject)} {topic}", 92),
        ])

    return unique_sequence(candidates)


def enforce_unique_package_titles(theme, packages, existing_metadata=None):
    existing_metadata = existing_metadata or {}
    used = set()

    for collection in ("content", "archive"):
        for item in existing_metadata.get(collection) or []:
            key = social_title_key(package_youtube_title(item))
            if key:
                used.add(key)

    for package in packages:
        current_title = package_youtube_title(package)
        current_key = social_title_key(current_title)

        if current_key and current_key not in used:
            used.add(current_key)
            continue

        for candidate in package_title_alternatives(theme, package):
            candidate = sanitize_social_title(
                theme,
                candidate,
                (package.get("content_signal") or {}).get("topic") or candidate,
                clip={
                    "suggested_title": package.get("title", ""),
                    "source_title": package.get("source_title", ""),
                    "source_channel": package.get("source_channel", ""),
                    "topic_fingerprint": package.get("tags", []),
                    "transcript_excerpt": package.get("transcript_excerpt", ""),
                },
                source_title=package.get("source_title", ""),
                channel=package.get("source_channel", ""),
                content_format="popular" if package.get("content_format") == "popular_segment_short" else "countdown",
            )
            key = social_title_key(candidate)

            if key and key not in used and social_title_is_publishable(theme, candidate, topic_terms=[candidate]):
                set_package_public_title(package, candidate)
                used.add(key)
                break

        else:
            if current_key:
                used.add(current_key)

    return packages


def build_social_caption(theme_label, topic, adjective="", countdown_slot=None, content_format="countdown", source_title=""):
    topic = editorial_title_topic(topic)

    if content_format == "popular":
        theme_key = str(theme_label or "").strip().lower().replace(" ", "_")
        caption_patterns = {
            "crime_legal": [
                "{topic}, with the context that makes the case feel different.",
                "{topic}. The short clip gives the detail room to land.",
                "{topic}. A clean case detail, shown with the original context.",
            ],
            "finance": [
                "{topic}. The clip explains the catch without burying the point.",
                "{topic}, framed around the part that changes the math.",
                "{topic}. A short market/business moment with the context intact.",
            ],
            "comedy": [
                "{topic}. The setup is quick, and the turn does the work.",
                "{topic}. A short joke moment with the payoff left intact.",
                "{topic}. The clip keeps the room reaction and the turn together.",
            ],
            "sports": [
                "{topic}. The clip keeps the debate and reaction together.",
                "{topic}. A short sports moment with the context still attached.",
                "{topic}. The take lands because the reaction is included.",
            ],
            "gaming": [
                "{topic}. The clip keeps the take and reaction in one piece.",
                "{topic}. A short gaming moment with the context still attached.",
                "{topic}. The argument works because the setup stays in.",
            ],
            "tech_ai": [
                "{topic}. The clip keeps the technical point clear and short.",
                "{topic}. A quick builder moment with the limitation included.",
                "{topic}. The point lands because the context stays in.",
            ],
            "wellness": [
                "{topic}. The clip keeps the practical health context intact.",
                "{topic}. A short wellness moment with the useful detail included.",
                "{topic}. The advice works because the setup stays in.",
            ],
            "politics": [
                "{topic}. The clip keeps the claim and context together.",
                "{topic}. A short policy moment with the messy part included.",
                "{topic}. The argument lands because the context stays in.",
            ],
            "pop_culture": [
                "{topic}. The clip keeps the answer and reaction together.",
                "{topic}. A short culture moment with the turn left intact.",
                "{topic}. The moment works because the reaction stays in.",
            ],
        }
        patterns = caption_patterns.get(theme_key) or [
            "{topic}. The clip keeps the setup and payoff together.",
            "{topic}. A short moment with the context still attached.",
            "{topic}. The point lands because the setup stays in.",
        ]
        return compact_text(
            patterns[title_variant_index(theme_label, topic, source_title, count=len(patterns))].format(topic=topic),
            160,
        )

    slot_text = f"Number {countdown_slot}: " if countdown_slot else ""
    caption_patterns = [
        f"{slot_text}{topic}. The moment that made the cut.",
        f"{slot_text}{topic}. Short setup, real payoff.",
        f"{slot_text}{topic}. The clip says more than the headline.",
    ]
    return compact_text(caption_patterns[title_variant_index(theme_label, topic, countdown_slot, count=len(caption_patterns))], 160)


def countdown_heading(theme, adjective, total_count):
    adjective_text = str(adjective or "best").replace("_", " ").upper()

    if int(total_count or 0) <= 1:
        theme_key = str(theme or "").strip().lower()
        theme_noun = THEME_TITLE_NOUNS.get(theme_key, theme_key.replace("_", " ").title() or "Interview")
        return compact_text(f"THE {adjective_text} {theme_noun.upper()} MOMENT THIS WEEK", 96)

    return compact_text(f"TOP {int(total_count)} {adjective_text} MOMENTS THIS WEEK", 96)


def normalized_topic_words(topic):
    cleaned = editorial_title_topic(topic)
    return {
        word
        for word in words_from_text(cleaned)
        if len(word) >= 4 and word not in WEAK_TOPIC_WORDS
    }


def topics_overlap(left, right):
    left_words = normalized_topic_words(left)
    right_words = normalized_topic_words(right)

    if not left_words or not right_words:
        return False

    overlap = left_words & right_words
    needed = 1 if min(len(left_words), len(right_words)) <= 2 else 2
    return len(overlap) >= needed


def popular_item_duplicates_countdown(theme, item, countdown_packages):
    clip = item.get("clip") or {}
    source_url = clip.get("source_video_url") or item.get("source_video_url") or ""
    item_topic = clean_headline_topic(
        theme,
        clip.get("suggested_title") or clip_summary(clip, item.get("source_title") or ""),
        clip=clip,
        source_title=item.get("source_title", ""),
        channel=item.get("channel_label", ""),
    )

    for package in countdown_packages:
        package_url = package.get("source_video_url") or ""

        if source_url and package_url and source_url != package_url:
            continue

        package_topic = (
            (package.get("content_signal") or {}).get("topic")
            or package.get("title")
            or ""
        )

        if topics_overlap(item_topic, package_topic):
            return True

    return False


def title_variant_index(*values, count=1):
    seed = "|".join(str(value or "") for value in values)
    return sum(ord(char) for char in seed) % max(1, count)


def build_theme_native_editorial_title(theme, topic, adjective, countdown_slot, total_count, is_recap=False):
    theme_key = str(theme or "").strip().lower()
    theme_noun = THEME_TITLE_NOUNS.get(theme_key, theme_key.replace("_", " ").title() or "Interview")
    topic_text = editorial_title_topic(topic)
    topic_text = re.sub(r"^the\s+", "", topic_text, flags=re.I)
    adjective_text = str(adjective or "best").replace("_", " ").title()
    period_text = period_label().title()

    if is_recap:
        patterns = {
            "comedy": [
                "{theme} Interviews: {adjective} Laughs From {period}",
                "{adjective} Comedy Signals From {period}",
            ],
            "sports": [
                "{adjective} Sports Debates From {period}",
                "{theme} Interviews: The Stories That Moved The Board",
            ],
            "finance": [
                "{adjective} Business Signals From {period}",
                "{theme} Interviews: The Operator Notes From {period}",
            ],
            "technology_ai": [
                "{adjective} AI Builder Signals From {period}",
                "{theme} Interviews: The Product Questions From {period}",
            ],
            "health_fitness": [
                "{adjective} Wellness Takeaways From {period}",
                "{theme} Interviews: Practical Health Signals From {period}",
            ],
            "politics": [
                "{adjective} Politics Context From {period}",
                "{theme} Interviews: The Claims Worth Reviewing",
            ],
            "truecrime": [
                "{adjective} Case Moments From {period}",
                "{theme} Interviews: Testimony Worth Context",
            ],
            "popculture": [
                "{adjective} Culture Reveals From {period}",
                "{theme} Interviews: The Guest Moments That Landed",
            ],
        }
        template_pool = patterns.get(theme_key, ["{adjective} {theme} Interview Signals From {period}"])
        template = template_pool[title_variant_index(theme, adjective, period_text, count=len(template_pool))]
        return compact_text(template.format(theme=theme_noun, adjective=adjective_text, period=period_text), 96)

    return build_social_title(theme, topic_text, content_format="countdown")


def compact_spoken_topic(text, max_length=58):
    text = re.sub(r"\s+", " ", clean_viewer_text(text)).strip(" .")

    if len(text) <= max_length:
        return text

    shortened = text[:max_length].rsplit(" ", 1)[0].strip(" ,.;:-")
    return shortened or text[:max_length].strip(" ,.;:-")


def spoken_hook_topic(topic, clip=None):
    clip = clip or {}
    candidate = (
        topic
        or clip.get("suggested_title")
        or clip.get("topic")
        or clip_summary(clip, clip.get("source_title") or "this moment")
    )
    candidate = editorial_title_topic(candidate)
    candidate = re.sub(
        r"^[A-Z][A-Za-z0-9'.-]+(?:\s+[A-Z][A-Za-z0-9'.-]+){0,3}\s+"
        r"(tells|explains|reveals|shares|breaks down|admits|describes|questions)\s+",
        "",
        candidate,
        flags=re.I,
    )
    return compact_spoken_topic(candidate, 58) or "this moment"


def natural_spoken_hook_topic(topic, clip=None):
    topic_text = spoken_hook_topic(topic, clip)
    topic_text = re.sub(r"^The\s+", "the ", topic_text)
    topic_text = re.sub(r"^A\s+", "a ", topic_text)
    topic_text = re.sub(r"^An\s+", "an ", topic_text)
    return topic_text


def spoken_hook_topic_is_vague(topic):
    lower = re.sub(r"\s+", " ", str(topic or "").strip().lower())
    words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", lower)
    meaningful = [
        word
        for word in words
        if word not in {
            "the", "a", "an", "this", "that", "moment", "detail", "part",
            "case", "story", "question", "clip", "standout", "thing",
        }
    ]
    return (
        not lower
        or lower in {"this detail", "that detail", "this moment", "that moment", "the standout moment"}
        or len(meaningful) == 0
    )


def repaired_spoken_hook_topic(theme, topic, clip=None):
    clip = clip or {}
    hook_topic = natural_spoken_hook_topic(topic, clip)

    if not spoken_hook_topic_is_vague(hook_topic):
        return hook_topic

    source_title = clip.get("source_title", "")
    repair_candidates = [
        transcript_topic_phrase(theme, clip),
        phrase_from_topic_terms(theme, clip, clip_topic_terms(clip)),
        source_title_topic(source_title, theme),
        source_subject_from_title(source_title),
        clip_summary(clip, source_title or "this moment"),
    ]

    for candidate in repair_candidates:
        repaired = natural_spoken_hook_topic(candidate, clip)

        if not spoken_hook_topic_is_vague(repaired):
            return compact_text(repaired, 44).strip(" .")

    return hook_topic


def concise_intro_hook_topic(theme, topic, clip=None, max_length=48):
    hook_topic = repaired_spoken_hook_topic(theme, topic, clip)
    hook_topic = re.sub(r"^(the|a|an)\s+", "", hook_topic, flags=re.I).strip()
    hook_topic = compact_spoken_topic(hook_topic, max_length)
    return hook_topic or "this moment"


SCRIPT_TOPIC_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "your", "this",
    "that", "moment", "clip", "part", "detail", "question", "inside",
    "around", "behind", "worth", "people", "case", "story", "read",
}

VAGUE_PUBLIC_SCRIPT_PATTERNS = [
    r"\bthis\s+(detail|moment|part)\s+changes\b",
    r"\bthis\s+changes\s+the\s+read\b",
    r"\bthe\s+case\s+sounds\s+one\s+way\b",
    r"\bthe\s+quiet\s+part\s+is\s+(this|that|the\s+detail|the\s+moment)\b",
    r"\bthe\s+setup\s+sounds\s+simple\b",
    r"\bwhy\s+this\s+made\s+the\s+cut\b",
]


def script_topic_words(topic):
    return [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", str(topic or "").lower())
        if word not in SCRIPT_TOPIC_STOPWORDS and len(word) >= 3
    ]


def public_hook_script_ok(script, topic):
    lower = str(script or "").strip().lower()
    if not lower:
        return False

    words = re.findall(r"[a-zA-Z0-9']+", lower)
    concise_intro = bool(re.match(r"^(number\s+\d+|standout)\s*:", lower))

    if len(words) < (5 if concise_intro else 7):
        return False

    if any(re.search(pattern, lower) for pattern in VAGUE_PUBLIC_SCRIPT_PATTERNS):
        return False

    topic_words = script_topic_words(topic)
    if topic_words and not any(word in lower for word in topic_words[:5]):
        return False

    return True


def build_moment_hook_script(theme, topic, adjective, clip=None, signal_source=""):
    theme_key = str(theme or "").strip().lower()
    hook_topic = repaired_spoken_hook_topic(theme, topic, clip)
    if re.match(r"^(why|how|what|when|where)\b", hook_topic, flags=re.I):
        hook_topic = hook_topic[0].lower() + hook_topic[1:]

    if re.match(r"^(wildest|funniest|weirdest|strangest|biggest|best|worst|most)\b", hook_topic, flags=re.I):
        hook_topic = f"the {hook_topic}"
    adjective_text = compact_text(str(adjective or "best").replace("most ", ""), 22).lower()
    signal_source = str(signal_source or "").strip().lower()

    theme_templates = {
        "comedy": [
            "They thought WHAT about {topic}? Wait for the turn.",
            "This starts with {topic}, then the room loses the plot.",
            "The setup is {topic}. The payoff is why this made the cut.",
            "Watch how fast {topic} turns into the actual joke.",
        ],
        "finance": [
            "The money question is {topic}. The catch is the part worth hearing.",
            "This sounds like a normal take on {topic}, then the math changes.",
            "Here is the part of {topic} that most people skip.",
            "If {topic} sounds obvious, this is the wrinkle.",
        ],
        "health_fitness": [
            "The detail inside {topic} is the part people usually miss.",
            "{topic} sounds basic, then the health takeaway actually clicks.",
            "If {topic} feels obvious, listen for the one practical detail.",
            "This is the tiny {topic} point that changes the advice.",
        ],
        "politics": [
            "This is where the {topic} argument gets uncomfortable.",
            "The claim about {topic} sounds clean. The implication does not.",
            "Listen for the part that makes {topic} messy.",
            "This is the moment where {topic} stops being a talking point.",
        ],
        "popculture": [
            "The answer on {topic} sounds safe, then it swerves.",
            "This {topic} moment gets awkward faster than expected.",
            "This {topic} clip is the part fans are going to replay.",
            "The question is {topic}. The reaction is the clip.",
        ],
        "sports": [
            "This take on {topic} gets competitive fast.",
            "The {topic} debate starts calm, then the locker-room edge shows up.",
            "This is the part that makes the {topic} argument real.",
            "If {topic} is the take, the reaction tells you everything.",
        ],
        "gaming": [
            "This take on {topic} is exactly what gamers argue about.",
            "The gaming desk sounds calm on {topic}, but the take has teeth.",
            "This starts as {topic}, then turns into the real debate.",
            "If {topic} is the headline, the reaction is the real story.",
        ],
        "technology_ai": [
            "This take on {topic} is where the builder room splits.",
            "The tech point inside {topic} sounds small, then the bigger problem appears.",
            "This is where {topic} becomes the detail people argue about.",
            "If {topic} sounds like hype, listen for the limitation.",
        ],
        "truecrime": [
            "The key question is {topic}. Listen to how the detail gets handled.",
            "The case sounds one way, until {topic} lands.",
            "The evidence turns on {topic}. The next line is the part to catch.",
            "Watch how {topic} shifts what the officer focuses on.",
        ],
    }

    templates = theme_templates.get(theme_key) or [
        "{topic} sounds simple, then the real point lands.",
        "This starts with {topic}, then the clip turns.",
        "The setup is {topic}. The payoff is why this made the cut.",
    ]

    start_index = title_variant_index(theme_key, hook_topic, adjective_text, signal_source, count=len(templates))
    ordered_templates = templates[start_index:] + templates[:start_index]

    for template in ordered_templates:
        script = template.format(topic=hook_topic, adjective=adjective_text).strip()
        script = compact_text(script, 118).rstrip(".") + "."

        if public_hook_script_ok(script, hook_topic):
            return script

    fallback_scripts = {
        "comedy": "The setup is {topic}. Listen for the turn that makes the room react.",
        "finance": "The key money question is {topic}. The next part is the catch.",
        "health_fitness": "The useful health point is {topic}. Listen for the practical detail.",
        "politics": "The argument is {topic}. The next line is where it gets messy.",
        "popculture": "The question is {topic}. The reaction is what makes the clip work.",
        "sports": "The debate is {topic}. The reaction tells you why it matters.",
        "gaming": "The take is {topic}. Watch how quickly the room pushes back.",
        "technology_ai": "The builder question is {topic}. The limitation is the part to catch.",
        "truecrime": "The evidence question is {topic}. Listen to what changes in the search.",
    }
    script = fallback_scripts.get(theme_key, "The point is {topic}. Listen for the turn.").format(topic=hook_topic)
    return compact_text(script, 118).rstrip(".") + "."


def build_editorial_intro(theme, topic, rank, total_count, adjective, clip, countdown_slot=None):
    slot = int(countdown_slot or countdown_slot_for_rank(rank, total_count))
    hook_topic = concise_intro_hook_topic(theme, topic, clip, max_length=48)
    script = f"Number {slot}: {hook_topic}."

    if len(re.findall(r"[a-zA-Z0-9']+", script)) < 6:
        script = f"Number {slot}: {hook_topic}. Watch this."

    return script


def build_output_package(theme, output_path, source_clip, topic_item, rank, adjective, date_key, is_recap=False):
    profile = theme_profile(theme)
    theme_label = profile["label"]
    caption_style = profile.get("caption_style", "")
    overlay_style = profile.get("overlay_style", "")
    framing_style = profile.get("framing_style", "")
    best_clip = topic_item["clips"][0]
    underlying_source_state_keys = source_keys_from_clips(theme, topic_item.get("clips") or [best_clip])
    topic = clean_headline_topic(
        theme,
        topic_item["topic"],
        clip=best_clip,
        source_title=best_clip.get("source_title", ""),
        channel=best_clip.get("source_channel", ""),
    )
    total_count = int(topic_item.get("_total_count") or DAILY_TOPIC_COUNT)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    title = build_theme_native_editorial_title(
        theme,
        topic,
        adjective,
        countdown_slot,
        total_count,
        is_recap=is_recap,
    )
    title = sanitize_social_title(
        theme,
        title,
        topic,
        clip=best_clip,
        source_title=best_clip.get("source_title", ""),
        channel=best_clip.get("source_channel", ""),
        content_format="countdown",
    )
    description = build_social_caption(
        theme_label,
        topic,
        adjective=adjective,
        countdown_slot=countdown_slot,
        content_format="countdown",
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
    rank_signals = dict(best_clip.get("rank_signals") or {})
    rank_signals.update({
        "editorial_rank": rank,
        "countdown_slot": countdown_slot,
        "countdown_total": total_count,
        "editorial_adjective": adjective,
        "content_format": "daily_editorial_recap" if is_recap else "daily_editorial_short",
    })
    title_quality = score_title_quality(
        theme,
        title,
        topic_terms=[topic, best_clip.get("source_title", ""), rank_signals.get("source_channel", "")],
    )
    rank_signals["title_quality"] = title_quality
    experiment = best_clip.get("experiment") or {
        "experiment_id": f"{theme}_countdown_packaging",
        "variant": profile.get("overlay_style") or profile.get("label", theme),
        "hypothesis": "Theme-specific countdown packaging improves engaged view rate and channel session depth.",
    }

    return {
        "theme": theme,
        "content_format": "daily_editorial_recap" if is_recap else "daily_editorial_short",
        "content_has_burned_captions": True,
        "upload_ready_requires_burned_captions": True,
        "caption_style": caption_style,
        "overlay_style": overlay_style,
        "framing_style": framing_style,
        "editorial_date": date_key,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(source_clip) if source_clip else "",
        "source_state_key": f"{theme}|editorial|{date_key}|{rank}",
        "underlying_source_state_keys": underlying_source_state_keys,
        "source_video_url": best_clip.get("source_video_url", ""),
        "source_channel": rank_signals.get("source_channel", ""),
        "source_title": best_clip.get("source_title", ""),
        "clip_start_time": best_clip.get("start_time"),
        "clip_end_time": best_clip.get("end_time"),
        "title": title,
        "title_quality": title_quality,
        "caption": compact_text(description, 160),
        "hashtags": hashtags,
        "tags": tags,
        "description": compact_text(description, 320),
        "transcript_excerpt": best_clip.get("transcript_excerpt", ""),
        "hook_reason": f"daily {adjective} theme: {topic}",
        "score": topic_item.get("score", best_clip.get("score")),
        "readiness_score": best_clip.get("readiness_score"),
        "rank_signals": rank_signals,
        "experiment": experiment,
        "content_signal": {
            "type": "ranked_countdown_moment",
            "rank": rank,
            "countdown_slot": countdown_slot,
            "total_count": total_count,
            "topic": topic,
            "adjective": adjective,
            "theme_archetype": rank_signals.get("theme_archetype", ""),
            "popularity_source": rank_signals.get("popularity_source", ""),
            "popularity_score": rank_signals.get("popularity_score", 0),
            "source_channel": rank_signals.get("source_channel", ""),
            "source_title": best_clip.get("source_title", ""),
        },
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
                "privacy_status": YOUTUBE_PRIVACY_STATUS,
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


THEME_VISUAL_STYLES = {
    "comedy": {
        "accent": "0xFFD166",
        "accent2": "0xFF2E88",
        "cream": "0xFFF4B8",
        "mint": "0x4DE1FF",
        "blue": "0xB7FF5A",
        "dark": "0x20151E",
        "name": "comedy_arcade_countdown",
    },
    "sports": {
        "accent": "0xB7FF5A",
        "accent2": "0x23A6FF",
        "cream": "0xF8FFE8",
        "mint": "0x62FFD0",
        "blue": "0x23A6FF",
        "dark": "0x0F1D22",
        "name": "sports_scoreboard_countdown",
    },
    "gaming": {
        "accent": "0x00F5D4",
        "accent2": "0xFF2E63",
        "cream": "0xFEE440",
        "mint": "0x8BFFEC",
        "blue": "0x7B2CBF",
        "dark": "0x050914",
        "name": "neon_arcade_esports_countdown",
    },
    "finance": {
        "accent": "0xD8FF65",
        "accent2": "0x00D6A3",
        "cream": "0xF5FFD0",
        "mint": "0x9BE7C7",
        "blue": "0x43B5FF",
        "dark": "0x101C1A",
        "name": "operator_notebook_countdown",
    },
    "technology_ai": {
        "accent": "0x61F7FF",
        "accent2": "0xA45CFF",
        "cream": "0xE7FBFF",
        "mint": "0xAEFFCB",
        "blue": "0x4D7DFF",
        "dark": "0x0D1324",
        "name": "builder_brief_countdown",
    },
    "health_fitness": {
        "accent": "0x7CFFB2",
        "accent2": "0xFFE85C",
        "cream": "0xFFF7C5",
        "mint": "0xB7FFD7",
        "blue": "0x5AD7FF",
        "dark": "0x10231B",
        "name": "wellness_takeaway_countdown",
    },
    "politics": {
        "accent": "0xF5F7FF",
        "accent2": "0xFF4D5F",
        "cream": "0xFFF1D6",
        "mint": "0x90D6FF",
        "blue": "0x527BFF",
        "dark": "0x121827",
        "name": "civic_context_countdown",
    },
    "truecrime": {
        "accent": "0xFFD08A",
        "accent2": "0xFF3D3D",
        "cream": "0xFFF0D2",
        "mint": "0xA8C7BA",
        "blue": "0x6EA9FF",
        "dark": "0x161112",
        "name": "case_file_countdown",
    },
    "popculture": {
        "accent": "0xFF71C8",
        "accent2": "0xFFE85C",
        "cream": "0xFFF3B0",
        "mint": "0x7FFFD4",
        "blue": "0x9EB6FF",
        "dark": "0x1B1224",
        "name": "culture_spotlight_countdown",
    },
}


def visual_style(rank, theme=None):
    theme_key = str(theme or "").strip().lower()
    style = dict(THEME_VISUAL_STYLES.get(theme_key) or THEME_VISUAL_STYLES["comedy"])
    style["rank"] = rank
    return style


def selected_topic_clips(topic_item):
    selected = []

    for clip in topic_item.get("clips", []):
        output_file = clip.get("output_file", "")

        if output_file and os.path.exists(output_file) and clip_is_editorial_usable(clip):
            selected.append(clip)

        if len(selected) >= EDITORIAL_CLIPS_PER_SHORT:
            break

    return selected


def editorial_subtitle_model():
    global EDITORIAL_SUBTITLE_MODEL

    if EDITORIAL_SUBTITLE_MODEL is None:
        import subtitle_generation

        EDITORIAL_SUBTITLE_MODEL = subtitle_generation.create_transcriber()

    return EDITORIAL_SUBTITLE_MODEL


def captioned_editorial_source_clip(theme, clip, scratch_dir):
    if not EDITORIAL_BURN_SOURCE_CAPTIONS:
        return clip

    source_file = clip.get("output_file", "")

    if not source_file or not os.path.exists(source_file):
        return clip

    if not clip_is_editorial_usable(clip):
        raise RuntimeError(f"source clip failed editorial visual QC: {os.path.basename(source_file)}")

    if clip.get("content_has_burned_captions") or source_file.lower().endswith("_captioned.mp4"):
        return clip

    import subtitle_generation

    subtitle_generation.configure_theme(theme)
    caption_dir = os.path.join(scratch_dir, "captioned_sources")
    os.makedirs(caption_dir, exist_ok=True)
    basename = os.path.splitext(os.path.basename(source_file))[0]
    output_file = os.path.join(caption_dir, clean_filename(f"{basename}_captioned") + ".mp4")
    ass_path = os.path.join(caption_dir, clean_filename(f"{basename}_captioned") + ".ass")

    if (
        os.path.exists(output_file)
        and os.path.getsize(output_file) > 0
        and os.path.getmtime(output_file) >= os.path.getmtime(source_file)
    ):
        captioned = dict(clip)
        captioned["raw_output_file"] = source_file
        captioned["output_file"] = output_file
        captioned["content_has_burned_captions"] = True
        captioned["editorial_captioned_source_file"] = output_file
        return captioned

    print(f"Burning source captions for editorial clip: {os.path.basename(source_file)}")
    words = subtitle_generation.transcribe_words(editorial_subtitle_model(), source_file)

    if not words:
        raise RuntimeError(f"No subtitle words were detected for editorial source clip: {source_file}")

    event_count = subtitle_generation.build_ass_subtitles(words, ass_path, clip_metadata=clip)

    if event_count <= 0:
        raise RuntimeError(f"No subtitle events were created for editorial source clip: {source_file}")

    subtitle_generation.burn_subtitles(source_file, ass_path, output_file)
    captioned = dict(clip)
    captioned["raw_output_file"] = source_file
    captioned["output_file"] = output_file
    captioned["content_has_burned_captions"] = True
    captioned["editorial_captioned_source_file"] = output_file
    captioned["editorial_caption_word_count"] = len(words)
    captioned["editorial_caption_event_count"] = event_count
    return captioned


def captioned_editorial_source_clips(theme, clips, scratch_dir):
    captioned = []

    for clip in clips:
        try:
            captioned.append(captioned_editorial_source_clip(theme, clip, scratch_dir))
        except RuntimeError as error:
            print(f"Skipping source clip before editorial packaging: {error}")

    return captioned


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


def editorial_intro_duration(audio_path=None):
    target = min(EDITORIAL_INTRO_TARGET_SECONDS, EDITORIAL_INTRO_MAX_SECONDS)

    if audio_path:
        audio_duration = get_duration(audio_path)
        if audio_duration > 0:
            target = max(target, audio_duration + INTRO_AUDIO_SAFETY_PAD_SECONDS)

    return max(3.25, min(EDITORIAL_INTRO_ABSOLUTE_MAX_SECONDS, target))


def source_audio_fade_filter(duration):
    fade_duration = min(
        EDITORIAL_SOURCE_AUDIO_FADE_IN_SECONDS,
        max(0.0, float(duration or 0.0) / 3.0),
    )

    if fade_duration <= 0.001:
        return ""

    return f"afade=t=in:st=0:d={fade_duration:.3f},"


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
    draw.rounded_rectangle((0, 36, 20, 88), radius=4, fill=(accent[0], accent[1], accent[2], 220))
    draw.rounded_rectangle((width - 20, 36, width - 1, 88), radius=4, fill=(accent2[0], accent2[1], accent2[2], 184))
    draw.rectangle((0, 54, width, 61), fill=(255, 244, 184, 28))
    draw.rectangle((0, 68, width, 73), fill=(183, 215, 194, 22))
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


def countdown_handoff_timing(spin_end, final_lock):
    handoff_start = max(0.0, float(spin_end) - 0.05)
    available = max(0.4, float(final_lock) - handoff_start)
    handoff_duration = max(0.68, min(1.05, available * 0.62))
    return handoff_start, handoff_duration


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


def card_morph_layer(source_card, final_card, width, height, progress):
    progress = clamp(progress)
    layer = Image.new("RGBA", (max(1, int(width)), max(1, int(height))), (0, 0, 0, 0))
    source = source_card.resize(layer.size, Image.Resampling.LANCZOS)
    final = final_card.resize(layer.size, Image.Resampling.LANCZOS)
    source_alpha = max(0.0, 1.0 - ease_in_out_cubic((progress - 0.86) / 0.14))
    final_alpha = ease_in_out_cubic((progress - 0.62) / 0.28)

    if progress >= 0.96:
        layer.alpha_composite(final)
        return layer

    if source_alpha > 0.01:
        layer.alpha_composite(multiply_alpha(source, source_alpha))

    if final_alpha > 0.01:
        layer.alpha_composite(multiply_alpha(final, final_alpha))

    return layer


def selected_card_start_pose(source_index, source_card, spin_end, wheel_top, wheel_height, row_spacing, total_scroll, lock_center, display_index):
    offset = wheel_offset_at(spin_end, spin_end)
    layout = wheel_card_layout(
        source_index,
        source_card,
        offset,
        wheel_top,
        wheel_height,
        row_spacing,
        total_scroll,
        lock_center,
    )

    if layout["visible"]:
        return {
            "x": layout["x"],
            "y": layout["y"],
            "scale": layout["scale"],
            "alpha": max(0.72, layout["alpha"]),
        }

    side = -1 if display_index % 2 == 0 else 1
    return {
        "x": 58 + side * 230,
        "y": int(lock_center + (display_index - 2) * row_spacing),
        "scale": 0.88,
        "alpha": 0.74,
    }


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


def draw_wheel_mechanism(draw, accent, accent2, t, wheel_top, wheel_height, lock_center, progress):
    alpha = int(126 * ((1 - clamp(progress)) ** 1.35))

    if alpha <= 4:
        return

    rail_left = 48
    rail_right = 1032
    rail_color = (accent2[0], accent2[1], accent2[2], alpha)
    accent_color = (accent[0], accent[1], accent[2], min(210, alpha + 44))

    draw.rounded_rectangle(
        (rail_left - 12, wheel_top - 46, rail_right + 12, wheel_top + wheel_height + 46),
        radius=34,
        fill=(0, 0, 0, min(82, max(18, alpha // 2))),
        outline=(255, 255, 255, max(18, alpha // 3)),
        width=2,
    )
    draw.line((rail_left + 8, wheel_top - 18, rail_left + 8, wheel_top + wheel_height + 18), fill=rail_color, width=5)
    draw.line((rail_right - 8, wheel_top - 18, rail_right - 8, wheel_top + wheel_height + 18), fill=rail_color, width=5)
    draw.line((rail_left + 30, lock_center, rail_right - 30, lock_center), fill=accent_color, width=5)

    pulley_centers = [
        (rail_left + 8, wheel_top + 42),
        (rail_right - 8, wheel_top + 42),
        (rail_left + 8, wheel_top + wheel_height - 42),
        (rail_right - 8, wheel_top + wheel_height - 42),
    ]

    for pulley_index, (cx, cy) in enumerate(pulley_centers):
        radius = 34
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(0, 0, 0, max(30, alpha // 2)),
            outline=(accent[0], accent[1], accent[2], max(52, alpha)),
            width=4,
        )
        spoke_angle = t * 6.2 + pulley_index * 0.7

        for spoke_index in range(4):
            angle = spoke_angle + spoke_index * math.pi / 2
            ex = cx + math.cos(angle) * (radius - 7)
            ey = cy + math.sin(angle) * (radius - 7)
            draw.line((cx, cy, ex, ey), fill=(accent2[0], accent2[1], accent2[2], max(36, alpha)), width=3)

    draw.rounded_rectangle(
        (rail_left + 14, lock_center - 94, rail_right - 14, lock_center + 94),
        radius=18,
        outline=(255, 244, 184, max(28, int(alpha * 0.72))),
        width=3,
    )

    for tick_index in range(8):
        phase = (tick_index / 8.0 + t * 0.55) % 1.0
        y = int(wheel_top + phase * wheel_height)
        tick_alpha = int(alpha * (0.35 + 0.65 * (1 - abs((y - lock_center) / max(1, wheel_height / 2)))))
        draw.rounded_rectangle(
            (rail_left + 2, y - 12, rail_left + 30, y + 12),
            radius=5,
            fill=(accent[0], accent[1], accent[2], max(18, tick_alpha)),
        )
        draw.rounded_rectangle(
            (rail_right - 30, y - 12, rail_right - 2, y + 12),
            radius=5,
            fill=(accent[0], accent[1], accent[2], max(18, tick_alpha)),
        )


def draw_card_carrier(draw, x, y, width, height, accent, accent2, alpha, t, index):
    raw_alpha = clamp(alpha)

    if raw_alpha <= 0.18:
        return

    alpha = int(130 * raw_alpha)
    mid_y = int(y + height / 2)
    left_anchor = int(x - 32)
    right_anchor = int(x + width + 32)
    belt_alpha = max(18, int(alpha * 0.55))
    pin_alpha = max(28, int(alpha * 0.82))

    draw.line(
        (left_anchor, mid_y, right_anchor, mid_y),
        fill=(accent2[0], accent2[1], accent2[2], belt_alpha),
        width=3,
    )
    draw.line(
        (left_anchor, mid_y + 14, right_anchor, mid_y + 14),
        fill=(255, 244, 184, max(12, int(alpha * 0.22))),
        width=2,
    )

    for side_x in (left_anchor, right_anchor):
        draw.ellipse(
            (side_x - 13, mid_y - 13, side_x + 13, mid_y + 13),
            fill=(0, 0, 0, max(22, int(alpha * 0.45))),
            outline=(accent[0], accent[1], accent[2], pin_alpha),
            width=3,
        )
        spoke = t * 8.0 + index * 0.64

        for spoke_index in range(3):
            angle = spoke + spoke_index * (math.pi * 2 / 3)
            end_x = side_x + math.cos(angle) * 10
            end_y = mid_y + math.sin(angle) * 10
            draw.line(
                (side_x, mid_y, end_x, end_y),
                fill=(255, 244, 184, max(18, int(alpha * 0.52))),
                width=2,
            )


def draw_morph_energy(draw, accent, accent2, t, progress):
    progress = clamp(progress)

    if progress <= 0.03 or progress >= 0.82:
        return

    bloom = math.sin(math.pi * progress)
    alpha = int(138 * bloom)
    pull_x = 540 + int(math.sin(t * 4.2) * 18)

    for arc_index in range(5):
        radius_x = int(220 + arc_index * 92 + 120 * progress)
        radius_y = int(126 + arc_index * 62 + 66 * progress)
        left = pull_x - radius_x
        right = pull_x + radius_x
        y = 940 + int(math.sin(t * 4.8 + arc_index) * 14)
        arc_alpha = int(alpha * (0.12 + 0.17 * abs(math.sin(t * 5.4 + arc_index))))
        draw.arc(
            (left, y - radius_y, right, y + radius_y),
            start=202,
            end=338,
            fill=(accent2[0], accent2[1], accent2[2], max(10, arc_alpha)),
            width=2 if arc_index % 2 else 3,
        )

    for streak_index in range(26):
        angle = -0.36 + (streak_index % 9) * 0.09 + math.sin(t * 3.4 + streak_index) * 0.035
        lane_offset = (streak_index // 9) - 1
        radius = 150 + (streak_index % 7) * 72 + 170 * progress
        start_x = int(pull_x + math.cos(angle) * radius - 160 * progress)
        start_y = int(930 + lane_offset * 176 + math.sin(t * 6.1 + streak_index) * 52)
        length = int(34 + 88 * bloom + (streak_index % 4) * 12)
        end_x = int(start_x + length)
        end_y = int(start_y - length * (0.18 + progress * 0.10))
        streak_alpha = int(alpha * (0.10 + 0.32 * abs(math.sin(t * 7.2 + streak_index))))
        draw.line(
            (start_x, start_y, end_x, end_y),
            fill=(255, 244, 184, max(8, streak_alpha)),
            width=1 + (streak_index % 3 == 0),
        )

    for spark_index in range(14):
        angle = t * 4.0 + spark_index * 0.82
        radius = 60 + (spark_index % 5) * 28 + 90 * progress
        cx = int(pull_x + math.cos(angle) * radius)
        cy = int(940 + math.sin(angle * 0.82) * radius * 1.35)
        spark_alpha = int(alpha * (0.20 + 0.30 * abs(math.sin(angle))))
        draw.rounded_rectangle(
            (cx - 4, cy - 4, cx + 4, cy + 4),
            radius=3,
            fill=(accent[0], accent[1], accent[2], max(12, spark_alpha)),
        )


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
    display_index_by_key = {
        entry.get("source_state_key"): index
        for index, entry in enumerate(display_entries)
    }
    current_entry = next(
        (entry for entry in display_entries if int(entry.get("slot") or 0) == int(countdown_slot or 0)),
        None,
    )
    source_banners = ensure_display_banners(source_banners, display_entries)
    scan_cards = [make_scan_banner_card(banner, accent, accent2, fonts) for banner in source_banners]
    source_index_by_key = {}
    for index, banner in enumerate(source_banners):
        source_index_by_key.setdefault(banner.get("source_state_key"), index)
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
            final_progress = ease_in_out_cubic((t - spin_end) / max(0.1, final_lock - spin_end))

            if t < final_lock:
                lane_progress = final_progress
                draw_wheel_mechanism(draw, accent, accent2, t, wheel_top, wheel_height, lock_center, lane_progress)
                draw_morph_energy(draw, accent, accent2, t, final_progress)

                offset = wheel_offset_at(min(t, spin_end), spin_end)
                handoff_start, handoff_duration = countdown_handoff_timing(spin_end, final_lock)
                lock_progress = ease_in_out_cubic((t - handoff_start) / handoff_duration)
                wheel_exit_progress = ease_out_cubic((t - handoff_start) / 0.38)

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

                    display_index = display_index_by_key.get(key)
                    display_morph_progress = 0.0

                    if display_index is not None:
                        display_morph_progress = ease_in_out_cubic(
                            (t - handoff_start - display_index * 0.026) / handoff_duration
                        )

                    if alpha <= 0.025:
                        continue

                    if lock_progress > 0 and key not in display_keys:
                        alpha *= max(0.0, 1 - wheel_exit_progress * 1.08)
                    elif lock_progress > 0:
                        alpha *= max(0.46, 1 - wheel_exit_progress * 0.36)

                    if key in display_keys and display_morph_progress > 0.26:
                        continue

                    if lock_progress > 0 and key not in display_keys:
                        side = -1 if index % 2 == 0 else 1
                        sweep = ease_out_cubic(lock_progress)
                        center_pull = int((lock_center - (y + card.height / 2)) * 0.18 * sweep)
                        x += int(side * sweep * (260 + (index % 3) * 42))
                        y += center_pull + int(math.sin(index * 1.7 + t * 8.5) * 12 * sweep)
                        angle = side * sweep * 2.8
                        alpha *= max(0.0, 1 - max(sweep * 1.42, wheel_exit_progress * 1.08))
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
                    draw_card_carrier(draw, x, y, scaled_w, scaled_h, accent, accent2, alpha, t, index)
                    paste_rotated(frame, scaled, x, y, angle, alpha)

            if final_progress > 0:
                handoff_start, handoff_duration = countdown_handoff_timing(spin_end, final_lock)
                for index, card in enumerate(final_cards):
                    entry = display_entries[index]
                    key = entry.get("source_state_key")
                    source_index = source_index_by_key.get(key, index)
                    source_card = scan_cards[source_index] if source_index < len(scan_cards) else card
                    target_x = 58
                    target_y = top_board_y(index)
                    card_progress = ease_in_out_cubic((t - handoff_start - index * 0.016) / handoff_duration)
                    if card_progress <= 0.01:
                        continue
                    start_pose = selected_card_start_pose(
                        source_index,
                        source_card,
                        spin_end,
                        wheel_top,
                        wheel_height,
                        row_spacing,
                        total_scroll,
                        lock_center,
                        index,
                    )
                    source_width = int(source_card.width * start_pose["scale"])
                    source_height = int(source_card.height * start_pose["scale"])
                    start_x = int(start_pose["x"])
                    start_y = int(start_pose["y"])
                    size_progress = ease_in_out_cubic((card_progress - 0.46) / 0.38)
                    card_width = int(source_width + (964 - source_width) * size_progress)
                    card_height = int(source_height + (176 - source_height) * size_progress)
                    position_progress = ease_out_cubic(card_progress)
                    x = int(start_x + (target_x - start_x) * position_progress)
                    y = int(start_y + (target_y - start_y) * position_progress)
                    alpha = min(1.0, start_pose["alpha"] + card_progress * 0.34)
                    glow_alpha = int(95 * card_progress * (0.6 + 0.4 * math.sin(t * 9 + index)))

                    if card_progress > 0.94:
                        draw.rounded_rectangle(
                            (42, target_y - 12, 1038, target_y + 188),
                            radius=12,
                            fill=(accent2[0], accent2[1], accent2[2], 0),
                            outline=(accent[0], accent[1], accent[2], max(0, int(glow_alpha * card_progress))),
                            width=3,
                        )

                    if card_progress > 0.76 and int(entry.get("slot") or 0) == countdown_slot:
                        pulse = 0.5 + 0.5 * math.sin(t * 9.5)
                        draw.rounded_rectangle(
                            (x - 10, y - 10, x + card_width + 10, y + card_height + 10),
                            radius=10,
                            outline=(accent2[0], accent2[1], accent2[2], int((110 + 100 * pulse) * card_progress)),
                            width=8,
                        )

                    morph_layer = card_morph_layer(source_card, card, card_width, card_height, card_progress)
                    paste_rotated(frame, morph_layer, x, y, 0, alpha)

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

    topic_clips = captioned_editorial_source_clips(
        theme,
        selected_topic_clips(topic_item),
        scratch_dir,
    )

    if not topic_clips:
        raise RuntimeError(f"No rendered source clips found for topic: {topic_item.get('topic', '')}")

    best_clip = topic_clips[0]
    source_clip = best_clip["output_file"]
    topic = clean_headline_topic(
        theme,
        topic_item["topic"],
        clip=best_clip,
        source_title=best_clip.get("source_title", ""),
        channel=best_clip.get("source_channel", ""),
    )
    total_count = int(topic_item.get("_total_count") or DAILY_TOPIC_COUNT)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    script = build_editorial_intro(theme, topic, rank, total_count, adjective, best_clip, countdown_slot=countdown_slot)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, rank)
    intro_duration = editorial_intro_duration(intro_audio)
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

    style = visual_style(rank, theme)
    theme_label = theme_profile(theme)["label"]
    theme_label_upper = theme_label.upper()
    period_upper = period_label().upper()
    output_filename = clean_filename(f"{date_key}_{theme}_countdown_{countdown_slot:02d}_{topic}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    ranking_title = countdown_heading(theme, adjective, total_count)
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
            f"{source_audio_fade_filter(duration)}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip{index}_a]"
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
    topic_clips = captioned_editorial_source_clips(
        theme,
        [dict(clip) for clip in selected_topic_clips(topic_item)],
        scratch_dir,
    )

    if not topic_clips:
        raise RuntimeError(f"No rendered source clips found for topic: {topic_item.get('topic', '')}")

    best_clip = topic_clips[0]
    best_clip["_countdown_context"] = context
    source_clip = best_clip["output_file"]
    topic = clean_headline_topic(
        theme,
        topic_item["topic"],
        clip=best_clip,
        source_title=best_clip.get("source_title", ""),
        channel=best_clip.get("source_channel", ""),
    )
    total_count = int(topic_item.get("_total_count") or len(context.get("top_entries", [])) or EDITORIAL_COUNTDOWN_SIZE)
    countdown_slot = int(topic_item.get("_countdown_slot") or countdown_slot_for_rank(rank, total_count))
    current_entry = topic_item.get("_countdown_entry") or {
        "slot": countdown_slot,
        "topic": topic,
        "summary": clip_summary(best_clip, topic),
        "source_title": best_clip.get("source_title") or "source episode",
        "clip_file": source_clip,
    }
    script = build_editorial_intro(theme, topic, rank, total_count, reel_adjective, best_clip, countdown_slot=countdown_slot)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, rank)
    intro_duration = editorial_intro_duration(intro_audio)
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

    style = visual_style(rank, theme)
    theme_label = context.get("theme_label") or theme_profile(theme)["label"]
    output_filename = clean_filename(f"{date_key}_{theme}_countdown_{countdown_slot:02d}_{topic}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    ranking_title = countdown_heading(theme, reel_adjective, total_count)
    ranking_subtitle = watched_header_text(context)
    moment_label = f"#{countdown_slot}"
    number_label = f"NUMBER {countdown_slot}"
    current_topic = clean_headline_topic(
        theme,
        current_entry.get("topic") or topic,
        clip=best_clip,
        source_title=best_clip.get("source_title", ""),
        channel=best_clip.get("source_channel", ""),
    )
    topic_text = compact_text(current_topic.upper(), 90)
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
            f"{source_audio_fade_filter(duration)}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip{index}_a]"
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


def popular_segment_labels(item, theme=""):
    source = popular_segment_signal_source(item)
    theme_key = str(theme or "").strip().lower()
    labels = {
        "comedy": ("JOKE FILE", "BEST TURN", "WAIT FOR THE PAYOFF"),
        "sports": ("GAME FILE", "KEY TAKE", "WATCH THE REACTION"),
        "gaming": ("QUEUE FILE", "HOT TAKE", "WATCH THE TURN"),
        "finance": ("MARKET NOTE", "KEY TAKEAWAY", "WATCH THE CATCH"),
        "technology_ai": ("BUILDER NOTE", "KEY LIMIT", "WATCH THE TURN"),
        "health_fitness": ("HEALTH NOTE", "KEY DETAIL", "WATCH THE ADVICE"),
        "politics": ("CIVICS FILE", "KEY CLAIM", "WATCH THE CONTEXT"),
        "popculture": ("CULTURE FILE", "KEY REACTION", "WATCH THE SWERVE"),
        "truecrime": ("CASE FILE", "KEY DETAIL", "WATCH THE CONTEXT"),
    }
    primary, secondary, detail = labels.get(theme_key, ("CLIP FILE", "KEY MOMENT", "WATCH THE TURN"))

    if source == "youtube_heatmap":
        return primary, secondary, detail

    if source in {"timestamp_mentions", "chapters", "public_popularity_signal"}:
        return primary, secondary, detail

    return primary, "EDITOR PICK", detail


def build_popular_segment_script(theme, item):
    clip = item.get("clip") or {}
    title, topic, _topic_terms = popular_segment_public_title(theme, item)
    topic = title if title and not re.search(r"^needs\s+specific\s+", title, flags=re.I) else topic
    topic = editorial_title_topic(topic or clip.get("suggested_title") or clip_summary(clip, item.get("source_title") or "this moment"))
    hook_topic = concise_intro_hook_topic(theme, topic, clip, max_length=50)
    script = f"Standout: {hook_topic}."

    if len(re.findall(r"[a-zA-Z0-9']+", script)) < 6:
        script = f"Standout: {hook_topic}. Watch this."

    return script


def build_popular_output_package(theme, output_path, item, index, date_key, script, intro_audio, intro_duration, clip_duration):
    profile = theme_profile(theme)
    theme_label = profile["label"]
    caption_style = profile.get("caption_style", "")
    overlay_style = profile.get("overlay_style", "")
    framing_style = profile.get("framing_style", "")
    clip = item["clip"]
    underlying_source_state_keys = source_keys_from_clips(theme, [clip])
    item_source_key = str(item.get("source_state_key") or "").strip()

    if item_source_key and item_source_key not in underlying_source_state_keys:
        underlying_source_state_keys.append(item_source_key)

    source_title = item.get("source_title") or clip.get("source_title") or "Podcast interview"
    channel = item.get("channel_label") or "Podcast Channel"
    title, topic, topic_terms = popular_segment_public_title(theme, item)
    signal_source = popular_segment_signal_source(item)
    description = build_social_caption(
        theme_label,
        topic,
        content_format="popular",
        source_title=source_title,
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
    rank_signals = dict(clip.get("rank_signals") or {})
    rank_signals.update({
        "popular_segment_index": index,
        "content_format": "popular_segment_short",
        "popular_segment_signal_source": signal_source,
    })
    title_quality = score_title_quality(
        theme,
        title,
        topic_terms=topic_terms,
    )
    rank_signals["title_quality"] = title_quality
    experiment = clip.get("experiment") or {
        "experiment_id": f"{theme}_popular_segment_packaging",
        "variant": signal_source,
        "hypothesis": "External popularity-backed clips outperform internally scored clips when packaging is otherwise similar.",
    }

    return {
        "theme": theme,
        "content_format": "popular_segment_short",
        "content_has_burned_captions": True,
        "upload_ready_requires_burned_captions": True,
        "caption_style": caption_style,
        "overlay_style": overlay_style,
        "framing_style": framing_style,
        "editorial_date": date_key,
        "video_file": os.path.abspath(output_path),
        "source_clip_file": os.path.abspath(clip.get("output_file", "")),
        "source_state_key": f"{theme}|popular|{date_key}|{index}|{item.get('source_state_key', '')}",
        "underlying_source_state_keys": underlying_source_state_keys,
        "source_video_url": item.get("source_video_url") or clip.get("source_video_url", ""),
        "source_channel": channel,
        "source_title": source_title,
        "clip_start_time": clip.get("start_time"),
        "clip_end_time": clip.get("end_time"),
        "title": title,
        "title_quality": title_quality,
        "caption": compact_text(description, 160),
        "hashtags": hashtags,
        "tags": tags,
        "description": compact_text(description, 320),
        "transcript_excerpt": clip.get("transcript_excerpt", ""),
        "hook_reason": f"popular segment signal: {clip.get('rank_signals', {}).get('popularity_source', 'replay/popularity')}",
        "score": item.get("sort_score", clip.get("score")),
        "readiness_score": clip.get("readiness_score"),
        "rank_signals": rank_signals,
        "experiment": experiment,
        "popularity_score": item.get("popularity_score", 0),
        "content_signal": {
            "type": "most_replayed_or_popular_segment",
            "popularity_score": item.get("popularity_score", 0),
            "source": signal_source,
            "channel_label": channel,
            "source_title": source_title,
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
                "privacy_status": YOUTUBE_PRIVACY_STATUS,
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

    clip = captioned_editorial_source_clip(theme, item["clip"], scratch_dir)
    source_clip = clip.get("output_file", "")

    if not source_clip or not os.path.exists(source_clip):
        raise RuntimeError(f"Missing rendered source clip for popular segment: {item.get('source_title', '')}")

    source_title = compact_text(item.get("source_title") or clip.get("source_title") or "Podcast interview", 76)
    channel = compact_text(item.get("channel_label") or "Podcast Channel", 42)
    topic = compact_text(
        clean_headline_topic(theme, clip_summary(clip, source_title), clip=clip, source_title=source_title, channel=channel),
        72,
    )
    style = visual_style(index, theme)
    accent = style["accent"]
    accent2 = style["accent2"]
    cream = style.get("cream", "0xFFF4B8")
    mint = style.get("mint", "0xB7D7C2")
    dark = style.get("dark", "0x2E3440")
    profile = theme_profile(theme)
    archive_label = f"THE {profile['label'].upper()} ARCHIVE"
    signal_label, popularity_label, detail_label = popular_segment_labels(item, theme)
    hero_label = compact_text(signal_label, 18).upper()
    script = build_popular_segment_script(theme, item)
    intro_audio = synthesize_intro_audio(script, scratch_dir, date_key, theme, 1000 + index)
    intro_duration = max(
        POPULAR_SEGMENT_INTRO_SECONDS,
        min(EDITORIAL_INTRO_MAX_SECONDS, get_duration(intro_audio) + 0.45),
    )
    clip_duration = clip_play_duration_for(source_clip, max(POPULAR_SEGMENT_MAX_SECONDS - intro_duration, EDITORIAL_CLIP_MIN_SECONDS))
    output_filename = clean_filename(f"{date_key}_{theme}_popular_{index:02d}_{source_title}") + "_upload.mp4"
    output_path = os.path.join(output_dir, output_filename)
    source_title_size = fitted_label_font_size(source_title, max_width=860, max_size=44, min_size=28)
    topic_size = fitted_label_font_size(topic, max_width=780, max_size=48, min_size=34)
    channel_size = fitted_label_font_size(channel, max_width=560, max_size=31, min_size=22)
    hero_label_size = fitted_label_font_size(hero_label, max_width=760, max_size=154, min_size=86)
    font_bold = ffmpeg_path(font_path_or_fallback(FONT_BOLD_FILE, FONT_FILE))
    font_meta = ffmpeg_path(font_path_or_fallback(FONT_META_FILE, FONT_FILE))
    font_display = ffmpeg_path(font_path_or_fallback(FONT_DISPLAY_FILE, FONT_BOLD_FILE))

    filters = [
        f"[0:v]trim=0:{intro_duration:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=18:2,eq=brightness=-0.34:saturation=1.10,setsar=1[intro_bg]",
        "[intro_bg]"
        f"drawbox=x=0:y=0:w=1080:h=1920:color={dark}@0.24:t=fill,"
        f"drawtext=fontfile='{font_display}':text='{drawtext_text(hero_label)}':x=44:y=244:fontsize={hero_label_size}:fontcolor={cream}@0.12,"
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
        f"drawbox=x=82:y=1622:w=778:h=134:color=black@0.82:t=fill,"
        f"drawbox=x=82:y=1622:w=778:h=134:color={mint}@0.66:t=2,"
        f"drawbox=x=82:y=1622:w=14:h=134:color={accent}@0.96:t=fill,"
        f"drawtext=fontfile='{font_bold}':text='{drawtext_text(topic.upper())}':x=118:y=1646:fontsize={topic_size}:fontcolor=white:shadowcolor=black@0.52:shadowx=2:shadowy=2,"
        f"drawtext=fontfile='{font_meta}':text='{drawtext_text(channel.upper())}':x=120:y=1714:fontsize=24:fontcolor={cream}@0.88,"
        f"drawbox=x=74:y=1848:w=932:h=7:color=black@0.52:t=fill,"
        f"drawbox=x=74:y=1848:w='932*t/{clip_duration:.3f}':h=7:color={accent}@0.98:t=fill,"
        f"drawbox=x=74:y=1861:w='932*t/{clip_duration:.3f}':h=3:color={mint}@0.78:t=fill,"
        f"format=yuv420p[clip_v]",
        f"[0:a]atrim=0:{intro_duration:.3f},volume={INTRO_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS[intro_bed]",
        f"[1:a]atrim=0:{intro_duration:.3f},volume=1.0,asetpts=PTS-STARTPTS[intro_voice]",
        "[intro_bed][intro_voice]amix=inputs=2:duration=longest:dropout_transition=0,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[intro_a]",
        f"[0:a]atrim=0:{clip_duration:.3f},volume={CLIP_SOURCE_AUDIO_VOLUME},asetpts=PTS-STARTPTS,{source_audio_fade_filter(clip_duration)}aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[clip_a]",
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
    underlying_source_state_keys = []

    for item in packages:
        for key in item.get("underlying_source_state_keys") or []:
            if key and key not in underlying_source_state_keys:
                underlying_source_state_keys.append(key)

    package["underlying_source_state_keys"] = underlying_source_state_keys
    package["source_context"] = [
        {
            "source_video_url": item.get("source_video_url", ""),
            "source_channel": item.get("source_channel", ""),
            "source_title": item.get("source_title", ""),
            "transcript_excerpt": item.get("transcript_excerpt", ""),
            "clip_start_time": item.get("clip_start_time"),
            "clip_end_time": item.get("clip_end_time"),
            "editorial_date": item.get("editorial_date", ""),
        }
        for item in packages
    ]
    return finalize_editorial_package(package, "full daily recap")


def synthetic_editorial_source_key(source_key):
    key = str(source_key or "")
    return "|editorial|" in key or "|popular|" in key


def package_underlying_source_keys(theme, package):
    keys = []

    for key in package.get("underlying_source_state_keys") or []:
        key = str(key or "").strip()

        if key and not synthetic_editorial_source_key(key) and key not in keys:
            keys.append(key)

    rank_signals = package.get("rank_signals") or {}

    for key in [
        rank_signals.get("source_state_key"),
        package.get("source_state_key"),
    ]:
        key = str(key or "").strip()

        if key and not synthetic_editorial_source_key(key) and key not in keys:
            keys.append(key)

    source_url = str(package.get("source_video_url") or "").strip()

    if source_url:
        fallback_key = f"{theme}|{source_url}"

        if fallback_key not in keys:
            keys.append(fallback_key)

    return keys


def mark_editorial_sources_completed(theme, packages, metadata_file):
    executed = load_json_file(EXECUTED_FILE, {})
    pulled = load_json_file(PULLED_FILE, {})

    if not isinstance(executed, dict):
        executed = {}

    if not isinstance(pulled, dict):
        pulled = {}

    changed_executed = False
    changed_pulled = False
    completed_count = 0

    for package in packages or []:
        if not package_is_upload_ready(package):
            continue

        source_keys = package_underlying_source_keys(theme, package)
        final_video_file = os.path.abspath(package.get("video_file", "")) if package.get("video_file") else ""
        package_key = str(package.get("source_state_key") or "").strip()

        for source_key in source_keys:
            existing = executed.get(source_key, {})

            if not isinstance(existing, dict):
                existing = {}

            pulled_record = pulled.get(source_key, {})

            if not isinstance(pulled_record, dict):
                pulled_record = {}

            final_video_files = list(existing.get("final_video_files") or [])
            metadata_files = list(existing.get("metadata_files") or [])
            editorial_packages = list(existing.get("editorial_packages") or [])

            if final_video_file and final_video_file not in final_video_files:
                final_video_files.append(final_video_file)

            if metadata_file and metadata_file not in metadata_files:
                metadata_files.append(metadata_file)

            if package_key and package_key not in editorial_packages:
                editorial_packages.append(package_key)

            updated = {
                **existing,
                "theme": theme,
                "video_url": package.get("source_video_url") or pulled_record.get("video_url", existing.get("video_url", "")),
                "title": package.get("source_title") or pulled_record.get("title", existing.get("title", "")),
                "funnel_status": "subtitled",
                "subtitle_status": "complete",
                "upload_status": existing.get("upload_status", "pending"),
                "final_video_count": len(final_video_files),
                "final_video_files": final_video_files,
                "metadata_files": metadata_files,
                "editorial_packages": editorial_packages,
            }
            mark_stage(updated, "subtitled")
            mark_stage(updated, "completed")
            executed[source_key] = updated
            changed_executed = True
            completed_count += 1

            pulled_entry = pulled.get(source_key)

            if isinstance(pulled_entry, dict):
                mark_stage(pulled_entry, "subtitled")
                mark_stage(pulled_entry, "upload_ready")
                pulled_entry["funnel_status"] = "upload_ready"
                pulled_entry["subtitle_status"] = "complete"
                changed_pulled = True

    if changed_executed:
        write_json_file(EXECUTED_FILE, executed)

    if changed_pulled:
        write_json_file(PULLED_FILE, pulled)

    if completed_count:
        print(f"Marked {completed_count} underlying source record(s) as completed/subtitled.")


def save_editorial_metadata(theme, paths, packages, brief):
    metadata_path = paths["final_metadata_file"]
    metadata_default = {
        "theme": theme,
        "content": [],
        "archive": [],
        "daily_editorial": brief,
    }
    preserve_existing = os.getenv("SHORTFORM_PRESERVE_EDITORIAL_BACKLOG", "1") != "0"

    if preserve_existing and os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0:
        metadata = load_json_file(metadata_path, metadata_default)
        metadata["content"] = [
            item
            for item in metadata.get("content", [])
            if item.get("video_file") and os.path.exists(item.get("video_file"))
        ]
        metadata["archive"] = [
            item
            for item in metadata.get("archive", [])
            if item.get("video_file") and os.path.exists(item.get("video_file"))
        ]
    elif APPEND_METADATA and os.path.exists(metadata_path) and os.path.getsize(metadata_path) > 0:
        metadata = load_json_file(metadata_path, metadata_default)
        metadata["content"] = [
            item
            for item in metadata.get("content", [])
            if item.get("editorial_date") != brief["date"]
        ]
    else:
        metadata = metadata_default

    metadata["theme"] = theme
    metadata["daily_editorial"] = brief
    packages = enforce_unique_package_titles(theme, packages, metadata)
    metadata["content"] = dedupe_packages(metadata.get("content", []) + packages)
    metadata["archive"] = dedupe_packages(metadata.get("archive", []))
    write_json_file(metadata_path, metadata)

    if os.getenv("SHORTFORM_DEFER_EDITORIAL_SOURCE_COMPLETION", "0") == "1":
        print("Deferred source completion marking until final editorial quota pass.")
    else:
        mark_editorial_sources_completed(theme, packages, metadata_path)

    return metadata_path


def cleanup_stale_editorial_outputs(theme, paths, date_key, packages):
    if os.getenv("SHORTFORM_PRESERVE_EDITORIAL_BACKLOG", "1") != "0":
        return

    output_dir = paths["final_videos_path"]
    archive_dir = paths.get("archive_path", os.path.join(paths["output_path"], "archive"))
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
            os.makedirs(archive_dir, exist_ok=True)
            target = os.path.abspath(os.path.join(archive_dir, filename))
            base, ext = os.path.splitext(target)
            counter = 2

            while os.path.exists(target):
                target = f"{base}_{counter}{ext}"
                counter += 1

            os.replace(filepath, target)
            print(f"Archived stale editorial output instead of deleting it: {os.path.basename(target)}")
        except OSError:
            pass


def run_exhaustive_rendered_editorial_for_theme(theme, paths, rendered_clips, date_key, start):
    print("Exhaust rendered editorial mode enabled: packaging every rendered clip that passes existing visual/editorial checks.")
    items = exhaustive_rendered_segment_items(theme, paths, rendered_clips)
    packages = []
    rejected_items = []

    print(f"Exhaustive rendered clip candidates: {len(items)}")

    for index, item in enumerate(items, start=1):
        print(
            f"Rendering exhaustive rendered clip #{index}/{len(items)}: "
            f"{item.get('channel_label', 'Podcast Channel')} - {item.get('source_title', '')}"
        )

        try:
            package = render_popular_segment_short(
                theme=theme,
                item=item,
                index=index,
                date_key=date_key,
                paths=paths,
            )
        except Exception as error:
            rejected_items.append({
                "type": "exhaustive_rendered_segment",
                "rank": index,
                "source_title": item.get("source_title", ""),
                "rejection_reasons": [f"render failed: {str(error).splitlines()[0][:260]}"],
            })
            print(
                f"Skipping exhaustive rendered clip #{index} after render failure: "
                f"{str(error).splitlines()[0][:260]}"
            )
            continue

        if not package_is_upload_ready(package):
            gate_flags = (package.get("editorial_gates") or {}).get("flags", [])
            render_reasons = (package.get("render_qc") or {}).get("rejection_reasons", [])
            rejection_reasons = list(render_reasons) + [f"editorial gate: {flag}" for flag in gate_flags]
            rejected_items.append({
                "type": "exhaustive_rendered_segment",
                "rank": index,
                "source_title": item.get("source_title", ""),
                "rejection_reasons": rejection_reasons,
            })
            reason_text = "; ".join(rejection_reasons) or "package did not pass upload-ready checks"
            print(f"Skipping rejected exhaustive rendered clip #{index} from upload metadata: {reason_text}")
            continue

        packages.append(package)

    brief = {
        "theme": theme,
        "date": date_key,
        "topic_count": 0,
        "popular_segment_count": len(packages),
        "rejected_count": len(rejected_items),
        "package_target": "exhaust_rendered_pool",
        "package_shortfall": 0,
        "package_target_met": True,
        "format": "exhaustive_rendered_clip_packaging",
        "content_strategy": "package every already-rendered clip that passes visual/editorial checks for the current production cycle",
        "items": [],
        "popular_segments": [
            {
                "rank": index,
                "source_title": package.get("source_title", ""),
                "channel_label": package.get("source_channel", ""),
                "source_video_url": package.get("source_video_url", ""),
                "output_file": package.get("video_file", ""),
                "title": package.get("title", ""),
                "caption": package.get("caption", ""),
                "script": package.get("editorial_script", ""),
                "content_signal": package.get("content_signal", {}),
            }
            for index, package in enumerate(packages, start=1)
        ],
        "rejected_items": rejected_items,
        "source_scan": {
            "watched_hours": 0,
            "hours_phrase": "",
            "source_count": len({item.get("source_state_key") for item in items}),
        },
        "recap_file": "",
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


def run_daily_editorial_for_theme(theme_name=DEFAULT_THEME):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    start = time.time()
    paths = ensure_theme(theme_name)
    theme = paths["theme"]
    date_key = os.getenv("SHORTFORM_EDITORIAL_DATE", datetime.now().strftime("%Y-%m-%d"))
    print(f"=== Generating ranked countdown for theme: {theme} ({date_key}) ===")

    rendered_clips = load_rendered_clip_reviews(paths["metadata_path"])

    if not rendered_clips:
        print("No rendered ranked clips found for editorial generation.\n")
        return 0

    if EXHAUST_RENDERED_EDITORIAL_CLIPS:
        return run_exhaustive_rendered_editorial_for_theme(theme, paths, rendered_clips, date_key, start)

    countdown_count = min(DAILY_TOPIC_COUNT, EDITORIAL_COUNTDOWN_SIZE)
    all_topic_groups = group_clips_by_topic(rendered_clips, theme=theme)

    if not all_topic_groups:
        print("No topic groups found for editorial generation.\n")
        return 0

    packages = []
    countdown_packages = []
    brief_items = []
    popular_brief_items = []
    rejected_items = []
    visually_rejected_countdown_sources = set()
    used_countdown_sources = set()
    reel_adjective = take_next_adjectives(theme, 1)[0]
    source_scan_context = build_countdown_context(
        theme,
        paths,
        rendered_clips,
        all_topic_groups[:countdown_count],
        reel_adjective,
    )
    print(
        f"Countdown setup: watched {format_hours_phrase(source_scan_context.get('watched_hours', 0))} "
        f"across {source_scan_context.get('source_count', 0)} {theme} interviews; angle: {reel_adjective}"
    )
    print(
        "Editorial package target: "
        f"{EDITORIAL_FINAL_PACKAGE_TARGET} upload-ready final package(s) "
        f"({UPLOAD_READY_TARGET_PER_THEME} upload queue + {RESERVE_TARGET_PER_THEME} reserve)"
    )

    countdown_attempts = 0
    countdown_attempt_limit = max(countdown_count * 4, min(len(all_topic_groups), countdown_count * 6))

    while len(countdown_packages) < countdown_count and countdown_attempts < countdown_attempt_limit:
        countdown_attempts += 1
        available_clips = [
            clip
            for clip in rendered_clips
            if clip_state_key(theme, clip) not in used_countdown_sources
        ]
        candidate_groups = group_clips_by_topic(available_clips, theme=theme)

        if not candidate_groups:
            break

        slot_rank = len(countdown_packages) + 1
        context_groups = candidate_groups[:countdown_count]
        context = build_countdown_context(theme, paths, available_clips, context_groups, reel_adjective)
        attach_countdown_context(context_groups, context)
        topic_item = context_groups[0]
        topic_item["_countdown_context"] = context
        topic_item["_total_count"] = countdown_count
        topic_item["_countdown_slot"] = countdown_slot_for_rank(slot_rank, countdown_count)
        adjective = reel_adjective
        topic_source_keys = source_keys_from_clips(theme, topic_item.get("clips") or [])
        print(f"Rendering countdown short #{topic_item['_countdown_slot']}: {adjective} - {topic_item['topic']}")
        try:
            package = render_editorial_short(
                theme=theme,
                topic_item=topic_item,
                rank=slot_rank,
                adjective=adjective,
                date_key=date_key,
                paths=paths,
            )
        except Exception as error:
            rejected_items.append({
                "type": "countdown",
                "countdown_slot": topic_item.get("_countdown_slot"),
                "topic": topic_item.get("topic", ""),
                "rejection_reasons": [f"render failed: {str(error).splitlines()[0][:260]}"],
            })
            print(
                f"Skipping countdown short #{topic_item.get('_countdown_slot')} after render failure: "
                f"{str(error).splitlines()[0][:260]}"
            )
            used_countdown_sources.update(topic_source_keys)
            continue

        if not package_is_upload_ready(package):
            gate_flags = (package.get("editorial_gates") or {}).get("flags", [])
            render_reasons = (package.get("render_qc") or {}).get("rejection_reasons", [])
            rejection_reasons = list(render_reasons) + [f"editorial gate: {flag}" for flag in gate_flags]
            rejected_items.append({
                "type": "countdown",
                "countdown_slot": topic_item["_countdown_slot"],
                "topic": topic_item["topic"],
                "rejection_reasons": rejection_reasons,
            })

            if any(
                re.search(r"(background|misses speaker|no-speaker|off-center|render_qc_failed)", reason, flags=re.I)
                for reason in rejection_reasons
            ):
                for clip in topic_item.get("clips") or []:
                    visually_rejected_countdown_sources.add(clip_state_key(theme, clip))

            used_countdown_sources.update(topic_source_keys)
            reason_text = "; ".join(rejection_reasons) or "package did not pass upload-ready checks"
            print(f"Skipping rejected countdown short #{topic_item['_countdown_slot']} from upload metadata: {reason_text}")
            continue

        used_countdown_sources.update(source_keys_from_clips(theme, selected_topic_clips(topic_item)))
        packages.append(package)
        countdown_packages.append(package)
        brief_items.append({
            "rank": slot_rank,
            "countdown_slot": topic_item["_countdown_slot"],
            "adjective": adjective,
            "topic": package.get("content_signal", {}).get("topic") or editorial_title_topic(topic_item["topic"]),
            "title": package.get("title", ""),
            "caption": package.get("caption", ""),
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

    if RENDER_POPULAR_SEGMENT_SHORTS and len(packages) < EDITORIAL_FINAL_PACKAGE_TARGET:
        raw_popular_items = popular_segment_items(theme, paths, rendered_clips)
        popular_items = []

        for item in raw_popular_items:
            if item.get("source_state_key") in visually_rejected_countdown_sources:
                rejected_items.append({
                    "type": "popular_segment",
                    "source_title": item.get("source_title", ""),
                    "rejection_reasons": ["source already failed countdown visual/background-lock QC"],
                })
                print(
                    "Skipping popular segment source already rejected by visual QC: "
                    f"{item.get('source_title', '')}"
                )
                continue

            if popular_item_duplicates_countdown(theme, item, countdown_packages):
                rejected_items.append({
                    "type": "popular_segment",
                    "source_title": item.get("source_title", ""),
                    "rejection_reasons": ["popular segment duplicates countdown source/topic"],
                })
                print(
                    "Skipping duplicate popular segment already covered by countdown: "
                    f"{item.get('source_title', '')}"
                )
                continue

            if clip_is_popular_segment_usable(item.get("clip") or {}):
                popular_items.append(item)
                continue

            rejected_items.append({
                "type": "popular_segment",
                "source_title": item.get("source_title", ""),
                "rejection_reasons": ["source clip failed strict popular-segment visual QC"],
            })
            print(
                "Skipping popular segment source with weak visual QC: "
                f"{item.get('source_title', '')}"
            )

        if popular_items:
            print(f"Rendering {len(popular_items)} most replayed/popular segment shorts...")

        for index, item in enumerate(popular_items, start=1):
            if len(packages) >= EDITORIAL_FINAL_PACKAGE_TARGET:
                print(
                    "Editorial package target reached; "
                    f"stopping popular-segment rendering at {len(packages)} ready package(s)."
                )
                break

            print(
                f"Rendering popular segment #{index}: "
                f"{item.get('channel_label', 'Podcast Channel')} - {item.get('source_title', '')}"
            )
            try:
                package = render_popular_segment_short(
                    theme=theme,
                    item=item,
                    index=index,
                    date_key=date_key,
                    paths=paths,
                )
            except Exception as error:
                rejected_items.append({
                    "type": "popular_segment",
                    "rank": index,
                    "source_title": item.get("source_title", ""),
                    "rejection_reasons": [f"render failed: {str(error).splitlines()[0][:260]}"],
                })
                print(
                    f"Skipping popular segment #{index} after render failure: "
                    f"{str(error).splitlines()[0][:260]}"
                )
                continue

            if not package_is_upload_ready(package):
                gate_flags = (package.get("editorial_gates") or {}).get("flags", [])
                render_reasons = (package.get("render_qc") or {}).get("rejection_reasons", [])
                rejection_reasons = list(render_reasons) + [f"editorial gate: {flag}" for flag in gate_flags]
                rejected_items.append({
                    "type": "popular_segment",
                    "rank": index,
                    "source_title": item.get("source_title", ""),
                    "rejection_reasons": rejection_reasons,
                })
                reason_text = "; ".join(rejection_reasons) or "package did not pass upload-ready checks"
                print(f"Skipping rejected popular segment #{index} from upload metadata: {reason_text}")
                continue

            packages.append(package)
            popular_brief_items.append({
                "rank": index,
                "source_title": item.get("source_title", ""),
                "channel_label": item.get("channel_label", ""),
                "source_video_url": item.get("source_video_url", ""),
                "popularity_score": item.get("popularity_score", 0),
                "output_file": package["video_file"],
                "title": package.get("title", ""),
                "caption": package.get("caption", ""),
                "script": package.get("editorial_script", ""),
                "content_signal": package.get("content_signal", {}),
            })
        if not popular_items:
            print("No replay/popularity-backed source segments found for popular segment shorts.")
    elif RENDER_POPULAR_SEGMENT_SHORTS:
        print(
            "Popular segment rendering skipped because the editorial package target "
            f"was already reached ({len(packages)}/{EDITORIAL_FINAL_PACKAGE_TARGET})."
        )

    if len(packages) < EDITORIAL_FINAL_PACKAGE_TARGET:
        print(
            "Editorial package target not fully met: "
            f"{len(packages)}/{EDITORIAL_FINAL_PACKAGE_TARGET} upload-ready package(s). "
            "This usually means the rendered usable source pool was too small after final QC."
        )

    package_shortfall = max(0, EDITORIAL_FINAL_PACKAGE_TARGET - len(packages))
    brief = {
        "theme": theme,
        "date": date_key,
        "topic_count": len(brief_items),
        "popular_segment_count": len(popular_brief_items),
        "rejected_count": len(rejected_items),
        "package_target": EDITORIAL_FINAL_PACKAGE_TARGET,
        "package_shortfall": package_shortfall,
        "package_target_met": package_shortfall == 0,
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
            "watched_hours": source_scan_context.get("watched_hours", 0),
            "hours_phrase": format_hours_phrase(source_scan_context.get("watched_hours", 0)),
            "source_count": source_scan_context.get("source_count", 0),
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
    parser = argparse.ArgumentParser(description="Generate ranked editorial shorts.")
    parser.add_argument("--theme", help="Optional theme to generate. Omit to run every active theme.")
    args = parser.parse_args()
    run_daily_editorial(theme=args.theme)
