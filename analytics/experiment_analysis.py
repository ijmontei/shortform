import argparse
import os
import time

from analytics.youtube_metrics import load_theme_metrics
from theme_config import BASE_DIR, clean_theme_name, discover_themes, write_json_file


REPORT_DIR = os.path.join(BASE_DIR, "logs", "analytics", "experiment_reports")


def safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def average(records, key):
    values = [safe_float(record.get(key)) for record in records if record.get(key) is not None]

    if not values:
        return None

    return round(sum(values) / len(values), 5)


def group_records(records, key_func):
    grouped = {}

    for record in records:
        key = key_func(record) or "unknown"
        grouped.setdefault(str(key), []).append(record)

    return grouped


def summarize_group(name, records):
    ranked_examples = sorted(
        records,
        key=lambda item: safe_float(item.get("performance_score")),
        reverse=True,
    )[:5]
    return {
        "name": name,
        "count": len(records),
        "avg_performance_score": average(records, "performance_score"),
        "avg_engaged_view_rate": average(records, "engaged_view_rate"),
        "avg_average_percent_viewed": average(records, "average_percent_viewed"),
        "avg_likes_per_engaged_view": average(records, "likes_per_engaged_view"),
        "top_examples": [
            {
                "title": item.get("title", ""),
                "video_id": item.get("video_id", ""),
                "performance_score": item.get("performance_score"),
            }
            for item in ranked_examples
        ],
    }


def ranked_groups(grouped):
    return sorted(
        [summarize_group(name, records) for name, records in grouped.items()],
        key=lambda item: safe_float(item.get("avg_performance_score")),
        reverse=True,
    )


def build_experiment_report(theme=None):
    themes = [clean_theme_name(theme)] if theme else discover_themes()
    records = []

    for theme_name in themes:
        records.extend(load_theme_metrics(theme_name))

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "themes": themes,
        "record_count": len(records),
        "by_experiment_variant": ranked_groups(group_records(
            records,
            lambda item: "|".join([
                item.get("theme", ""),
                item.get("experiment_id", ""),
                item.get("experiment_variant", ""),
            ]).strip("|"),
        )),
        "by_intro_mode": ranked_groups(group_records(records, lambda item: item.get("intro_mode"))),
        "by_archetype": ranked_groups(group_records(records, lambda item: item.get("archetype"))),
        "by_content_format": ranked_groups(group_records(records, lambda item: item.get("content_format"))),
        "by_theme": ranked_groups(group_records(records, lambda item: item.get("theme"))),
        "by_source_show": ranked_groups(group_records(
            records,
            lambda item: item.get("source_show") or item.get("source_channel") or item.get("source_title"),
        )),
        "by_source_tier": ranked_groups(group_records(records, lambda item: item.get("source_tier"))),
        "by_routing_status": ranked_groups(group_records(records, lambda item: item.get("routing_status"))),
        "by_caption_style": ranked_groups(group_records(records, lambda item: item.get("caption_style"))),
    }

    os.makedirs(REPORT_DIR, exist_ok=True)
    filename = f"{clean_theme_name(theme)}_experiment_report.json" if theme else "all_experiment_report.json"
    path = os.path.join(REPORT_DIR, filename)
    write_json_file(path, report)
    print(f"Experiment report: {path}")
    return path, report


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize Shortform analytics by experiment and package variant.")
    parser.add_argument("--theme", help="Optional theme to summarize. Omit for every theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_experiment_report(theme=args.theme)
