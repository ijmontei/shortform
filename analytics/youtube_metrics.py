import argparse
import datetime as dt
import os
import time

from analytics.performance_scoring import normalize_metrics, performance_score
from theme_config import BASE_DIR, clean_theme_name, discover_themes, ensure_theme, load_json_file, load_theme_config, write_json_file
from theme_profile import load_theme_profile


YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
YOUTUBE_ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_ANALYTICS_SCOPES = [YOUTUBE_READONLY_SCOPE, YOUTUBE_ANALYTICS_READONLY_SCOPE]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
YOUTUBE_ANALYTICS_SERVICE_NAME = "youtubeAnalytics"
YOUTUBE_ANALYTICS_API_VERSION = "v2"
DEFAULT_YOUTUBE_CLIENT_ID = "690163065093-9l55nu1kn2te6k1eqltn69bnpj872lke.apps.googleusercontent.com"
CLIENT_SECRETS_FILE = os.path.join(BASE_DIR, "client_secrets.json")
METRICS_PATH = os.path.join(BASE_DIR, "logs", "analytics")
ANALYTICS_METRICS = [
    "views",
    "engagedViews",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
]


def metric_record_from_package(package, observed_metrics=None):
    observed_metrics = normalize_metrics(observed_metrics or {})
    experiment = package.get("experiment") or {}
    rank_signals = package.get("rank_signals") or {}
    content_signal = package.get("content_signal") or {}
    profile = load_theme_profile(package.get("theme", ""))
    metadata_style = profile.get("metadata_style") or {}
    source_channel = (
        package.get("source_channel")
        or package.get("channel_label")
        or rank_signals.get("source_channel")
        or content_signal.get("channel_label")
        or ""
    )
    source_title = (
        package.get("source_title")
        or rank_signals.get("source_title")
        or content_signal.get("source_title")
        or ""
    )
    record = {
        "video_id": ((package.get("platform_uploads") or {}).get("youtube_shorts") or {}).get("video_id", ""),
        "theme": package.get("theme", ""),
        "content_format": package.get("content_format", ""),
        "source_channel": source_channel,
        "source_show": source_channel or source_title,
        "source_title": source_title,
        "source_video_url": package.get("source_video_url", ""),
        "source_tier": package.get("source_tier", rank_signals.get("source_tier", "")),
        "routing_status": package.get("routing_status", rank_signals.get("routing_status", "")),
        "origin_theme": package.get("origin_theme", rank_signals.get("origin_theme", "")),
        "routed_from_theme": package.get("routed_from_theme", rank_signals.get("routed_from_theme", "")),
        "archetype": rank_signals.get("theme_archetype", ""),
        "intro_mode": rank_signals.get("recommended_intro_mode", ""),
        "caption_style": package.get("caption_style", rank_signals.get("caption_style", "")),
        "framing_style": package.get("framing_style", rank_signals.get("framing_style", "")),
        "overlay_style": package.get("overlay_style", rank_signals.get("overlay_style", "")),
        "title_style": package.get("title_style", metadata_style.get("title_style", "")),
        "experiment_id": experiment.get("experiment_id", ""),
        "experiment_variant": experiment.get("variant", ""),
        "experiment": experiment,
        "rank_signals": {
            "theme_signal_score": rank_signals.get("theme_signal_score"),
            "transformation_score": rank_signals.get("transformation_score"),
            "reused_content_risk": rank_signals.get("reused_content_risk"),
            "popularity_score": rank_signals.get("popularity_score"),
            "popularity_source": rank_signals.get("popularity_source"),
            "readiness_tier": rank_signals.get("readiness_tier"),
        },
        "duration": package.get("duration", package.get("source_play_duration", 0.0)),
        "title": package.get("title", ""),
        "published_at": ((package.get("platform_uploads") or {}).get("youtube_shorts") or {}).get("uploaded_at", ""),
        **observed_metrics,
    }
    record["performance_score"] = performance_score(record)
    record["collected_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return record


def save_metric_record(record):
    theme = record.get("theme", "unknown") or "unknown"
    video_id = record.get("video_id") or record.get("title", "draft")
    safe_id = "".join(char if char.isalnum() or char in "._-" else "_" for char in video_id)[:80]
    path = os.path.join(METRICS_PATH, theme, f"{safe_id}.json")
    write_json_file(path, record)
    return path


def load_theme_metrics(theme):
    directory = os.path.join(METRICS_PATH, clean_theme_name(theme))

    if not os.path.isdir(directory):
        return []

    return [
        load_json_file(os.path.join(directory, filename), {})
        for filename in os.listdir(directory)
        if filename.endswith(".json")
    ]


def get_oauth_client_config():
    if os.path.exists(CLIENT_SECRETS_FILE):
        return None

    client_id = os.getenv("YOUTUBE_CLIENT_ID", DEFAULT_YOUTUBE_CLIENT_ID).strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if not client_id:
        raise RuntimeError("Missing YouTube OAuth client ID. Set YOUTUBE_CLIENT_ID or create client_secrets.json.")

    if not client_secret:
        raise RuntimeError(
            "Missing YouTube OAuth client secret. Save the Desktop app OAuth JSON as client_secrets.json "
            "or set YOUTUBE_CLIENT_SECRET."
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


def theme_token_file(theme):
    config = load_theme_config(theme)
    token_file = str((config.get("youtube") or {}).get("token_file") or "").strip()

    if token_file:
        return token_file if os.path.isabs(token_file) else os.path.join(BASE_DIR, token_file)

    return os.path.join(BASE_DIR, f"youtube_token_{clean_theme_name(theme)}.json")


def get_authenticated_credentials(theme, scopes=None):
    scopes = scopes or YOUTUBE_ANALYTICS_SCOPES

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as error:
        raise RuntimeError(
            "YouTube analytics dependencies are missing. Run: "
            ".\\venv_313\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from error

    token_file = theme_token_file(theme)
    credentials = None

    if os.path.exists(token_file):
        credentials = Credentials.from_authorized_user_file(token_file, scopes)

        if not credentials.has_scopes(scopes):
            print(f"Saved token for {theme} is missing YouTube Analytics scopes; reauthorizing.")
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())

    if not credentials or not credentials.valid:
        client_config = get_oauth_client_config()

        if client_config is None:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes)
        else:
            flow = InstalledAppFlow.from_client_config(client_config, scopes)

        credentials = flow.run_local_server(
            port=0,
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true",
        )

    os.makedirs(os.path.dirname(token_file), exist_ok=True)

    with open(token_file, "w", encoding="utf-8") as token_handle:
        token_handle.write(credentials.to_json())

    return credentials


def get_youtube_services(theme):
    try:
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "YouTube analytics dependencies are missing. Run: "
            ".\\venv_313\\Scripts\\python.exe -m pip install -r requirements.txt"
        ) from error

    credentials = get_authenticated_credentials(theme)
    youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)
    youtube_analytics = build(
        YOUTUBE_ANALYTICS_SERVICE_NAME,
        YOUTUBE_ANALYTICS_API_VERSION,
        credentials=credentials,
    )
    return youtube, youtube_analytics


