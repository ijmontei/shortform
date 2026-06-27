import argparse
import json
import os
import shutil
import sys
import time
import traceback as traceback_module

import ytdlp_auth
from clip_generation import run_clip_generation
from daily_editorial import run_daily_editorial
from pipeline_doctor import run_doctor
from reconcile_editorial_gates import reconcile_theme
from subtitle_generation import run_subtitle_generation
from theme_config import BASE_DIR, TEMP_PATH, THEMES_OUTPUT_PATH, clean_theme_name, discover_themes, future_theme_guard_message, future_themes_allowed, get_theme_paths, load_json_file, load_theme_config, requested_env_theme_names, write_json_file
from validate_outputs import validate_outputs
from video_fetch import run_video_fetch


LOGS_PATH = os.path.join(BASE_DIR, "logs")
RUNS_LOG_PATH = os.path.join(LOGS_PATH, "runs")
LATEST_LOG_FILE = os.path.join(LOGS_PATH, "run_latest.log")
LATEST_SUMMARY_FILE = os.path.join(LOGS_PATH, "run_latest_summary.json")
MEDIA_AUTH_WAIT_STATUS_FILE = os.path.join(LOGS_PATH, "media_auth_wait_latest.json")
DEFAULT_YOUTUBE_UPLOAD_LIMIT = int(os.getenv("SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT", "15"))
PIPELINE_STAGES = ["pull", "clip", "editorial", "subtitle", "reconcile", "manifest", "upload"]


class TeeStream:
    def __init__(self, stream, *files):
        self.stream = stream
        self.files = files

    def write(self, text):
        try:
            self.stream.write(text)
        except UnicodeEncodeError:
            self.stream.write(text.encode(self.stream.encoding or "utf-8", errors="replace").decode(self.stream.encoding or "utf-8"))

        for file_handle in self.files:
            file_handle.write(text)
            file_handle.flush()

    def flush(self):
        self.stream.flush()

        for file_handle in self.files:
            file_handle.flush()


class RunLogContext:
    def __init__(self, args):
        self.args = args
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.started_stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
        self.history_log_file = os.path.join(RUNS_LOG_PATH, f"run_{self.started_stamp}_{os.getpid()}.log")
        self.original_stdout = None
        self.original_stderr = None
        self.latest_handle = None
        self.history_handle = None

    def __enter__(self):
        os.makedirs(RUNS_LOG_PATH, exist_ok=True)
        self.latest_handle = open(LATEST_LOG_FILE, "w", encoding="utf-8", buffering=1)
        self.history_handle = open(self.history_log_file, "w", encoding="utf-8", buffering=1)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = TeeStream(sys.stdout, self.latest_handle, self.history_handle)
        sys.stderr = TeeStream(sys.stderr, self.latest_handle, self.history_handle)

        print(f"=== shortform run started: {self.started_at} ===")
        print(f"Latest log: {LATEST_LOG_FILE}")
        print(f"History log: {self.history_log_file}\n")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status = "failed" if exc_type else "complete"
        intentional_exit = bool(exc_type and issubclass(exc_type, SystemExit))

        if exc_type and not intentional_exit:
            traceback_module.print_exception(exc_type, exc_value, traceback)
        elif intentional_exit and exc_value:
            print(str(exc_value))

        print(f"\n=== shortform run {status}: {ended_at} ===")

        summary = {
            "started_at": self.started_at,
            "ended_at": ended_at,
            "status": status,
            "latest_log_file": LATEST_LOG_FILE,
            "history_log_file": self.history_log_file,
            "args": vars(self.args),
        }

        if exc_value:
            summary["error"] = str(exc_value)
            if not intentional_exit:
                summary["traceback"] = "".join(
                    traceback_module.format_exception(exc_type, exc_value, traceback)
                )

        os.makedirs(LOGS_PATH, exist_ok=True)

        with open(LATEST_SUMMARY_FILE, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=4)

        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

        for file_handle in [self.latest_handle, self.history_handle]:
            if file_handle:
                file_handle.close()

        return False


def format_duration(seconds):
    seconds = max(0, float(seconds))
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)

    if hours:
        return f"{hours}h {minutes}m {remainder:.1f}s"

    if minutes:
        return f"{minutes}m {remainder:.1f}s"

    return f"{remainder:.1f}s"


def timed_stage(summary, label, action):
    start = time.time()
    action()
    elapsed = time.time() - start
    summary[label] = elapsed
    print(f"{label} complete in {format_duration(elapsed)}")
    return elapsed


