import argparse
import os

from theme_config import discover_themes, ensure_theme


def read_channels(channels_file):
    if not os.path.exists(channels_file):
        return []

    with open(channels_file, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]


def write_channels(channels_file, channels):
    with open(channels_file, "w", encoding="utf-8") as f:
        f.write("\n".join(channels))
        f.write("\n")


def create_theme(theme):
    paths = ensure_theme(theme)

    if not os.path.exists(paths["channels_file"]):
        write_channels(paths["channels_file"], [])

    print(f"Theme ready: {paths['theme']}")
    print(f"Channels file: {paths['channels_file']}")
    print(f"Output folder: {paths['output_path']}")


def add_channel(theme, channel_url):
    paths = ensure_theme(theme)
    channels = read_channels(paths["channels_file"])

    if channel_url not in channels:
        channels.append(channel_url)
        write_channels(paths["channels_file"], channels)

    print(f"Added channel to theme '{paths['theme']}': {channel_url}")


def list_themes():
    for theme in discover_themes():
        paths = ensure_theme(theme)
        channels = read_channels(paths["channels_file"])
        print(f"{paths['theme']}: {len(channels)} channels")


def main():
    parser = argparse.ArgumentParser(description="Manage shortform channel themes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a theme folder.")
    create_parser.add_argument("theme")

    add_parser = subparsers.add_parser("add-channel", help="Add a YouTube channel URL to a theme.")
    add_parser.add_argument("theme")
    add_parser.add_argument("channel_url")

    subparsers.add_parser("list", help="List configured themes.")

    args = parser.parse_args()

    if args.command == "create":
        create_theme(args.theme)
    elif args.command == "add-channel":
        add_channel(args.theme, args.channel_url)
    elif args.command == "list":
        list_themes()


if __name__ == "__main__":
    main()
