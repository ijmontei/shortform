import argparse
import calendar
import json
import os
import random
import re
import sys
import time

from editorial_gates import evaluate_editorial_gates
from theme_config import (
    BASE_DIR,
    DEFAULT_THEME,
    EXECUTED_FILE,
    assert_theme_allowed_for_active_run,
    clean_theme_name,
    discover_themes,
    ensure_theme,
    load_json_file,
    load_theme_config,
    mark_stage,
    write_json_file,
)
from theme_profile import get_review_policy


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
DEFAULT_YOUTUBE_CLIENT_ID = "690163065093-9l55nu1kn2te6k1eqltn69bnpj872lke.apps.googleusercontent.com"
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BASE_DIR, "youtube_token.json")
THEME_TOKEN_FILES = {
    "comedy": os.path.join(BASE_DIR, "youtube_token_comedy.json"),
    "finance": os.path.join(BASE_DIR, "youtube_token_finance.json"),
    "health_fitness": os.path.join(BASE_DIR, "youtube_token_health_fitness.json"),
    "politics": os.path.join(BASE_DIR, "youtube_token_politics.json"),
    "popculture": os.path.join(BASE_DIR, "youtube_token_popculture.json"),
    "sports": os.path.join(BASE_DIR, "youtube_token_sports.json"),
    "gaming": os.path.join(BASE_DIR, "youtube_token_gaming.json"),
    "technology_ai": os.path.join(BASE_DIR, "youtube_token_technology_ai.json"),
    "truecrime": os.path.join(BASE_DIR, "youtube_token_truecrime.json"),
}
THEME_CHANNEL_HANDLES = {
    "comedy": "@TheJokeArchive",
    "finance": "@TheEconomistArchive",
    "health_fitness": "@HealthScienceArchive",
    "politics": "@CivicsArchive",
    "popculture": "@MainstreamArchive",
    "sports": "@SportsAthelticsArchive",
    "gaming": "@VideoGamerArchive",
    "technology_ai": "@TechAIArchive",
    "truecrime": "@CriminologyArchive",
}
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_UPLOAD_RETRIES = 5
DEFAULT_YOUTUBE_UPLOAD_LIMIT = int(os.getenv("SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT", "0"))
YOUTUBE_UPLOAD_COOLDOWN_FILE = os.path.join(BASE_DIR, "logs", "youtube_upload_cooldowns.json")
YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS = max(
    0.0,
    float(os.getenv("SHORTFORM_YOUTUBE_UPLOAD_LIMIT_COOLDOWN_HOURS", "24")) * 3600,
)
IGNORE_YOUTUBE_UPLOAD_COOLDOWN = os.getenv("SHORTFORM_IGNORE_YOUTUBE_UPLOAD_COOLDOWN", "0") == "1"

CURRENT_THEME = None
UPLOAD_PATH = None
FINAL_METADATA_FILE = None
CURRENT_THEME_CONFIG = {}


class YouTubeUploadHalted(RuntimeError):
    pass


def format_duration(seconds):
    seconds = max(0, float(seconds))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)

    if hours:
        return f"{hours}h {minutes}m {remainder:.1f}s"

    if minutes:
        return f"{minutes}m {remainder:.1f}s"

    return f"{remainder:.1f}s"


def utc_timestamp(epoch_seconds=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if epoch_seconds is None else epoch_seconds))


