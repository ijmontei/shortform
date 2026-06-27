import os
import time
from datetime import datetime, timezone

import yt_dlp
import ytdlp_auth

from theme_config import (
    BASE_DIR,
    PULLED_FILE,
    assert_theme_allowed_for_active_run,
    clean_theme_name,
    discover_themes,
    ensure_theme,
    load_json_file,
    load_theme_config,
    mark_stage,
    requested_env_theme_names,
    theme_config_path,
    video_state_key,
    write_json_file,
)
from theme_profile import episode_route_targets, source_disqualified_by_theme_name


def build_ytdl_opts(extra_opts=None, use_cookies=False):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": ytdlp_auth.QuietYtdlpLogger(),
        **ytdlp_auth.youtube_js_runtime_options(),
        "socket_timeout": int(os.getenv("SHORTFORM_YTDLP_SOCKET_TIMEOUT", "18")),
        "extractor_retries": int(os.getenv("SHORTFORM_YTDLP_EXTRACTOR_RETRIES", "2")),
        "retries": int(os.getenv("SHORTFORM_YTDLP_RETRIES", "4")),
    }

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(BASE_DIR, "cookies.txt"),
    )
    cookie_browsers = get_cookie_browser_candidates()

    if use_cookies:
        if os.path.exists(cookies_file):
            opts["cookiefile"] = cookies_file
        elif cookie_browsers:
            opts["cookiesfrombrowser"] = cookie_browser_to_tuple(cookie_browsers[0])

    if os.getenv("SHORTFORM_FORCE_IPV4", "1") == "1":
        opts["source_address"] = "0.0.0.0"

    if extra_opts:
        opts.update(extra_opts)

    return opts


