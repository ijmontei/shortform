from functools import lru_cache

from analytics.youtube_metrics import load_theme_metrics


MIN_PRIOR_SAMPLES = 3


def _safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _duration_bucket(duration):
    duration = _safe_float(duration)

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


def _average(values):
    values = [_safe_float(value) for value in values if value is not None]

    if not values:
        return 0.0

    return sum(values) / len(values)


def _group_stats(records, key_func):
    grouped = {}

    for record in records:
        key = str(key_func(record) or "").strip()

        if not key:
            continue

        grouped.setdefault(key, []).append(_safe_float(record.get("performance_score")))

    return {
        key: {
            "count": len(values),
            "avg_performance_score": _average(values),
        }
        for key, values in grouped.items()
    }


@lru_cache(maxsize=64)
def build_feedback_prior(theme):
    records = [
        record
        for record in load_theme_metrics(theme)
        if record.get("performance_score") is not None
    ]
    baseline = _average(record.get("performance_score") for record in records)

    return {
        "theme": theme,
        "record_count": len(records),
        "baseline_performance_score": baseline,
        "sources": _group_stats(records, lambda item: item.get("source_channel") or item.get("source_title")),
        "archetypes": _group_stats(records, lambda item: item.get("archetype")),
        "intro_modes": _group_stats(records, lambda item: item.get("intro_mode")),
        "caption_styles": _group_stats(records, lambda item: item.get("caption_style")),
        "content_formats": _group_stats(records, lambda item: item.get("content_format")),
        "duration_buckets": _group_stats(records, lambda item: _duration_bucket(item.get("duration"))),
    }


def _component(name, value, stats, baseline, weight):
    if not value:
        return {
            "area": name,
            "value": "",
            "count": 0,
            "avg_performance_score": None,
            "delta": 0.0,
            "weighted_delta": 0.0,
        }

    row = (stats or {}).get(str(value), {})
    count = int(row.get("count") or 0)

    if count < MIN_PRIOR_SAMPLES:
        return {
            "area": name,
            "value": str(value),
            "count": count,
            "avg_performance_score": row.get("avg_performance_score"),
            "delta": 0.0,
            "weighted_delta": 0.0,
        }

    avg = _safe_float(row.get("avg_performance_score"))
    normalized_delta = max(-1.0, min(1.0, (avg - baseline) / 0.20))
    confidence = min(1.0, count / 12.0)
    weighted_delta = normalized_delta * confidence * weight

    return {
        "area": name,
        "value": str(value),
        "count": count,
        "avg_performance_score": avg,
        "delta": normalized_delta,
        "weighted_delta": weighted_delta,
    }


def score_analytics_feedback_prior(
    theme,
    source_record=None,
    archetype="",
    intro_mode="",
    caption_style="",
    content_format="raw_candidate",
    duration=0,
):
    prior = build_feedback_prior(theme)
    baseline = _safe_float(prior.get("baseline_performance_score"))
    record_count = int(prior.get("record_count") or 0)

    if record_count < MIN_PRIOR_SAMPLES or baseline <= 0:
        return {
            "enabled": False,
            "record_count": record_count,
            "baseline_performance_score": baseline,
            "score_adjustment": 0.0,
            "components": [],
        }

    source_record = source_record or {}
    source_key = source_record.get("channel") or source_record.get("title") or ""
    duration_bucket = _duration_bucket(duration)
    components = [
        _component("source", source_key, prior.get("sources"), baseline, 0.34),
        _component("archetype", archetype, prior.get("archetypes"), baseline, 0.24),
        _component("intro_mode", intro_mode, prior.get("intro_modes"), baseline, 0.16),
        _component("caption_style", caption_style, prior.get("caption_styles"), baseline, 0.10),
        _component("content_format", content_format, prior.get("content_formats"), baseline, 0.06),
        _component("duration_bucket", duration_bucket, prior.get("duration_buckets"), baseline, 0.10),
    ]
    combined = sum(item["weighted_delta"] for item in components)
    score_adjustment = max(-0.06, min(0.06, combined * 0.06))

    return {
        "enabled": True,
        "record_count": record_count,
        "baseline_performance_score": baseline,
        "duration_bucket": duration_bucket,
        "score_adjustment": score_adjustment,
        "components": components,
    }
