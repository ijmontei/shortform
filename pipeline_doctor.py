import os
import json
import shutil
import subprocess
import sys
import time

import yt_dlp

import ytdlp_auth
from theme_config import BASE_DIR, discover_themes, get_theme_paths, load_theme_config
from theme_engine_validate import validate_theme_engine


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
MEDIA_AUTH_WAIT_STATUS_FILE = os.path.join(BASE_DIR, "logs", "media_auth_wait_latest.json")


def status_line(ok, label, detail=""):
    marker = "OK" if ok else "FAIL"
    text = f"[{marker}] {label}"

    if detail:
        text = f"{text}: {detail}"

    print(text)
    return ok


def load_json_file(path):
    if not path or not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def find_executable(primary_path, fallback_name):
    if os.path.exists(primary_path):
        return primary_path

    resolved = shutil.which(fallback_name)
    return resolved or ""


def check_runtime():
    checks = []
    checks.append(status_line(sys.version_info >= (3, 10), "Python", sys.version.split()[0]))

    ffmpeg = find_executable(FFMPEG_EXE, "ffmpeg")
    ffprobe = find_executable(FFPROBE_EXE, "ffprobe")
    checks.append(status_line(bool(ffmpeg), "FFmpeg", ffmpeg or "not found"))
    checks.append(status_line(bool(ffprobe), "FFprobe", ffprobe or "not found"))

    version = getattr(yt_dlp.version, "__version__", "")
    checks.append(status_line(bool(version), "yt-dlp", version or "unknown"))
    return checks


def check_themes():
    checks = []
    themes = discover_themes()
    checks.append(status_line(bool(themes), "Themes discovered", ", ".join(themes) or "none"))

    for theme in themes:
        config = load_theme_config(theme)
        paths = get_theme_paths(theme)
        channels = config.get("channels", [])
        youtube = config.get("youtube", {})
        handle = youtube.get("channel_handle", "")
        token_file = youtube.get("token_file", "")

        checks.append(status_line(bool(channels), f"{theme} channels", f"{len(channels)} configured"))

        if handle:
            detail = handle

            if token_file:
                detail = f"{detail}, token={token_file}"

            checks.append(status_line(True, f"{theme} YouTube routing", detail))
        else:
            checks.append(status_line(True, f"{theme} YouTube routing", f"generation-only; configure youtube.channel_handle in {paths['theme_config_file']} before upload"))

    return checks


def check_theme_engine():
    report = validate_theme_engine(write_report=True)
    phase_scope = report.get("phase_scope") or {}
    detail = (
        f"{report['theme_count']} themes, "
        f"errors={report['error_count']}, warnings={report['warning_count']}, "
        f"generation-only={report['generation_only_themes']}, "
        f"future-configs={len(phase_scope.get('future_configured_themes') or [])}, "
        f"scope-ok={bool(phase_scope.get('phase_scope_ok'))}"
    )
    return [status_line(report["status"] == "ok", "Theme engine schema", detail)]


def process_running(image_name):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False

    return image_name.lower() in (result.stdout or "").lower()


