import argparse
import json
import os
import re
import time

from quality_lab import build_theme_quality_report
from editorial_gates import evaluate_editorial_gates
from theme_config import BASE_DIR, discover_themes, load_json_file, write_json_file
from theme_engine_validate import REPORT_PATH as THEME_ENGINE_VALIDATION_REPORT, validate_theme_engine
from validate_outputs import validate_outputs
import ytdlp_auth


LOGS_PATH = os.path.join(BASE_DIR, "logs")
PRODUCTION_REVIEWS_PATH = os.path.join(LOGS_PATH, "production_reviews")
MEDIA_AUTH_WAIT_STATUS_FILE = os.path.join(LOGS_PATH, "media_auth_wait_latest.json")


def safe_read_text(path, max_chars=120000):
    if not path or not os.path.exists(path):
        return ""

    with open(path, "rb") as f:
        data = f.read(max_chars)

    return data.replace(b"\x00", b"").decode("utf-8", errors="replace")


def parse_run_log(log_path):
    text = safe_read_text(log_path)
    current_theme = ""
    theme_fetch = {}
    slow_sources = []
    failures = []
    stage_timings = {}
    scoring_source = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()

        theme_match = re.search(r"=== Running theme end-to-end: ([^=]+?) ===", line)
        if theme_match:
            current_theme = theme_match.group(1).strip()
            stage_timings.setdefault(current_theme, {})
            continue

        fetch_match = re.search(r"New videos:\s*(\d+);\s*refreshed existing:\s*(\d+)", line)
        if fetch_match and current_theme:
            theme_fetch[current_theme] = {
                "new_videos": int(fetch_match.group(1)),
                "refreshed_existing": int(fetch_match.group(2)),
            }
            continue

        scoring_match = re.search(r"Downloading audio-only package for scoring:\s*(.+)", line)
        if scoring_match:
            scoring_source = scoring_match.group(1).strip()
            continue

        duration_match = re.search(r"=== Candidate scoring duration for video:\s*([0-9.]+)\s*seconds.*\((\d+) kept", line)
        if duration_match:
            seconds = float(duration_match.group(1))
            slow_sources.append({
                "theme": current_theme,
                "source": scoring_source,
                "seconds": seconds,
                "kept_for_theme_ranking": int(duration_match.group(2)),
            })
            continue

        stage_match = re.search(r"^(pull|clip|editorial|subtitle|upload|total):\s*(.+)$", line)
        if stage_match and current_theme:
            stage_timings.setdefault(current_theme, {})[stage_match.group(1)] = stage_match.group(2)
            continue

        if line.startswith("Failed to ") or " failed" in line.lower() or "ERROR:" in line:
            failures.append({
                "theme": current_theme,
                "line": line[:500],
            })

    slow_sources = sorted(slow_sources, key=lambda item: item["seconds"], reverse=True)
    return {
        "theme_fetch": theme_fetch,
        "slow_sources": slow_sources[:25],
        "failures": failures[:100],
        "stage_timings": stage_timings,
    }


def theme_output_summary(theme):
    final_metadata_path = os.path.join(BASE_DIR, "output", "themes", theme, "metadata.json")
    metadata = load_json_file(final_metadata_path, {"theme": theme, "content": []})
    content = metadata.get("content") or []
    temp_metadata_path = os.path.join(BASE_DIR, "output", "temp", theme, "metadata")
    clip_reviews = 0
    source_dossiers = 0

    if os.path.isdir(temp_metadata_path):
        clip_reviews = len([
            name for name in os.listdir(temp_metadata_path)
            if name.endswith("_clip_review.json")
        ])
        dossier_dir = os.path.join(temp_metadata_path, "source_dossiers")

        if os.path.isdir(dossier_dir):
            source_dossiers = len([
                name for name in os.listdir(dossier_dir)
                if name.endswith("_source_dossier.json")
            ])

    rejected = [
        item for item in content
        if ((item.get("posting_status") or {}).get("youtube_shorts") == "rejected")
        or ((item.get("review") or {}).get("rejected"))
    ]
    failed = [
        item for item in content
        if ((item.get("posting_status") or {}).get("youtube_shorts") == "failed")
    ]
    ready = [
        item for item in content
        if ((item.get("posting_status") or {}).get("youtube_shorts") == "ready")
    ]
    approved = [
        item for item in content
        if ((item.get("review") or {}).get("approved"))
    ]
    editorial = [
        item for item in content
        if str(item.get("content_format", "")).startswith(("daily_editorial", "popular_segment"))
    ]
    editorial_gate_failures = []
    gate_passed_ready = []

    for index, item in enumerate(content, start=1):
        gates = item.get("editorial_gates") or evaluate_editorial_gates(theme, item)
        status = (item.get("posting_status") or {}).get("youtube_shorts")

        if not gates.get("passed", True):
            editorial_gate_failures.append({
                "index": index,
                "title": item.get("title", ""),
                "video_file": item.get("video_file", ""),
                "flags": gates.get("flags", []),
                "transformation_score": gates.get("transformation_score"),
                "theme_signal_score": gates.get("theme_signal_score"),
                "reused_content_risk": gates.get("reused_content_risk"),
            })
        elif status == "ready":
            gate_passed_ready.append(item)

    return {
        "rendered_ready_outputs": len(ready),
        "upload_ready_outputs": len(gate_passed_ready),
        "metadata_items": len(content),
        "editorial_videos_generated": len(editorial),
        "approved_metadata_items": len(approved),
        "rejected_metadata_items": len(rejected),
        "failed_metadata_items": len(failed),
        "clip_review_files": clip_reviews,
        "source_dossier_files": source_dossiers,
        "editorial_gate_failure_count": len(editorial_gate_failures),
        "editorial_gate_failures": editorial_gate_failures[:10],
    }


