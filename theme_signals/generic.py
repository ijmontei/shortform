import math
import re


DEFAULT_ARCHETYPE_KEYWORDS = {
    "heated_exchange": ["wrong", "disagree", "push back", "debate", "argument"],
    "surprising_reveal": ["surprising", "nobody", "secret", "truth", "realized"],
    "clean_explanation": ["because", "means", "reason", "works", "example"],
    "practical_takeaway": ["should", "how to", "rule", "lesson", "mistake"],
    "quotable_line": ["always", "never", "the thing", "the problem", "the truth"],
}


def normalized_words(text):
    return re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", (text or "").lower())


def keyword_hits(text, keywords):
    normalized = f" {(text or '').lower()} "
    hits = []

    for keyword in keywords or []:
        key = str(keyword).lower().strip()

        if not key:
            continue

        if " " in key:
            if key in normalized:
                hits.append(key)
        elif re.search(rf"\b{re.escape(key)}\b", normalized):
            hits.append(key)

    return hits


def infer_archetype(text, configured_archetypes):
    text = (text or "").lower()

    for archetype in configured_archetypes or []:
        readable = str(archetype).replace("_", " ").lower()
        parts = [part for part in readable.split() if len(part) > 3]

        if parts and any(re.search(rf"\b{re.escape(part)}\b", text) for part in parts):
            return str(archetype)

    for archetype, keywords in DEFAULT_ARCHETYPE_KEYWORDS.items():
        if keyword_hits(text, keywords):
            return archetype

    return (configured_archetypes or ["clean_explanation"])[0]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    metadata = metadata or {}
    profile = metadata.get("theme_profile") or {}
    signal_config = profile.get("theme_signals") or {}
    packaging = profile.get("packaging") or {}
    metadata_style = profile.get("metadata_style") or {}
    positive = signal_config.get("positive_keywords") or []
    negative = signal_config.get("negative_keywords") or []
    keyword_weights = {
        str(key).lower(): float(value)
        for key, value in (signal_config.get("keyword_weights") or {}).items()
    }
    positive_hits = keyword_hits(text, positive)
    negative_hits = keyword_hits(text, negative)
    weighted_hit_score = sum(keyword_weights.get(hit, 1.0) for hit in positive_hits)
    words = normalized_words(text)
    specificity_hits = len([word for word in words if any(char.isdigit() for char in word)])
    question_bonus = 0.18 if "?" in (text or "") else 0.0
    score = 1.0 - math.exp(-(weighted_hit_score + 0.4 * specificity_hits) / 3.0)
    score = min(1.0, max(0.0, score + question_bonus - 0.10 * len(negative_hits)))
    concerns = []

    if signal_config.get("penalize_missing_theme_signal", True) and score < 0.18:
        concerns.append("weak theme-specific signal")

    if negative_hits:
        concerns.append(f"negative theme keywords: {', '.join(negative_hits[:4])}")

    archetype = infer_archetype(text, signal_config.get("archetypes") or [])

    return {
        "theme_signal_score": float(score),
        "signals": {
            "positive_keyword_hits": positive_hits[:10],
            "negative_keyword_hits": negative_hits[:10],
            "specificity_hits": specificity_hits,
        },
        "concerns": concerns,
        "archetype": archetype,
        "recommended_intro_mode": packaging.get("default_intro_mode", "context_card"),
        "recommended_title_templates": metadata_style.get("title_templates", []),
    }
