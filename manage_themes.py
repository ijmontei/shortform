import argparse

from theme_config import discover_themes, ensure_theme, load_theme_config, write_theme_config


def create_theme(theme, channels=None):
    paths = ensure_theme(theme, channels=channels or [])
    config = load_theme_config(paths["theme"])

    print(f"Theme ready: {paths['theme']}")
    print(f"Theme config: {paths['theme_config_file']}")
    print(f"Final videos: {paths['final_videos_path']}")
    print(f"Metadata: {paths['final_metadata_path']}")
    print(f"Channels: {len(config['channels'])}")


def add_channel(theme, channel_url):
    paths = ensure_theme(theme)
    config = load_theme_config(paths["theme"])
    channels = config["channels"]

    if channel_url not in channels:
        channels.append(channel_url)
        write_theme_config(paths["theme"], channels)

    print(f"Added channel to theme '{paths['theme']}': {channel_url}")


def list_themes():
    themes = discover_themes()

    if not themes:
        print("No themes configured.")
        return

    for theme in themes:
        config = load_theme_config(theme)
        print(f"{theme}: {len(config['channels'])} channels")


def main():
    parser = argparse.ArgumentParser(description="Manage shortform channel themes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a theme JSON file.")
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
