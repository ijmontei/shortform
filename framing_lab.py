import argparse
import json
import os
import time

from theme_config import BASE_DIR, ensure_theme, write_json_file

import clip_generation as cg


DEFAULT_STRATEGIES = [
    "face_locked",
    "stable_face_lock",
    "group_face_lock",
    "dual_speaker_stack",
    "center_safe",
]


def safe_name(value):
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value or "")).strip("_") or "sample"


def candidate_media_files(paths):
    videos_path = paths["videos_path"]

    if not os.path.isdir(videos_path):
        return []

    media = []

    for filename in sorted(os.listdir(videos_path)):
        lowered = filename.lower()

        if lowered.endswith(".part"):
            continue

        if not lowered.endswith((".mp4", ".mkv", ".webm", ".mov")):
            continue

        path = os.path.abspath(os.path.join(videos_path, filename))

        if os.path.getsize(path) <= 1_000_000:
            continue

        media.append(path)

    return media


def cut_sample(source_file, sample_file, start_seconds, duration_seconds):
    cg.run_subprocess([
        cg.FFMPEG_EXE,
        "-y",
        "-ss", str(max(0.0, float(start_seconds))),
        "-i", source_file,
        "-t", str(max(1.0, float(duration_seconds))),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        sample_file,
    ], "framing lab sample cut")
    cg.assert_file_exists(sample_file, "Framing lab sample")


def attempt_summary(attempt):
    qc = attempt.get("render_qc") or {}
    crop = qc.get("crop") or {}
    frame_path = qc.get("frame_path") or {}

    return {
        "strategy": attempt.get("strategy", ""),
        "quality": round(float(qc.get("attempt_quality_score") or 0.0), 4),
        "visual_quality": round(float(qc.get("visual_quality_score") or 0.0), 4),
        "passed": bool(qc.get("passed")),
        "flags": qc.get("flags", []),
        "audit_file": qc.get("frame_audit_file", ""),
        "face_presence_rate": round(float(frame_path.get("face_presence_rate") or 0.0), 4),
        "alive_no_face_frame_ratio": round(float(frame_path.get("alive_no_face_frame_ratio") or 0.0), 4),
        "longest_no_face_run_ratio": round(float(frame_path.get("longest_no_face_run_ratio") or 0.0), 4),
        "low_information_frame_ratio": round(float(frame_path.get("low_information_frame_ratio") or 0.0), 4),
        "dead_frame_ratio": round(float(frame_path.get("dead_frame_ratio") or 0.0), 4),
        "alive_frame_rate": round(float(frame_path.get("alive_frame_rate") or 0.0), 4),
        "blank_background_frame_ratio": round(float(frame_path.get("blank_background_frame_ratio") or 0.0), 4),
        "avg_edge_density": round(float(frame_path.get("avg_edge_density") or 0.0), 4),
        "avg_laplacian_var": round(float(frame_path.get("avg_laplacian_var") or 0.0), 2),
        "avg_face_plausibility": round(float(frame_path.get("avg_face_plausibility") or 0.0), 4),
        "avg_face_center_offset_ratio": round(float(frame_path.get("avg_face_center_offset_ratio") or 0.0), 4),
        "center_jitter_ratio": round(float(frame_path.get("center_jitter_ratio") or 0.0), 4),
        "continuity_center_jitter_ratio": round(float(frame_path.get("continuity_center_jitter_ratio") or 0.0), 4),
        "visual_cut_ratio": round(float(frame_path.get("visual_cut_ratio") or 0.0), 4),
        "avg_sample_visual_change": round(float(frame_path.get("avg_sample_visual_change") or 0.0), 4),
        "framing_score": round(float(crop.get("framing_score") or 0.0), 4),
        "face_detection_rate": round(float(crop.get("face_detection_rate") or 0.0), 4),
        "stable_face_confidence": round(float(crop.get("stable_face_confidence") or 0.0), 4),
        "group_face_confidence": round(float(crop.get("group_face_confidence") or 0.0), 4),
        "group_face_span_px": round(float(crop.get("group_face_span_px") or 0.0), 2),
        "dual_stack_frame_rate": round(float(crop.get("dual_stack_frame_rate") or 0.0), 4),
        "dual_stack_detection_rate": round(float(crop.get("dual_stack_detection_rate") or 0.0), 4),
        "dual_stack_fallback_frame_rate": round(float(crop.get("dual_stack_fallback_frame_rate") or 0.0), 4),
    }


