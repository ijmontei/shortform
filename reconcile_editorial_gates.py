import argparse
import os
import shutil
import time

from editorial_gates import evaluate_editorial_gates
from theme_config import BASE_DIR, clean_theme_name, discover_themes, ensure_theme, load_json_file, write_json_file


RECONCILIATION_LOG_DIR = os.path.join(BASE_DIR, "logs", "reconciliation")


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


def write_reconciliation_report(result):
    os.makedirs(RECONCILIATION_LOG_DIR, exist_ok=True)
    theme = clean_theme_name(result.get("theme") or "unknown")
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    report = {
        **result,
        "generated_at": utc_now(),
    }
    latest_path = os.path.join(RECONCILIATION_LOG_DIR, f"reconcile_{theme}_latest.json")
    history_path = os.path.join(RECONCILIATION_LOG_DIR, f"reconcile_{theme}_{stamp}.json")
    report["latest_report_file"] = latest_path
    report["history_report_file"] = history_path
    write_json_file(latest_path, report)
    write_json_file(history_path, report)
    return latest_path


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
    checked_count = 0
    gate_changed_count = 0
    refreshed_count = 0
    quarantined_count = 0
    status_counts = {}

    for index, package in enumerate(metadata.get("content", []), start=1):
        status = (package.get("posting_status") or {}).get("youtube_shorts", "")
        status_counts[status or "missing"] = status_counts.get(status or "missing", 0) + 1
        checked_count += 1

        if status in {"ready", "failed", "uploaded"}:
            refresh_preupload_quality(package)
            refreshed_count += 1

        gates = evaluate_editorial_gates(theme, package_with_effective_youtube_metadata(package))

        if package.get("editorial_gates") != gates:
            changed = True
            gate_changed_count += 1

            if not dry_run:
                package["editorial_gates"] = gates

        if status in {"ready", "failed", "uploaded"} and not gates.get("passed", True):
            changed = True
            update_record = {
                "index": index,
                "title": package.get("title", ""),
                "previous_status": status,
                "flags": gates.get("flags", []),
                "video_file": package.get("video_file", ""),
                "gate_summary": {
                    "title_support": gates.get("title_support", {}),
                    "title_quality": gates.get("title_quality", {}),
                    "render_qc_passed": gates.get("render_qc_passed"),
                    "context_evidence": gates.get("context_evidence", {}),
                },
            }
            updated.append(update_record)

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
                quarantine_file = quarantine_revision_file(paths, package, dry_run=dry_run)
                if quarantine_file:
                    quarantined_count += 1
                    update_record["quarantine_file"] = quarantine_file

        elif status == "needs_revision" and not gates.get("passed", True):
            quarantine_path = quarantine_revision_file(paths, package, dry_run=dry_run)

            if quarantine_path:
                changed = True
                quarantined_count += 1

        elif not package.get("editorial_gates"):
            changed = True

    if changed and not dry_run:
        write_json_file(paths["final_metadata_file"], metadata)

    result = {
        "theme": theme,
        "dry_run": dry_run,
        "checked_count": checked_count,
        "status_counts": status_counts,
        "refreshed_preupload_qc_count": refreshed_count,
        "gate_changed_count": gate_changed_count,
        "quarantined_count": quarantined_count,
        "updated_count": len(updated),
        "updated": updated,
        "metadata_file": paths["final_metadata_file"],
    }
    result["report_file"] = write_reconciliation_report(result)
    return result


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
