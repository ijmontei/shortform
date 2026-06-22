import os

import yt_dlp

from theme_config import BASE_DIR


DEFAULT_AUTH_TEST_URL = "https://www.youtube.com/watch?v=vyKU6Pd5KAA"


class RestrictedVideoAuthError(RuntimeError):
    pass


class QuietYtdlpLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def youtube_cookie_file():
    return os.getenv("SHORTFORM_YTDLP_COOKIES", os.path.join(BASE_DIR, "cookies.txt"))


def get_cookie_browser_candidates():
    if os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") == "1":
        return []

    requested = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "").strip()

    if requested:
        candidates = [browser.strip() for browser in requested.split(",") if browser.strip()]
    else:
        candidates = [
            "chrome:Profile 2",
            "chrome:Default",
            "chrome",
            "edge:Default",
            "edge",
            "firefox",
        ]

    seen = set()
    unique = []

    for candidate in candidates:
        key = candidate.lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


def cookie_browser_to_tuple(candidate):
    parts = str(candidate or "").split(":", 1)
    browser = parts[0].strip()

    if len(parts) == 1 or not parts[1].strip():
        return (browser,)

    return (browser, parts[1].strip())


def is_cookie_load_error(error):
    message = str(error).lower()
    cookie_markers = [
        "could not copy chrome cookie database",
        "could not copy edge cookie database",
        "could not find chrome cookies database",
        "could not find edge cookies database",
        "could not find firefox cookies database",
        "failed to decrypt with dpapi",
        "failed to load cookies",
        "permission denied",
        "cookie database",
        "cookies.sqlite",
    ]
    return any(marker in message for marker in cookie_markers)


def is_auth_needed_error(error):
    message = str(error).lower()
    auth_markers = [
        "sign in to confirm your age",
        "sign in to confirm",
        "this video may be inappropriate",
        "use --cookies",
        "use --cookies-from-browser",
        "confirm you're not a bot",
        "not a bot",
        "login required",
        "private video",
        "members-only",
        "members only",
    ]
    return any(marker in message for marker in auth_markers)


def is_unavailable_video_error(error):
    message = str(error).lower()
    unavailable_markers = [
        "this video is unavailable",
        "video unavailable",
        "copyright claim",
        "has been removed",
    ]
    return any(marker in message for marker in unavailable_markers)


def is_format_unavailable_error(error):
    message = str(error).lower()
    format_markers = [
        "requested format is not available",
        "only images are available",
        "no video formats found",
    ]
    return any(marker in message for marker in format_markers)


def is_restricted_or_unavailable_error(error):
    return is_auth_needed_error(error) or is_unavailable_video_error(error)


def clear_cookie_options(opts):
    opts.pop("cookiefile", None)
    opts.pop("cookiesfrombrowser", None)
    return opts


def cookie_sources():
    sources = []
    cookiefile = youtube_cookie_file()

    if cookiefile and os.path.exists(cookiefile) and os.path.getsize(cookiefile) > 0:
        sources.append(("cookiefile", cookiefile))

    for browser in get_cookie_browser_candidates():
        sources.append(("browser", browser))

    return sources


def apply_cookie_source(ydl_opts, source):
    kind, value = source
    opts = clear_cookie_options(dict(ydl_opts))
    opts.setdefault("logger", QuietYtdlpLogger())

    if kind == "cookiefile":
        opts["cookiefile"] = value
    elif kind == "browser":
        opts["cookiesfrombrowser"] = cookie_browser_to_tuple(value)

    return opts


def cookie_source_label(source):
    kind, value = source

    if kind == "cookiefile":
        return f"cookie file {value}"

    return f"browser cookies {value}"


def auth_help_message(errors=None):
    cookiefile = youtube_cookie_file()
    message = (
        "YouTube authentication is required for restricted videos, but no available cookie source "
        "unlocked the video. Export a fresh signed-in, age-verified YouTube cookie file to "
        f"{cookiefile}, or close Chrome fully and allow browser-cookie access. Then run "
        "`python ytdlp_auth.py` to verify before running the full pipeline."
    )

    if errors:
        message += "\nAttempt details:\n" + "\n".join(f"- {item}" for item in errors[-6:])

    return message


def run_ytdlp_authenticated(ydl_opts, operation, *, reason="restricted YouTube media"):
    sources = cookie_sources()

    if not sources:
        raise RestrictedVideoAuthError(auth_help_message(["No cookies.txt or browser cookie source was available."]))

    errors = []

    for index, source in enumerate(sources, start=1):
        opts = apply_cookie_source(ydl_opts, source)
        label = cookie_source_label(source)

        try:
            if len(sources) > 1:
                print(f" -> Trying YouTube auth via {label} ({index}/{len(sources)})")

            with yt_dlp.YoutubeDL(opts) as ydl:
                return operation(ydl)
        except Exception as error:
            if not (is_cookie_load_error(error) or is_auth_needed_error(error)):
                raise

            errors.append(f"{label}: {str(error).splitlines()[0][:260]}")

            if index < len(sources):
                print(f" -> {label} did not unlock {reason}; trying next auth source.")

    raise RestrictedVideoAuthError(auth_help_message(errors))


def run_ytdlp_with_auth_retry(ydl_opts, operation, *, auth_required=False, reason="YouTube media"):
    if auth_required:
        return run_ytdlp_authenticated(ydl_opts, operation, reason=reason)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return operation(ydl)
    except Exception as error:
        if not is_auth_needed_error(error):
            raise

        print(" -> Video requires sign-in; retrying with YouTube cookies.")
        return run_ytdlp_authenticated(ydl_opts, operation, reason=reason)


def media_auth_required():
    return os.getenv("SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA", "1") != "0"


def verify_youtube_auth(video_url=None):
    video_url = video_url or os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "ignore_no_formats_error": True,
        "format": "bv*+ba/best",
        "js_runtimes": {"node": {}},
        "allow_remote_features": True,
    }

    info = run_ytdlp_authenticated(
        opts,
        lambda ydl: ydl.extract_info(video_url, download=False),
        reason="age-restricted auth test",
    )
    formats = [
        item for item in (info or {}).get("formats", [])
        if item.get("vcodec") != "none" or item.get("acodec") != "none"
    ]

    if not formats:
        raise RestrictedVideoAuthError(
            "YouTube auth passed, but yt-dlp could not see downloadable audio/video formats. "
            "Update yt-dlp and make sure Node.js is available for YouTube challenge solving. "
            "Then test with: python -m yt_dlp --cookies cookies.txt --list-formats "
            f"{video_url}"
        )

    return {
        "id": (info or {}).get("id", ""),
        "title": (info or {}).get("title", ""),
        "duration": (info or {}).get("duration", 0),
        "format_count": len(formats),
        "url": video_url,
    }


if __name__ == "__main__":
    try:
        result = verify_youtube_auth()
        print("YouTube restricted-video auth OK")
        print(f"Video: {result['id']} - {result['title']}")
        print(f"Formats available: {result['format_count']}")
    except Exception as error:
        print("YouTube restricted-video auth FAILED")
        print(error)
        raise SystemExit(1)
