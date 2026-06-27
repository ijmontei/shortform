import argparse
import json
import os
import time

from theme_config import BASE_DIR, discover_themes, ensure_theme, load_json_file, write_json_file

RESCAN_MISSING_FRAME_METRICS = os.getenv("SHORTFORM_QUALITY_LAB_RESCAN_FRAMES", "1") != "0"
INCLUDE_VERIFICATION_ARTIFACTS = os.getenv("SHORTFORM_QUALITY_LAB_INCLUDE_VERIFICATION", "0") == "1"
VERIFICATION_NAME_MARKERS = (
    "_verification",
    "_smoke",
    "_debug",
    "_test",
)


def is_verification_artifact(path):
    if INCLUDE_VERIFICATION_ARTIFACTS:
        return False

    name = os.path.basename(str(path or "")).lower()
    return any(marker in name for marker in VERIFICATION_NAME_MARKERS)


def _average_report_metric(reports, key):
    values = [
        float(report.get(key) or 0.0)
        for report in reports
        if report.get(key) is not None
    ]

    if not values:
        return None

    return round(sum(values) / len(values), 4)


def _frame_path_for_clip(clip, render_qc):
    frame_path = render_qc.get("frame_path") or {}

    has_current_metrics = (
        "dead_frame_ratio" in frame_path
        and "alive_no_face_frame_ratio" in frame_path
        and "longest_no_face_run_ratio" in frame_path
        and "visual_cut_ratio" in frame_path
        and "continuity_center_jitter_ratio" in frame_path
    )

    if has_current_metrics or not RESCAN_MISSING_FRAME_METRICS:
        return frame_path

    output_file = clip.get("output_file", "")

    if not output_file or not os.path.exists(output_file):
        return frame_path

    try:
        import clip_generation

        rescanned = clip_generation.analyze_final_frame_path(output_file)
        return rescanned or frame_path
    except Exception:
        return frame_path


