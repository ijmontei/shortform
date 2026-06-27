import argparse
import os
import time

from theme_config import clean_theme_name, discover_themes, ensure_theme, load_json_file, write_json_file


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def package_label(package):
    return os.path.basename(package.get("video_file", "")) or package.get("title", "untitled")


def review_status(package):
    review = package.get("review") or {}

    if review.get("rejected") or package.get("posting_status", {}).get("youtube_shorts") == "rejected":
        return "rejected"

    if review.get("approved"):
        return "approved"

    return "needs_review"


def load_theme_metadata(theme):
    paths = ensure_theme(theme)
    return paths, load_json_file(paths["final_metadata_file"], {"theme": clean_theme_name(theme), "content": []})


def save_theme_metadata(paths, metadata):
    write_json_file(paths["final_metadata_file"], metadata)


def find_package(content, selector):
    if selector.index is not None:
        index = int(selector.index) - 1

        if index < 0 or index >= len(content):
            raise SystemExit(f"Index {selector.index} is outside the review queue.")

        return index, content[index]

    wanted = os.path.basename(selector.video_file or "")

    if not wanted:
        raise SystemExit("Provide --index or --video-file.")

    for index, package in enumerate(content):
        if os.path.basename(package.get("video_file", "")) == wanted:
            return index, package

    raise SystemExit(f"No package matched video file '{wanted}'.")


def list_queue(theme=None, show_all=False):
    themes = [clean_theme_name(theme)] if theme else discover_themes()
    total = 0

    for theme_name in themes:
        _, metadata = load_theme_metadata(theme_name)
        content = metadata.get("content", [])
        rows = []

        for index, package in enumerate(content, start=1):
            status = review_status(package)

            if not show_all and status != "needs_review":
                continue

            rows.append((index, status, package))

        if not rows:
            continue

        print(f"\n{theme_name}")

        for index, status, package in rows:
            total += 1
            print(
                f"{index:03d} [{status}] {package.get('title', 'Untitled')} "
                f"({package_label(package)})"
            )

    if not total:
        print("No matching review items found.")

    return total


def approve_package(theme, selector, notes=""):
    paths, metadata = load_theme_metadata(theme)
    index, package = find_package(metadata.get("content", []), selector)
    review = package.setdefault("review", {})
    review.update({
        "approved": True,
        "rejected": False,
        "rejection_reason": "",
        "notes": notes or review.get("notes", ""),
        "reviewed_at": utc_now(),
    })

    if package.get("video_file"):
        package.setdefault("posting_status", {})["youtube_shorts"] = "ready"

    save_theme_metadata(paths, metadata)
    print(f"Approved {clean_theme_name(theme)} item {index + 1}: {package_label(package)}")


def reject_package(theme, selector, reason, notes=""):
    if not reason:
        raise SystemExit("--reason is required when rejecting a package.")

    paths, metadata = load_theme_metadata(theme)
    index, package = find_package(metadata.get("content", []), selector)
    review = package.setdefault("review", {})
    review.update({
        "approved": False,
        "rejected": True,
        "rejection_reason": reason,
        "notes": notes or review.get("notes", ""),
        "reviewed_at": utc_now(),
    })
    package.setdefault("posting_status", {})["youtube_shorts"] = "rejected"
    save_theme_metadata(paths, metadata)
    print(f"Rejected {clean_theme_name(theme)} item {index + 1}: {package_label(package)}")


def request_revision(theme, selector, action, notes=""):
    valid_actions = {
        "regenerate_title",
        "regenerate_captions",
        "try_shorter_cut",
        "try_longer_cut",
        "try_cold_open",
        "try_context_card",
        "try_alternate_framing",
        "mark_source_weak",
        "mark_source_high_value",
    }

    if action not in valid_actions:
        raise SystemExit(f"Unknown action '{action}'. Valid actions: {', '.join(sorted(valid_actions))}")

    paths, metadata = load_theme_metadata(theme)
    index, package = find_package(metadata.get("content", []), selector)
    review = package.setdefault("review", {})
    requests = review.setdefault("requests", [])
    request = {
        "action": action,
        "notes": notes,
        "requested_at": utc_now(),
        "status": "open",
    }
    requests.append(request)
    review["approved"] = False
    review["rejected"] = False
    review["needs_revision"] = True
    review["reviewed_at"] = utc_now()
    package.setdefault("posting_status", {})["youtube_shorts"] = "needs_revision"
    save_theme_metadata(paths, metadata)
    print(f"Requested {action} for {clean_theme_name(theme)} item {index + 1}: {package_label(package)}")


def parse_args():
    parser = argparse.ArgumentParser(description="Approve or reject generated Shortform output packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List packages waiting for review.")
    list_parser.add_argument("--theme", help="Optional theme to inspect.")
    list_parser.add_argument("--all", action="store_true", help="Show approved/rejected packages too.")

    for command in ["approve", "reject"]:
        subparser = subparsers.add_parser(command, help=f"{command.title()} one package.")
        subparser.add_argument("--theme", required=True, help="Theme containing the package.")
        selector_group = subparser.add_mutually_exclusive_group(required=True)
        selector_group.add_argument("--index", type=int, help="1-based package index in the theme metadata file.")
        selector_group.add_argument("--video-file", help="Video filename or path to match.")
        subparser.add_argument("--notes", default="", help="Optional review notes.")

        if command == "reject":
            subparser.add_argument("--reason", required=True, help="Reason this package should not upload.")

    request_parser = subparsers.add_parser("request", help="Request a regeneration/framing/cut/title action.")
    request_parser.add_argument("--theme", required=True, help="Theme containing the package.")
    request_selector = request_parser.add_mutually_exclusive_group(required=True)
    request_selector.add_argument("--index", type=int, help="1-based package index in the theme metadata file.")
    request_selector.add_argument("--video-file", help="Video filename or path to match.")
    request_parser.add_argument("--action", required=True, help="Revision action to request.")
    request_parser.add_argument("--notes", default="", help="Optional request notes.")

    return parser.parse_args()


def main():
    args = parse_args()

    if args.command == "list":
        list_queue(theme=args.theme, show_all=args.all)
    elif args.command == "approve":
        approve_package(args.theme, args, notes=args.notes)
    elif args.command == "reject":
        reject_package(args.theme, args, reason=args.reason, notes=args.notes)
    elif args.command == "request":
        request_revision(args.theme, args, action=args.action, notes=args.notes)


if __name__ == "__main__":
    main()
