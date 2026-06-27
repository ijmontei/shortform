import os

from theme_profile import get_risk_controls
from metadata_generation.titles import score_title_quality


TRANSFORMED_CONTENT_FORMATS = {
    "daily_editorial_short",
    "daily_editorial_recap",
    "popular_segment_short",
}
RAW_RECYCLER_CONTENT_FORMATS = {
    "raw_subtitled_clip",
    "classic_clip",
    "selected_clip",
}
FINANCIAL_CLAIM_TERMS = {
    "buy",
    "sell",
    "stock",
    "stocks",
    "crypto",
    "bitcoin",
    "invest",
    "investment",
    "portfolio",
    "tax",
    "market",
    "recession",
    "rate cut",
}
MEDICAL_CLAIM_TERMS = {
    "cure",
    "diagnose",
    "diagnosis",
    "supplement",
    "dose",
    "dosage",
    "therapy",
    "treatment",
    "medicine",
    "medical",
    "doctor",
    "disease",
    "anxiety",
    "depression",
    "hormone",
}
GENERIC_SOURCE_TITLES = {
    "",
    "daily podcast scan",
    "podcast interview",
    "source episode",
    "podcast channel",
}


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_passed(value, default=True):
    if isinstance(value, dict):
        return bool(value.get("passed", default))
    return default


def _text(value):
    return str(value or "").strip()


def _has_text(value, min_len=3):
    return len(_text(value)) >= min_len


def _is_generic_source_title(value):
    return _text(value).lower() in GENERIC_SOURCE_TITLES


def _context_items(package, rank_signals):
    items = []
    primary = {
        "source_video_url": package.get("source_video_url") or rank_signals.get("source_video_url"),
        "source_channel": package.get("source_channel") or rank_signals.get("source_channel"),
        "source_title": package.get("source_title") or rank_signals.get("source_title"),
        "transcript_excerpt": package.get("transcript_excerpt") or rank_signals.get("transcript_excerpt"),
        "clip_start_time": package.get("clip_start_time", rank_signals.get("clip_start_time")),
        "clip_end_time": package.get("clip_end_time", rank_signals.get("clip_end_time")),
        "speaker": package.get("speaker") or rank_signals.get("speaker"),
        "source_date": package.get("source_date") or rank_signals.get("source_date"),
    }
    items.append(primary)

    for item in package.get("source_context") or []:
        if isinstance(item, dict):
            items.append(item)

    return items


def _has_time_pair(item):
    start = item.get("clip_start_time", item.get("start_time"))
    end = item.get("clip_end_time", item.get("end_time"))

    try:
        return float(end) > float(start) >= 0
    except (TypeError, ValueError):
        return False


def _contains_any(text, terms):
    lowered = _text(text).lower()
    return any(term in lowered for term in terms)


def context_evidence_for(package, rank_signals):
    items = _context_items(package, rank_signals)
    has_source_url = any(_has_text(item.get("source_video_url"), 8) for item in items)
    has_source_title = any(
        _has_text(item.get("source_title"), 8) and not _is_generic_source_title(item.get("source_title"))
        for item in items
    )
    has_source_channel = any(_has_text(item.get("source_channel"), 3) for item in items)
    has_transcript_excerpt = any(_has_text(item.get("transcript_excerpt"), 24) for item in items)
    has_clip_timing = any(_has_time_pair(item) for item in items)
    has_speaker_or_date = any(
        _has_text(item.get("speaker"), 3)
        or _has_text(item.get("source_date"), 6)
        or _has_text(item.get("editorial_date"), 6)
        for item in items
    )
    has_source_identity = has_source_channel or has_source_title
    has_context_quote = has_transcript_excerpt
    source_count = sum(
        1
        for item in items
        if _has_text(item.get("source_video_url"), 8)
        or (_has_text(item.get("source_title"), 8) and not _is_generic_source_title(item.get("source_title")))
    )

    return {
        "has_source_url": has_source_url,
        "has_source_title": has_source_title,
        "has_source_channel": has_source_channel,
        "has_source_identity": has_source_identity,
        "has_transcript_excerpt": has_transcript_excerpt,
        "has_context_quote": has_context_quote,
        "has_clip_timing": has_clip_timing,
        "has_speaker_or_date": has_speaker_or_date,
        "source_context_count": source_count,
    }