def summarize_clip_review(path):
    payload = load_json_file(path, {})
    selected = payload.get("selected") or []
    inventory = payload.get("candidate_inventory") or {}
    source_title = ""
    source_video_url = ""
    topic_counts = {}
    visual_scores = []
    readiness_scores = []
    theme_signal_scores = []
    transformation_scores = []
    reused_content_risks = []
    analytics_feedback_adjustments = []
    analytics_feedback_enabled = 0
    readiness_tiers = {}
    dead_frame_ratios = []
    alive_frame_rates = []
    face_presence_rates = []
    face_plausibility_scores = []
    alive_no_face_ratios = []
    longest_no_face_run_ratios = []
    visual_cut_ratios = []
    continuity_center_jitter_ratios = []
    dual_stack_frame_rates = []
    render_strategy_counts = {}
    qc_flags = {}
    rejected_count = 0
    readiness_missing_count = 0

    for clip in selected:
        render_qc = clip.get("render_qc") or {}
        crop = render_qc.get("crop") or {}
        visual_score = render_qc.get("visual_quality_score")
        frame_path = _frame_path_for_clip(clip, render_qc)
        readiness_score = clip.get("readiness_score")
        theme_signal_score = clip.get("theme_signal_score")
        transformation_score = clip.get("transformation_score")
        reused_content_risk = clip.get("reused_content_risk")
        readiness_tier = (clip.get("rank_signals") or {}).get("readiness_tier", "")
        analytics_feedback = (clip.get("rank_signals") or {}).get("analytics_feedback_prior") or {}
        source_title = source_title or clip.get("source_title", "")
        source_video_url = source_video_url or clip.get("source_video_url", "")

        for term in clip.get("topic_fingerprint") or []:
            topic_counts[term] = topic_counts.get(term, 0) + 1

        if visual_score is not None:
            visual_scores.append(float(visual_score or 0.0))

        if readiness_score is not None:
            readiness_scores.append(float(readiness_score or 0.0))
        else:
            readiness_missing_count += 1

        if theme_signal_score is not None:
            theme_signal_scores.append(float(theme_signal_score or 0.0))

        if transformation_score is not None:
            transformation_scores.append(float(transformation_score or 0.0))

        if reused_content_risk is not None:
            reused_content_risks.append(float(reused_content_risk or 0.0))

        if analytics_feedback.get("enabled"):
            analytics_feedback_enabled += 1
            analytics_feedback_adjustments.append(float(analytics_feedback.get("score_adjustment") or 0.0))

        if readiness_tier:
            readiness_tiers[readiness_tier] = readiness_tiers.get(readiness_tier, 0) + 1

        if "dead_frame_ratio" in frame_path:
            dead_frame_ratios.append(float(frame_path.get("dead_frame_ratio") or 0.0))

        if "alive_frame_rate" in frame_path:
            alive_frame_rates.append(float(frame_path.get("alive_frame_rate") or 0.0))

        if "face_presence_rate" in frame_path:
            face_presence_rates.append(float(frame_path.get("face_presence_rate") or 0.0))

        if "alive_no_face_frame_ratio" in frame_path:
            alive_no_face_ratios.append(float(frame_path.get("alive_no_face_frame_ratio") or 0.0))

        if "longest_no_face_run_ratio" in frame_path:
            longest_no_face_run_ratios.append(float(frame_path.get("longest_no_face_run_ratio") or 0.0))

        if "visual_cut_ratio" in frame_path:
            visual_cut_ratios.append(float(frame_path.get("visual_cut_ratio") or 0.0))

        if "continuity_center_jitter_ratio" in frame_path:
            continuity_center_jitter_ratios.append(float(frame_path.get("continuity_center_jitter_ratio") or 0.0))

        if "avg_face_plausibility" in frame_path:
            face_plausibility_scores.append(float(frame_path.get("avg_face_plausibility") or 0.0))

        strategy = render_qc.get("render_strategy") or crop.get("strategy") or ""

        if strategy:
            render_strategy_counts[strategy] = render_strategy_counts.get(strategy, 0) + 1

        if crop.get("dual_stack_frame_rate") is not None:
            dual_stack_frame_rates.append(float(crop.get("dual_stack_frame_rate") or 0.0))

        for flag in render_qc.get("flags") or []:
            qc_flags[flag] = qc_flags.get(flag, 0) + 1

        if render_qc.get("rejected"):
            rejected_count += 1

    return {
        "file": path,
        "title": source_title or os.path.basename(path).replace("_clip_review.json", "").replace("_", " "),
        "video_url": source_video_url,
        "selected_count": len(selected),
        "top_candidate_count": len(payload.get("top_candidates") or []),
        "inventory_total_candidates": inventory.get("total_candidates", 0),
        "inventory_zones": {
            key: len(value or [])
            for key, value in (inventory.get("best_by_interview_zone") or {}).items()
        },
        "inventory_signals": {
            key: len(value or [])
            for key, value in (inventory.get("best_by_signal") or {}).items()
        },
        "inventory_archetypes": {
            key: len(value or [])
            for key, value in (inventory.get("best_by_archetype") or {}).items()
        },
        "avg_visual_quality": (
            round(sum(visual_scores) / len(visual_scores), 4)
            if visual_scores else None
        ),
        "avg_readiness_score": (
            round(sum(readiness_scores) / len(readiness_scores), 4)
            if readiness_scores else None
        ),
        "avg_theme_signal_score": (
            round(sum(theme_signal_scores) / len(theme_signal_scores), 4)
            if theme_signal_scores else None
        ),
        "avg_transformation_score": (
            round(sum(transformation_scores) / len(transformation_scores), 4)
            if transformation_scores else None
        ),
        "avg_reused_content_risk": (
            round(sum(reused_content_risks) / len(reused_content_risks), 4)
            if reused_content_risks else None
        ),
        "analytics_feedback_enabled_count": analytics_feedback_enabled,
        "avg_analytics_feedback_adjustment": (
            round(sum(analytics_feedback_adjustments) / len(analytics_feedback_adjustments), 4)
            if analytics_feedback_adjustments else None
        ),
        "readiness_missing_count": readiness_missing_count,
        "readiness_tiers": readiness_tiers,
        "avg_dead_frame_ratio": (
            round(sum(dead_frame_ratios) / len(dead_frame_ratios), 4)
            if dead_frame_ratios else None
        ),
        "avg_alive_frame_rate": (
            round(sum(alive_frame_rates) / len(alive_frame_rates), 4)
            if alive_frame_rates else None
        ),
        "avg_face_presence_rate": (
            round(sum(face_presence_rates) / len(face_presence_rates), 4)
            if face_presence_rates else None
        ),
        "avg_alive_no_face_frame_ratio": (
            round(sum(alive_no_face_ratios) / len(alive_no_face_ratios), 4)
            if alive_no_face_ratios else None
        ),
        "avg_longest_no_face_run_ratio": (
            round(sum(longest_no_face_run_ratios) / len(longest_no_face_run_ratios), 4)
            if longest_no_face_run_ratios else None
        ),
        "avg_visual_cut_ratio": (
            round(sum(visual_cut_ratios) / len(visual_cut_ratios), 4)
            if visual_cut_ratios else None
        ),
        "avg_continuity_center_jitter_ratio": (
            round(sum(continuity_center_jitter_ratios) / len(continuity_center_jitter_ratios), 4)
            if continuity_center_jitter_ratios else None
        ),
        "avg_face_plausibility": (
            round(sum(face_plausibility_scores) / len(face_plausibility_scores), 4)
            if face_plausibility_scores else None
        ),
        "avg_dual_stack_frame_rate": (
            round(sum(dual_stack_frame_rates) / len(dual_stack_frame_rates), 4)
            if dual_stack_frame_rates else None
        ),
        "render_strategy_counts": render_strategy_counts,
        "rejected_count": rejected_count,
        "qc_flags": qc_flags,
        "topic_summary": [
            {"topic": topic, "count": count}
            for topic, count in sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        ],
    }


