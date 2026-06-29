import argparse
import json
import os
import subprocess
import sys
import time

from editorial_gates import RAW_RECYCLER_CONTENT_FORMATS, TRANSFORMED_CONTENT_FORMATS, evaluate_editorial_gates
from theme_config import BASE_DIR, THEMES_OUTPUT_PATH, clean_theme_name, discover_themes, ensure_theme, future_themes_allowed, load_json_file, write_json_file
from theme_profile import get_review_policy


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


ENABLE_FRAME_QA = os.getenv("SHORTFORM_VALIDATE_FRAME_QA", "1") != "0"
FINAL_FRAME_AUDITS = os.getenv("SHORTFORM_VALIDATE_FRAME_AUDITS", "1") != "0"
MIN_FINAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_FINAL_VISUAL_QUALITY", "0.55"))
EDITORIAL_FACE_QA_FORMATS = {"raw_subtitled_clip", "classic_clip"}
MIN_DOCUMENTARY_FINAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_DOCUMENTARY_FINAL_VISUAL_QUALITY", "0.60"))
MAX_TRANSFORMED_NO_FACE_RUN = float(os.getenv("SHORTFORM_MAX_TRANSFORMED_NO_FACE_RUN", "0.50"))
MAX_TRANSFORMED_ALIVE_NO_FACE = float(os.getenv("SHORTFORM_MAX_TRANSFORMED_ALIVE_NO_FACE", "0.62"))
DEFAULT_YOUTUBE_PRIVACY_STATUS = os.getenv("SHORTFORM_YOUTUBE_PRIVACY_STATUS", "public").strip().lower()
if DEFAULT_YOUTUBE_PRIVACY_STATUS not in {"public", "unlisted", "private"}:
    DEFAULT_YOUTUBE_PRIVACY_STATUS = "public"


def package_with_effective_youtube_metadata(package):
    package = dict(package or {})
    youtube_package = (package.get("platforms") or {}).get("youtube_shorts") or {}
    youtube_title = str(youtube_package.get("title") or "").strip()

    if youtube_title:
        package["title"] = youtube_title

    return package


def probe_video(path):
    result = subprocess.run(
        [
            FFPROBE_EXE,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-show_entries", "format=duration",
            "-of", "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe failed with exit code {result.returncode}")

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    duration = float((payload.get("format") or {}).get("duration") or 0)

    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": duration,
    }


def frame_audit_path(theme, video_file):
    audit_dir = os.path.join(BASE_DIR, "logs", "frame_validation", theme)
    os.makedirs(audit_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(video_file))[0]
    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in name)
    return os.path.join(audit_dir, f"{safe_name}_audit.jpg")


