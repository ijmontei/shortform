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
    cookie_browsers = get_cookie_browser_candidates()

    if os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookie_browsers:
        opts["cookiesfrombrowser"] = (cookie_browsers[0],)

    if os.getenv("SHORTFORM_FORCE_IPV4", "1") == "1":
        opts["source_address"] = "0.0.0.0"

    if extra_opts:
        opts.update(extra_opts)

    return opts


def get_cookie_browser_candidates():
    if os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") == "1":
        return []

    requested = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "chrome,edge,firefox")
    return [browser.strip() for browser in requested.split(",") if browser.strip()]


def is_cookie_load_error(error):
    message = str(error).lower()
    cookie_markers = [
        "could not copy chrome cookie database",
        "could not copy edge cookie database",
        "could not find firefox cookies database",
        "failed to decrypt with dpapi",
        "failed to load cookies",
        "permission denied",
    ]
    return any(marker in message for marker in cookie_markers)


def run_ytdlp_with_cookie_fallback(ydl_opts, operation):
    browsers = get_cookie_browser_candidates()
    attempted = []
    last_cookie_error = None

    if not ydl_opts.get("cookiesfrombrowser") or not browsers:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return operation(ydl)

    for browser in browsers:
        attempted.append(browser)
        opts = dict(ydl_opts)
        opts["cookiesfrombrowser"] = (browser,)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return operation(ydl)
        except Exception as error:
            if not is_cookie_load_error(error):
                raise

            last_cookie_error = error

            if browser == browsers[-1]:
                break

            print(f" -> {browser} cookie access failed; trying next browser.")

    raise RuntimeError(
        "Unable to load browser cookies from "
        f"{', '.join(attempted)}. Close Chrome/Edge/Firefox and retry, or export YouTube cookies to cookies.txt."
    ) from last_cookie_error


def latest_video_for_channel(channel_url):
    ydl_opts = build_ytdl_opts({
        "extract_flat": True,
        "playlist_items": "1",
        "playlistend": 1,
        "simulate": True,
        "skip_download": True,
    })

    try:
        info = run_ytdlp_with_cookie_fallback(
            ydl_opts,
            lambda ydl: ydl.extract_info(channel_url, download=False),
        )

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