def summarize_source_dossier(path):
    payload = load_json_file(path, {})
    batch_plan = payload.get("clip_batch_plan") or {}
    readiness_distribution = payload.get("readiness_distribution") or {}
    signal_coverage = payload.get("signal_coverage") or {}
    selected_clips = payload.get("selected_clips") or []
    editorial_decision = payload.get("editorial_decision") or {}
    processing_metrics = payload.get("processing_metrics") or {}
    elite_count = int(readiness_distribution.get("elite") or 0)
    strong_count = int(readiness_distribution.get("strong") or 0)
    usable_count = int(readiness_distribution.get("usable") or 0)
    total_readiness_windows = sum(
        int(readiness_distribution.get(key) or 0)
        for key in ["elite", "strong", "usable", "review", "weak", "reject"]
    )
    elite_density = elite_count / total_readiness_windows if total_readiness_windows else 0.0
    strong_density = strong_count / total_readiness_windows if total_readiness_windows else 0.0
    selected_tiers = {}
    selected_readiness_scores = []

    for clip in selected_clips:
        tier = clip.get("readiness_tier", "")
        selected_tiers[tier] = selected_tiers.get(tier, 0) + 1

        if clip.get("readiness_score") is not None:
            selected_readiness_scores.append(float(clip.get("readiness_score") or 0.0))

    selected_elite_count = int(selected_tiers.get("elite") or 0)
    selected_strong_count = int(selected_tiers.get("strong") or 0)
    selected_usable_count = int(selected_tiers.get("usable") or 0)
    selected_publishable_count = selected_elite_count + selected_strong_count
    avg_selected_readiness = (
        sum(selected_readiness_scores) / len(selected_readiness_scores)
        if selected_readiness_scores else 0.0
    )
    external_signal_count = (
        int(signal_coverage.get("timestamp_marker_count") or 0)
        + int(signal_coverage.get("comment_topic_term_count") or 0)
        + int(signal_coverage.get("youtube_data_api_timestamp_marker_count") or 0)
        + int(signal_coverage.get("youtube_data_api_comment_topic_term_count") or 0)
    )
    has_public_replay_signal = bool(
        signal_coverage.get("has_heatmap")
        or signal_coverage.get("has_chapters")
        or external_signal_count
    )
    source_value_score = round(
        selected_elite_count * 10.0
        + selected_strong_count * 6.0
        + selected_usable_count * 2.0
        + min(14.0, elite_count * 0.28)
        + min(8.0, strong_count * 0.015)
        + min(2.0, usable_count * 0.001)
        + min(5.0, elite_density * 320)
        + min(3.0, strong_density * 24)
        + min(10, external_signal_count) * 0.28
        + (2.0 if has_public_replay_signal else 0.0),
        4,
    )

    if (
        selected_elite_count >= 2
        or (selected_publishable_count >= 3 and avg_selected_readiness >= 0.80)
        or (selected_publishable_count >= 2 and elite_count >= 15 and has_public_replay_signal)
    ):
        mining_tier = "primary_milk_source"
    elif (
        selected_publishable_count >= 1
        or elite_count >= 5
        or strong_density >= 0.08
        or source_value_score >= 14
    ):
        mining_tier = "selective_source"
    elif strong_count >= 60 or usable_count >= 500 or source_value_score >= 5:
        mining_tier = "thin_but_usable"
    else:
        mining_tier = "weak_source"

    return {
        "file": path,
        "title": (payload.get("source") or {}).get("title", ""),
        "video_url": (payload.get("source") or {}).get("video_url", ""),
        "source_value_score": source_value_score,
        "mining_tier": mining_tier,
        "has_public_replay_signal": has_public_replay_signal,
        "external_signal_count": external_signal_count,
        "signal_coverage": signal_coverage,
        "editorial_decision": editorial_decision,
        "processing_metrics": processing_metrics,
        "candidate_window_policy": processing_metrics.get("candidate_window_policy", {}),
        "runtime_seconds": processing_metrics.get("total_source_workflow_seconds") or processing_metrics.get("scoring_seconds"),
        "candidate_count": processing_metrics.get("candidate_count", 0),
        "selected_clips_per_hour_processed": processing_metrics.get("selected_clips_per_hour_processed"),
        "slow_source_review": bool(processing_metrics.get("slow_source_review")),
        "selected_readiness_distribution": selected_tiers,
        "avg_selected_readiness": round(avg_selected_readiness, 4) if selected_readiness_scores else None,
        "elite_density": round(elite_density, 5),
        "strong_density": round(strong_density, 5),
        "score_distribution": payload.get("score_distribution") or {},
        "readiness_distribution": readiness_distribution,
        "topic_summary": (payload.get("topic_summary") or [])[:12],
        "batch_plan_total_recommended": batch_plan.get("total_recommended", 0),
        "batch_counts": [
            {
                "batch": batch.get("batch", ""),
                "count": len(batch.get("clips") or []),
            }
            for batch in batch_plan.get("batches") or []
        ],
    }


