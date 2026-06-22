import argparse
import json
import os
import subprocess
import sys
import time

from theme_config import BASE_DIR, discover_themes, ensure_theme, load_json_file, write_json_file


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


ENABLE_FRAME_QA = os.getenv("SHORTFORM_VALIDATE_FRAME_QA", "1") != "0"
FINAL_FRAME_AUDITS = os.getenv("SHORTFORM_VALIDATE_FRAME_AUDITS", "1") != "0"
MIN_FINAL_VISUAL_QUALITY = float(os.getenv("SHORTFORM_MIN_FINAL_VISUAL_QUALITY", "0.55"))
EDITORIAL_FACE_QA_FORMATS = {"raw_subtitled_clip", "classic_clip"}


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
        "unstable final subject position",
        "alive frames often miss speaker",
        "extended no-speaker run in final crop",
        "weak final face plausibility",
    }

    for flag in sorted(hard_flags & non_face_hard_flags):
        issues.append(flag)

    if content_format in EDITORIAL_FACE_QA_FORMATS:
        for flag in sorted(hard_flags & face_hard_flags):
            issues.append(flag)

    if float(frame_qc.get("visual_quality_score") or 0.0) < MIN_FINAL_VISUAL_QUALITY:
        issues.append(
            f"low visual quality score ({float(frame_qc.get('visual_quality_score') or 0.0):.2f})"
        )

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
        if status not in {"ready", "failed", "uploaded"}:
            item_issues.append(f"unexpected YouTube posting status '{status}'")

        frame_qc = {}
        frame_issues = []

        if ENABLE_FRAME_QA:
            frame_qc, frame_issues = validate_frame_quality(theme, package, video_file)
            item_issues.extend(frame_issues)

        for issue in item_issues:
            issues.append(f"{label}: {issue}")

        results.append({
            "index": index,
            "video_file": video_file,
            "content_format": package.get("content_format", ""),
            "posting_status": status,
            "width": media["width"],
            "height": media["height"],
            "duration": round(media["duration"], 3),
            "frame_qc": frame_qc,
            "status": "ok" if not item_issues else "failed",
            "issues": item_issues,
        })

    return checked, issues, results


def validate_outputs(theme=None):
    themes = [theme] if theme else discover_themes()
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
