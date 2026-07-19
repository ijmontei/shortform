import os
import shutil
import time

from theme_config import clean_theme_name, ensure_theme, load_json_file, write_json_file


UPLOADABLE_STATUSES = {"ready", "failed"}
REVISION_STATUSES = {"needs_revision", "rejected"}


def utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def package_status(package):
    return str(((package.get("posting_status") or {}).get("youtube_shorts") or "")).lower()


def package_uploadable(package):
    return package_status(package) in UPLOADABLE_STATUSES


def package_key(package):
    source_key = str(package.get("source_state_key") or "").strip()
    content_format = str(package.get("content_format") or "").strip()
    output_name = os.path.basename(str(package.get("video_file") or ""))
    title = str(package.get("title") or "").strip().lower()
    return "|".join([source_key, content_format, output_name, title])


def unique_destination_path(directory, filename):
    os.makedirs(directory, exist_ok=True)
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 2

    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{base}_{counter}{ext}")
        counter += 1

    return candidate


def move_package_video(package, target_dir):
    video_file = str(package.get("video_file") or "").strip()

    if not video_file or not os.path.exists(video_file):
        return False

    source = os.path.abspath(video_file)
    target_dir = os.path.abspath(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    if os.path.dirname(source) == target_dir:
        package["video_file"] = source
        return True

    target = unique_destination_path(target_dir, os.path.basename(source))
    shutil.move(source, target)
    package["video_file"] = os.path.abspath(target)
    return True


def package_has_existing_video(package):
    video_file = str(package.get("video_file") or "").strip()
    return bool(video_file and os.path.exists(video_file))


def package_in_directory(package, directory):
    video_file = str(package.get("video_file") or "").strip()

    if not video_file:
        return False

    try:
        return os.path.commonpath([os.path.abspath(video_file), os.path.abspath(directory)]) == os.path.abspath(directory)
    except ValueError:
        return False


def dedupe_packages(packages):
    deduped = []
    seen = set()

    for package in packages or []:
        if not isinstance(package, dict):
            continue

        key = package_key(package)

        if key in seen:
            continue

        seen.add(key)
        deduped.append(package)

    return deduped


def uploadable_content_count(content, content_dir):
    return sum(
        1
        for package in content or []
        if package_uploadable(package)
        and package_has_existing_video(package)
        and package_in_directory(package, content_dir)
    )


def drop_missing_video_packages(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    dropped = []

    for collection in ("content", "archive"):
        retained = []

        for package in metadata.get(collection) or []:
            if not isinstance(package, dict):
                continue

            video_file = str(package.get("video_file") or "").strip()

            if video_file and os.path.exists(video_file):
                retained.append(package)
                continue

            dropped.append({
                "collection": collection,
                "title": package.get("title", ""),
                "video_file": video_file,
                "posting_status": package_status(package),
                "source_state_key": package.get("source_state_key", ""),
                "dropped_at": utc_timestamp(),
            })

        metadata[collection] = retained

    if dropped:
        existing = metadata.get("dropped_missing_outputs") or []
        metadata["dropped_missing_outputs"] = (existing + dropped)[-200:]

    return dropped


def package_video_paths(metadata):
    paths = set()

    for collection in ("content", "archive", "needs_revision"):
        for package in metadata.get(collection) or []:
            if not isinstance(package, dict):
                continue

            video_file = str(package.get("video_file") or "").strip()

            if not video_file:
                continue

            paths.add(os.path.normcase(os.path.abspath(video_file)))

    return paths


def title_from_filename(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = stem.removesuffix("_upload")
    parts = stem.split("_")

    while parts and (
        parts[0].isdigit()
        or parts[0].count("-") == 2
        or parts[0] in {"countdown", "popular", "daily", "scan"}
        or parts[0].lower() in {"comedy", "finance", "popculture", "technology", "ai", "gaming"}
    ):
        parts.pop(0)

    title = " ".join(parts).replace("  ", " ").strip()
    return title or stem.replace("_", " ").strip()


def rescue_orphan_video_packages(theme, metadata, content_dir, archive_dir):
    metadata = metadata if isinstance(metadata, dict) else {}
    known_paths = package_video_paths(metadata)
    rescued = []

    for directory, collection in ((content_dir, "content"), (archive_dir, "archive")):
        if not os.path.isdir(directory):
            continue

        for filename in os.listdir(directory):
            if not filename.lower().endswith(".mp4"):
                continue

            path = os.path.abspath(os.path.join(directory, filename))
            normalized = os.path.normcase(path)

            if normalized in known_paths:
                continue

            package = {
                "theme": theme,
                "title": title_from_filename(filename),
                "video_file": path,
                "posting_status": {"youtube_shorts": "ready"},
                "upload_status": "pending",
                "content_has_burned_captions": True,
                "upload_ready_requires_burned_captions": True,
                "archive_status": "rescued_orphan_file" if collection == "archive" else "",
                "rescued_from_orphan_file_at": utc_timestamp(),
                "source_state_key": f"rescued_orphan|{theme}|{filename}",
                "content_format": "rescued_editorial_output",
            }
            metadata.setdefault(collection, []).append(package)
            known_paths.add(normalized)
            rescued.append(package)

    return rescued


def separate_revision_packages(metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    revision_packages = metadata.get("needs_revision") if isinstance(metadata.get("needs_revision"), list) else []
    moved = []

    for collection in ("content", "archive"):
        retained = []

        for package in metadata.get(collection) or []:
            if not isinstance(package, dict):
                continue

            if package_status(package) in REVISION_STATUSES:
                package["revision_collection_source"] = collection
                revision_packages.append(package)
                moved.append(package)
                continue

            retained.append(package)

        metadata[collection] = retained

    metadata["needs_revision"] = dedupe_packages(revision_packages)
    return moved


def promote_archive_packages(archive, content, content_dir, queue_limit):
    promoted = []
    remaining_archive = []
    if queue_limit and queue_limit > 0:
        existing_uploadable = uploadable_content_count(content, content_dir)
        max_promotions = max(0, queue_limit - existing_uploadable)
    else:
        max_promotions = len(archive or [])

    for package in archive or []:
        if len(promoted) >= max_promotions:
            remaining_archive.append(package)
            continue

        if not package_uploadable(package) or not package_has_existing_video(package):
            remaining_archive.append(package)
            continue

        if not move_package_video(package, content_dir):
            remaining_archive.append(package)
            continue

        package["archive_status"] = "promoted"
        package["promoted_from_archive_at"] = utc_timestamp()
        content.append(package)
        promoted.append(package)

    return remaining_archive, promoted


def archive_overflow_packages(content, archive, archive_dir, queue_limit):
    if queue_limit is None or queue_limit <= 0:
        return content, archive, []

    retained_content = []
    archived = []
    uploadable_seen = 0
    existing_archive_keys = {package_key(package) for package in archive or []}

    for package in content or []:
        if (
            package_uploadable(package)
            and package_has_existing_video(package)
            and not package_in_directory(package, archive_dir)
        ):
            uploadable_seen += 1

            if uploadable_seen > queue_limit:
                if move_package_video(package, archive_dir):
                    package["archive_status"] = "archived_overflow"
                    package["archived_at"] = utc_timestamp()
                    key = package_key(package)

                    if key not in existing_archive_keys:
                        archive.append(package)
                        existing_archive_keys.add(key)

                    archived.append(package)
                    continue

        retained_content.append(package)

    return retained_content, archive, archived


def prepare_upload_queue(theme, queue_limit=15):
    theme = clean_theme_name(theme)
    paths = ensure_theme(theme)
    content_dir = paths["final_videos_path"]
    archive_dir = paths["archive_path"]
    metadata_file = paths["final_metadata_file"]
    metadata = load_json_file(metadata_file, {"theme": theme, "content": [], "archive": []})

    content = metadata.get("content") if isinstance(metadata, dict) else []
    archive = metadata.get("archive") if isinstance(metadata, dict) else []
    content = dedupe_packages(content if isinstance(content, list) else [])
    archive = dedupe_packages(archive if isinstance(archive, list) else [])
    metadata["content"] = content
    metadata["archive"] = archive
    rescued = rescue_orphan_video_packages(theme, metadata, content_dir, archive_dir)
    dropped_missing = drop_missing_video_packages(metadata)
    revision_moved = separate_revision_packages(metadata)
    content = metadata["content"]
    archive = metadata["archive"]

    promoted = []
    archived = []

    if archive and (not queue_limit or queue_limit <= 0 or uploadable_content_count(content, content_dir) < queue_limit):
        archive, promoted = promote_archive_packages(archive, content, content_dir, queue_limit)

    content, archive, archived = archive_overflow_packages(content, archive, archive_dir, queue_limit)

    metadata["theme"] = theme
    metadata["content"] = dedupe_packages(content)
    metadata["archive"] = dedupe_packages(archive)
    metadata["archive_policy"] = {
        "upload_queue_limit": queue_limit if queue_limit and queue_limit > 0 else "unlimited",
        "archive_dir": archive_dir,
        "updated_at": utc_timestamp(),
    }
    write_json_file(metadata_file, metadata)

    return {
        "theme": theme,
        "content_count": len(metadata["content"]),
        "archive_count": len(metadata["archive"]),
        "promoted_count": len(promoted),
        "archived_count": len(archived),
        "rescued_orphan_count": len(rescued),
        "dropped_missing_count": len(dropped_missing),
        "revision_moved_count": len(revision_moved),
        "content_dir": content_dir,
        "archive_dir": archive_dir,
    }