def build_source_mining_index(dossier_reports):
    def tier_priority(value):
        return {
            "primary_milk_source": 3,
            "selective_source": 2,
            "thin_but_usable": 1,
            "weak_source": 0,
        }.get(value, 0)

    ranked = sorted(
        dossier_reports,
        key=lambda item: (
            tier_priority(item.get("mining_tier", "")),
            float(item.get("source_value_score") or 0.0),
            int((item.get("readiness_distribution") or {}).get("elite") or 0),
            int((item.get("readiness_distribution") or {}).get("strong") or 0),
        ),
        reverse=True,
    )

    return [
        {
            "rank": index,
            "title": report.get("title", ""),
            "video_url": report.get("video_url", ""),
            "source_value_score": report.get("source_value_score", 0.0),
            "mining_tier": report.get("mining_tier", ""),
            "has_public_replay_signal": bool(report.get("has_public_replay_signal")),
            "external_signal_count": int(report.get("external_signal_count") or 0),
            "readiness_distribution": report.get("readiness_distribution") or {},
            "selected_readiness_distribution": report.get("selected_readiness_distribution") or {},
            "avg_selected_readiness": report.get("avg_selected_readiness"),
            "elite_density": report.get("elite_density"),
            "strong_density": report.get("strong_density"),
            "recommended_batch_clip_count": report.get("batch_plan_total_recommended", 0),
            "candidate_window_policy": report.get("candidate_window_policy", {}),
            "top_batches": report.get("batch_counts", [])[:5],
            "top_topics": report.get("topic_summary", [])[:8],
            "dossier_file": report.get("file", ""),
        }
        for index, report in enumerate(ranked, start=1)
    ]