def write_media_auth_wait_status(
    status,
    *,
    attempt=0,
    wait_seconds=0,
    start_wait=None,
    retry_interval=0,
    cookie_export_dirs=None,
    browser_cookie_fallback=False,
    browser_cookie_fallback_ready=False,
    checked_cookie_export_count=0,
    new_cookie_exports_checked=0,
    last_error="",
    verification=None,
):
    elapsed = 0
    remaining = 0

    if start_wait:
        elapsed = max(0, time.time() - start_wait)

        if wait_seconds:
            remaining = max(0, wait_seconds - elapsed)

    candidates = ytdlp_auth.discover_cookie_exports(
        search_dirs=cookie_export_dirs or ytdlp_auth.default_cookie_export_search_dirs(),
        limit=12,
    )
    browser_lock = ytdlp_auth.browser_lock_status()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "attempt": attempt,
        "retry_interval_seconds": int(retry_interval or 0),
        "wait_seconds": int(wait_seconds or 0),
        "elapsed_seconds": round(elapsed, 1),
        "remaining_seconds": round(remaining, 1),
        "checked_cookie_export_count": int(checked_cookie_export_count or 0),
        "new_cookie_exports_checked": int(new_cookie_exports_checked or 0),
        "cookie_export_dirs": [
            os.path.abspath(os.path.expanduser(str(path)))
            for path in (cookie_export_dirs or ytdlp_auth.default_cookie_export_search_dirs())
        ],
        "browser_cookie_fallback": bool(browser_cookie_fallback),
        "browser_cookie_fallback_ready": bool(browser_cookie_fallback_ready),
        "browser_cookie_lock": browser_lock,
        "latest_cookie_exports": [
            {
                "path": candidate["path"],
                "size": candidate["size"],
                "modified_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(candidate["modified"]),
                ),
            }
            for candidate in candidates
        ],
        "last_error": (str(last_error or "").splitlines() or [""])[0][:500],
        "verification": verification or {},
    }
    os.makedirs(os.path.dirname(MEDIA_AUTH_WAIT_STATUS_FILE), exist_ok=True)

    with open(MEDIA_AUTH_WAIT_STATUS_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    return payload


def write_content_manifest(theme):
    paths = get_theme_paths(theme)
    content_dir = paths["final_videos_path"]
    metadata_file = paths["final_metadata_file"]
    metadata = load_json_file(metadata_file, {"theme": theme, "content": []})
    packages = metadata.get("content") if isinstance(metadata, dict) else []
    packages = packages if isinstance(packages, list) else []
    video_files = []

    if os.path.isdir(content_dir):
        video_files = [
            os.path.join(content_dir, filename)
            for filename in sorted(os.listdir(content_dir))
            if filename.lower().endswith(".mp4")
        ]

    ready_count = 0
    captioned_ready_count = 0
    moved_uncaptioned_ready = 0

    for package in packages:
        status = ((package.get("posting_status") or {}).get("youtube_shorts") or "").lower()

        if status == "ready":
            captions_required = package.get("upload_ready_requires_burned_captions", True)

            if captions_required and not package.get("content_has_burned_captions"):
                posting_status = package.setdefault("posting_status", {})
                posting_status["youtube_shorts"] = "needs_revision"
                review = package.setdefault("review", {})
                flags = set(review.get("flags") or [])
                flags.add("missing_burned_captions")
                review["flags"] = sorted(flags)
                moved_uncaptioned_ready += 1
                continue

            ready_count += 1

            if package.get("content_has_burned_captions"):
                captioned_ready_count += 1

    if moved_uncaptioned_ready:
        write_json_file(metadata_file, metadata)

    lines = [
        f"theme: {theme}",
        f"generated_at: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"content_dir: {content_dir}",
        f"metadata_file: {metadata_file}",
        f"mp4_count: {len(video_files)}",
        f"metadata_items: {len(packages)}",
        f"ready_items: {ready_count}",
        f"ready_items_with_burned_captions: {captioned_ready_count}",
        "",
    ]

    for video_file in video_files:
        try:
            size_mb = os.path.getsize(video_file) / (1024 * 1024)
        except OSError:
            size_mb = 0.0

        lines.append(f"- {video_file} ({size_mb:.1f} MB)")

    manifest_file = os.path.join(paths["output_path"], "content_manifest.txt")
    os.makedirs(os.path.dirname(manifest_file), exist_ok=True)

    with open(manifest_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")

    print(
        f"content manifest written for {theme}: {manifest_file} "
        f"({len(video_files)} mp4, {captioned_ready_count}/{ready_count} ready captioned)"
    )
    if moved_uncaptioned_ready:
        print(
            f" -> moved {moved_uncaptioned_ready} uncaptioned ready item(s) "
            "to needs_revision; upload-ready means burned captions are present"
        )
    return manifest_file


def path_within_workspace(path):
    base = os.path.normcase(os.path.abspath(BASE_DIR))
    target = os.path.normcase(os.path.abspath(path))
    return target == base or target.startswith(base + os.sep)


def remove_workspace_path(path):
    if not path:
        return False

    absolute = os.path.abspath(path)

    if not path_within_workspace(absolute):
        raise RuntimeError(f"Refusing to remove path outside workspace: {absolute}")

    if not os.path.exists(absolute):
        return False

    if os.path.isdir(absolute):
        shutil.rmtree(absolute)
    else:
        os.remove(absolute)

    return True


def remove_workspace_glob(directory, suffixes):
    removed = []

    if not directory or not os.path.isdir(directory):
        return removed

    absolute_directory = os.path.abspath(directory)

    if not path_within_workspace(absolute_directory):
        raise RuntimeError(f"Refusing to scan outside workspace: {absolute_directory}")

    for filename in os.listdir(absolute_directory):
        if not any(filename.endswith(suffix) for suffix in suffixes):
            continue

        path = os.path.join(absolute_directory, filename)

        if os.path.isfile(path) and remove_workspace_path(path):
            removed.append(path)

    return removed


def reset_funnel_state_for_themes(themes):
    selected = {clean_theme_name(theme) for theme in themes}
    removed_executed = 0
    reset_pulled = 0
    sample_paths = [get_theme_paths(theme) for theme in selected]
    executed_file = sample_paths[0]["executed_file"] if sample_paths else os.path.join(BASE_DIR, "src", "executed_id.json")
    pulled_file = sample_paths[0]["pulled_file"] if sample_paths else os.path.join(BASE_DIR, "src", "pulled.json")

    executed = load_json_file(executed_file, {})

    if isinstance(executed, dict):
        for key in list(executed.keys()):
            key_theme = clean_theme_name(str(key).split("|", 1)[0])
            record_theme = ""

            if isinstance(executed.get(key), dict):
                record_theme = clean_theme_name(executed[key].get("theme", ""))

            if key_theme in selected or record_theme in selected:
                removed_executed += 1
                executed.pop(key, None)

        write_json_file(executed_file, executed)

    pulled = load_json_file(pulled_file, {})
    stage_keys = [
        "stages",
        "clips_created_at",
        "upload_ready_at",
        "uploaded_at",
        "executed_at",
        "subtitle_status",
        "upload_status",
    ]

    if isinstance(pulled, dict):
        for key, record in pulled.items():
            if not isinstance(record, dict):
                continue

            key_theme = clean_theme_name(str(key).split("|", 1)[0])
            record_theme = clean_theme_name(record.get("theme", ""))

            if key_theme not in selected and record_theme not in selected:
                continue

            changed = False

            for stage_key in stage_keys:
                if stage_key in record:
                    record.pop(stage_key, None)
                    changed = True

            if changed:
                reset_pulled += 1

        write_json_file(pulled_file, pulled)

    return removed_executed, reset_pulled


def inactive_generated_theme_names(active_themes):
    active = {clean_theme_name(theme) for theme in active_themes or []}
    names = set()

    for root in [THEMES_OUTPUT_PATH, TEMP_PATH]:
        if not os.path.isdir(root):
            continue

        for filename in os.listdir(root):
            path = os.path.join(root, filename)

            if os.path.isdir(path):
                theme = clean_theme_name(filename)

                if theme not in active:
                    names.add(theme)

    return sorted(names)


def clean_generated_artifacts(themes, include_inactive=False):
    removed = []
    themes_to_reset = [clean_theme_name(theme) for theme in themes]

    if include_inactive:
        inactive_themes = inactive_generated_theme_names(themes)

        for inactive_theme in inactive_themes:
            paths = get_theme_paths(inactive_theme)

            for target in [
                paths["output_path"],
                paths["temp_path"],
                os.path.join(LOGS_PATH, "frame_validation", inactive_theme),
            ]:
                if remove_workspace_path(target):
                    removed.append(target)

        if inactive_themes:
            print(
                "Clean-slate removed inactive/future generated theme folders: "
                f"{', '.join(inactive_themes)}"
            )
            themes_to_reset.extend(inactive_themes)

    for theme in themes:
        paths = get_theme_paths(theme)
        metadata_path = paths["metadata_path"]
        targets = [
            paths["final_videos_path"],
            paths["final_metadata_file"],
            os.path.join(paths["output_path"], "content_manifest.txt"),
            paths["clips_path"],
            paths["subtitle_temp_path"],
            os.path.join(metadata_path, "editorial"),
            os.path.join(metadata_path, "section_uploads"),
            os.path.join(metadata_path, "upload_ready"),
            os.path.join(metadata_path, "final"),
            os.path.join(metadata_path, "source_dossiers"),
            os.path.join(metadata_path, "frame_audits"),
            os.path.join(LOGS_PATH, "frame_validation", clean_theme_name(theme)),
        ]

        for target in targets:
            if remove_workspace_path(target):
                removed.append(target)

        removed.extend(remove_workspace_glob(
            metadata_path,
            [
                "_clip_review.json",
                "_clip_review.csv",
                "_theme_selection.json",
            ],
        ))

    removed_executed, reset_pulled = reset_funnel_state_for_themes(themes_to_reset)

    for theme in themes:
        get_theme_paths(theme, create=True)

    print(
        "Clean-slate reset complete: "
        f"removed {len(removed)} artifact path(s), "
        f"removed {removed_executed} executed record(s), "
        f"reset {reset_pulled} pulled record(s)."
    )

    return {
        "removed_paths": removed,
        "removed_executed_records": removed_executed,
        "reset_pulled_records": reset_pulled,
        "inactive_cleanup_enabled": include_inactive,
    }


def resolved_youtube_upload_limit(args):
    if args.youtube_upload_limit is not None:
        return args.youtube_upload_limit

    if DEFAULT_YOUTUBE_UPLOAD_LIMIT <= 0:
        return None

    return DEFAULT_YOUTUBE_UPLOAD_LIMIT


def theme_has_youtube_upload_route(theme):
    config = load_theme_config(theme)
    youtube = config.get("youtube") or {}
    return bool(str(youtube.get("channel_handle") or "").strip())


def run_requires_youtube_upload(themes, args):
    if args.skip_youtube:
        return False

    return any(theme_has_youtube_upload_route(theme) for theme in themes)


def run_requires_media_auth_preflight(args):
    if args.clean_slate_only:
        return False

    if getattr(args, "skip_media_auth_preflight", False):
        return False

    return ytdlp_auth.media_auth_required()


def run_restricted_media_auth_preflight(
    wait_seconds=0,
    retry_interval=20,
    cookie_export_dirs=None,
    allow_browser_cookie_fallback=False,
):
    if (
        os.getenv("SHORTFORM_SKIP_YOUTUBE_AUTH_PREFLIGHT", "0") == "1"
        or os.getenv("SHORTFORM_SKIP_MEDIA_AUTH_PREFLIGHT", "0") == "1"
    ):
        print("YouTube restricted-video auth preflight skipped by environment.\n")
        return

    if not ytdlp_auth.media_auth_required():
        print("YouTube restricted-video auth preflight skipped; media auth is not required.\n")
        return

    print("Checking YouTube restricted-video authentication...")

    if allow_browser_cookie_fallback:
        print(
            "Browser-cookie fallback is enabled for this run. "
            "Close Chrome/Edge fully so yt-dlp can read the browser cookie store."
        )

    start_wait = time.time()
    attempt = 1
    checked_cookie_export_keys = set()
    last_auth_detail_at = 0

    try:
        while True:
            new_cookie_exports_checked = 0
            install_result = {}

            if cookie_export_dirs is not None:
                install_result = ytdlp_auth.install_newest_valid_cookie_export(
                    search_dirs=cookie_export_dirs or ytdlp_auth.default_cookie_export_search_dirs(),
                    exclude_keys=checked_cookie_export_keys,
                )
                checked_cookie_export_keys.update(install_result.get("attempted_keys") or [])
                new_cookie_exports_checked = len(install_result.get("attempted") or [])

                if install_result.get("installed"):
                    installed = install_result["install"]
                    verification = installed.get("verification") or {}
                    print(
                        "Installed verified cookie export before auth check: "
                        f"{installed['source']} ({verification.get('id', '')} - {verification.get('title', '')})"
                    )
                elif install_result.get("attempted"):
                    print(
                        "No watched cookie export passed restricted-video auth yet "
                        f"({new_cookie_exports_checked} new checked; "
                        f"{len(checked_cookie_export_keys)} total remembered)."
                    )

            try:
                browser_fallback_ready = (
                    allow_browser_cookie_fallback
                    and not ytdlp_auth.process_running("chrome.exe")
                    and not ytdlp_auth.process_running("msedge.exe")
                )

                if allow_browser_cookie_fallback and not browser_fallback_ready:
                    print("Browser-cookie fallback armed, but Chrome/Edge still appears to be running.")

                result = ytdlp_auth.verify_youtube_auth(
                    include_browser_fallback=browser_fallback_ready,
                    browser_fallback_armed=allow_browser_cookie_fallback,
                )
                write_media_auth_wait_status(
                    "ok",
                    attempt=attempt,
                    wait_seconds=wait_seconds,
                    start_wait=start_wait,
                    retry_interval=retry_interval,
                    cookie_export_dirs=cookie_export_dirs,
                    browser_cookie_fallback=allow_browser_cookie_fallback,
                    browser_cookie_fallback_ready=browser_fallback_ready,
                    checked_cookie_export_count=len(checked_cookie_export_keys),
                    new_cookie_exports_checked=new_cookie_exports_checked,
                    verification=result,
                )
                break
            except ytdlp_auth.RestrictedVideoAuthError as error:
                if not wait_seconds or time.time() - start_wait >= wait_seconds:
                    browser_fallback_ready = (
                        allow_browser_cookie_fallback
                        and not ytdlp_auth.process_running("chrome.exe")
                        and not ytdlp_auth.process_running("msedge.exe")
                    )
                    write_media_auth_wait_status(
                        "failed",
                        attempt=attempt,
                        wait_seconds=wait_seconds,
                        start_wait=start_wait,
                        retry_interval=retry_interval,
                        cookie_export_dirs=cookie_export_dirs,
                        browser_cookie_fallback=allow_browser_cookie_fallback,
                        browser_cookie_fallback_ready=browser_fallback_ready,
                        checked_cookie_export_count=len(checked_cookie_export_keys),
                        new_cookie_exports_checked=new_cookie_exports_checked,
                        last_error=error,
                    )
                    raise

                remaining = max(0, int(wait_seconds - (time.time() - start_wait)))
                now = time.time()
                show_detail = attempt == 1 or new_cookie_exports_checked or now - last_auth_detail_at >= 600

                if show_detail:
                    print("Restricted-video auth is not ready yet.")
                    print(str(error).splitlines()[0])
                    last_auth_detail_at = now
                else:
                    print("Restricted-video auth still waiting; no new valid cookie export detected.")

                print(
                    "Close Chrome/Edge fully or install a broader cookie export; "
                    f"retrying in {retry_interval}s ({remaining}s left, attempt {attempt})."
                )
                browser_fallback_ready = (
                    allow_browser_cookie_fallback
                    and not ytdlp_auth.process_running("chrome.exe")
                    and not ytdlp_auth.process_running("msedge.exe")
                )
                write_media_auth_wait_status(
                    "waiting",
                    attempt=attempt,
                    wait_seconds=wait_seconds,
                    start_wait=start_wait,
                    retry_interval=retry_interval,
                    cookie_export_dirs=cookie_export_dirs,
                    browser_cookie_fallback=allow_browser_cookie_fallback,
                    browser_cookie_fallback_ready=browser_fallback_ready,
                    checked_cookie_export_count=len(checked_cookie_export_keys),
                    new_cookie_exports_checked=new_cookie_exports_checked,
                    last_error=error,
                )
                time.sleep(max(1, retry_interval))
                attempt += 1
    except ytdlp_auth.RestrictedVideoAuthError as error:
        print("Restricted-video auth failed.")
        print(error)
        raise SystemExit(str(error))

    print(f"Restricted-video auth OK: {result['id']} - {result['title']}\n")


def run_youtube_auth_preflight():
    run_restricted_media_auth_preflight()


def empty_theme_summary():
    summary = {stage: 0.0 for stage in PIPELINE_STAGES}
    summary["total"] = 0.0
    return summary


def selected_pipeline_stages(args):
    stages = list(PIPELINE_STAGES)

    if args.only_stage:
        return [args.only_stage]

    if args.start_at_stage:
        stages = stages[stages.index(args.start_at_stage):]

    if args.stop_after_stage:
        stages = stages[:stages.index(args.stop_after_stage) + 1]

    return stages


def reconcile_stage_for_theme(theme):
    result = reconcile_theme(theme)
    moved = int(result.get("updated_count") or 0)

    if moved:
        print(f" -> moved {moved} gate-failed package(s) to needs_revision")
    else:
        print(" -> no gate-failed ready packages found")


def run_stage_for_theme(theme, stage, args, summary):
    if stage == "pull":
        timed_stage(summary, "pull", lambda: run_video_fetch(theme=theme))
        return True

    if stage == "clip":
        print(f"starting clip generation for {theme}")
        timed_stage(summary, "clip", lambda: run_clip_generation(theme=theme))
        return True

    if stage == "editorial":
        if args.skip_editorial:
            summary["editorial"] = 0.0
            print(f"daily editorial generation skipped for {theme}")
            return True

        print(f"starting daily editorial generation for {theme}")
        timed_stage(summary, "editorial", lambda: run_daily_editorial(theme=theme))
        return True

    if stage == "subtitle":
        if args.classic_clips or args.skip_editorial:
            print(f"starting classic subtitle generation for {theme}")
            timed_stage(summary, "subtitle", lambda: run_subtitle_generation(theme=theme))
        else:
            summary["subtitle"] = 0.0
            print(f"classic raw-clip subtitle generation skipped for {theme}; editorial outputs are upload-ready")

        return True

    if stage == "reconcile":
        print(f"reconciling editorial gates for {theme}")
        timed_stage(summary, "reconcile", lambda: reconcile_stage_for_theme(theme))
        return True

    if stage == "manifest":
        timed_stage(summary, "manifest", lambda: write_content_manifest(theme))
        return True

    if stage == "upload":
        if args.skip_youtube:
            summary["upload"] = 0.0
            print(f"upload-ready videos and metadata are prepared for {theme}; YouTube upload skipped")
            return True

        if not theme_has_youtube_upload_route(theme):
            summary["upload"] = 0.0
            print(
                f"YouTube upload skipped for generation-only theme '{theme}'. "
                f"Configure youtube.channel_handle in src/themes/{theme}.json to enable uploads."
            )
            return True

        print(f"starting YouTube private draft upload for {theme}")
        from upload import YouTubeUploadHalted, upload_youtube

        try:
            timed_stage(
                summary,
                "upload",
                lambda: upload_youtube(theme=theme, limit=resolved_youtube_upload_limit(args)),
            )
        except YouTubeUploadHalted as error:
            print(f"YouTube uploads halted for {theme}: {error}")
            return False

        print(f"YouTube upload complete for {theme}")
        return True

    raise ValueError(f"Unknown pipeline stage: {stage}")


def run_pipeline_for_theme(theme, args):
    theme_start = time.time()
    summary = empty_theme_summary()
    stages = selected_pipeline_stages(args)
    print(f"=== Running theme end-to-end: {theme} ===\n")

    for stage in stages:
        if stage == "pull":
            print(f"fetching latest videos for {theme}")
        elif stage != "upload":
            print(f"running {stage} stage for {theme}")

        succeeded = run_stage_for_theme(theme, stage, args, summary)

        if not succeeded:
            summary["total"] = time.time() - theme_start
            print_theme_summary(theme, summary)
            print("")
            return False, summary

    summary["total"] = time.time() - theme_start
    print_theme_summary(theme, summary)
    print("")
    return True, summary


def run_pipeline_by_stage(themes, args):
    run_start = time.time()
    stages = selected_pipeline_stages(args)
    theme_summaries = {theme: empty_theme_summary() for theme in themes}
    theme_started_at = {theme: run_start for theme in themes}
    failed_themes = []
    blocked_themes = set()

    print(
        "Running by process stage: "
        + " -> ".join(stages)
        + "\n"
    )

    for stage in stages:
        stage_start = time.time()
        runnable_themes = [theme for theme in themes if theme not in blocked_themes]

        if not runnable_themes:
            print(f"=== Stage: {stage} skipped; no themes remain runnable ===\n")
            break

        print(f"=== Stage: {stage} for themes: {', '.join(runnable_themes)} ===\n")

        for theme in runnable_themes:
            summary = theme_summaries[theme]

            try:
                print(f"--- {stage}: {theme} ---")
                succeeded = run_stage_for_theme(theme, stage, args, summary)
            except Exception as error:
                print(f"Theme '{theme}' failed during {stage}: {error}")
                traceback_module.print_exc()
                summary["error"] = str(error)
                summary["failed_stage"] = stage
                succeeded = False

            if not succeeded:
                summary["failed_stage"] = stage
                blocked_themes.add(theme)

                if theme not in failed_themes:
                    failed_themes.append(theme)

            summary["total"] = time.time() - theme_started_at[theme]
            print("")

        print(f"Stage {stage} complete in {format_duration(time.time() - stage_start)}\n")

    for theme in themes:
        theme_summaries[theme]["total"] = time.time() - theme_started_at[theme]

    return failed_themes, theme_summaries


def run_pipeline_by_theme(themes, args):
    failed_themes = []
    theme_summaries = {}

    for theme_name in themes:
        try:
            succeeded, summary = run_pipeline_for_theme(theme_name, args)
        except Exception as error:
            print(f"Theme '{theme_name}' failed with an unexpected error: {error}")
            traceback_module.print_exc()
            summary = empty_theme_summary()
            summary["error"] = str(error)
            succeeded = False

        theme_summaries[theme_name] = summary

        if not succeeded:
            failed_themes.append(theme_name)

    return failed_themes, theme_summaries


def print_theme_summary(theme, summary):
    print(f"--- Timing summary for {theme} ---")

    for label in ["pull", "clip", "editorial", "subtitle", "reconcile", "manifest", "upload", "total"]:
        if label in summary:
            print(f"{label}: {format_duration(summary[label])}")

    print("")


def print_overall_summary(theme_summaries):
    totals = {"pull": 0.0, "clip": 0.0, "editorial": 0.0, "subtitle": 0.0, "reconcile": 0.0, "manifest": 0.0, "upload": 0.0, "total": 0.0}

    for summary in theme_summaries.values():
        for label in totals:
            totals[label] += summary.get(label, 0.0)

    print("=== Overall Timing Summary ===")

    for theme, summary in theme_summaries.items():
        print(
            f"{theme}: total={format_duration(summary.get('total', 0.0))}, "
            f"pull={format_duration(summary.get('pull', 0.0))}, "
            f"clip={format_duration(summary.get('clip', 0.0))}, "
            f"editorial={format_duration(summary.get('editorial', 0.0))}, "
            f"subtitle={format_duration(summary.get('subtitle', 0.0))}, "
            f"reconcile={format_duration(summary.get('reconcile', 0.0))}, "
            f"manifest={format_duration(summary.get('manifest', 0.0))}, "
            f"upload={format_duration(summary.get('upload', 0.0))}"
        )

    print(
        "all themes: "
        f"total={format_duration(totals['total'])}, "
        f"pull={format_duration(totals['pull'])}, "
        f"clip={format_duration(totals['clip'])}, "
        f"editorial={format_duration(totals['editorial'])}, "
        f"subtitle={format_duration(totals['subtitle'])}, "
        f"reconcile={format_duration(totals['reconcile'])}, "
        f"manifest={format_duration(totals['manifest'])}, "
        f"upload={format_duration(totals['upload'])}"
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Run the shortform pipeline.")
    parser.add_argument(
        "--theme",
        help="Optional theme to run. Omit this to run every configured theme.",
    )
    parser.add_argument(
        "--start-at-theme",
        help="When running all themes, skip configured themes before this theme.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=["auto", "stage", "theme"],
        default="auto",
        help=(
            "Pipeline orchestration mode. auto runs all themes by stage and single-theme runs "
            "end-to-end; theme preserves the older one-theme-at-a-time ordering."
        ),
    )
    parser.add_argument(
        "--start-at-stage",
        choices=PIPELINE_STAGES,
        help="Resume production at this process stage without rerunning earlier stages.",
    )
    parser.add_argument(
        "--stop-after-stage",
        choices=PIPELINE_STAGES,
        help="Stop production after this process stage completes.",
    )
    parser.add_argument(
        "--only-stage",
        choices=PIPELINE_STAGES,
        help="Run exactly one process stage for the selected themes.",
    )
    parser.add_argument(
        "--clean-slate",
        action="store_true",
        help="Remove generated final clips, working clips, subtitle scratch, editorial metadata, and funnel state for the selected themes before running.",
    )
    parser.add_argument(
        "--clean-slate-only",
        action="store_true",
        help="Perform --clean-slate and exit without running fetch/clip/editorial/upload stages.",
    )
    parser.add_argument(
        "--keep-inactive-output",
        action="store_true",
        help="With --clean-slate, keep generated folders for inactive/future themes instead of removing them.",
    )
    parser.add_argument(
        "--upload-youtube",
        action="store_true",
        help="Upload ready clips to YouTube after subtitle generation. Uploading is now enabled by default.",
    )
    parser.add_argument(
        "--skip-youtube",
        action="store_true",
        help="Skip YouTube upload after subtitle generation.",
    )
    parser.add_argument(
        "--skip-media-auth-preflight",
        action="store_true",
        help="Skip restricted-video media auth preflight. Use only for public-video/debug tests.",
    )
    parser.add_argument(
        "--wait-for-media-auth",
        type=int,
        default=0,
        metavar="SECONDS",
        help=(
            "Keep retrying restricted-video media auth for this many seconds before production. "
            "Useful when you need time to close Chrome or install a fresh cookies.txt."
        ),
    )
    parser.add_argument(
        "--media-auth-retry-interval",
        type=int,
        default=20,
        metavar="SECONDS",
        help="Retry interval for --wait-for-media-auth.",
    )
    parser.add_argument(
        "--watch-cookie-exports",
        nargs="*",
        metavar="DIR",
        help=(
            "During --wait-for-media-auth, scan DIR for new cookie exports and install the newest "
            "one that passes restricted-video auth. Defaults to Downloads when no DIR is provided."
        ),
    )
    parser.add_argument(
        "--allow-browser-cookie-fallback",
        action="store_true",
        help=(
            "During media-auth preflight, allow yt-dlp to try browser cookie profiles after cookies.txt. "
            "Close Chrome/Edge fully first; browser databases are usually locked while the browser is open."
        ),
    )
    parser.add_argument(
        "--skip-editorial",
        action="store_true",
        help="Skip ranked countdown/editorial generation.",
    )
    parser.add_argument(
        "--classic-clips",
        action="store_true",
        help="Also generate classic raw subtitled clips in addition to editorial recaps.",
    )
    parser.add_argument(
        "--youtube-upload-limit",
        type=int,
        help="Optional max number of YouTube uploads per theme for this run.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run pipeline health checks and exit before any production work.",
    )
    parser.add_argument(
        "--validate-outputs",
        action="store_true",
        help="Validate generated output videos and metadata, then exit.",
    )
    parser.add_argument(
        "--validate-theme-engine",
        action="store_true",
        help="Validate all theme profile schemas and upload-routing readiness, then exit.",
    )
    parser.add_argument(
        "--theme-engine-audit",
        action="store_true",
        help="Audit the current implementation against the phase-one theme-engine brief, then exit.",
    )
    parser.add_argument(
        "--visual-regression",
        action="store_true",
        help="Render countdown transition previews and contact sheets for visual QA, then exit.",
    )
    parser.add_argument(
        "--reconcile-editorial-gates",
        action="store_true",
        help="Move gate-failed ready packages into needs_revision, then exit.",
    )
    parser.add_argument(
        "--scaffold-theme",
        help="Create a new theme JSON from the universal theme-engine schema, then exit.",
    )
    parser.add_argument(
        "--scaffold-profile",
        default="generic",
        help="Optional profile preset for --scaffold-theme.",
    )
    parser.add_argument(
        "--force-scaffold",
        action="store_true",
        help="Allow --scaffold-theme to overwrite an existing theme JSON.",
    )
    parser.add_argument(
        "--production-review",
        action="store_true",
        help="Create a consolidated production QC/postmortem report, then exit.",
    )
    parser.add_argument(
        "--review-dashboard",
        action="store_true",
        help="Create a local HTML review dashboard for generated clips, then exit.",
    )
    parser.add_argument(
        "--collect-analytics",
        action="store_true",
        help="Collect YouTube Analytics metrics for uploaded videos, then exit.",
    )
    parser.add_argument(
        "--analytics-days",
        type=int,
        default=30,
        help="Lookback days for --collect-analytics when --analytics-start-date is omitted.",
    )
    parser.add_argument(
        "--analytics-start-date",
        help="Optional YouTube Analytics start date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--analytics-end-date",
        help="Optional YouTube Analytics end date, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--experiment-report",
        action="store_true",
        help="Build an analytics experiment report from collected metric records, then exit.",
    )
    parser.add_argument(
        "--skip-review-validation",
        action="store_true",
        help="When using --production-review, reuse the latest validation report instead of running validation.",
    )
    parser.add_argument(
        "--skip-review-quality",
        action="store_true",
        help="When using --production-review, reuse the latest quality reports instead of rebuilding them.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.only_stage and (args.start_at_stage or args.stop_after_stage):
        raise SystemExit("--only-stage cannot be combined with --start-at-stage or --stop-after-stage.")

    if args.start_at_stage and args.stop_after_stage:
        if PIPELINE_STAGES.index(args.start_at_stage) > PIPELINE_STAGES.index(args.stop_after_stage):
            raise SystemExit("--start-at-stage cannot come after --stop-after-stage.")

    theme = clean_theme_name(args.theme) if args.theme else None

    if args.production_review:
        from production_review import create_production_review

        create_production_review(
            theme=theme,
            run_validation=not args.skip_review_validation,
            run_quality=not args.skip_review_quality,
        )
        return

    if args.review_dashboard:
        from review_dashboard import build_dashboard

        build_dashboard(theme=theme)
        return

    if args.validate_theme_engine:
        from theme_engine_validate import print_validation_summary, validate_theme_engine

        report = validate_theme_engine(theme=theme, write_report=True)
        print_validation_summary(report)

        if report["status"] != "ok":
            raise SystemExit(1)

        return

    if args.theme_engine_audit:
        from theme_engine_audit import build_audit, print_audit

        report = build_audit()
        print_audit(report)

        if report["status"] != "complete":
            raise SystemExit(1)

        return

    if args.visual_regression:
        from visual_regression import build_visual_regression_pack, print_visual_regression_report

        report = build_visual_regression_pack(theme=theme)
        print_visual_regression_report(report)

        if report["status"] == "error":
            raise SystemExit(1)

        return

    if args.scaffold_theme:
        from theme_scaffold import create_theme_scaffold

        create_theme_scaffold(
            args.scaffold_theme,
            profile_name=args.scaffold_profile,
            force=args.force_scaffold,
        )
        return

    if args.collect_analytics:
        from analytics.youtube_metrics import collect_all_theme_metrics, collect_theme_metrics

        if theme:
            collect_theme_metrics(
                theme,
                days=args.analytics_days,
                start_date=args.analytics_start_date,
                end_date=args.analytics_end_date,
            )
        else:
            collect_all_theme_metrics(
                days=args.analytics_days,
                start_date=args.analytics_start_date,
                end_date=args.analytics_end_date,
            )

        if not args.experiment_report:
            return

    if args.experiment_report:
        from analytics.experiment_analysis import build_experiment_report

        build_experiment_report(theme=theme)
        return

    with RunLogContext(args):
        if args.doctor:
            if not run_doctor(include_auth=True):
                raise SystemExit("Pipeline doctor found one or more failed checks.")

            return

        if args.validate_outputs:
            if not validate_outputs(theme=theme):
                raise SystemExit("Output validation found one or more failed checks.")

            return

        if args.reconcile_editorial_gates:
            if theme:
                reconcile_theme(theme)
            else:
                from reconcile_editorial_gates import reconcile_all

                reconcile_all()

            return

        explicit_theme_selection = [theme] if theme else requested_env_theme_names()
        guard_message = future_theme_guard_message(explicit_theme_selection)

        if guard_message:
            raise SystemExit(guard_message)

        themes = [theme] if theme else discover_themes()
        guard_message = future_theme_guard_message(themes)

        if guard_message:
            raise SystemExit(guard_message)

        start_at_theme = clean_theme_name(args.start_at_theme) if args.start_at_theme else None

        if start_at_theme and not theme:
            if start_at_theme not in themes:
                raise SystemExit(
                    f"--start-at-theme '{start_at_theme}' is not configured. "
                    f"Available themes: {', '.join(themes)}"
                )

            start_index = themes.index(start_at_theme)
            skipped_themes = themes[:start_index]
            themes = themes[start_index:]

            if skipped_themes:
                print(
                    "Skipping themes before "
                    f"{start_at_theme}: {', '.join(skipped_themes)}\n"
                )
        elif start_at_theme and theme:
            print("--start-at-theme ignored because --theme was provided.\n")

        if not themes:
            print("No themes configured. Add JSON theme files in src/themes.")
            return

        single_theme_run = bool(theme or os.getenv("SHORTFORM_THEME"))

        if single_theme_run:
            theme_label = themes[0] if themes else (theme or clean_theme_name(os.getenv("SHORTFORM_THEME")))
            print(f"Running one theme: {theme_label}\n")
        else:
            print(f"Running all themes: {', '.join(themes)}\n")

        if args.clean_slate_only:
            args.clean_slate = True

        if run_requires_media_auth_preflight(args):
            run_restricted_media_auth_preflight(
                wait_seconds=max(0, int(args.wait_for_media_auth or 0)),
                retry_interval=max(1, int(args.media_auth_retry_interval or 20)),
                cookie_export_dirs=args.watch_cookie_exports,
                allow_browser_cookie_fallback=bool(args.allow_browser_cookie_fallback),
            )

        if args.clean_slate:
            print(f"Cleaning generated artifacts and funnel state for: {', '.join(themes)}")
            clean_inactive = (
                not single_theme_run
                and not future_themes_allowed()
                and not args.keep_inactive_output
                and not start_at_theme
            )
            if start_at_theme and not args.keep_inactive_output:
                print(
                    "Clean-slate inactive/future cleanup disabled for resumed "
                    f"--start-at-theme run; skipped theme outputs are preserved."
                )
            clean_generated_artifacts(themes, include_inactive=clean_inactive)

            if args.clean_slate_only:
                print("Clean-slate reset complete; exiting before production stages.")
                return

        print(f"Default YouTube upload limit per theme: {resolved_youtube_upload_limit(args) or 'unlimited'}\n")

        if run_requires_youtube_upload(themes, args):
            print("YouTube upload routing is configured for at least one requested theme.")
        else:
            print("YouTube upload routing not configured for requested generation-only themes, or upload was skipped.\n")

        if args.execution_mode == "stage":
            use_stage_major = True
        elif args.execution_mode == "theme":
            use_stage_major = False
        else:
            use_stage_major = not single_theme_run

        if use_stage_major:
            failed_themes, theme_summaries = run_pipeline_by_stage(themes, args)
        else:
            failed_themes, theme_summaries = run_pipeline_by_theme(themes, args)

        print_overall_summary(theme_summaries)

        if failed_themes:
            print(f"Pipeline finished with upload failures for: {', '.join(failed_themes)}")
            sys.exit(1)

        print("Pipeline complete for all requested themes.")


if __name__ == "__main__":
    main()