def validate_frame_quality(theme, package, video_file):
    if not ENABLE_FRAME_QA:
        return {}, []

    try:
        import clip_generation

        frame_qc = clip_generation.analyze_final_frame_path(video_file)

        if FINAL_FRAME_AUDITS:
            audit = clip_generation.create_frame_audit_contact_sheet(
                video_file,
                frame_audit_path(theme, video_file),
            )
            frame_qc["audit_file"] = audit.get("path", "")
            frame_qc["audit_created"] = bool(audit.get("created"))
    except Exception as error:
        return {"error": str(error)}, [f"frame QA failed: {error}"]

    issues = []
    content_format = package.get("content_format", "")
    hard_flags = set(frame_qc.get("flags") or [])
    non_face_hard_flags = {
        "could not open final render",
        "no final render frames",
        "no readable final frames",
        "final render has black frames",
        "final render has low-information frames",
        "final render has dead visual frames",
        "low final alive-frame rate",
    }
    face_hard_flags = {
        "low final face presence",
        "subject off-center in final crop",
        "subject severely off-center in final crop",
        "unstable final subject position",
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "weak final face plausibility",
        "probable tiny/background face lock",
        "probable picture-in-picture/background lock",
    }

    for flag in sorted(hard_flags & non_face_hard_flags):
        issues.append(flag)

    if content_format in EDITORIAL_FACE_QA_FORMATS:
        for flag in sorted(hard_flags & face_hard_flags):
            issues.append(flag)

    visual_score = float(frame_qc.get("visual_quality_score") or 0.0)
    face_presence = float(frame_qc.get("face_presence_rate") or 0.0)
    no_face_run = float(frame_qc.get("longest_no_face_run_ratio") or 0.0)
    alive_no_face = float(frame_qc.get("alive_no_face_frame_ratio") or 0.0)
    max_center_offset = float(frame_qc.get("max_face_center_offset_ratio") or 0.0)
    documentary_non_face_ok = (
        clean_theme_name(theme) in {"politics", "truecrime"}
        and content_format in TRANSFORMED_CONTENT_FORMATS
        and visual_score >= MIN_DOCUMENTARY_FINAL_VISUAL_QUALITY
        and no_face_run <= MAX_TRANSFORMED_NO_FACE_RUN
        and alive_no_face <= MAX_TRANSFORMED_ALIVE_NO_FACE
        and not (hard_flags & non_face_hard_flags)
        and not {
            "alive frames often miss speaker",
            "extended no-speaker run in final crop",
            "probable tiny/background face lock",
            "probable picture-in-picture/background lock",
            "subject severely off-center in final crop",
        } & hard_flags
    )

    if visual_score < MIN_FINAL_VISUAL_QUALITY and not documentary_non_face_ok:
        issues.append(
            f"low visual quality score ({visual_score:.2f})"
        )

    if content_format in TRANSFORMED_CONTENT_FORMATS:
        if no_face_run > (MAX_TRANSFORMED_NO_FACE_RUN if documentary_non_face_ok else 0.34):
            issues.append(f"transformed package has long no-speaker run ({no_face_run:.2f})")

        if alive_no_face > (MAX_TRANSFORMED_ALIVE_NO_FACE if documentary_non_face_ok else 0.46):
            issues.append(f"transformed package often misses speaker ({alive_no_face:.2f})")

        if face_presence and face_presence < (0.22 if documentary_non_face_ok else 0.36) and alive_no_face > 0.48:
            issues.append(f"transformed package has low speaker presence ({face_presence:.2f})")

        if (
            max_center_offset > 0.72
            and alive_no_face > 0.30
            and {
                "subject off-center in final crop",
                "unstable final subject position",
                "probable tiny/background face lock",
                "probable picture-in-picture/background lock",
            } & hard_flags
        ):
            issues.append("transformed package likely locked to background instead of speaker")

        if "probable picture-in-picture/background lock" in hard_flags:
            issues.append("transformed package likely locked to picture-in-picture/background")

    return frame_qc, issues