def build_review_source_mining_index(review_reports):
    source_reports = []

    for report in review_reports:
        readiness_tiers = report.get("readiness_tiers") or {}
        selected_count = int(report.get("selected_count") or 0)
        inventory_candidates = int(report.get("inventory_total_candidates") or 0)
        top_candidate_count = int(report.get("top_candidate_count") or 0)
        elite_count = int(readiness_tiers.get("elite") or 0)
        strong_count = int(readiness_tiers.get("strong") or 0)
        usable_count = int(readiness_tiers.get("usable") or 0)
        avg_readiness = float(report.get("avg_readiness_score") or 0.0)
        source_value_score = round(
            elite_count * 7.0
            + strong_count * 4.0
            + usable_count * 1.3
            + min(25, top_candidate_count) * 0.18
            + min(50, inventory_candidates / 1000.0) * 0.55
            + avg_readiness * max(1, selected_count) * 3.0,
            4,
        )

        if elite_count or strong_count >= 3 or source_value_score >= 16:
            mining_tier = "primary_milk_source"
        elif strong_count or avg_readiness >= 0.70 or source_value_score >= 7:
            mining_tier = "selective_source"
        elif usable_count or inventory_candidates >= 1200:
            mining_tier = "thin_but_usable"
        else:
            mining_tier = "weak_source"

        source_reports.append({
            "rank": 0,
            "title": report.get("title", ""),
            "video_url": report.get("video_url", ""),
            "source_value_score": source_value_score,
            "mining_tier": mining_tier,
            "has_public_replay_signal": False,
            "external_signal_count": 0,
            "readiness_distribution": readiness_tiers,
            "recommended_batch_clip_count": selected_count,
            "top_batches": [],
            "top_topics": report.get("topic_summary") or [],
            "dossier_file": "",
            "review_file": report.get("file", ""),
        })

    ranked = sorted(
        source_reports,
        key=lambda item: (
            float(item.get("source_value_score") or 0.0),
            int((item.get("readiness_distribution") or {}).get("elite") or 0),
            int((item.get("readiness_distribution") or {}).get("strong") or 0),
        ),
        reverse=True,
    )

    for index, report in enumerate(ranked, start=1):
        report["rank"] = index

    return ranked


def merge_source_mining_indexes(dossier_index, review_index):
    merged = []
    seen = set()

    def tier_priority(value):
        return {
            "primary_milk_source": 3,
            "selective_source": 2,
            "thin_but_usable": 1,
            "weak_source": 0,
        }.get(value, 0)

    def artifact_key(item):
        path = item.get("dossier_file") or item.get("review_file") or ""
        name = os.path.basename(str(path))

        for suffix in ["_source_dossier.json", "_clip_review.json"]:
            if name.endswith(suffix):
                return name[:-len(suffix)].lower()

        return ""

    for item in dossier_index + review_index:
        identity = artifact_key(item) or (
            str(item.get("video_url") or "").strip().lower(),
            str(item.get("title") or "").strip().lower(),
        )

        if identity in seen:
            continue

        seen.add(identity)
        merged.append(dict(item))

    ranked = sorted(
        merged,
        key=lambda item: (
            tier_priority(item.get("mining_tier", "")),
            float(item.get("source_value_score") or 0.0),
            int((item.get("readiness_distribution") or {}).get("elite") or 0),
            int((item.get("readiness_distribution") or {}).get("strong") or 0),
        ),
        reverse=True,
    )

    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    return ranked


