import argparse
import json
import os
import sys
import time

import ytdlp_auth
from clip_generation import run_clip_generation
from daily_editorial import run_daily_editorial
from pipeline_doctor import run_doctor
from subtitle_generation import run_subtitle_generation
from theme_config import BASE_DIR, clean_theme_name, discover_themes
from validate_outputs import validate_outputs
from video_fetch import run_video_fetch


LOGS_PATH = os.path.join(BASE_DIR, "logs")
RUNS_LOG_PATH = os.path.join(LOGS_PATH, "runs")
LATEST_LOG_FILE = os.path.join(LOGS_PATH, "run_latest.log")
LATEST_SUMMARY_FILE = os.path.join(LOGS_PATH, "run_latest_summary.json")
DEFAULT_YOUTUBE_UPLOAD_LIMIT = int(os.getenv("SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT", "15"))


class TeeStream:
    def __init__(self, stream, *files):
        self.stream = stream
        self.files = files

    def write(self, text):
        self.stream.write(text)

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


def resolved_youtube_upload_limit(args):
    if args.youtube_upload_limit is not None:
        return args.youtube_upload_limit

    if DEFAULT_YOUTUBE_UPLOAD_LIMIT <= 0:
        return None

    return DEFAULT_YOUTUBE_UPLOAD_LIMIT


def run_youtube_auth_preflight():
    if os.getenv("SHORTFORM_SKIP_YOUTUBE_AUTH_PREFLIGHT", "0") == "1":
        print("YouTube restricted-video auth preflight skipped by environment.\n")
        return

    if not ytdlp_auth.media_auth_required():
        print("YouTube restricted-video auth preflight skipped; media auth is not required.\n")
        return

    print("Checking YouTube restricted-video authentication...")
    try:
        result = ytdlp_auth.verify_youtube_auth()
    except ytdlp_auth.RestrictedVideoAuthError as error:
        print("Restricted-video auth failed.")
        print(error)
        raise SystemExit(str(error))

    print(f"Restricted-video auth OK: {result['id']} - {result['title']}\n")


def run_pipeline_for_theme(theme, args):
    theme_start = time.time()
    summary = {}
    print(f"=== Running theme end-to-end: {theme} ===\n")

    timed_stage(summary, "pull", lambda: run_video_fetch(theme=theme))

    print(f"starting clip generation for {theme}")
    timed_stage(summary, "clip", lambda: run_clip_generation(theme=theme))

    if args.skip_editorial:
        summary["editorial"] = 0.0
        print(f"daily editorial generation skipped for {theme}")
    else:
        print(f"starting daily editorial generation for {theme}")
        timed_stage(summary, "editorial", lambda: run_daily_editorial(theme=theme))

    if args.classic_clips or args.skip_editorial:
        print(f"starting classic subtitle generation for {theme}")
        timed_stage(summary, "subtitle", lambda: run_subtitle_generation(theme=theme))
    else:
        summary["subtitle"] = 0.0
        print("classic raw-clip subtitle generation skipped; editorial outputs are upload-ready")

    if args.skip_youtube:
        summary["upload"] = 0.0
        summary["total"] = time.time() - theme_start
        print_theme_summary(theme, summary)
        print(f"upload-ready videos and metadata are prepared for {theme}; YouTube upload skipped\n")
        return True, summary

    print(f"starting YouTube private draft upload for {theme}")
    from upload import YouTubeUploadHalted, upload_youtube

    try:
        timed_stage(
            summary,
            "upload",
            lambda: upload_youtube(theme=theme, limit=resolved_youtube_upload_limit(args)),
        )
    except YouTubeUploadHalted as error:
        summary["total"] = time.time() - theme_start
        print_theme_summary(theme, summary)
        print(f"YouTube uploads halted for {theme}: {error}\n")
        return False, summary

    summary["total"] = time.time() - theme_start
    print_theme_summary(theme, summary)
    print(f"YouTube upload complete for {theme}\n")
    return True, summary


def print_theme_summary(theme, summary):
    print(f"--- Timing summary for {theme} ---")

    for label in ["pull", "clip", "editorial", "subtitle", "upload", "total"]:
        if label in summary:
            print(f"{label}: {format_duration(summary[label])}")

    print("")


def print_overall_summary(theme_summaries):
    totals = {"pull": 0.0, "clip": 0.0, "editorial": 0.0, "subtitle": 0.0, "upload": 0.0, "total": 0.0}

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
            f"upload={format_duration(summary.get('upload', 0.0))}"
        )

    print(
        "all themes: "
        f"total={format_duration(totals['total'])}, "
        f"pull={format_duration(totals['pull'])}, "
        f"clip={format_duration(totals['clip'])}, "
        f"editorial={format_duration(totals['editorial'])}, "
        f"subtitle={format_duration(totals['subtitle'])}, "
        f"upload={format_duration(totals['upload'])}"
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Run the shortform pipeline.")
    parser.add_argument(
        "--theme",
        help="Optional theme to run. Omit this to run every configured theme.",
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
    return parser.parse_args()


def main():
    args = parse_args()

    with RunLogContext(args):
        if args.doctor:
            if not run_doctor(include_auth=True):
                raise SystemExit("Pipeline doctor found one or more failed checks.")

            return

        theme = clean_theme_name(args.theme) if args.theme else None

        if args.validate_outputs:
            if not validate_outputs(theme=theme):
                raise SystemExit("Output validation found one or more failed checks.")

            return

        themes = [theme] if theme else discover_themes()

        if not themes:
            print("No themes configured. Add JSON theme files in src/themes.")
            return

        if theme:
            print(f"Running one theme: {theme}\n")
        else:
            print(f"Running all themes: {', '.join(themes)}\n")

        print(f"Default YouTube upload limit per theme: {resolved_youtube_upload_limit(args) or 'unlimited'}\n")
        run_youtube_auth_preflight()

        failed_themes = []
        theme_summaries = {}

        for theme_name in themes:
            succeeded, summary = run_pipeline_for_theme(theme_name, args)
            theme_summaries[theme_name] = summary

            if not succeeded:
                failed_themes.append(theme_name)

        print_overall_summary(theme_summaries)

        if failed_themes:
            print(f"Pipeline finished with upload failures for: {', '.join(failed_themes)}")
            sys.exit(1)

        print("Pipeline complete for all requested themes.")


if __name__ == "__main__":
    main()