def run_strategy_bakeoff(theme, source_file, sample_index, start_seconds, duration_seconds, strategies):
    paths = ensure_theme(theme)
    cg.configure_theme(theme)
    face_cascades = cg.load_face_cascades()
    report_dir = os.path.join(BASE_DIR, "logs", "framing_lab", theme)
    audit_dir = os.path.join(report_dir, "audits")
    temp_dir = os.path.join(report_dir, "temp")
    os.makedirs(audit_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    source_key = safe_name(os.path.splitext(os.path.basename(source_file))[0])
    sample_key = f"{sample_index:02d}_{source_key}_{int(start_seconds)}_{int(duration_seconds)}"
    sample_file = os.path.join(temp_dir, f"{sample_key}_sample.mp4")
    cleanup = [sample_file]
    attempts = []

    try:
        cut_sample(source_file, sample_file, start_seconds, duration_seconds)
        preflight = cg.preflight_clip_visual_qc(sample_file, face_cascades)

        for strategy in strategies:
            tracked_file = os.path.join(temp_dir, f"{sample_key}_{strategy}.avi")
            final_file = os.path.join(temp_dir, f"{sample_key}_{strategy}.mp4")
            cleanup.extend([tracked_file, final_file])

            try:
                attempt = cg.render_crop_attempt(
                    temp_subclip=sample_file,
                    temp_tracked_avi=tracked_file,
                    final_filename=final_file,
                    strategy=strategy,
                    model=None,
                    face_cascades=face_cascades,
                    expected_duration=duration_seconds,
                    audit_path=os.path.join(audit_dir, f"{sample_key}_{strategy}.jpg"),
                )
                attempts.append(attempt_summary(attempt))
            except Exception as error:
                attempts.append({
                    "strategy": strategy,
                    "quality": 0.0,
                    "visual_quality": 0.0,
                    "passed": False,
                    "flags": [f"strategy failed: {error}"],
                    "audit_file": "",
                })

        winner = max(attempts, key=lambda item: item.get("quality", 0.0)) if attempts else {}
        return {
            "source_file": source_file,
            "sample_file": sample_file,
            "sample_file_retained": False,
            "sample_index": sample_index,
            "start_seconds": float(start_seconds),
            "duration_seconds": float(duration_seconds),
            "preflight": preflight,
            "winner": winner.get("strategy", ""),
            "winner_quality": winner.get("quality", 0.0),
            "attempts": attempts,
        }
    finally:
        for path in cleanup:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass


def run_framing_lab(theme, limit=2, start_seconds=0.0, duration_seconds=4.0, strategies=None):
    strategies = strategies or DEFAULT_STRATEGIES
    paths = ensure_theme(theme)
    media_files = candidate_media_files(paths)[:max(1, int(limit))]
    report_dir = os.path.join(BASE_DIR, "logs", "framing_lab", theme)
    os.makedirs(report_dir, exist_ok=True)
    samples = []

    for index, source_file in enumerate(media_files, start=1):
        print(f"Framing lab sample {index}: {source_file}")
        samples.append(run_strategy_bakeoff(
            theme=theme,
            source_file=source_file,
            sample_index=index,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
            strategies=strategies,
        ))

    strategy_wins = {}
    strategy_quality = {}
    flag_counts = {}

    for sample in samples:
        if sample.get("winner"):
            strategy_wins[sample["winner"]] = strategy_wins.get(sample["winner"], 0) + 1

        for attempt in sample.get("attempts", []):
            strategy = attempt.get("strategy", "")
            strategy_quality.setdefault(strategy, []).append(float(attempt.get("quality") or 0.0))

            for flag in attempt.get("flags") or []:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1

    report = {
        "theme": theme,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings": {
            "limit": int(limit),
            "start_seconds": float(start_seconds),
            "duration_seconds": float(duration_seconds),
            "strategies": strategies,
        },
        "summary": {
            "samples": len(samples),
            "strategy_wins": strategy_wins,
            "avg_strategy_quality": {
                strategy: round(sum(values) / len(values), 4)
                for strategy, values in sorted(strategy_quality.items())
                if values
            },
            "flag_counts": flag_counts,
        },
        "samples": samples,
    }
    output_path = os.path.join(report_dir, "framing_lab_latest.json")
    write_json_file(output_path, report)
    print(f"\nFraming lab report: {output_path}")
    return output_path, report


def parse_args():
    parser = argparse.ArgumentParser(description="Run a short framing strategy bakeoff across local downloaded media.")
    parser.add_argument("--theme", default="comedy", help="Theme to inspect.")
    parser.add_argument("--limit", type=int, default=2, help="Number of local media files to sample.")
    parser.add_argument("--start", type=float, default=0.0, help="Start time inside each media file.")
    parser.add_argument("--seconds", type=float, default=4.0, help="Sample duration in seconds.")
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated crop strategies to compare.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_framing_lab(
        theme=args.theme,
        limit=args.limit,
        start_seconds=args.start,
        duration_seconds=args.seconds,
        strategies=[item.strip() for item in args.strategies.split(",") if item.strip()],
    )