def evaluate_editorial_gates(theme, package):
    package = package or {}
    content_format = str(package.get("content_format") or "").strip()
    rank_signals = package.get("rank_signals") or {}
    render_qc = package.get("render_qc") or {}
    risk_controls = get_risk_controls(theme)
    minimum_transformation = _float(risk_controls.get("minimum_transformation_score"), 0.55)
    theme_signal_score = _float(
        package.get("theme_signal_score", rank_signals.get("theme_signal_score")),
        0.0,
    )
    transformation_score = _float(
        package.get("transformation_score", rank_signals.get("transformation_score")),
        0.0,
    )
    reused_content_risk = _float(
        package.get("reused_content_risk", rank_signals.get("reused_content_risk")),
        0.0,
    )
    captionability_score = _float(rank_signals.get("captionability_score"), 1.0)
    first_second_qc = package.get("first_second_qc") or rank_signals.get("first_second_qc") or {}
    first_second_passed = _bool_passed(first_second_qc, default=True)
    render_passed = _bool_passed(render_qc, default=True)
    title_quality = (
        package.get("title_quality")
        or rank_signals.get("title_quality")
        or score_title_quality(theme, package.get("title", ""), topic_terms=package.get("topic_fingerprint") or [])
    )
    context_evidence = context_evidence_for(package, rank_signals)
    allow_raw_clip_uploads = os.getenv("SHORTFORM_ALLOW_RAW_CLIP_UPLOADS", "0") == "1"
    flags = []

    if (
        content_format in RAW_RECYCLER_CONTENT_FORMATS
        and not allow_raw_clip_uploads
    ):
        flags.append("raw_recycler_clip_not_transformed")

    if (
        content_format
        and content_format not in TRANSFORMED_CONTENT_FORMATS
        and content_format not in RAW_RECYCLER_CONTENT_FORMATS
    ):
        flags.append("unknown_content_format")

    if (
        package.get("upload_ready_requires_burned_captions")
        and not package.get("content_has_burned_captions")
    ):
        flags.append("missing_burned_captions")

    if not first_second_passed:
        flags.append("first_second_qc_failed")

    if not render_passed:
        flags.append("render_qc_failed")

    if transformation_score < minimum_transformation:
        flags.append("transformation_below_theme_minimum")

    if reused_content_risk >= 0.42:
        flags.append("high_reused_content_risk")

    if theme_signal_score < 0.18:
        flags.append("weak_theme_signal")

    if captionability_score < 0.58:
        flags.append("weak_captionability")

    if not title_quality.get("length_ok", True):
        flags.append("title_length_outside_quality_range")

    if title_quality.get("generic_title"):
        flags.append("generic_title")

    if title_quality.get("mechanical_title"):
        flags.append("mechanical_title")

    if title_quality.get("repetitive_title"):
        flags.append("repetitive_title")

    if not title_quality.get("theme_native_title", True):
        flags.append("weak_theme_native_title")

    if _float(title_quality.get("theme_fit"), 1.0) < 0.52:
        flags.append("weak_title_theme_fit")

    if _float(title_quality.get("specificity"), 1.0) < 0.28:
        flags.append("low_title_specificity")

    if not title_quality.get("not_clickbait", True):
        flags.append("clickbait_title")

    if risk_controls.get("requires_claim_context"):
        intro_mode = (
            (package.get("content_signal") or {}).get("recommended_intro_mode")
            or rank_signals.get("recommended_intro_mode")
            or ""
        )

        if intro_mode == "cold_open":
            flags.append("claim_context_theme_using_cold_open")

        if not context_evidence["has_source_url"]:
            flags.append("missing_claim_source_url")

        if not context_evidence["has_source_title"]:
            flags.append("missing_claim_source_title")

        if not context_evidence["has_transcript_excerpt"]:
            flags.append("missing_claim_transcript_excerpt")

        if not context_evidence["has_clip_timing"]:
            flags.append("missing_claim_clip_timing")

    if risk_controls.get("requires_fact_check"):
        if not context_evidence["has_source_identity"]:
            flags.append("missing_fact_check_source_identity")

        if not context_evidence["has_context_quote"]:
            flags.append("missing_fact_check_quote_context")

    text_blob = " ".join([
        _text(package.get("title")),
        _text(package.get("caption")),
        _text(package.get("description")),
        _text(package.get("transcript_excerpt")),
    ])

    if risk_controls.get("requires_financial_review") and _contains_any(text_blob, FINANCIAL_CLAIM_TERMS):
        if not (context_evidence["has_context_quote"] and context_evidence["has_clip_timing"]):
            flags.append("financial_claim_context_missing")

    if risk_controls.get("requires_medical_review") and _contains_any(text_blob, MEDICAL_CLAIM_TERMS):
        if not (context_evidence["has_context_quote"] and context_evidence["has_clip_timing"]):
            flags.append("medical_claim_context_missing")

    review_required = bool(
        flags
        or (risk_controls.get("requires_fact_check"))
        or (risk_controls.get("requires_financial_review"))
        or (risk_controls.get("requires_medical_review"))
        or (risk_controls.get("requires_claim_context"))
    )

    return {
        "passed": not flags,
        "review_required": review_required,
        "flags": flags,
        "minimum_transformation_score": minimum_transformation,
        "theme_signal_score": theme_signal_score,
        "transformation_score": transformation_score,
        "reused_content_risk": reused_content_risk,
        "captionability_score": captionability_score,
        "title_quality": title_quality,
        "context_evidence": context_evidence,
        "first_second_passed": first_second_passed,
        "render_qc_passed": render_passed,
        "risk_profile": {
            "requires_fact_check": bool(risk_controls.get("requires_fact_check")),
            "requires_financial_review": bool(risk_controls.get("requires_financial_review")),
            "requires_medical_review": bool(risk_controls.get("requires_medical_review")),
            "requires_claim_context": bool(risk_controls.get("requires_claim_context")),
        },
        "content_format": content_format,
        "allow_raw_clip_uploads": allow_raw_clip_uploads,
    }