def uploaded_packages(theme):
    paths = ensure_theme(theme)
    metadata = load_json_file(paths["final_metadata_file"], {"theme": clean_theme_name(theme), "content": []})
    packages = []

    for package in metadata.get("content", []):
        upload = (package.get("platform_uploads") or {}).get("youtube_shorts") or {}
        video_id = upload.get("video_id", "")

        if video_id:
            packages.append((package, video_id))

    return paths, metadata, packages


def fetch_video_public_stats(youtube, video_ids):
    if not video_ids:
        return {}

    stats = {}

    for index in range(0, len(video_ids), 50):
        chunk = video_ids[index:index + 50]
        response = youtube.videos().list(
            part="statistics,snippet,status",
            id=",".join(chunk),
            maxResults=50,
        ).execute()

        for item in response.get("items", []):
            video_id = item.get("id", "")
            raw_stats = item.get("statistics", {}) or {}
            snippet = item.get("snippet", {}) or {}
            status = item.get("status", {}) or {}
            stats[video_id] = {
                "views": int(raw_stats.get("viewCount") or 0),
                "likes": int(raw_stats.get("likeCount") or 0),
                "comments": int(raw_stats.get("commentCount") or 0),
                "youtube_published_at": snippet.get("publishedAt", ""),
                "youtube_privacy_status": status.get("privacyStatus", ""),
            }

    return stats


