import os
import time
from datetime import datetime

import yt_dlp

from theme_config import (
    BASE_DIR,
    PULLED_FILE,
    discover_themes,
    ensure_theme,
    load_json_file,
    load_theme_config,
    mark_stage,
    video_state_key,
    write_json_file,
)


def build_ytdl_opts(extra_opts=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": int(os.getenv("SHORTFORM_YTDLP_SOCKET_TIMEOUT", "18")),
        "extractor_retries": int(os.getenv("SHORTFORM_YTDLP_EXTRACTOR_RETRIES", "2")),
        "retries": int(os.getenv("SHORTFORM_YTDLP_RETRIES", "4")),
    }

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(BASE_DIR, "cookies.txt"),
    )
    cookies_browser = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "")

    if os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_browser and os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") != "1":
        opts["cookiesfrombrowser"] = (cookies_browser,)

    if os.getenv("SHORTFORM_FORCE_IPV4", "1") == "1":
        opts["source_address"] = "0.0.0.0"

    if extra_opts:
        opts.update(extra_opts)

    return opts


def latest_video_for_channel(channel_url):
    ydl_opts = build_ytdl_opts({
        "extract_flat": True,
        "playlist_items": "1",
        "playlistend": 1,
        "simulate": True,
        "skip_download": True,
    })

    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
        except Exception as error:
            if "Could not copy Chrome cookie database" not in str(error):
                raise

            print(" -> Chrome cookie access failed; retrying without browser cookies.")
            retry_opts = dict(ydl_opts)
            retry_opts.pop("cookiesfrombrowser", None)

            with yt_dlp.YoutubeDL(retry_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)

        if not info:
            return None

        if "entries" in info and info["entries"]:
            video = info["entries"][0]
        else:
            video = info

        views_int = video.get("view_count", 0)
        views_str = f"{views_int:,} views" if views_int else "N/A"
        raw_date = video.get("upload_date")
        date_str = (
            datetime.strptime(raw_date, "%Y%m%d").strftime("%b %d, %Y")
            if raw_date
            else "N/A"
        )
        video_id = video.get("id") or video.get("url")
        video_url = video.get("webpage_url") or video.get("url") or f"https://www.youtube.com/watch?v={video_id}"

        if video_id and not str(video_url).startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={video_id}"

        return {
            "title": video.get("title", "Unknown Title"),
            "video_url": video_url,
            "views": views_str,
            "date_time": date_str,
            "channel_url": channel_url,
        }

    except Exception as error:
        print(f"Error collecting video data for {channel_url}: {error}")
        return None


def run_video_fetch_for_theme(theme_name):
    start = time.time()
    paths = ensure_theme(theme_name)
    theme = paths["theme"]
    config = load_theme_config(theme)
    channels = config["channels"]

    print(f"=== Fetching latest videos for theme: {theme} ===")

    if not channels:
        print(f"No channels found for theme '{theme}'. Add URLs to {paths['theme_config_file']}")
        return

    pulled = load_json_file(PULLED_FILE, {})
    if not isinstance(pulled, dict):
        pulled = {}

    new_count = 0
    refreshed_count = 0

    for channel in channels:
        latest_video = latest_video_for_channel(channel)

        if not latest_video:
            continue

        pulled_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        latest_video["theme"] = theme
        latest_video["pulled_at"] = pulled_at
        state_key = video_state_key(theme, latest_video["video_url"])

        if state_key in pulled:
            refreshed_count += 1
            existing_record = pulled.get(state_key, {})
        else:
            new_count += 1
            existing_record = {}

        merged_record = {
            **existing_record,
            **latest_video,
        }
        mark_stage(merged_record, "fetched", pulled_at)
        pulled[state_key] = merged_record

    write_json_file(PULLED_FILE, pulled)

    print(f"Saved pulled registry: {PULLED_FILE}")
    print(f"New videos: {new_count}; refreshed existing: {refreshed_count}")
    print(f"It took {round((time.time() - start) / 60, 2)} minutes!\n")


def run_video_fetch(theme=None):
    themes = [theme] if theme else discover_themes()

    if not themes:
        print("No themes configured. Add JSON files in src/themes.")
        return

    for theme_name in themes:
        run_video_fetch_for_theme(theme_name)


if __name__ == "__main__":
    run_video_fetch()