def check_auth():
    if not ytdlp_auth.media_auth_required():
        return [status_line(True, "Restricted-video auth", "not required by current environment")]

    checks = []
    ytdlp_auth.ensure_bgutil_pot_provider()
    bgutil_ping = ytdlp_auth.bgutil_ping()
    checks.append(status_line(
        bool(bgutil_ping.get("ok")),
        "YouTube PO-token provider",
        (
            f"http://127.0.0.1:{ytdlp_auth.BGUTIL_DEFAULT_PORT}/ping OK"
            if bgutil_ping.get("ok")
            else f"not reachable: {bgutil_ping.get('error', 'unknown error')}"
        ),
    ))
    checks.append(status_line(
        True,
        "YouTube media download auth policy",
        os.getenv("SHORTFORM_MEDIA_AUTH_POLICY", "on_demand"),
    ))

    cookie_file = ytdlp_auth.youtube_cookie_file()
    browser_fallback_enabled = ytdlp_auth.browser_cookie_fallback_enabled()
    strict_result = None
    strict_error = None

    if os.path.exists(cookie_file):
        age_hours = (time.time() - os.path.getmtime(cookie_file)) / 3600
        detail = f"{ytdlp_auth.cookie_file_diagnostics_text(cookie_file)}, modified {age_hours:.1f} hours ago"
        checks.append(status_line(True, "YouTube cookie file", detail))

        try:
            strict_result = ytdlp_auth.verify_cookie_file(cookie_file)
            checks.append(status_line(
                True,
                "YouTube cookie file restricted auth",
                f"{strict_result['id']} - {strict_result['title']}",
            ))
        except Exception as error:
            strict_error = error
            checks.append(status_line(
                browser_fallback_enabled,
                "YouTube cookie file restricted auth",
                (
                    str(error).splitlines()[0] + "; browser fallback will be tested"
                    if browser_fallback_enabled
                    else str(error).splitlines()[0]
                ),
            ))
    else:
        checks.append(status_line(False, "YouTube cookie file", f"missing at {cookie_file}"))

    browser_candidates = ytdlp_auth.get_cookie_browser_candidates()
    checks.append(status_line(
        bool(browser_candidates),
        "Browser cookie profiles",
        ", ".join(browser_candidates[:8]) + ("..." if len(browser_candidates) > 8 else ""),
    ))

    browser_lock = ytdlp_auth.browser_lock_status()
    browser_detail = []
    blockers = browser_lock.get("blocking_browsers") or []
    visible_titles = [
        item.get("window_title")
        for item in (browser_lock.get("processes") or [])
        if item.get("window_title") and item.get("window_title") != "N/A"
    ]

    if blockers:
        browser_detail.append(f"blocking={','.join(blockers)}")
        browser_detail.append(f"blocking_processes={browser_lock.get('blocking_process_count', 0)}")

        if visible_titles:
            browser_detail.append(f"visible_tab={visible_titles[0]}")
    else:
        observed = ",".join(browser_lock.get("observed_browsers") or [])
        browser_detail.append("configured browser not locked")
        if observed:
            browser_detail.append(f"other_browsers_running={observed}")

    checks.append(status_line(
        True,
        "Browser cookie lock status",
        "; ".join(browser_detail),
    ))

    checks.append(status_line(
        True,
        "Browser cookie fallback",
        (
            "enabled; Firefox browser cookies are primary unless overridden"
            if browser_fallback_enabled
            else "disabled for deterministic production runs"
        ),
    ))

    if strict_result:
        checks.append(status_line(True, "Restricted-video auth", f"{strict_result['id']} - {strict_result['title']}"))
        checks.append(status_line(True, "Restricted-video auth report", ytdlp_auth.AUTH_REPORT_FILE))
        return checks

    if not browser_fallback_enabled:
        checks.append(status_line(
            False,
            "Restricted-video auth",
            (
                str(strict_error).splitlines()[0]
                if strict_error
                else "project cookie file did not pass restricted-video auth"
            ),
        ))
        checks.append(status_line(
            os.path.exists(ytdlp_auth.AUTH_REPORT_FILE),
            "Restricted-video auth report",
            ytdlp_auth.AUTH_REPORT_FILE,
        ))
        wait_status = load_json_file(MEDIA_AUTH_WAIT_STATUS_FILE)
        if wait_status:
            browser_lock = wait_status.get("browser_cookie_lock") or {}
            checks.append(status_line(
                wait_status.get("status") == "ok",
                "Restricted-video auth wait status",
                (
                    f"{wait_status.get('status', 'unknown')}; "
                    f"attempt={wait_status.get('attempt', 0)}; "
                    f"checked_exports={wait_status.get('checked_cookie_export_count', 0)}; "
                    f"browser_fallback_armed={bool(wait_status.get('browser_cookie_fallback'))}; "
                    f"browser_fallback_ready={bool(wait_status.get('browser_cookie_fallback_ready'))}; "
                    f"browser_blockers={','.join(browser_lock.get('blocking_browsers') or []) or 'none'}; "
                    f"browser_processes={browser_lock.get('process_count', 0)}; "
                    f"{MEDIA_AUTH_WAIT_STATUS_FILE}"
                ),
            ))
        else:
            checks.append(status_line(False, "Restricted-video auth wait status", f"missing at {MEDIA_AUTH_WAIT_STATUS_FILE}"))
        return checks

    try:
        result = ytdlp_auth.verify_youtube_auth(include_browser_fallback=True)
    except Exception as error:
        first_line = str(error).splitlines()[0]
        if "copy chrome cookie database" in str(error).lower() or "cookie database" in str(error).lower():
            first_line += " (browser profile may be locked; close the selected browser fully or re-export cookies.txt)"
        checks.append(status_line(False, "Restricted-video auth", first_line))
        checks.append(status_line(
            os.path.exists(ytdlp_auth.AUTH_REPORT_FILE),
            "Restricted-video auth report",
            ytdlp_auth.AUTH_REPORT_FILE,
        ))
        return checks

    checks.append(status_line(True, "Restricted-video auth", f"{result['id']} - {result['title']}"))
    checks.append(status_line(True, "Restricted-video auth report", ytdlp_auth.AUTH_REPORT_FILE))
    return checks


def run_doctor(include_auth=True):
    print(f"shortform pipeline doctor: {BASE_DIR}\n")
    checks = []
    checks.extend(check_runtime())
    print("")
    checks.extend(check_themes())
    print("")
    checks.extend(check_theme_engine())
    print("")

    if include_auth:
        checks.extend(check_auth())
        print("")

    passed = all(checks)
    status_line(passed, "Pipeline doctor", "all checks passed" if passed else "one or more checks failed")
    return passed


if __name__ == "__main__":
    sys.exit(0 if run_doctor(include_auth=True) else 1)