def channel_url_candidates(channel_url):
    value = str(channel_url or "").strip()
    if not value:
        return []

    root = value.rstrip("/")
    candidates = [root]

    if root.lower().endswith("/videos"):
        base = root[:-7].rstrip("/")
        candidates.extend([base, f"{base}/streams"])
    elif not root.lower().endswith("/streams"):
        candidates.append(f"{root}/videos")
        candidates.append(f"{root}/streams")

    unique = []
    seen = set()
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def is_probable_youtube_video_id(video_id):
    value = str(video_id or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return len(value) == 11 and all(char in allowed for char in value)


def is_supported_youtube_video_url(video_url):
    value = str(video_url or "").strip().lower()
    return (
        "youtube.com/watch?" in value
        or "youtube.com/shorts/" in value
        or "youtu.be/" in value
    )


def get_cookie_browser_candidates():
    return ytdlp_auth.get_cookie_browser_candidates()


def cookie_browser_to_tuple(candidate):
    return ytdlp_auth.cookie_browser_to_tuple(candidate)


def is_cookie_load_error(error):
    return ytdlp_auth.is_cookie_load_error(error)


def run_ytdlp_with_cookie_fallback(ydl_opts, operation):
    return ytdlp_auth.run_ytdlp_with_auth_retry(
        ydl_opts,
        operation,
        auth_required=bool(ydl_opts.get("cookiefile") or ydl_opts.get("cookiesfrombrowser")),
        reason="channel metadata fetch",
    )


def latest_video_for_channel(channel_url):
    ydl_opts = build_ytdl_opts({
        "extract_flat": True,
        "playlist_items": "1",
        "playlistend": 1,
        "simulate": True,
        "skip_download": True,
    }, use_cookies=os.getenv("SHORTFORM_USE_COOKIES_FOR_FETCH") == "1")

    errors = []

    for candidate_url in channel_url_candidates(channel_url):
        try:
            info = run_ytdlp_with_cookie_fallback(
                ydl_opts,
                lambda ydl: ydl.extract_info(candidate_url, download=False),
            )

            if not info:
                continue

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

            if not is_supported_youtube_video_url(video_url):
                if is_probable_youtube_video_id(video_id):
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    errors.append(
                        f"{candidate_url}: first result was not a playable video URL ({video_url})"
                    )
                    continue

            return {
                "title": video.get("title", "Unknown Title"),
                "video_url": video_url,
                "views": views_str,
                "date_time": date_str,
                "channel_url": candidate_url,
                "configured_channel_url": channel_url,
            }

        except Exception as error:
            errors.append(f"{candidate_url}: {str(error).splitlines()[0][:220]}")

    if errors:
        print(f"Skipping source after {len(errors)} fetch attempt(s): {channel_url}")
        print(f" -> {errors[-1]}")

    return None


def pulled_record_has_generated_clips(record):
    stages = record.get("stages") if isinstance(record, dict) else {}
    stages = stages if isinstance(stages, dict) else {}
    return bool(
        record.get("clips_generated_at")
        or record.get("clips_generated_count")
        or stages.get("clips_generated")
    )


def prune_guard_disqualified_pulled_records(theme, pulled):
    removed_count = 0
    marked_count = 0

    for state_key, record in list((pulled or {}).items()):
        if not isinstance(record, dict):
            continue

        if clean_theme_name(record.get("theme", "")) != theme:
            continue

        disqualified, guard_hits = source_disqualified_by_theme_name(theme, record)

        if not disqualified:
            continue

        if pulled_record_has_generated_clips(record):
            record["source_guard_disqualified"] = True
            record["source_guard_disqualified_reason"] = guard_hits
            marked_count += 1
        else:
            del pulled[state_key]
            removed_count += 1

    return removed_count, marked_count


def run_video_fetch_for_theme(theme_name):
    theme_name = assert_theme_allowed_for_active_run(theme_name)
    start = time.time()
    paths = ensure_theme(theme_name)
    theme = paths["theme"]
    config = load_theme_config(theme)
    channels = config["channels"]
    priority_channels = set(config.get("priority_channels") or [])
    secondary_channels = set(config.get("secondary_channels") or [])
    enable_episode_routing = os.getenv("SHORTFORM_ENABLE_EPISODE_ROUTING", "1") != "0"

    print(f"=== Fetching latest videos for theme: {theme} ===")

    if not channels:
        print(f"No channels found for theme '{theme}'. Add URLs to {paths['theme_config_file']}")
        return

    pulled = load_json_file(PULLED_FILE, {})
    if not isinstance(pulled, dict):
        pulled = {}

    new_count = 0
    refreshed_count = 0
    routed_count = 0

    for channel in channels:
        latest_video = latest_video_for_channel(channel)

        if not latest_video:
            continue

        pulled_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        source_tier = "priority" if channel in priority_channels else ("secondary" if channel in secondary_channels else "legacy")
        route_result = episode_route_targets(
            theme,
            channel,
            latest_video.get("channel_url", ""),
            latest_video.get("title", ""),
        ) if enable_episode_routing else {"targets": [theme], "matches": []}
        route_targets = [
            clean_theme_name(target)
            for target in route_result.get("targets", [theme])
            if os.path.exists(theme_config_path(target))
        ]

        if theme not in route_targets:
            route_targets.insert(0, theme)

        latest_video["theme"] = theme
        latest_video["pulled_at"] = pulled_at
        latest_video["source_tier"] = source_tier
        latest_video["route_targets"] = route_targets
        latest_video["routing_override_matches"] = route_result.get("matches", [])

        for target_theme in route_targets:
            guard_record = {
                **latest_video,
                "theme": target_theme,
                "source_tier": source_tier,
            }
            disqualified, guard_hits = source_disqualified_by_theme_name(target_theme, guard_record)

            if disqualified:
                print(
                    f"Skipping fetched source for theme '{target_theme}' by source guard: "
                    f"{latest_video.get('title', 'Unknown Title')}"
                )
                print(f" -> guard signals: {', '.join(map(str, guard_hits))}")
                continue

            state_key = video_state_key(target_theme, latest_video["video_url"])

            if state_key in pulled:
                if target_theme == theme:
                    refreshed_count += 1
                existing_record = pulled.get(state_key, {})
            else:
                if target_theme == theme:
                    new_count += 1
                else:
                    routed_count += 1
                existing_record = {}

            merged_record = {
                **existing_record,
                **latest_video,
                "theme": target_theme,
                "origin_theme": existing_record.get("origin_theme") or theme,
                "routed_from_theme": "" if target_theme == theme else theme,
                "routing_status": "primary" if target_theme == theme else "episode_override",
            }
            mark_stage(merged_record, "fetched", pulled_at)
            pulled[state_key] = merged_record

    removed_count, marked_count = prune_guard_disqualified_pulled_records(theme, pulled)

    write_json_file(PULLED_FILE, pulled)

    print(f"Saved pulled registry: {PULLED_FILE}")
    print(f"New videos: {new_count}; refreshed existing: {refreshed_count}; routed copies: {routed_count}")
    if removed_count or marked_count:
        print(
            "Source guard cleanup: "
            f"removed {removed_count} stale pulled record(s), "
            f"marked {marked_count} generated record(s) as disqualified"
        )
    print(f"It took {round((time.time() - start) / 60, 2)} minutes!\n")


def run_video_fetch(theme=None):
    explicit_theme_selection = [theme] if theme else requested_env_theme_names()
    for theme_name in explicit_theme_selection:
        assert_theme_allowed_for_active_run(theme_name)

    themes = [theme] if theme else discover_themes()

    if not themes:
        print("No themes configured. Add JSON files in src/themes.")
        return

    for theme_name in themes:
        run_video_fetch_for_theme(theme_name)


if __name__ == "__main__":
    run_video_fetch()
