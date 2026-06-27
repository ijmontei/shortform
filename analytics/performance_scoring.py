def safe_divide(numerator, denominator):
    denominator = float(denominator or 0)

    if denominator <= 0:
        return 0.0

    return float(numerator or 0) / denominator


def normalize_metrics(metrics):
    metrics = dict(metrics or {})
    engaged_views = float(metrics.get("engaged_views") or 0)
    views = float(metrics.get("views") or 0)
    metrics["engaged_view_rate"] = metrics.get("engaged_view_rate", safe_divide(engaged_views, views))
    metrics["likes_per_engaged_view"] = metrics.get(
        "likes_per_engaged_view",
        safe_divide(metrics.get("likes"), engaged_views),
    )
    metrics["comments_per_engaged_view"] = metrics.get(
        "comments_per_engaged_view",
        safe_divide(metrics.get("comments"), engaged_views),
    )
    metrics["subs_per_1000_engaged_views"] = metrics.get(
        "subs_per_1000_engaged_views",
        safe_divide(metrics.get("subs_gained"), engaged_views) * 1000,
    )
    metrics["subs_gained_per_1000_engaged_views"] = metrics.get(
        "subs_gained_per_1000_engaged_views",
        metrics["subs_per_1000_engaged_views"],
    )
    return metrics


def performance_score(metrics):
    metrics = normalize_metrics(metrics)
    return (
        0.35 * float(metrics.get("engaged_view_rate") or 0)
        + 0.25 * float(metrics.get("average_percent_viewed") or 0)
        + 0.15 * float(metrics.get("likes_per_engaged_view") or 0)
        + 0.10 * float(metrics.get("comments_per_engaged_view") or 0)
        + 0.15 * min(1.0, float(metrics.get("subs_per_1000_engaged_views") or 0) / 10.0)
    )