def parse_utc_timestamp(value):
    try:
        return calendar.timegm(time.strptime(str(value or ""), "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0.0


def configure_theme(theme_name):
    global CURRENT_THEME, UPLOAD_PATH, FINAL_METADATA_FILE, CURRENT_THEME_CONFIG

    theme_name = assert_theme_allowed_for_active_run(theme_name)
    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    UPLOAD_PATH = theme_paths["upload_path"]
    FINAL_METADATA_FILE = theme_paths["final_metadata_file"]
    CURRENT_THEME_CONFIG = load_theme_config(CURRENT_THEME)
    return theme_paths


def load_json(path, default):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def load_metadata():
    return load_json(FINAL_METADATA_FILE, {"theme": CURRENT_THEME, "content": []})


def save_metadata(metadata):
    metadata["theme"] = CURRENT_THEME
    write_json_file(FINAL_METADATA_FILE, metadata)


def get_oauth_client_config():
    if os.path.exists(CLIENT_SECRETS_FILE):
        return None

    client_id = os.getenv("YOUTUBE_CLIENT_ID", DEFAULT_YOUTUBE_CLIENT_ID).strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id:
        raise RuntimeError(
            "Missing YouTube OAuth client ID. Set YOUTUBE_CLIENT_ID or create client_secrets.json."
        )

    if not client_secret:
        raise RuntimeError(
            "Missing YouTube OAuth client secret. Download the Desktop app OAuth JSON from "
            "Google Cloud and save it as client_secrets.json, or set YOUTUBE_CLIENT_SECRET."
        )

    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_token_file():
    youtube_config = CURRENT_THEME_CONFIG.get("youtube", {}) if isinstance(CURRENT_THEME_CONFIG, dict) else {}
    configured_token_file = str(youtube_config.get("token_file", "")).strip()

    if configured_token_file:
        if os.path.isabs(configured_token_file):
            return configured_token_file

        return os.path.join(BASE_DIR, configured_token_file)

    if CURRENT_THEME in THEME_TOKEN_FILES:
        return THEME_TOKEN_FILES[CURRENT_THEME]

    return os.path.join(BASE_DIR, f"youtube_token_{clean_theme_name(CURRENT_THEME)}.json")


def get_expected_channel_handle():
    youtube_config = CURRENT_THEME_CONFIG.get("youtube", {}) if isinstance(CURRENT_THEME_CONFIG, dict) else {}
    configured_handle = str(youtube_config.get("channel_handle", "")).strip()
    return configured_handle or THEME_CHANNEL_HANDLES.get(CURRENT_THEME, "")


def theme_upload_route_label(theme_name):
    config = load_theme_config(theme_name)
    youtube = config.get("youtube") or {}
    configured_handle = str(youtube.get("channel_handle", "")).strip()
    return configured_handle or THEME_CHANNEL_HANDLES.get(clean_theme_name(theme_name), "")


def theme_has_upload_route(theme_name):
    return bool(theme_upload_route_label(theme_name))


def get_authenticated_service():
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "YouTube upload dependencies are missing. Run: "
            ".\\venv_313\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from error

    credentials = None
    token_file = get_token_file()

    if os.path.exists(token_file):
        try:
            credentials = Credentials.from_authorized_user_file(token_file, YOUTUBE_SCOPES)
        except (ValueError, RefreshError) as error:
            backup_token_file = f"{token_file}.invalid.{time.strftime('%Y%m%d_%H%M%S')}.bak"
            os.replace(token_file, backup_token_file)
            print(
                f"Saved token for {CURRENT_THEME} could not be read; "
                f"moved it to {backup_token_file} and will reauthorize."
            )
            credentials = None

        if credentials and not credentials.has_scopes(YOUTUBE_SCOPES):
            print(f"Saved token is missing required YouTube scopes; reauthorizing {CURRENT_THEME}.")
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            backup_token_file = f"{token_file}.revoked.{time.strftime('%Y%m%d_%H%M%S')}.bak"
            os.replace(token_file, backup_token_file)
            print(
                f"Saved token for {CURRENT_THEME} is expired or revoked; "
                f"moved it to {backup_token_file} and will reauthorize."
            )
            credentials = None

    if not credentials or not credentials.valid:
        client_config = get_oauth_client_config()

        if client_config is None:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, YOUTUBE_SCOPES)

        credentials = flow.run_local_server(
            port=0,
            prompt="consent",
            authorization_prompt_message=(
                "\nOpen this URL and choose the expected YouTube channel:\n{url}\n"
            ),
            success_message="YouTube authorization complete. You can close this tab.",
            open_browser=True,
        )

    with open(token_file, "w", encoding="utf-8") as token_handle:
        token_handle.write(credentials.to_json())

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


def channel_label(channel):
    snippet = channel.get("snippet", {})
    return snippet.get("customUrl") or snippet.get("title") or channel.get("id") or "unknown channel"


def get_channel_by_handle(youtube, handle):
    response = youtube.channels().list(part="snippet", forHandle=handle, maxResults=1).execute()
    channels = response.get("items", [])
    return channels[0] if channels else None


def validate_authenticated_channel(youtube):
    expected_handle = get_expected_channel_handle()

    if not expected_handle:
        raise YouTubeUploadHalted(
            f"No YouTube channel is configured for theme '{CURRENT_THEME}'. "
            f"Add youtube.channel_handle to src/themes/{CURRENT_THEME}.json."
        )

    response = youtube.channels().list(part="snippet", mine=True, maxResults=1).execute()
    channels = response.get("items", [])

    if not channels:
        raise YouTubeUploadHalted(
            f"No YouTube channel is available for the authenticated {CURRENT_THEME} account. "
            f"Open YouTube Studio, make sure {expected_handle} is active, delete {os.path.basename(get_token_file())}, "
            "and authorize again."
        )

    authenticated_channel = channels[0]
    expected_channel = get_channel_by_handle(youtube, expected_handle)

    if not expected_channel:
        raise YouTubeUploadHalted(
            f"Could not find expected YouTube channel {expected_handle}. Check the handle in upload.py."
        )

    if authenticated_channel.get("id") != expected_channel.get("id"):
        raise YouTubeUploadHalted(
            f"{CURRENT_THEME} is expected to upload to {expected_handle}, but the saved token is for "
            f"{channel_label(authenticated_channel)}. Delete {os.path.basename(get_token_file())} and authorize the correct channel."
        )

    print(f"Authenticated YouTube channel for '{CURRENT_THEME}': {channel_label(authenticated_channel)}", flush=True)


def clip_already_uploaded(package):
    youtube_status = package.get("posting_status", {}).get("youtube_shorts", "")
    youtube_result = package.get("platform_uploads", {}).get("youtube_shorts", {})
    return bool(youtube_result.get("video_id")) or youtube_status == "uploaded"


def require_review_approval_for_upload():
    return os.getenv(
        "SHORTFORM_REQUIRE_REVIEW_APPROVAL_FOR_UPLOAD",
        os.getenv("SHORTFORM_REQUIRE_REVIEW_APPROVAL_FOR_PRIVATE_UPLOAD", "0"),
    ) == "1"


def require_manual_approval_for_public_upload():
    return os.getenv("SHORTFORM_REQUIRE_MANUAL_APPROVAL_FOR_PUBLIC_UPLOAD", "0") == "1"


def package_privacy_status(package):
    youtube_package = (package.get("platforms") or {}).get("youtube_shorts") or {}
    privacy = (
        os.getenv("SHORTFORM_YOUTUBE_PRIVACY_STATUS", "")
        or youtube_package.get("privacy_status")
        or "public"
    )
    privacy = str(privacy or "public").strip().lower()

    if privacy not in {"private", "unlisted", "public"}:
        return "public"

    return privacy


MOJIBAKE_REPLACEMENTS = {
    "вЂ™": "'",
    "вЂ": "'",
    "вЂњ": '"',
    "вЂќ": '"',
    "вЂ“": "-",
    "вЂ”": "-",
    "вЂ¦": "...",
    "Â": "",
}

MOJIBAKE_REPLACEMENTS.update({
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

PUBLIC_THEME_LABELS = {
    "comedy": "Comedy",
    "finance": "Finance",
    "gaming": "Gaming",
    "health_fitness": "Health & Fitness",
    "politics": "Politics",
    "popculture": "Pop Culture",
    "sports": "Sports",
    "technology_ai": "Technology AI",
    "truecrime": "True Crime",
}


def clean_public_text(value):
    text = str(value or "")

    for broken, fixed in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken, fixed)

    text = re.sub(r"\?{2,}\s*s\b", "'s", text)
    text = text.replace("???", "")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[\u0400-\u04FF]+", "", text)
    text = re.sub(r"^\?+\s*", "", text)
    text = re.sub(r"\s+([:;,.!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_public_text(value, max_length):
    text = clean_public_text(value)

    if len(text) <= max_length:
        return text

    return text[: max(0, max_length - 1)].rstrip(" ,.;:-") + "..."


def title_looks_machine_generated(title):
    lower = clean_public_text(title).lower()

    if not lower:
        return True

    if "в" in lower or "�" in lower:
        return True

    awkward_patterns = [
        r"\bbehind\s+happens\b",
        r"\bbehind\s+(are|is|was|were|has|have|had|does|do|did|this|that|the)\b",
        r"\bbehind\s+.*\s+is$",
        r"\bbehind\s+openai\s+mark\s+chen$",
        r"\bwhy\s+.+\s+matters$",
        r"\bevidence\s+question\s+around\b",
        r"\bcase\s+moment\s+inside\b",
        r"\bdetail\s+that\s+changes\s+the\s+case\b",
        r"\bpop\s+culture\s+missed\b",
        r"^the\s+builders\s+are\s+debating$",
    ]

    return any(re.search(pattern, lower) for pattern in awkward_patterns)


def package_first_rank_signal(package):
    rank_signals = (package or {}).get("rank_signals") or {}
    if isinstance(rank_signals, dict):
        return rank_signals
    if isinstance(rank_signals, list):
        return next((item for item in rank_signals if isinstance(item, dict)), {})
    return {}


def fallback_upload_title(package):
    signal = package.get("content_signal") or {}
    rank_signals = package_first_rank_signal(package)
    topic = (
        signal.get("topic")
        or package.get("caption")
        or package.get("hook_reason")
        or package.get("source_title")
        or "Podcast moment"
    )
    topic = re.sub(r"^daily\s+.+?\s+theme:\s*", "", str(topic), flags=re.I)
    topic = compact_public_text(topic, 58).strip(" .:-")
    theme_key = clean_theme_name(package.get("theme") or CURRENT_THEME or "podcast")
    theme = PUBLIC_THEME_LABELS.get(theme_key, str(theme_key).replace("_", " ").title())
    content_format = str(package.get("content_format") or "")

    if content_format.startswith("daily_editorial"):
        total = int(rank_signals.get("countdown_total") or signal.get("total_count") or 0)
        slot = int(rank_signals.get("countdown_slot") or signal.get("countdown_slot") or 0)
        adjective = clean_public_text(rank_signals.get("editorial_adjective") or signal.get("adjective") or "best")

        if total and slot:
            return compact_public_text(f"#{slot} of {total}: {adjective.title()} {theme} Moment", 96)

        return compact_public_text(f"{adjective.title()} {theme} Moment: {topic}", 96)

    if content_format == "popular_segment_short":
        source = clean_public_text((signal.get("source") or rank_signals.get("popular_segment_signal_source") or "")).lower()
        prefix = "Most Replayed" if "heatmap" in source else "Most Popular"
        return compact_public_text(f"{prefix}: {topic}", 96)

    channel = clean_public_text(package.get("source_channel") or "")

    if channel and channel.lower() not in topic.lower():
        return compact_public_text(f"{topic} | {channel}", 96)

    return compact_public_text(topic, 96) or "Shortform clip"


def sanitize_editorial_upload_title(package, title):
    try:
        import daily_editorial
    except Exception:
        return title

    signal = package.get("content_signal") or {}
    first_rank_signal = package_first_rank_signal(package)
    theme = clean_theme_name(package.get("theme") or CURRENT_THEME or "")
    content_format = "popular" if package.get("content_format") == "popular_segment_short" else "countdown"
    topic = signal.get("topic") or package.get("caption") or package.get("hook_reason") or title
    source_title = package.get("source_title", "") or first_rank_signal.get("source_title", "")
    channel = package.get("source_channel", "") or first_rank_signal.get("source_channel", "")
    clip = {
        "suggested_title": package.get("title") or title,
        "source_title": source_title,
        "source_channel": channel,
        "transcript_excerpt": package.get("transcript_excerpt", ""),
        "topic_fingerprint": package.get("topic_fingerprint") or first_rank_signal.get("topic_fingerprint") or [],
    }
    return daily_editorial.sanitize_social_title(
        theme,
        title,
        topic,
        clip=clip,
        source_title=source_title,
        channel=channel,
        content_format=content_format,
    )


def sanitize_youtube_metadata(package):
    package = dict(package or {})
    platforms = dict(package.get("platforms") or {})
    youtube_package = dict(platforms.get("youtube_shorts") or {})

    title = clean_public_text(youtube_package.get("title") or package.get("title") or "")

    if title_looks_machine_generated(title):
        title = fallback_upload_title(package)

    title = sanitize_editorial_upload_title(package, title)
    title = compact_public_text(title, 100)
    description = clean_public_text(youtube_package.get("description") or package.get("description") or "")
    tags = youtube_package.get("tags") or package.get("tags") or []
    tags = [compact_public_text(tag, 500) for tag in tags if compact_public_text(tag, 500)]

    package["title"] = title
    package["description"] = description
    package["tags"] = tags
    youtube_package["title"] = title
    youtube_package["description"] = description
    youtube_package["tags"] = tags
    platforms["youtube_shorts"] = youtube_package
    package["platforms"] = platforms
    return package


def package_with_effective_youtube_metadata(package):
    return sanitize_youtube_metadata(package)


def refresh_package_render_qc(package):
    video_file = package.get("video_file", "")

    if not video_file or not os.path.exists(video_file):
        return package

    try:
        import clip_generation

        frame_qc = clip_generation.analyze_final_frame_path(video_file, max_samples=24)
    except Exception as error:
        existing_qc = dict(package.get("render_qc") or {})
        existing_qc["passed"] = False
        existing_qc["rejected"] = True
        existing_qc["flags"] = sorted(set(
            list(existing_qc.get("flags") or [])
            + [f"upload preflight frame QA failed: {error}"]
        ))
        existing_qc.setdefault("rejection_reasons", []).append(
            f"upload preflight frame QA failed: {error}"
        )
        package["render_qc"] = existing_qc
        return package

    existing_qc = dict(package.get("render_qc") or {})
    existing_flags = list(existing_qc.get("flags") or [])
    existing_rejections = list(existing_qc.get("rejection_reasons") or [])
    frame_flags = list(frame_qc.get("flags") or [])
    rejections = list(existing_rejections)
    hard_upload_flags = {
        "could not open final render",
        "no final render frames",
        "no readable final frames",
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
        "probable background lock instead of speaker",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
        "probable flat-surface false face lock",
        "probable small-object/background face lock",
        "probable broadcast/b-roll montage instead of speaker clip",
        "subject severely off-center in final crop",
    }

    for flag in sorted(set(frame_flags) & hard_upload_flags):
        if flag not in rejections:
            rejections.append(flag)

    passed = not rejections and bool(existing_qc.get("passed", True))

    package["render_qc"] = {
        **existing_qc,
        "frame_qc_version": frame_qc.get("frame_qc_version", existing_qc.get("frame_qc_version", "")),
        "passed": passed,
        "rejected": bool(rejections) or bool(existing_qc.get("rejected", False)),
        "flags": sorted(set(existing_flags + frame_flags + rejections)),
        "visual_quality_score": frame_qc.get(
            "visual_quality_score",
            existing_qc.get("visual_quality_score", 0.0),
        ),
        "frame_path": frame_qc,
        "rejection_reasons": rejections,
        "render_strategy": existing_qc.get("render_strategy", "upload_preflight_frame_audit"),
        "upload_preflight_refreshed": True,
    }
    return package


def audio_rejection_reasons(audio_qc):
    flags = set((audio_qc or {}).get("flags") or [])
    hard_flags = {
        "audio start is empty",
        "no clear audio onset in first five seconds",
        "slow audio/narration start",
        "possible clipped/distorted intro audio",
    }
    return sorted(flags & hard_flags)


def refresh_package_intro_audio_qc(package):
    video_file = package.get("video_file", "")

    if not video_file or not os.path.exists(video_file):
        return package

    try:
        import content_qc

        audio_qc = content_qc.analyze_audio_start(video_file)
    except Exception as error:
        audio_qc = {
            "flags": [f"upload preflight intro audio QA failed: {error}"],
        }

    render_qc = dict(package.get("render_qc") or {})
    existing_flags = list(render_qc.get("flags") or [])
    existing_rejections = list(render_qc.get("rejection_reasons") or [])
    audio_flags = list(audio_qc.get("flags") or [])
    rejections = list(existing_rejections)

    for reason in audio_rejection_reasons(audio_qc):
        if reason not in rejections:
            rejections.append(reason)

    if any(flag.startswith("upload preflight intro audio QA failed") for flag in audio_flags):
        if "upload preflight intro audio QA failed" not in rejections:
            rejections.append("upload preflight intro audio QA failed")

    render_qc["intro_audio"] = audio_qc
    render_qc["flags"] = sorted(set(existing_flags + audio_flags + rejections))
    render_qc["rejection_reasons"] = rejections
    render_qc["rejected"] = bool(rejections) or bool(render_qc.get("rejected", False))
    render_qc["passed"] = not rejections and bool(render_qc.get("passed", True))
    render_qc["upload_preflight_audio_refreshed"] = True
    package["render_qc"] = render_qc
    return package


def review_skip_reason(package):
    refresh_package_render_qc(package)
    refresh_package_intro_audio_qc(package)
    review = package.get("review") or {}
    youtube_status = package.get("posting_status", {}).get("youtube_shorts", "")
    gate_package = package_with_effective_youtube_metadata(package)
    theme = clean_theme_name(package.get("theme") or CURRENT_THEME or "")
    editorial_gates = evaluate_editorial_gates(theme, gate_package)
    privacy = package_privacy_status(package)
    review_policy = get_review_policy(theme)

    if review.get("rejected") or youtube_status == "rejected":
        reason = review.get("rejection_reason", "")
        return f"rejected by review{': ' + reason if reason else ''}"

    if package.get("upload_ready_requires_burned_captions", True) and not package.get("content_has_burned_captions"):
        return "missing burned-in captions"

    if not editorial_gates.get("passed", True):
        return f"editorial gates failed: {', '.join(editorial_gates.get('flags') or [])}"

    if (
        privacy == "public"
        and require_manual_approval_for_public_upload()
        and review_policy.get("require_manual_approval_before_public", True)
        and not review.get("approved")
    ):
        return f"manual review approval required before {privacy} upload"

    if review.get("needs_revision") or youtube_status == "needs_revision":
        requests = review.get("requests") or []
        action = requests[-1].get("action", "revision") if requests else "revision"
        return f"waiting for requested {action}"

    if require_review_approval_for_upload() and not review.get("approved"):
        return "waiting for manual review approval"

    return ""


def force_can_bypass_review_skip(package, blocked_reason):
    if not blocked_reason:
        return True

    privacy = package_privacy_status(package)

    if privacy != "private":
        return False

    protected_reasons = [
        "editorial gates failed",
        "rejected by review",
        "waiting for requested",
    ]
    return not any(str(blocked_reason).startswith(reason) for reason in protected_reasons)


def build_youtube_body(package):
    package = sanitize_youtube_metadata(package)
    youtube_package = package.get("platforms", {}).get("youtube_shorts", {})
    title = youtube_package.get("title") or package.get("title") or "Shortform clip"
    description = youtube_package.get("description") or package.get("description") or ""
    tags = youtube_package.get("tags") or package.get("tags") or []
    privacy_status = package_privacy_status(package)

    if "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts".strip()

    return {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": [str(tag)[:500] for tag in tags][:25],
            "categoryId": str(youtube_package.get("category_id", "22")),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }


def upload_video(youtube, video_path, package):
    try:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as error:
        raise RuntimeError(
            "YouTube upload dependencies are missing. Run: "
            ".\\venv_313\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from error

    body = build_youtube_body(package)
    insert_request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(
            video_path,
            chunksize=8 * 1024 * 1024,
            resumable=True,
        ),
    )

    response = None
    retry = 0

    while response is None:
        try:
            _, response = insert_request.next_chunk()
        except HttpError as error:
            status = getattr(error.resp, "status", None)

            if status not in RETRIABLE_STATUS_CODES or retry >= MAX_UPLOAD_RETRIES:
                raise

            retry += 1
            sleep_seconds = min(60, (2 ** retry) + random.random())
            print(f" -> YouTube upload retry {retry}/{MAX_UPLOAD_RETRIES} in {sleep_seconds:.1f}s")
            time.sleep(sleep_seconds)

    return response


def get_http_error_status(error):
    response = getattr(error, "resp", None)
    return getattr(response, "status", None)


def get_http_error_text(error):
    content = getattr(error, "content", b"")

    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")

    return str(content or error)


def get_http_error_reasons(error):
    error_text = get_http_error_text(error)
    combined_text = f"{error_text}\n{error}"

    try:
        payload = json.loads(error_text)
    except json.JSONDecodeError:
        return {reason for reason in FATAL_YOUTUBE_REASON_MESSAGES if reason in combined_text}

    reasons = set()

    for item in payload.get("error", {}).get("errors", []):
        reason = item.get("reason")

        if reason:
            reasons.add(reason)

    status = payload.get("error", {}).get("status", "")

    if status:
        reasons.add(status)

    for reason in FATAL_YOUTUBE_REASON_MESSAGES:
        if reason in combined_text:
            reasons.add(reason)

    return reasons


FATAL_YOUTUBE_REASON_MESSAGES = {
    "youtubeSignupRequired": (
        "The Google account authorized successfully, but it does not have an active YouTube channel. "
        "Open YouTube Studio with that account, create/activate the channel, delete the theme token file, "
        "then run the uploader again."
    ),
    "rateLimitExceeded": (
        "YouTube rejected the upload because the project hit the video upload rate limit. "
        "Wait a few minutes, then rerun with --limit 1 or another small limit."
    ),
    "uploadLimitExceeded": (
        "YouTube rejected the upload because the channel or account hit its upload limit. "
        "Wait for YouTube's upload window to reset, then rerun upload.py or run.py; "
        "qualified files that were not uploaded will stay queued."
    ),
    "quotaExceeded": (
        "YouTube rejected the upload because the project quota is exhausted. "
        "Wait for quota to reset or request more quota in Google Cloud, then rerun with a small --limit."
    ),
}


def get_fatal_youtube_error_message(error):
    status = get_http_error_status(error)
    reasons = get_http_error_reasons(error)
    error_text = f"{get_http_error_text(error)}\n{error}"

    if "exceeded the number of videos" in error_text:
        reasons.add("uploadLimitExceeded")

    for reason, message in FATAL_YOUTUBE_REASON_MESSAGES.items():
        if reason in reasons:
            return message

    if status == 429:
        return FATAL_YOUTUBE_REASON_MESSAGES["rateLimitExceeded"]

    return None


def load_upload_cooldowns():
    payload = load_json(YOUTUBE_UPLOAD_COOLDOWN_FILE, {"themes": {}})

    if not isinstance(payload, dict):
        payload = {"themes": {}}

    payload.setdefault("themes", {})
    return payload


def save_upload_cooldowns(payload):
    os.makedirs(os.path.dirname(YOUTUBE_UPLOAD_COOLDOWN_FILE), exist_ok=True)
    write_json_file(YOUTUBE_UPLOAD_COOLDOWN_FILE, payload)


def upload_cooldown_key():
    return CURRENT_THEME or DEFAULT_THEME


def upload_limit_error_details_from_package(package):
    error_payload = ((package.get("platform_uploads") or {}).get("youtube_shorts_last_error") or {})
    message = str(error_payload.get("message") or "")

    if "uploadLimitExceeded" not in message and "exceeded the number of videos" not in message:
        return None

    failed_at = parse_utc_timestamp(error_payload.get("failed_at"))

    if failed_at <= 0:
        failed_at = time.time()

    return {
        "reason": "uploadLimitExceeded",
        "message": message[-1000:],
        "failed_at_epoch": failed_at,
        "failed_at": utc_timestamp(failed_at),
        "resume_after_epoch": failed_at + YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS,
        "resume_after": utc_timestamp(failed_at + YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS),
    }


def infer_upload_limit_cooldown_from_metadata(metadata):
    latest = None

    for package in (metadata or {}).get("content", []):
        if ((package.get("posting_status") or {}).get("youtube_shorts") or "").lower() != "failed":
            continue

        details = upload_limit_error_details_from_package(package)

        if not details:
            continue

        if latest is None or details["failed_at_epoch"] > latest["failed_at_epoch"]:
            latest = details

    return latest


def record_upload_limit_cooldown(reason, message="", failed_at_epoch=None):
    if reason != "uploadLimitExceeded" or YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS <= 0:
        return None

    failed_at_epoch = failed_at_epoch or time.time()
    resume_after_epoch = failed_at_epoch + YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS
    payload = load_upload_cooldowns()
    key = upload_cooldown_key()
    payload["themes"][key] = {
        "theme": CURRENT_THEME,
        "channel_handle": get_expected_channel_handle(),
        "reason": reason,
        "message": str(message or "")[-1000:],
        "failed_at": utc_timestamp(failed_at_epoch),
        "resume_after": utc_timestamp(resume_after_epoch),
        "cooldown_hours": round(YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS / 3600, 3),
        "updated_at": utc_timestamp(),
    }
    save_upload_cooldowns(payload)
    return payload["themes"][key]


def active_upload_cooldown(metadata=None):
    if IGNORE_YOUTUBE_UPLOAD_COOLDOWN or YOUTUBE_UPLOAD_LIMIT_COOLDOWN_SECONDS <= 0:
        return None

    now = time.time()
    payload = load_upload_cooldowns()
    key = upload_cooldown_key()
    entry = payload.get("themes", {}).get(key)

    if entry:
        resume_after_epoch = parse_utc_timestamp(entry.get("resume_after"))

        if resume_after_epoch > now:
            return {
                **entry,
                "remaining_seconds": resume_after_epoch - now,
                "source": "cooldown_file",
            }

    inferred = infer_upload_limit_cooldown_from_metadata(metadata or {})

    if inferred and inferred["resume_after_epoch"] > now:
        entry = record_upload_limit_cooldown(
            inferred["reason"],
            message=inferred.get("message", ""),
            failed_at_epoch=inferred["failed_at_epoch"],
        )
        return {
            **(entry or inferred),
            "remaining_seconds": inferred["resume_after_epoch"] - now,
            "source": "metadata",
        }

    return None


def mark_youtube_uploaded(package, response):
    video_id = response["id"]
    privacy_status = package_privacy_status(package)
    package.setdefault("posting_status", {})["youtube_shorts"] = "uploaded"
    package.setdefault("platform_uploads", {})["youtube_shorts"] = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy_status": privacy_status,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    package.setdefault("platform_metrics", {}).setdefault("youtube_shorts", {})
    package["platform_metrics"]["youtube_shorts"]["posted"] = True


def mark_executed_uploaded(package, response):
    source_state_key = package.get("source_state_key", "")

    if not source_state_key:
        return

    executed = load_json_file(EXECUTED_FILE, {})

    if not isinstance(executed, dict):
        executed = {}

    existing = executed.get(source_state_key, {})
    youtube_uploads = existing.get("youtube_uploads", [])
    video_id = response.get("id", "")
    video_file = package.get("video_file", "")

    if video_id and not any(item.get("video_id") == video_id for item in youtube_uploads):
        youtube_uploads.append({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": package.get("title", ""),
            "deleted_local_file": os.path.abspath(video_file) if video_file else "",
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    final_video_files = [
        path
        for path in existing.get("final_video_files", [])
        if os.path.abspath(path) != os.path.abspath(video_file)
    ]

    updated = {
        **existing,
        "theme": package.get("theme", CURRENT_THEME),
        "video_url": package.get("source_video_url", existing.get("video_url", "")),
        "title": package.get("source_title", existing.get("title", "")),
        "funnel_status": "uploaded",
        "upload_status": "uploaded",
        "youtube_uploads": youtube_uploads,
        "final_video_files": final_video_files,
    }
    mark_stage(updated, "youtube_uploaded")
    executed[source_state_key] = updated
    write_json_file(EXECUTED_FILE, executed)


def delete_uploaded_video_file(package):
    video_file = package.get("video_file", "")

    if not video_file:
        return False

    absolute_path = os.path.abspath(video_file)
    upload_root = os.path.abspath(UPLOAD_PATH)

    if os.path.commonpath([absolute_path, upload_root]) != upload_root:
        return False

    if not os.path.exists(absolute_path):
        return False

    os.remove(absolute_path)
    print(f" -> Deleted uploaded local file: {os.path.basename(absolute_path)}")
    return True


def mark_youtube_failed(package, error):
    package.setdefault("posting_status", {})["youtube_shorts"] = "failed"
    package.setdefault("platform_uploads", {})["youtube_shorts_last_error"] = {
        "message": str(error)[-1000:],
        "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def upload_youtube_for_theme(theme_name=DEFAULT_THEME, limit=None, force=False):
    upload_start = time.time()
    configure_theme(theme_name)
    effective_limit = limit

    if effective_limit is None and DEFAULT_YOUTUBE_UPLOAD_LIMIT > 0:
        effective_limit = DEFAULT_YOUTUBE_UPLOAD_LIMIT

    if not get_expected_channel_handle():
        print(
            f"Skipping YouTube upload for generation-only theme '{CURRENT_THEME}'. "
            f"Add youtube.channel_handle to src/themes/{CURRENT_THEME}.json to enable uploads."
        )
        return 0

    metadata = load_metadata()
    content = metadata.get("content", [])

    if not content:
        print(f"No upload-ready metadata found for theme '{CURRENT_THEME}'.")
        return 0

    cooldown = active_upload_cooldown(metadata)

    if cooldown:
        print(
            f"YouTube upload skipped for '{CURRENT_THEME}' because the last upload-limit "
            f"error is still cooling down. Estimated retry after: {cooldown.get('resume_after')} "
            f"({format_duration(cooldown.get('remaining_seconds', 0))} remaining)."
        )
        return 0

    youtube = get_authenticated_service()
    validate_authenticated_channel(youtube)
    uploaded_count = 0

    print(f"YouTube upload run cap for this theme: {effective_limit or 'unlimited'}")

    remaining_content = []

    for index, package in enumerate(content):
        video_path = package.get("video_file", "")

        if not video_path or not os.path.exists(video_path):
            if not clip_already_uploaded(package):
                remaining_content.append(package)
            continue

        if clip_already_uploaded(package) and not force:
            print(f"Skipping already uploaded YouTube clip: {os.path.basename(video_path)}")
            delete_uploaded_video_file(package)
            continue

        blocked_reason = review_skip_reason(package)

        if blocked_reason and (not force or not force_can_bypass_review_skip(package, blocked_reason)):
            print(f"Skipping YouTube clip: {os.path.basename(video_path)} ({blocked_reason})")
            remaining_content.append(package)
            continue

        if package.get("posting_status", {}).get("youtube_shorts") not in {"ready", "failed", "uploaded"}:
            remaining_content.append(package)
            continue

        privacy_status = package_privacy_status(package)
        print(f"Uploading {privacy_status} YouTube Short: {os.path.basename(video_path)}")

        try:
            item_start = time.time()
            response = upload_video(youtube, video_path, package)
            mark_youtube_uploaded(package, response)
            mark_executed_uploaded(package, response)
            delete_uploaded_video_file(package)
            save_metadata(metadata)
            uploaded_count += 1
            print(
                f" -> Uploaded: https://www.youtube.com/watch?v={response['id']} "
                f"in {format_duration(time.time() - item_start)}"
            )
        except Exception as error:
            mark_youtube_failed(package, error)
            remaining_content.append(package)
            print(f" -> YouTube upload failed: {error}")

            halt_message = get_fatal_youtube_error_message(error)

            if halt_message:
                reasons = get_http_error_reasons(error)
                if "uploadLimitExceeded" in reasons:
                    cooldown = record_upload_limit_cooldown(
                        "uploadLimitExceeded",
                        message=str(error),
                    )

                    if cooldown:
                        halt_message = (
                            f"{halt_message} Estimated retry after {cooldown.get('resume_after')}."
                        )

                remaining_content.extend(content[index + 1:])
                metadata["content"] = remaining_content
                save_metadata(metadata)
                raise YouTubeUploadHalted(halt_message) from error

            save_metadata(metadata)

        if effective_limit is not None and uploaded_count >= effective_limit:
            remaining_content.extend(content[index + 1:])
            break

    metadata["content"] = remaining_content
    save_metadata(metadata)
    print(
        f"YouTube uploads complete for '{CURRENT_THEME}'. "
        f"Uploaded: {uploaded_count}. Took {format_duration(time.time() - upload_start)}"
    )
    return uploaded_count


def authorize_youtube_for_theme(theme_name=DEFAULT_THEME):
    configure_theme(theme_name)

    if not get_expected_channel_handle():
        raise YouTubeUploadHalted(
            f"No YouTube channel is configured for theme '{CURRENT_THEME}'. "
            f"Add youtube.channel_handle to src/themes/{CURRENT_THEME}.json to create a token."
        )

    token_file = get_token_file()
    print(f"Authorizing YouTube channel for theme '{CURRENT_THEME}'.", flush=True)
    print(f"Expected channel: {get_expected_channel_handle()}", flush=True)
    print(f"Token file: {token_file}", flush=True)
    youtube = get_authenticated_service()
    validate_authenticated_channel(youtube)
    print(f"YouTube token ready: {token_file}", flush=True)
    return token_file


def upload_youtube(theme=None, limit=None, force=False, all_themes=False):
    if theme:
        return upload_youtube_for_theme(theme_name=theme, limit=limit, force=force)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return upload_youtube_for_theme(theme_name=requested_theme, limit=limit, force=force)

    if not all_themes:
        print("No theme specified. Use --theme THEME for a targeted upload, or --all to upload every theme.")
        return 0

    total_uploaded = 0

    for theme_name in discover_themes():
        total_uploaded += upload_youtube_for_theme(theme_name=theme_name, limit=limit, force=force)

    return total_uploaded


def parse_args():
    parser = argparse.ArgumentParser(description="Upload shortform clips to YouTube with each theme's configured privacy.")
    parser.add_argument("--theme", help="Optional theme to upload.")
    parser.add_argument("--all", action="store_true", help="Upload every discovered theme.")
    parser.add_argument("--limit", type=int, help="Optional max number of clips to upload per theme.")
    parser.add_argument("--force", action="store_true", help="Re-upload clips even if metadata has a YouTube video ID.")
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Create or refresh the OAuth token for a theme, validate the channel, and exit without uploading.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        if args.auth_only:
            if args.all:
                raise YouTubeUploadHalted("--auth-only must be run with one --theme at a time.")

            if not args.theme and not os.getenv("SHORTFORM_THEME"):
                raise YouTubeUploadHalted("--auth-only requires --theme THEME.")

            authorize_youtube_for_theme(theme_name=args.theme or os.getenv("SHORTFORM_THEME"))
            return

        upload_youtube(theme=args.theme, limit=args.limit, force=args.force, all_themes=args.all)
    except YouTubeUploadHalted as error:
        print(f"YouTube uploads halted: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
