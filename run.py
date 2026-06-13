import argparse
import sys
import time

from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation
from theme_config import clean_theme_name, discover_themes
from video_fetch import run_video_fetch


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


def run_pipeline_for_theme(theme, args):
    theme_start = time.time()
    summary = {}
    print(f"=== Running theme end-to-end: {theme} ===\n")

    timed_stage(summary, "pull", lambda: run_video_fetch(theme=theme))

    print(f"starting clip generation for {theme}")
    timed_stage(summary, "clip", lambda: run_clip_generation(theme=theme))

    print(f"starting subtitle generation for {theme}")
    timed_stage(summary, "subtitle", lambda: run_subtitle_generation(theme=theme))

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
            lambda: upload_youtube(theme=theme, limit=args.youtube_upload_limit),
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

    for label in ["pull", "clip", "subtitle", "upload", "total"]:
        if label in summary:
            print(f"{label}: {format_duration(summary[label])}")

    print("")


def print_overall_summary(theme_summaries):
    totals = {"pull": 0.0, "clip": 0.0, "subtitle": 0.0, "upload": 0.0, "total": 0.0}

    for summary in theme_summaries.values():
        for label in totals:
            totals[label] += summary.get(label, 0.0)

    print("=== Overall Timing Summary ===")

    for theme, summary in theme_summaries.items():
        print(
            f"{theme}: total={format_duration(summary.get('total', 0.0))}, "
            f"pull={format_duration(summary.get('pull', 0.0))}, "
            f"clip={format_duration(summary.get('clip', 0.0))}, "
            f"subtitle={format_duration(summary.get('subtitle', 0.0))}, "
            f"upload={format_duration(summary.get('upload', 0.0))}"
        )

    print(
        "all themes: "
        f"total={format_duration(totals['total'])}, "
        f"pull={format_duration(totals['pull'])}, "
        f"clip={format_duration(totals['clip'])}, "
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
        "--youtube-upload-limit",
        type=int,
        help="Optional max number of YouTube uploads per theme for this run.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    theme = clean_theme_name(args.theme) if args.theme else None
    themes = [theme] if theme else discover_themes()

    if not themes:
        print("No themes configured. Add JSON theme files in src/themes.")
        return

    if theme:
        print(f"Running one theme: {theme}\n")
    else:
        print(f"Running all themes: {', '.join(themes)}\n")

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