def latest_restricted_auth_audit_status():
    audit = load_json_file(os.path.join(LOGS_PATH, "theme_engine_audit_latest.json"), {})

    for item in audit.get("requirements") or []:
        if str(item.get("requirement") or "").startswith("Restricted/age-gated YouTube media auth"):
            return {
                "status": item.get("status", "missing"),
                "gap": item.get("gap", ""),
                "evidence": item.get("evidence", []),
            }

    return {"status": "missing", "gap": "No latest theme-engine auth audit found.", "evidence": []}


def restricted_media_auth_summary():
    diagnostics = ytdlp_auth.cookie_file_diagnostics()
    wait_status = load_json_file(MEDIA_AUTH_WAIT_STATUS_FILE, {})
    return {
        "required": ytdlp_auth.media_auth_required(),
        "cookie_file": diagnostics.get("path", ""),
        "cookie_exists": diagnostics.get("exists", False),
        "cookie_size_kb": diagnostics.get("size_kb", 0.0),
        "cookie_non_comment_lines": diagnostics.get("non_comment_lines", 0),
        "cookie_modified_at": diagnostics.get("modified_at", ""),
        "cookie_age_hours": diagnostics.get("age_hours"),
        "cookie_domains": diagnostics.get("domains", []),
        "cookie_warnings": diagnostics.get("warnings", []),
        "latest_audit": latest_restricted_auth_audit_status(),
        "wait_status_file": MEDIA_AUTH_WAIT_STATUS_FILE,
        "wait_status": wait_status,
    }


