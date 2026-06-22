import argparse
import json
import os
import random
import sys
import time

from theme_config import (
    BASE_DIR,
    DEFAULT_THEME,
    EXECUTED_FILE,
    clean_theme_name,
    discover_themes,
    ensure_theme,
    load_json_file,
    load_theme_config,
    mark_stage,
    write_json_file,
)


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
}
THEME_CHANNEL_HANDLES = {
    "comedy": "@TheJokeArchive",
    "finance": "@TheEconomistArchive",
}
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_UPLOAD_RETRIES = 5
DEFAULT_YOUTUBE_UPLOAD_LIMIT = int(os.getenv("SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT", "15"))

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


def configure_theme(theme_name):
    global CURRENT_THEME, UPLOAD_PATH, FINAL_METADATA_FILE, CURRENT_THEME_CONFIG

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


def get_authenticated_service():
    try:
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
        credentials = Credentials.from_authorized_user_file(token_file, YOUTUBE_SCOPES)

        if not credentials.has_scopes(YOUTUBE_SCOPES):
            print(f"Saved token is missing required YouTube scopes; reauthorizing {CURRENT_THEME}.")
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        client_config = get_oauth_client_config()

        if client_config is None:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, YOUTUBE_SCOPES)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, YOUTUBE_SCOPES)

        credentials = flow.run_local_server(port=0, prompt="consent")

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

    print(f"Authenticated YouTube channel for '{CURRENT_THEME}': {channel_label(authenticated_channel)}")


def clip_already_uploaded(package):
    youtube_status = package.get("posting_status", {}).get("youtube_shorts", "")
    youtube_result = package.get("platform_uploads", {}).get("youtube_shorts", {})
    return bool(youtube_result.get("video_id")) or youtube_status == "uploaded"


def build_youtube_body(package):
    youtube_package = package.get("platforms", {}).get("youtube_shorts", {})
    title = youtube_package.get("title") or package.get("title") or "Shortform clip"
    description = youtube_package.get("description") or package.get("description") or ""
    tags = youtube_package.get("tags") or package.get("tags") or []

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
            "privacyStatus": "private",
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

    try:
        payload = json.loads(error_text)
    except json.JSONDecodeError:
        return {reason for reason in FATAL_YOUTUBE_REASON_MESSAGES if reason in str(error)}

    reasons = set()

    for item in payload.get("error", {}).get("errors", []):
        reason = item.get("reason")

        if reason:
            reasons.add(reason)

    status = payload.get("error", {}).get("status", "")

    if status:
        reasons.add(status)

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
    "quotaExceeded": (
        "YouTube rejected the upload because the project quota is exhausted. "
        "Wait for quota to reset or request more quota in Google Cloud, then rerun with a small --limit."
    ),
}


def get_fatal_youtube_error_message(error):
    status = get_http_error_status(error)
    reasons = get_http_error_reasons(error)

    for reason, message in FATAL_YOUTUBE_REASON_MESSAGES.items():
        if reason in reasons:
            return message

    if status == 429:
        return FATAL_YOUTUBE_REASON_MESSAGES["rateLimitExceeded"]

    return None


def mark_youtube_uploaded(package, response):
    video_id = response["id"]
    package.setdefault("posting_status", {})["youtube_shorts"] = "uploaded"
    package.setdefault("platform_uploads", {})["youtube_shorts"] = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "privacy_status": "private",
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

    metadata = load_metadata()
    content = metadata.get("content", [])

    if not content:
        print(f"No upload-ready metadata found for theme '{CURRENT_THEME}'.")
        return 0

    youtube = get_authenticated_service()
    validate_authenticated_channel(youtube)
    uploaded_count = 0

    print(f"YouTube upload limit for this run/theme: {effective_limit or 'unlimited'}")

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

        if package.get("posting_status", {}).get("youtube_shorts") not in {"ready", "failed", "uploaded"}:
            remaining_content.append(package)
            continue

        print(f"Uploading private YouTube draft: {os.path.basename(video_path)}")

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
            save_metadata(metadata)
            print(f" -> YouTube upload failed: {error}")

            halt_message = get_fatal_youtube_error_message(error)

            if halt_message:
                raise YouTubeUploadHalted(halt_message) from error

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
    parser = argparse.ArgumentParser(description="Upload shortform clips to YouTube as private drafts.")
    parser.add_argument("--theme", help="Optional theme to upload.")
    parser.add_argument("--all", action="store_true", help="Upload every discovered theme.")
    parser.add_argument("--limit", type=int, help="Optional max number of clips to upload per theme.")
    parser.add_argument("--force", action="store_true", help="Re-upload clips even if metadata has a YouTube video ID.")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        upload_youtube(theme=args.theme, limit=args.limit, force=args.force, all_themes=args.all)
    except YouTubeUploadHalted as error:
        print(f"YouTube uploads halted: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
