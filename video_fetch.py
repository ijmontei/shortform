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
    video_state_key,
    write_json_file,
)


def build_ytdl_opts(extra_opts=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
    }

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(BASE_DIR, "cookies.txt"),
    )
    cookies_browser = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "chrome")

    if os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_browser and os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") != "1":
        opts["cookiesfrombrowser"] = (cookies_browser,)

    if extra_opts:
        opts.update(extra_opts)

    return opts


def latest_video_for_channel(channel_url):
    ydl_opts = build_ytdl_opts({
        "extract_flat": False,
        "playlist_items": "1",
        "simulate": True,
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
        video_url = video.get("webpage_url") or f"https://www.youtube.com/watch?v={video.get('id')}"

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

        latest_video["theme"] = theme
        latest_video["pulled_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        state_key = video_state_key(theme, latest_video["video_url"])

        if state_key in pulled:
            refreshed_count += 1
        else:
            new_count += 1

        pulled[state_key] = latest_video

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
