import argparse

from clip_generation import run_clip_generation
from subtitle_generation import run_subtitle_generation
from theme_config import clean_theme_name, discover_themes
from video_fetch import run_video_fetch


def parse_args():
    parser = argparse.ArgumentParser(description="Run the shortform pipeline.")
    parser.add_argument(
        "--theme",
        help="Optional theme to run. Omit this to run every configured theme.",
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

    run_video_fetch(theme=theme)
    print("video fetch complete")
    print("starting clip generation")
    run_clip_generation(theme=theme)
    print("clip generation complete")
    print("starting subtitle generation")
    run_subtitle_generation(theme=theme)
    print("subtitle generation complete")
    print("upload-ready videos and metadata are prepared")


if __name__ == "__main__":
    main()
