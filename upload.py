import json
import os

from theme_config import DEFAULT_THEME, discover_themes, ensure_theme


# OAuth 2.0 details
CLIENT_SECRETS_FILE = "client_secrets.json"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
CURRENT_THEME = None
UPLOAD_PATH = None
METADATA_PATH = None
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0
To make this script work, you need to populate the client_secrets.json file.
"""


def configure_theme(theme_name):
    global CURRENT_THEME, UPLOAD_PATH, METADATA_PATH

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    UPLOAD_PATH = theme_paths["upload_path"]
    METADATA_PATH = theme_paths["metadata_path"]
    return theme_paths


configure_theme(os.getenv("SHORTFORM_THEME", DEFAULT_THEME))


def get_authenticated_service():
    try:
        from googleapiclient.discovery import build
        from oauth2client.client import flow_from_clientsecrets
        from oauth2client.file import Storage
        from oauth2client.tools import run_flow
    except ImportError as error:
        raise RuntimeError(
            "YouTube upload dependencies are missing. Install "
            "google-api-python-client and oauth2client to enable uploading."
        ) from error

    flow = flow_from_clientsecrets(
        CLIENT_SECRETS_FILE,
        scope=YOUTUBE_UPLOAD_SCOPE,
        message=MISSING_CLIENT_SECRETS_MESSAGE,
    )
    storage = Storage("oauth2.json")
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        credentials = run_flow(flow, storage)

    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


def upload_video(youtube, video_path, title, description, privacy_status, tags=None):
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as error:
        raise RuntimeError(
            "YouTube upload dependencies are missing. Install "
            "google-api-python-client to enable uploading."
        ) from error

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }

    insert_request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=256 * 1024, resumable=True),
    )

    return insert_request.execute()


def load_upload_manifest():
    manifest_path = os.path.join(METADATA_PATH, "_upload_manifest.json")

    if not os.path.exists(manifest_path) or os.path.getsize(manifest_path) == 0:
        return []

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as error:
        print(f"Could not read upload manifest: {error}")
        return []


def package_for_video(video_path, manifest):
    absolute_path = os.path.abspath(video_path)

    for item in manifest:
        if item.get("video_file") == absolute_path:
            return item

    return {}


def delete_file(file_path):
    try:
        os.remove(file_path)
        print(f"Deleted file: {file_path}")
    except Exception as error:
        print(f"Error deleting file: {error}")


def upload_function(theme=None):
    if theme:
        return upload_function_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return upload_function_for_theme(requested_theme)

    for theme_name in discover_themes():
        upload_function_for_theme(theme_name)


def upload_function_for_theme(theme_name):
    configure_theme(theme_name)

    try:
        youtube = get_authenticated_service()
    except RuntimeError as error:
        print(error)
        return

    if not os.path.isdir(UPLOAD_PATH):
        print(f"No upload folder for theme '{CURRENT_THEME}': {UPLOAD_PATH}")
        return

    manifest = load_upload_manifest()
    delete_after_upload = os.getenv("SHORTFORM_DELETE_AFTER_UPLOAD") == "1"

    for filename in os.listdir(UPLOAD_PATH):
        if not filename.endswith(".mp4"):
            continue

        video_path = os.path.join(UPLOAD_PATH, filename)
        package = package_for_video(video_path, manifest)
        youtube_package = package.get("platforms", {}).get("youtube_shorts", {})
        title = youtube_package.get("title") or package.get("title") or os.path.splitext(filename)[0]
        description = youtube_package.get("description") or package.get("description") or "Uploaded via shortform"
        tags = youtube_package.get("tags") or package.get("tags")
        privacy_status = youtube_package.get("privacy_status", "private")

        try:
            response = upload_video(
                youtube,
                video_path,
                title,
                description,
                privacy_status,
                tags=tags,
            )
            print("Video uploaded successfully!")
            print("Video ID:", response["id"])

            if delete_after_upload:
                delete_file(video_path)
        except Exception as error:
            print("An error occurred:", error)


if __name__ == "__main__":
    upload_function()
