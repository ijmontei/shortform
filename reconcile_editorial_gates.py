import argparse
import os
import shutil
import time

from editorial_gates import evaluate_editorial_gates
from theme_config import clean_theme_name, discover_themes, ensure_theme, load_json_file, write_json_file


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def package_with_effective_youtube_metadata(package):
    package = dict(package or {})
    youtube_package = (package.get("platforms") or {}).get("youtube_shorts") or {}
    youtube_title = str(youtube_package.get("title") or "").strip()

    if youtube_title:
        package["title"] = youtube_title

    return package


def refresh_preupload_quality(package):
    try:
        from upload import refresh_package_intro_audio_qc, refresh_package_render_qc
    except Exception:
        return package

    refresh_package_render_qc(package)
    refresh_package_intro_audio_qc(package)
    return package


def path_within(path, root):
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def unique_destination(path):
    if not os.path.exists(path):
        return path

    directory = os.path.dirname(path)
    stem, extension = os.path.splitext(os.path.basename(path))

    for index in range(1, 1000):
        candidate = os.path.join(directory, f"{stem}_{index}{extension}")

        if not os.path.exists(candidate):
            return candidate

    raise RuntimeError(f"Could not choose a unique quarantine path for {path}")


def quarantine_revision_file(paths, package, dry_run=False):
    video_file = package.get("video_file", "")

    if not video_file or not os.path.exists(video_file):
        return ""

    output_root = paths["output_path"]
    content_root = paths["final_videos_path"]
    quarantine_root = os.path.join(output_root, "needs_revision")
    absolute_video = os.path.abspath(video_file)

    if not path_within(absolute_video, output_root):
        return ""

    if not path_within(absolute_video, content_root):
        return ""

    destination = unique_destination(os.path.join(quarantine_root, os.path.basename(video_file)))

    if dry_run:
        return destination

    os.makedirs(quarantine_root, exist_ok=True)
    shutil.move(absolute_video, destination)
    package["video_file"] = destination
    package.setdefault("review", {})["quarantine_file"] = destination
    package["review"]["quarantined_at"] = utc_now()
    return destination


def reconcile_theme(theme, dry_run=False):
    paths = ensure_theme(theme)
    theme = clean_theme_name(theme)
    metadata = load_json_file(paths["final_metadata_file"], {"theme": theme, "content": []})
    changed = False
    updated = []

    for index, package in enumerate(metadata.get("content", []), start=1):
        status = (package.get("posting_status") or {}).get("youtube_shorts", "")

        if status in {"ready", "failed", "uploaded"}:
            refresh_preupload_quality(package)

        gates = evaluate_editorial_gates(theme, package_with_effective_youtube_metadata(package))

        if package.get("editorial_gates") != gates:
            changed = True

            if not dry_run:
                package["editorial_gates"] = gates

        if status in {"ready", "failed", "uploaded"} and not gates.get("passed", True):
            changed = True
            updated.append({
                "index": index,
                "title": package.get("title", ""),
                "previous_status": status,
                "flags": gates.get("flags", []),
                "video_file": package.get("video_file", ""),
            })

            if not dry_run:
                review = package.setdefault("review", {})
                review["approved"] = False
                review["needs_revision"] = True
                review["rejection_reason"] = "; ".join(gates.get("flags") or [])
                review["reviewed_at"] = utc_now()
                requests = review.setdefault("requests", [])
                requests.append({
                    "action": "editorial_gate_revision",
                    "notes": f"Failed editorial gates: {', '.join(gates.get('flags') or [])}",
                    "requested_at": utc_now(),
                    "status": "open",
                })
                package.setdefault("posting_status", {})["youtube_shorts"] = "needs_revision"
                quarantine_revision_file(paths, package, dry_run=dry_run)

        elif status == "needs_revision" and not gates.get("passed", True):
            quarantine_path = quarantine_revision_file(paths, package, dry_run=dry_run)

            if quarantine_path:
                changed = True

        elif not package.get("editorial_gates"):
            changed = True

    if changed and not dry_run:
        write_json_file(paths["final_metadata_file"], metadata)

    return {
        "theme": theme,
        "dry_run": dry_run,
        "updated_count": len(updated),
        "updated": updated,
        "metadata_file": paths["final_metadata_file"],
    }


def reconcile_all(dry_run=False):
    return {
        theme: reconcile_theme(theme, dry_run=dry_run)
        for theme in discover_themes()
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Move gate-failed ready packages into review revision state.")
    parser.add_argument("--theme", help="Optional theme to reconcile. Omit with --all for every theme.")
    parser.add_argument("--all", action="store_true", help="Reconcile every discovered theme.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing metadata.")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.all:
        results = reconcile_all(dry_run=args.dry_run)
    elif args.theme:
        result = reconcile_theme(args.theme, dry_run=args.dry_run)
        results = {result["theme"]: result}
    else:
        raise SystemExit("Use --theme THEME or --all.")

    total = sum(result.get("updated_count", 0) for result in results.values())
    print(f"Editorial gate reconciliation complete. Updated: {total}")

    for theme, result in results.items():
        if result.get("updated_count"):
            print(f" - {theme}: {result['updated_count']} moved to needs_revision")

            for item in result.get("updated", [])[:10]:
                previous = item.get("previous_status") or "unknown"
                print(f"   #{item['index']} {item['title']} ({previous}) [{', '.join(item.get('flags') or [])}]")


if __name__ == "__main__":
    main()
