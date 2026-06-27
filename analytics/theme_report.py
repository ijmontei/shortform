import os
import time

from analytics.youtube_metrics import load_theme_metrics
from theme_config import BASE_DIR, discover_themes, write_json_file


REPORT_PATH = os.path.join(BASE_DIR, "logs", "analytics", "theme_reports")


def summarize(records, key):
    values = [float(record.get(key) or 0) for record in records if record.get(key) is not None]

    if not values:
        return None

    return round(sum(values) / len(values), 5)


def safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def duration_bucket(record):
    duration = safe_float(record.get("duration") or record.get("source_play_duration"))

    if duration <= 0:
        return "unknown"
    if duration < 15:
        return "under_15s"
    if duration < 25:
        return "15_24s"
    if duration < 40:
        return "25_39s"
    if duration < 55:
        return "40_54s"
    return "55s_plus"


def ranked_groups(groups):
    rows = []

    for name, items in groups.items():
        rows.append({
            "name": name,
            "count": len(items),
            "avg_performance_score": summarize(items, "performance_score"),
            "avg_engaged_view_rate": summarize(items, "engaged_view_rate"),
            "avg_average_percent_viewed": summarize(items, "average_percent_viewed"),
        })

    return sorted(
        rows,
        key=lambda item: (
            safe_float(item.get("avg_performance_score")),
            safe_float(item.get("avg_engaged_view_rate")),
            item.get("count", 0),
        ),
        reverse=True,
    )


def learning_recommendations(report_sections, minimum_samples=3):
    recommendations = []

    for section_name, rows in report_sections.items():
        qualified = [row for row in rows if int(row.get("count") or 0) >= minimum_samples]

        if not qualified:
            continue

        winner = qualified[0]
        loser = qualified[-1] if len(qualified) > 1 else None
        recommendations.append({
            "area": section_name,
            "action": "increase_weight_or_volume",
            "target": winner.get("name", ""),
            "reason": (
                f"{winner.get('count')} samples, "
                f"avg performance {winner.get('avg_performance_score')}"
            ),
        })

        if loser and safe_float(winner.get("avg_performance_score")) - safe_float(loser.get("avg_performance_score")) >= 0.08:
            recommendations.append({
                "area": section_name,
                "action": "deprioritize_or_review",
                "target": loser.get("name", ""),
                "reason": (
                    f"underperformed against {winner.get('name')} "
                    f"({loser.get('avg_performance_score')} vs {winner.get('avg_performance_score')})"
                ),
            })

    if not recommendations:
        recommendations.append({
            "area": "sample_size",
            "action": "collect_more_data",
            "target": "all_variants",
            "reason": f"Need at least {minimum_samples} uploaded videos per variant before changing theme strategy.",
        })

    return recommendations


def build_theme_analytics_report(theme):
    records = load_theme_metrics(theme)
    by_source = {}
    by_archetype = {}
    by_intro = {}
    by_experiment = {}
    by_content_format = {}
    by_caption_style = {}
    by_framing_style = {}
    by_overlay_style = {}
    by_title_style = {}
    by_duration = {}

    for record in records:
        by_source.setdefault(record.get("source_channel") or record.get("source_title") or "unknown", []).append(record)
        by_archetype.setdefault(record.get("archetype") or "unknown", []).append(record)
        by_intro.setdefault(record.get("intro_mode") or "unknown", []).append(record)
        experiment_key = "|".join([
            record.get("experiment_id", ""),
            record.get("experiment_variant", ""),
        ]).strip("|") or "unknown"
        by_experiment.setdefault(experiment_key, []).append(record)
        by_content_format.setdefault(record.get("content_format") or "unknown", []).append(record)
        by_caption_style.setdefault(record.get("caption_style") or "unknown", []).append(record)
        by_framing_style.setdefault(record.get("framing_style") or "unknown", []).append(record)
        by_overlay_style.setdefault(record.get("overlay_style") or "unknown", []).append(record)
        by_title_style.setdefault(record.get("title_style") or "unknown", []).append(record)
        by_duration.setdefault(duration_bucket(record), []).append(record)

    section_rankings = {
        "sources": ranked_groups(by_source)[:20],
        "archetypes": ranked_groups(by_archetype)[:20],
        "intro_modes": ranked_groups(by_intro)[:20],
        "experiments": ranked_groups(by_experiment)[:20],
        "content_formats": ranked_groups(by_content_format)[:20],
        "caption_styles": ranked_groups(by_caption_style)[:20],
        "framing_styles": ranked_groups(by_framing_style)[:20],
        "overlay_styles": ranked_groups(by_overlay_style)[:20],
        "title_styles": ranked_groups(by_title_style)[:20],
        "duration_buckets": ranked_groups(by_duration)[:20],
    }

    report = {
        "theme": theme,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_count": len(records),
        "summary": {
            "avg_performance_score": summarize(records, "performance_score"),
            "avg_engaged_view_rate": summarize(records, "engaged_view_rate"),
            "avg_average_percent_viewed": summarize(records, "average_percent_viewed"),
            "avg_likes_per_engaged_view": summarize(records, "likes_per_engaged_view"),
            "avg_comments_per_engaged_view": summarize(records, "comments_per_engaged_view"),
        },
        "top_sources": section_rankings["sources"],
        "top_archetypes": section_rankings["archetypes"],
        "top_intro_modes": section_rankings["intro_modes"],
        "top_experiments": section_rankings["experiments"],
        "top_content_formats": section_rankings["content_formats"],
        "top_caption_styles": section_rankings["caption_styles"],
        "top_framing_styles": section_rankings["framing_styles"],
        "top_overlay_styles": section_rankings["overlay_styles"],
        "top_title_styles": section_rankings["title_styles"],
        "top_duration_buckets": section_rankings["duration_buckets"],
        "learning_recommendations": learning_recommendations(section_rankings),
    }
    path = os.path.join(REPORT_PATH, f"{theme}_analytics_report.json")
    write_json_file(path, report)
    return path, report


def build_all_theme_reports():
    reports = {}

    for theme in discover_themes():
        path, report = build_theme_analytics_report(theme)
        reports[theme] = {"path": path, "summary": report.get("summary", {})}

    return reports