def build_theme_quality_report(theme):
    paths = ensure_theme(theme)
    metadata_path = paths["metadata_path"]
    review_reports = []
    dossier_reports = []
    excluded_artifacts = []

    if os.path.isdir(metadata_path):
        for filename in sorted(os.listdir(metadata_path)):
            if filename.endswith("_clip_review.json"):
                path = os.path.join(metadata_path, filename)

                if is_verification_artifact(path):
                    excluded_artifacts.append(path)
                    continue

                review_reports.append(summarize_clip_review(path))

    dossier_dir = os.path.join(metadata_path, "source_dossiers")

    if os.path.isdir(dossier_dir):
        for filename in sorted(os.listdir(dossier_dir)):
            if filename.endswith("_source_dossier.json"):
                path = os.path.join(dossier_dir, filename)

                if is_verification_artifact(path):
                    excluded_artifacts.append(path)
                    continue

                dossier_reports.append(summarize_source_dossier(path))

    total_selected = sum(report["selected_count"] for report in review_reports)
    total_rejected = sum(report.get("rejected_count", 0) for report in review_reports)
    total_inventory_candidates = sum(int(report.get("inventory_total_candidates") or 0) for report in review_reports)
    readiness_missing_count = sum(int(report.get("readiness_missing_count") or 0) for report in review_reports)
    visual_review_count = sum(1 for report in review_reports if report.get("avg_visual_quality") is not None)
    avg_visual_quality = (
        round(
            sum(float(report.get("avg_visual_quality") or 0.0) for report in review_reports if report.get("avg_visual_quality") is not None)
            / visual_review_count,
            4,
        )
        if visual_review_count else None
    )
    avg_readiness_score = _average_report_metric(review_reports, "avg_readiness_score")
    avg_theme_signal_score = _average_report_metric(review_reports, "avg_theme_signal_score")
    avg_transformation_score = _average_report_metric(review_reports, "avg_transformation_score")
    avg_reused_content_risk = _average_report_metric(review_reports, "avg_reused_content_risk")
    avg_analytics_feedback_adjustment = _average_report_metric(review_reports, "avg_analytics_feedback_adjustment")
    avg_dead_frame_ratio = _average_report_metric(review_reports, "avg_dead_frame_ratio")
    avg_alive_frame_rate = _average_report_metric(review_reports, "avg_alive_frame_rate")
    avg_face_presence_rate = _average_report_metric(review_reports, "avg_face_presence_rate")
    avg_alive_no_face_frame_ratio = _average_report_metric(review_reports, "avg_alive_no_face_frame_ratio")
    avg_longest_no_face_run_ratio = _average_report_metric(review_reports, "avg_longest_no_face_run_ratio")
    avg_visual_cut_ratio = _average_report_metric(review_reports, "avg_visual_cut_ratio")
    avg_continuity_center_jitter_ratio = _average_report_metric(review_reports, "avg_continuity_center_jitter_ratio")
    avg_face_plausibility = _average_report_metric(review_reports, "avg_face_plausibility")
    avg_dual_stack_frame_rate = _average_report_metric(review_reports, "avg_dual_stack_frame_rate")
    flag_counts = {}
    render_strategy_counts = {}

    for report in review_reports:
        for flag, count in report.get("qc_flags", {}).items():
            flag_counts[flag] = flag_counts.get(flag, 0) + int(count)

        for strategy, count in (report.get("render_strategy_counts") or {}).items():
            render_strategy_counts[strategy] = render_strategy_counts.get(strategy, 0) + int(count)

    batch_total = sum(int(report.get("batch_plan_total_recommended") or 0) for report in dossier_reports)
    dossier_source_mining_index = build_source_mining_index(dossier_reports)
    review_source_mining_index = build_review_source_mining_index(review_reports)
    source_mining_index = merge_source_mining_indexes(
        dossier_source_mining_index,
        review_source_mining_index,
    )

    if source_mining_index and not dossier_source_mining_index:
        batch_total = sum(int(report.get("recommended_batch_clip_count") or 0) for report in source_mining_index)
    source_mining_tiers = {}

    for source_report in source_mining_index:
        tier = source_report.get("mining_tier", "unknown")
        source_mining_tiers[tier] = source_mining_tiers.get(tier, 0) + 1

    slowest_sources = sorted(
        [
            {
                "title": report.get("title", ""),
                "video_url": report.get("video_url", ""),
                "runtime_seconds": report.get("runtime_seconds"),
                "candidate_count": report.get("candidate_count", 0),
                "selected_clips_per_hour_processed": report.get("selected_clips_per_hour_processed"),
                "slow_source_review": bool(report.get("slow_source_review")),
                "file": report.get("file", ""),
            }
            for report in dossier_reports
            if report.get("runtime_seconds") is not None
        ],
        key=lambda item: float(item.get("runtime_seconds") or 0.0),
        reverse=True,
    )

    report = {
        "theme": theme,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "clip_review_files": len(review_reports),
            "source_dossier_files": len(dossier_reports),
            "selected_clip_count": total_selected,
            "rejected_clip_count": total_rejected,
            "inventory_candidate_count": total_inventory_candidates,
            "recommended_batch_clip_count": batch_total,
            "avg_visual_quality": avg_visual_quality,
            "avg_readiness_score": avg_readiness_score,
            "avg_theme_signal_score": avg_theme_signal_score,
            "avg_transformation_score": avg_transformation_score,
            "avg_reused_content_risk": avg_reused_content_risk,
            "analytics_feedback_enabled_count": sum(
                int(report.get("analytics_feedback_enabled_count") or 0)
                for report in review_reports
            ),
            "avg_analytics_feedback_adjustment": avg_analytics_feedback_adjustment,
            "readiness_missing_count": readiness_missing_count,
            "avg_dead_frame_ratio": avg_dead_frame_ratio,
            "avg_alive_frame_rate": avg_alive_frame_rate,
            "avg_face_presence_rate": avg_face_presence_rate,
            "avg_alive_no_face_frame_ratio": avg_alive_no_face_frame_ratio,
            "avg_longest_no_face_run_ratio": avg_longest_no_face_run_ratio,
            "avg_visual_cut_ratio": avg_visual_cut_ratio,
            "avg_continuity_center_jitter_ratio": avg_continuity_center_jitter_ratio,
            "avg_face_plausibility": avg_face_plausibility,
            "avg_dual_stack_frame_rate": avg_dual_stack_frame_rate,
            "source_mining_tiers": source_mining_tiers,
            "slow_source_review_count": sum(1 for item in slowest_sources if item.get("slow_source_review")),
            "slowest_sources": slowest_sources[:10],
            "excluded_verification_artifact_count": len(excluded_artifacts),
            "render_strategy_counts": render_strategy_counts,
            "qc_flag_counts": flag_counts,
        },
        "clip_reviews": review_reports,
        "source_dossiers": dossier_reports,
        "source_mining_index": source_mining_index,
        "excluded_artifacts": excluded_artifacts,
    }

    output_dir = os.path.join(BASE_DIR, "logs", "quality_lab")
    os.makedirs(output_dir, exist_ok=True)
    suffix = "_with_verification" if INCLUDE_VERIFICATION_ARTIFACTS else ""
    output_path = os.path.join(output_dir, f"{theme}_quality_lab{suffix}.json")
    write_json_file(output_path, report)
    return output_path, report


