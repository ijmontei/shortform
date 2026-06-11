import argparse
import json
import os
import random
import time

from theme_config import BASE_DIR, DEFAULT_THEME, discover_themes, ensure_theme, write_json_file


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
DEFAULT_YOUTUBE_CLIENT_ID = "690163065093-voe56q26ls3orenmr3e8s9ec0s4fjtv5.apps.googleusercontent.com"
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
TOKEN_FILE = os.path.join(BASE_DIR, "youtube_token.json")
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_UPLOAD_RETRIES = 5

CURRENT_THEME = None
UPLOAD_PATH = None
FINAL_METADATA_FILE = None


def configure_theme(theme_name):
    global CURRENT_THEME, UPLOAD_PATH, FINAL_METADATA_FILE

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    UPLOAD_PATH = theme_paths["upload_path"]
    FINAL_METADATA_FILE = theme_paths["final_metadata_file"]
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

    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


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

    if os.path.exists(TOKEN_FILE):
        credentials = Credentials.from_authorized_user_file(TOKEN_FILE, [YOUTUBE_UPLOAD_SCOPE])

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        client_config = get_oauth_client_config()

        if client_config is None:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, [YOUTUBE_UPLOAD_SCOPE])
        else:
            flow = InstalledAppFlow.from_client_config(client_config, [YOUTUBE_UPLOAD_SCOPE])

        credentials = flow.run_local_server(port=0, prompt="consent")

    with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


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
            "tags": [str(tag)[:500] for tag in tags][:15],
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


def mark_youtube_failed(package, error):
    package.setdefault("posting_status", {})["youtube_shorts"] = "failed"
    package.setdefault("platform_uploads", {})["youtube_shorts_last_error"] = {
        "message": str(error)[-1000:],
        "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def upload_youtube_for_theme(theme_name=DEFAULT_THEME, limit=None, force=False):
    configure_theme(theme_name)
    metadata = load_metadata()
    content = metadata.get("content", [])

    if not content:
        print(f"No upload-ready metadata found for theme '{CURRENT_THEME}'.")
        return 0

    youtube = get_authenticated_service()
    uploaded_count = 0

    for package in content:
        video_path = package.get("video_file", "")

        if not video_path or not os.path.exists(video_path):
            continue

        if clip_already_uploaded(package) and not force:
            print(f"Skipping already uploaded YouTube clip: {os.path.basename(video_path)}")
            continue

        if package.get("posting_status", {}).get("youtube_shorts") not in {"ready", "failed", "uploaded"}:
            continue

        print(f"Uploading private YouTube draft: {os.path.basename(video_path)}")

        try:
            response = upload_video(youtube, video_path, package)
            mark_youtube_uploaded(package, response)
            save_metadata(metadata)
            uploaded_count += 1
            print(f" -> Uploaded: https://www.youtube.com/watch?v={response['id']}")
        except Exception as error:
            mark_youtube_failed(package, error)
            save_metadata(metadata)
            print(f" -> YouTube upload failed: {error}")

        if limit is not None and uploaded_count >= limit:
            break

    print(f"YouTube uploads complete for '{CURRENT_THEME}'. Uploaded: {uploaded_count}")
    return uploaded_count


def upload_youtube(theme=None, limit=None, force=False):
    if theme:
        return upload_youtube_for_theme(theme_name=theme, limit=limit, force=force)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return upload_youtube_for_theme(theme_name=requested_theme, limit=limit, force=force)

    total_uploaded = 0

    for theme_name in discover_themes():
        total_uploaded += upload_youtube_for_theme(theme_name=theme_name, limit=limit, force=force)

    return total_uploaded


def parse_args():
    parser = argparse.ArgumentParser(description="Upload shortform clips to YouTube as private drafts.")
    parser.add_argument("--theme", help="Optional theme to upload. Omit this to upload every theme.")
    parser.add_argument("--limit", type=int, help="Optional max number of clips to upload per theme.")
    parser.add_argument("--force", action="store_true", help="Re-upload clips even if metadata has a YouTube video ID.")
    return parser.parse_args()


def main():
    args = parse_args()
    upload_youtube(theme=args.theme, limit=args.limit, force=args.force)


if __name__ == "__main__":
    main()