def validate_theme(theme):
    paths = ensure_theme(theme)
    metadata = load_json_file(paths["final_metadata_file"], {"theme": theme, "content": []})
    content = metadata.get("content", [])
    issues = []
    results = []
    checked = 0

    if not isinstance(content, list):
        return 0, [f"{theme}: metadata content is not a list"], []

    for index, package in enumerate(content, start=1):
        video_file = package.get("video_file", "")
        label = f"{theme} item {index}"

        if not video_file:
            issues.append(f"{label}: missing video_file")
            results.append({"index": index, "video_file": video_file, "status": "missing_video_file"})
            continue

        if not os.path.exists(video_file):
            issues.append(f"{label}: video file does not exist: {video_file}")
            results.append({"index": index, "video_file": video_file, "status": "missing_file"})
            continue

        checked += 1

        try:
            media = probe_video(video_file)
        except Exception as error:
            issues.append(f"{label}: ffprobe failed: {error}")
            results.append({"index": index, "video_file": video_file, "status": "probe_failed", "error": str(error)})
            continue

        item_issues = []

        if media["width"] != 1080 or media["height"] != 1920:
            item_issues.append(f"expected 1080x1920, got {media['width']}x{media['height']}")

        if media["duration"] <= 0:
            item_issues.append("duration is zero")

        if media["duration"] > 60.5 and package.get("content_format") != "daily_editorial_recap":
            item_issues.append(f"short is longer than 60s ({media['duration']:.1f}s)")

        status = (package.get("posting_status") or {}).get("youtube_shorts", "")
        if status not in {"ready", "failed", "uploaded", "needs_revision", "rejected"}:
            item_issues.append(f"unexpected YouTube posting status '{status}'")

        gate_package = package_with_effective_youtube_metadata(package)
        editorial_gates = evaluate_editorial_gates(theme, gate_package)
        youtube_package = (package.get("platforms") or {}).get("youtube_shorts") or {}
        privacy_status = str(youtube_package.get("privacy_status") or DEFAULT_YOUTUBE_PRIVACY_STATUS).lower()
        review = package.get("review") or {}
        content_format = package.get("content_format", "")
        upload_candidate_status = status in {"ready", "uploaded", "failed"}

        if upload_candidate_status and not editorial_gates.get("passed", True):
            item_issues.append(f"editorial gates failed: {', '.join(editorial_gates.get('flags') or [])}")

        if status in {"ready", "uploaded"} and not package.get("content_has_burned_captions"):
            item_issues.append("ready/uploaded package is missing burned-in captions flag")

        if status in {"ready", "uploaded"} and package.get("upload_ready_requires_burned_captions", True) is not True:
            item_issues.append("ready/uploaded package does not require burned-in captions")

        if status in {"ready", "uploaded"} and content_format in TRANSFORMED_CONTENT_FORMATS and not package.get("content_has_burned_captions"):
            item_issues.append("transformed upload-ready package is missing burned-in captions")

        if status in {"ready", "uploaded"} and content_format in RAW_RECYCLER_CONTENT_FORMATS and os.getenv("SHORTFORM_ALLOW_RAW_CLIP_UPLOADS", "0") != "1":
            item_issues.append("raw recycler clip is marked upload-ready without SHORTFORM_ALLOW_RAW_CLIP_UPLOADS=1")

        if status in {"ready", "uploaded"} and not package.get("editorial_gates"):
            item_issues.append("ready/uploaded package is missing stored editorial gate result")

        if status in {"ready", "uploaded"} and not str(youtube_package.get("title") or package.get("title") or "").strip():
            item_issues.append("ready/uploaded package is missing YouTube title")

        if (
            privacy_status != "private"
            and os.getenv("SHORTFORM_REQUIRE_MANUAL_APPROVAL_FOR_PUBLIC_UPLOAD", "0") == "1"
            and get_review_policy(theme).get("require_manual_approval_before_public", True)
            and not review.get("approved")
        ):
            item_issues.append(f"{privacy_status} upload requires manual review approval")

        frame_qc = {}
        frame_issues = []

        if ENABLE_FRAME_QA:
            frame_qc, frame_issues = validate_frame_quality(theme, package, video_file)

            if upload_candidate_status:
                item_issues.extend(frame_issues)

        for issue in item_issues:
            issues.append(f"{label}: {issue}")

        results.append({
            "index": index,
            "video_file": video_file,
            "content_format": package.get("content_format", ""),
            "posting_status": status,
            "privacy_status": privacy_status,
            "width": media["width"],
            "height": media["height"],
            "duration": round(media["duration"], 3),
            "frame_qc": frame_qc,
            "editorial_gates": editorial_gates,
            "status": "ok" if not item_issues else "failed",
            "issues": item_issues,
        })

    return checked, issues, results


def validate_outputs(theme=None):
    themes = [theme] if theme else discover_themes()
    active_theme_set = {clean_theme_name(theme_name) for theme_name in themes}
    ignored_output_dirs = []

    if not theme and not future_themes_allowed() and os.path.isdir(THEMES_OUTPUT_PATH):
        ignored_output_dirs = [
            name
            for name in sorted(os.listdir(THEMES_OUTPUT_PATH))
            if os.path.isdir(os.path.join(THEMES_OUTPUT_PATH, name))
            and clean_theme_name(name) not in active_theme_set
        ]

        if ignored_output_dirs:
            print(
                "Ignoring inactive/future-theme output folders: "
                f"{', '.join(ignored_output_dirs)}"
            )

    total_checked = 0
    all_issues = []
    theme_reports = {}

    for theme_name in themes:
        checked, issues, results = validate_theme(theme_name)
        total_checked += checked
        all_issues.extend(issues)
        theme_reports[theme_name] = {
            "checked": checked,
            "issue_count": len(issues),
            "items": results,
        }
        print(f"{theme_name}: checked {checked} video files, issues={len(issues)}")

    if all_issues:
        print("\nOutput validation issues:")

        for issue in all_issues:
            print(f"- {issue}")

    report = {
        "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "themes": theme_reports,
        "ignored_inactive_output_dirs": ignored_output_dirs,
        "checked": total_checked,
        "issue_count": len(all_issues),
        "issues": all_issues,
    }
    report_path = os.path.join(BASE_DIR, "logs", "output_validation_latest.json")
    write_json_file(report_path, report)
    print(f"\nOutput validation report: {report_path}")
    print(f"Output validation complete: checked={total_checked}, issues={len(all_issues)}")
    return not all_issues


def parse_args():
    parser = argparse.ArgumentParser(description="Validate generated shortform output files and metadata.")
    parser.add_argument("--theme", help="Optional theme to validate. Omit to validate every theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    sys.exit(0 if validate_outputs(theme=args.theme) else 1)