def _date_string(value):
    if isinstance(value, dt.date):
        return value.isoformat()

    return str(value)


def parse_analytics_response(response):
    headers = [header.get("name", "") for header in response.get("columnHeaders", [])]
    rows = response.get("rows") or []

    if not rows:
        return {}

    raw = dict(zip(headers, rows[0]))
    normalized = {}

    for key, value in raw.items():
        if key == "engagedViews":
            normalized["engaged_views"] = float(value or 0)
        elif key == "averageViewDuration":
            normalized["average_view_duration"] = float(value or 0)
        elif key == "averageViewPercentage":
            percent = float(value or 0)
            normalized["average_percent_viewed"] = percent / 100.0 if percent > 1 else percent
        elif key == "subscribersGained":
            normalized["subs_gained"] = float(value or 0)
        elif key == "views":
            normalized["analytics_views"] = float(value or 0)
        else:
            normalized[key] = float(value or 0)

    if "views" not in normalized and "analytics_views" in normalized:
        normalized["views"] = normalized["analytics_views"]

    return normalized


def query_video_analytics(youtube_analytics, video_id, start_date, end_date):
    response = youtube_analytics.reports().query(
        ids="channel==MINE",
        startDate=_date_string(start_date),
        endDate=_date_string(end_date),
        metrics=",".join(ANALYTICS_METRICS),
        filters=f"video=={video_id}",
    ).execute()
    return parse_analytics_response(response)


def collect_theme_metrics(theme, days=30, start_date=None, end_date=None):
    theme = clean_theme_name(theme)
    today = dt.date.today()
    end = dt.date.fromisoformat(end_date) if end_date else today
    start = dt.date.fromisoformat(start_date) if start_date else end - dt.timedelta(days=int(days))
    paths, metadata, packages = uploaded_packages(theme)

    if not packages:
        print(f"No uploaded YouTube video IDs found for theme '{theme}'.")
        return {"theme": theme, "records": 0, "metric_files": [], "report_path": ""}

    youtube, youtube_analytics = get_youtube_services(theme)
    public_stats = fetch_video_public_stats(youtube, [video_id for _, video_id in packages])
    metric_files = []

    for package, video_id in packages:
        observed = dict(public_stats.get(video_id, {}))

        try:
            observed.update(query_video_analytics(youtube_analytics, video_id, start, end))
            observed["analytics_start_date"] = start.isoformat()
            observed["analytics_end_date"] = end.isoformat()
        except Exception as error:
            observed["analytics_error"] = str(error)[-1000:]

        record = metric_record_from_package(package, observed)
        metric_files.append(save_metric_record(record))
        package.setdefault("platform_metrics", {}).setdefault("youtube_shorts", {}).update(record)

    write_json_file(paths["final_metadata_file"], metadata)

    from analytics.theme_report import build_theme_analytics_report

    report_path, report = build_theme_analytics_report(theme)
    print(f"Collected {len(metric_files)} YouTube metric records for {theme}.")
    print(f"Analytics report: {report_path}")
    return {
        "theme": theme,
        "records": len(metric_files),
        "metric_files": metric_files,
        "report_path": report_path,
        "summary": report.get("summary", {}),
    }


def collect_all_theme_metrics(days=30, start_date=None, end_date=None):
    results = {}

    for theme in discover_themes():
        try:
            results[theme] = collect_theme_metrics(theme, days=days, start_date=start_date, end_date=end_date)
        except Exception as error:
            results[theme] = {"theme": theme, "error": str(error)}
            print(f"Analytics collection failed for {theme}: {error}")

    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Collect YouTube Analytics metrics for uploaded Shortform videos.")
    parser.add_argument("--theme", help="Theme to collect. Omit with --all to collect every theme.")
    parser.add_argument("--all", action="store_true", help="Collect every discovered theme.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window when --start-date is omitted.")
    parser.add_argument("--start-date", help="Analytics start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Analytics end date, YYYY-MM-DD.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.all:
        collect_all_theme_metrics(days=args.days, start_date=args.start_date, end_date=args.end_date)
        return

    if not args.theme:
        raise SystemExit("Use --theme THEME or --all.")

    collect_theme_metrics(args.theme, days=args.days, start_date=args.start_date, end_date=args.end_date)


if __name__ == "__main__":
    main()