def create_production_review(theme=None, run_validation=True, run_quality=True):
    themes = [theme] if theme else discover_themes()
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run_summary_path = os.path.join(LOGS_PATH, "run_latest_summary.json")
    run_log_path = os.path.join(LOGS_PATH, "run_latest.log")
    run_summary = load_json_file(run_summary_path, {})
    run_log_parse = parse_run_log(run_log_path)
    validation_ok = None

    if run_validation:
        validation_ok = validate_outputs(theme=theme)

    validation_report = load_json_file(os.path.join(LOGS_PATH, "output_validation_latest.json"), {})
    visual_regression_report = load_json_file(os.path.join(LOGS_PATH, "visual_regression_latest.json"), {})
    auth_summary = restricted_media_auth_summary()
    visual_regression_by_theme = {
        item.get("theme"): item
        for item in visual_regression_report.get("results") or []
        if item.get("theme")
    }
    theme_engine_validation = validate_theme_engine(theme=theme, write_report=True)
    quality_reports = {}

    for theme_name in themes:
        quality_report = {}

        if run_quality:
            _, quality_report = build_theme_quality_report(theme_name)
        else:
            quality_report = load_json_file(
                os.path.join(LOGS_PATH, "quality_lab", f"{theme_name}_quality_lab.json"),
                {},
            )

        quality_reports[theme_name] = quality_report

    theme_summaries = {}

    for theme_name in themes:
        quality_summary = (quality_reports.get(theme_name) or {}).get("summary") or {}
        validation_theme = (validation_report.get("themes") or {}).get(theme_name, {})
        visual_theme = visual_regression_by_theme.get(theme_name) or {}
        theme_summaries[theme_name] = {
            **theme_output_summary(theme_name),
            "fetch": (run_log_parse.get("theme_fetch") or {}).get(theme_name, {}),
            "timings": (run_log_parse.get("stage_timings") or {}).get(theme_name, {}),
            "validation_checked": validation_theme.get("checked", 0),
            "validation_issues": validation_theme.get("issue_count", 0),
            "visual_regression_status": visual_theme.get("status", "missing"),
            "visual_regression_contact_sheet": visual_theme.get("contact_sheet", ""),
            "visual_regression_video_file": visual_theme.get("video_file", ""),
            "visual_regression_placeholder_lane": visual_theme.get("max_placeholder_lane_ratio"),
            "selected_clip_count": quality_summary.get("selected_clip_count", 0),
            "rejected_clip_count": quality_summary.get("rejected_clip_count", 0),
            "avg_visual_quality": quality_summary.get("avg_visual_quality"),
            "avg_readiness_score": quality_summary.get("avg_readiness_score"),
            "avg_theme_signal_score": quality_summary.get("avg_theme_signal_score"),
            "avg_transformation_score": quality_summary.get("avg_transformation_score"),
            "avg_reused_content_risk": quality_summary.get("avg_reused_content_risk"),
            "analytics_feedback_enabled_count": quality_summary.get("analytics_feedback_enabled_count", 0),
            "avg_analytics_feedback_adjustment": quality_summary.get("avg_analytics_feedback_adjustment"),
            "source_mining_tiers": quality_summary.get("source_mining_tiers", {}),
            "slow_source_review_count": quality_summary.get("slow_source_review_count", 0),
            "slowest_sources": quality_summary.get("slowest_sources", []),
        }

    report = {
        "generated_at": generated_at,
        "themes": themes,
        "run_summary": run_summary,
        "run_log_file": run_log_path,
        "validation_ok": validation_ok,
        "validation_report_file": os.path.join(LOGS_PATH, "output_validation_latest.json"),
        "visual_regression_status": visual_regression_report.get("status"),
        "visual_regression_report_file": os.path.join(LOGS_PATH, "visual_regression_latest.json"),
        "visual_regression_root_dir": visual_regression_report.get("root_dir"),
        "restricted_media_auth": auth_summary,
        "theme_engine_validation_status": theme_engine_validation.get("status"),
        "theme_engine_validation_report_file": THEME_ENGINE_VALIDATION_REPORT,
        "theme_engine_validation_summary": {
            "theme_count": theme_engine_validation.get("theme_count"),
            "error_count": theme_engine_validation.get("error_count"),
            "warning_count": theme_engine_validation.get("warning_count"),
            "generation_only_themes": theme_engine_validation.get("generation_only_themes"),
        },
        "analytics_report_files": {
            theme_name: os.path.join(LOGS_PATH, "analytics", "theme_reports", f"{theme_name}_analytics_report.json")
            for theme_name in themes
        },
        "theme_summaries": theme_summaries,
        "slow_sources_from_log": run_log_parse.get("slow_sources", []),
        "failures_from_log": run_log_parse.get("failures", []),
        "quality_report_files": {
            theme_name: os.path.join(LOGS_PATH, "quality_lab", f"{theme_name}_quality_lab.json")
            for theme_name in themes
        },
    }
    os.makedirs(PRODUCTION_REVIEWS_PATH, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    report_path = os.path.join(PRODUCTION_REVIEWS_PATH, f"production_review_{stamp}.json")
    latest_path = os.path.join(PRODUCTION_REVIEWS_PATH, "production_review_latest.json")
    write_json_file(report_path, report)
    write_json_file(latest_path, report)
    print(f"Production review report: {report_path}")
    print(f"Production review latest: {latest_path}")
    return report_path, report


def parse_args():
    parser = argparse.ArgumentParser(description="Create a consolidated production QC/postmortem report.")
    parser.add_argument("--theme", help="Optional theme to review. Omit for every theme.")
    parser.add_argument("--skip-validation", action="store_true", help="Do not run output validation first.")
    parser.add_argument("--skip-quality", action="store_true", help="Do not rebuild quality-lab reports first.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    create_production_review(
        theme=args.theme,
        run_validation=not args.skip_validation,
        run_quality=not args.skip_quality,
    )
