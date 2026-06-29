import os
import shutil
import time

from theme_config import clean_theme_name, ensure_theme, load_json_file, write_json_file


UPLOADABLE_STATUSES = {"ready", "failed"}


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


def promote_archive_packages(archive, content, content_dir, queue_limit):
    promoted = []
    remaining_archive = []
    max_promotions = queue_limit if queue_limit and queue_limit > 0 else len(archive or [])

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

    promoted = []
    archived = []

    if uploadable_content_count(content, content_dir) == 0 and archive:
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
        "content_dir": content_dir,
        "archive_dir": archive_dir,
    }