def run_quality_lab(theme=None):
    themes = [theme] if theme else discover_themes()
    outputs = []

    for theme_name in themes:
        output_path, report = build_theme_quality_report(theme_name)
        outputs.append(output_path)
        summary = report.get("summary") or {}
        print(
            f"{theme_name}: reviews={summary.get('clip_review_files', 0)} "
            f"dossiers={summary.get('source_dossier_files', 0)} "
            f"selected={summary.get('selected_clip_count', 0)} "
            f"inventory_candidates={summary.get('inventory_candidate_count', 0)} "
            f"batch_recommendations={summary.get('recommended_batch_clip_count', 0)} "
            f"readiness={summary.get('avg_readiness_score')} "
            f"readiness_missing={summary.get('readiness_missing_count', 0)} "
            f"visual={summary.get('avg_visual_quality')} "
            f"alive={summary.get('avg_alive_frame_rate')} "
            f"dead={summary.get('avg_dead_frame_ratio')} "
            f"sources={summary.get('source_mining_tiers', {})} "
            f"excluded_debug={summary.get('excluded_verification_artifact_count', 0)}"
        )
        print(f"  report: {output_path}")

    latest_suffix = "_with_verification" if INCLUDE_VERIFICATION_ARTIFACTS else ""
    latest_path = os.path.join(BASE_DIR, "logs", f"quality_lab_latest{latest_suffix}.json")
    write_json_file(latest_path, {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reports": outputs,
    })
    print(f"\nQuality lab index: {latest_path}")
    return outputs


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize clip quality, visual QA, and source dossier coverage.")
    parser.add_argument("--theme", help="Optional theme to inspect. Omit to inspect every theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_quality_lab(theme=args.theme)
