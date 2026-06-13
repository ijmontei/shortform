import argparse
import sys

from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation
from theme_config import clean_theme_name, discover_themes
from video_fetch import run_video_fetch


def run_pipeline_for_theme(theme, args):
    print(f"=== Running theme end-to-end: {theme} ===\n")

    run_video_fetch(theme=theme)
    print(f"video fetch complete for {theme}")

    print(f"starting clip generation for {theme}")
    run_clip_generation(theme=theme)
    print(f"clip generation complete for {theme}")

    print(f"starting subtitle generation for {theme}")
    run_subtitle_generation(theme=theme)
    print(f"subtitle generation complete for {theme}")

    if args.skip_youtube:
        print(f"upload-ready videos and metadata are prepared for {theme}; YouTube upload skipped\n")
        return True

    print(f"starting YouTube private draft upload for {theme}")
    from upload import YouTubeUploadHalted, upload_youtube

    try:
        upload_youtube(theme=theme, limit=args.youtube_upload_limit)
    except YouTubeUploadHalted as error:
        print(f"YouTube uploads halted for {theme}: {error}\n")
        return False

    print(f"YouTube upload complete for {theme}\n")
    return True


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

    for theme_name in themes:
        if not run_pipeline_for_theme(theme_name, args):
            failed_themes.append(theme_name)

    if failed_themes:
        print(f"Pipeline finished with upload failures for: {', '.join(failed_themes)}")
        sys.exit(1)

    print("Pipeline complete for all requested themes.")


if __name__ == "__main__":
    main()
