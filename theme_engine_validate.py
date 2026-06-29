import argparse
import importlib.util
import os
import time

from theme_config import BASE_DIR, PHASE_ONE_ACTIVE_THEMES, THEMES_SRC_PATH, clean_theme_name, discover_themes, load_json_file, theme_config_path, write_json_file
from theme_profile import DEFAULT_SCORING_WEIGHTS, load_theme_profile, source_disqualified_by_theme_name


REPORT_PATH = os.path.join(BASE_DIR, "logs", "theme_engine_validation_latest.json")

REQUIRED_SECTIONS = [
    "brand",
    "youtube",
    "channels",
    "clip_rules",
    "scoring_weights",
    "theme_signals",
    "packaging",
    "metadata_style",
    "research",
    "risk_controls",
    "review_policy",
    "analytics",
    "experiments",
]

REQUIRED_BRAND_KEYS = ["channel_name", "positioning", "audience", "viewer_promise", "voice"]
REQUIRED_CLIP_RULE_KEYS = [
    "candidate_durations",
    "min_clip_duration",
    "max_clip_duration",
    "default_clip_count",
    "theme_clip_budget",
    "theme_candidates_per_video",
    "min_readiness_score",
]
REQUIRED_PACKAGING_KEYS = ["intro_modes", "default_intro_mode", "caption_style", "framing_style", "overlay_style"]
REQUIRED_METADATA_KEYS = ["title_style", "title_templates", "hashtags", "tags", "topic_tags"]
REQUIRED_RESEARCH_KEYS = ["priority", "community_thesis", "source_strategy"]
REQUIRED_REVIEW_KEYS = [
    "require_manual_approval_before_public",
    "reject_if_reused_risk_high",
    "reject_if_first_second_fails",
    "reject_if_no_clear_viewer_value",
]
REQUIRED_ANALYTICS_KEYS = ["primary_metric", "secondary_metrics", "review_after_hours", "success_thresholds"]
REQUIRED_EXPERIMENT_KEYS = ["enabled", "active"]
PROTECTED_THEME_RISK_REQUIREMENTS = {
    "finance": {
        "flags": ["requires_financial_review", "requires_claim_context"],
        "manual_keywords": ["named investments", "market predictions", "tax/legal advice"],
        "restricted_keywords": ["specific stock recommendation", "get-rich-quick", "unsupported prediction"],
        "minimum_transformation_score": 0.60,
    },
    "health_fitness": {
        "flags": ["requires_medical_review", "requires_claim_context"],
        "manual_keywords": ["medical protocols", "diet claims", "therapy claims"],
        "restricted_keywords": ["medical cure claims", "supplement claims", "mental-health crisis advice"],
        "minimum_transformation_score": 0.60,
    },
    "politics": {
        "flags": ["requires_fact_check", "requires_claim_context"],
        "manual_keywords": ["source identity", "date context", "speaker attribution"],
        "restricted_keywords": ["election claims", "war claims", "crime allegations", "legal accusations"],
        "minimum_transformation_score": 0.70,
    },
    "truecrime": {
        "flags": ["requires_fact_check", "requires_claim_context"],
        "manual_keywords": ["dignity review", "defamation review", "exploitation review", "victim context"],
        "restricted_keywords": ["victim-identifying", "minor-involved", "active investigations", "legal accusations"],
        "minimum_transformation_score": 0.70,
    },
}

SOURCE_GUARD_EXPECTATIONS = {
    "comedy": [
        {
            "expect": "pass",
            "title": "KT #773 - FRANCISCO RAMOS + DERRICK STROUP",
            "source_tier": "legacy",
            "channel_url": "https://www.youtube.com/channel/UCwzCMiicL-hBUzyjWiJaseg/videos",
        },
        {
            "expect": "block",
            "title": "Is The Fed Panic Already Fading? | Weekly Roundup",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@TheCompoundNews/videos",
        },
    ],
    "sports": [
        {
            "expect": "pass",
            "title": "NFL cancels supplemental draft, where does this leave Brendan Sorsby?| The Pivot",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@thepivotpodcast/videos",
        },
        {
            "expect": "block",
            "title": "A New Heights Father’s Day ft. Best Fictional Dads & Bonus Dad Stories From Our Guests | Bonus EP",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@newheightshow/videos",
        },
    ],
    "gaming": [
        {
            "expect": "pass",
            "title": "Nadeshot explains why esports orgs are changing creator strategy",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@Nadeshot/videos",
        },
        {
            "expect": "block",
            "title": "Is The Fed Panic Already Fading? | Weekly Roundup",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@TheCompoundNews/videos",
        },
    ],
    "finance": [
        {
            "expect": "pass",
            "title": "Is The Fed Panic Already Fading? | Weekly Roundup",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@ForwardGuidanceBW/videos",
        },
        {
            "expect": "block",
            "title": "How Markiplier Made a Movie Hollywood Couldn’t Ignore",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@ColinandSamir/videos",
        },
    ],
    "technology_ai": [
        {
            "expect": "pass",
            "title": "The woman behind Claude Code & Cowork: How she’s building cracked engineering teams",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@LennysPodcast/videos",
        },
        {
            "expect": "block",
            "title": "Explaining the NBA in Tech Terms",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@Waveform/videos",
        },
    ],
    "health_fitness": [
        {
            "expect": "pass",
            "title": "The 7 Habits of People Who Age Slower | Dr. Steve Horvath",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@FoundMyFitness/videos",
        },
        {
            "expect": "block",
            "title": "Billionaire's WARNING: I'm SELLING. The Crash Is Already Here!",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@TheDiaryOfACEO/videos",
        },
    ],
    "politics": [
        {
            "expect": "pass",
            "title": "Trump’s Social Media Advisor Reveals All: Epstein, Iran, and Mark Levin’s Israeli Propaganda",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@PiersMorganUncensored/videos",
        },
        {
            "expect": "block",
            "title": "Biggest Mysteries in Physics: Antimatter, Dark Energy & ToE - Don Lincoln | Lex Fridman Podcast #497",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@lexfridman/videos",
        },
    ],
    "popculture": [
        {
            "expect": "pass",
            "title": "David Duchovny Lives the Technicolor Universe While Eating Spicy Wings | Hot Ones",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@FirstWeFeast/videos",
        },
        {
            "expect": "block",
            "title": "SCOTUS Sides With Bayer on Roundup, DHS Secy Clashes With Dems",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@PBSNewsHour/videos",
        },
    ],
    "truecrime": [
        {
            "expect": "pass",
            "title": "Soft White Underbelly interview with homeless addiction survivor",
            "source_tier": "priority",
            "channel_url": "https://www.youtube.com/@SoftWhiteUnderbelly/videos",
        },
        {
            "expect": "block",
            "title": "Explaining the NBA in Tech Terms",
            "source_tier": "secondary",
            "channel_url": "https://www.youtube.com/@Waveform/videos",
        },
    ],
}


def configured_theme_names():
    if not os.path.isdir(THEMES_SRC_PATH):
        return []

    return [
        clean_theme_name(os.path.splitext(filename)[0])
        for filename in sorted(os.listdir(THEMES_SRC_PATH))
        if filename.lower().endswith(".json")
    ]


def _is_nonempty_list(value):
    return isinstance(value, list) and any(str(item).strip() for item in value)


def _safe_number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _list_contains_keyword(values, keyword):
    keyword = str(keyword or "").strip().lower()

    if not keyword:
        return True

    return any(keyword in str(item or "").lower() for item in values or [])


def _add_missing_raw_section_warnings(raw, warnings):
    for section in REQUIRED_SECTIONS:
        if section not in raw:
            warnings.append(f"missing raw '{section}' section; default profile values will be applied")


def _theme_signal_module_exists(theme, profile):
    candidates = []

    for value in [theme, profile, "generic"]:
        normalized = clean_theme_name(value or "generic").replace("-", "_")

        if normalized and normalized not in candidates:
            candidates.append(normalized)

    for module_name in candidates:
        if importlib.util.find_spec(f"theme_signals.{module_name}") is not None:
            return True, module_name

    return False, ""


def _validate_source_guard_cases(theme):
    case_results = []
    errors = []

    for index, case in enumerate(SOURCE_GUARD_EXPECTATIONS.get(theme, []), start=1):
        source_record = {
            "title": case.get("title", ""),
            "source_tier": case.get("source_tier", ""),
            "channel_url": case.get("channel_url", ""),
        }
        disqualified, hits = source_disqualified_by_theme_name(theme, source_record)
        expected_block = case.get("expect") == "block"
        passed = bool(disqualified) == expected_block

        case_results.append({
            "index": index,
            "expect": case.get("expect", ""),
            "passed": passed,
            "title": case.get("title", ""),
            "source_tier": case.get("source_tier", ""),
            "channel_url": case.get("channel_url", ""),
            "guard_disqualified": bool(disqualified),
            "guard_hits": hits,
        })

        if not passed:
            errors.append(
                f"source_guard case {index} expected {case.get('expect')} "
                f"for '{case.get('title')}' but got "
                f"{'block' if disqualified else 'pass'}"
            )

    return case_results, errors


def validate_theme_profile(theme_name):
    theme = clean_theme_name(theme_name)
    raw = load_json_file(theme_config_path(theme), {})
    profile = load_theme_profile(theme)
    errors = []
    warnings = []

    if raw.get("theme") and clean_theme_name(raw.get("theme")) != theme:
        warnings.append(f"theme field '{raw.get('theme')}' does not match filename '{theme}'")

    _add_missing_raw_section_warnings(raw, warnings)

    brand = profile.get("brand") or {}
    for key in REQUIRED_BRAND_KEYS:
        if not str(brand.get(key, "")).strip():
            warnings.append(f"brand.{key} is empty")

    channels = profile.get("channels") or []
    priority_channels = profile.get("priority_channels") or []
    secondary_channels = profile.get("secondary_channels") or []
    episode_routing_override = profile.get("episode_routing_override") or []
    phase = str(profile.get("phase") or raw.get("phase") or "").strip()
    is_phase_one = theme in PHASE_ONE_ACTIVE_THEMES
    raw_phase_one_active = raw.get("phase_one_active")

    if is_phase_one:
        if phase != "phase_one":
            errors.append("phase-one active theme must set phase='phase_one'")

        if raw_phase_one_active is False:
            errors.append("phase-one active theme cannot set phase_one_active=false")

        if not _is_nonempty_list(priority_channels):
            errors.append("phase-one theme must define priority_channels")

        if not _is_nonempty_list(secondary_channels):
            warnings.append("phase-one theme has no secondary_channels")

        if not episode_routing_override:
            warnings.append("phase-one theme has no episode_routing_override entries")
    else:
        if phase == "phase_one" or raw_phase_one_active is True:
            errors.append("non-phase-one theme is incorrectly marked active for phase one")

    if priority_channels and not set(priority_channels).issubset(set(channels)):
        errors.append("priority_channels must be included in merged channels")

    if secondary_channels and not set(secondary_channels).issubset(set(channels)):
        errors.append("secondary_channels must be included in merged channels")

    for index, route in enumerate(episode_routing_override, start=1):
        source = str(route.get("source") or "").strip()
        route_to = route.get("route_to") or []
        when = str(route.get("when") or "").strip()

        if not source:
            errors.append(f"episode_routing_override[{index}].source is empty")

        if not _is_nonempty_list(route_to):
            errors.append(f"episode_routing_override[{index}].route_to must name at least one theme")

        for target in route_to:
            target_theme = clean_theme_name(target)

            if not os.path.exists(theme_config_path(target_theme)):
                warnings.append(f"episode_routing_override[{index}] routes to missing theme '{target_theme}'")

        if not when:
            warnings.append(f"episode_routing_override[{index}].when is empty")

    if not _is_nonempty_list(channels):
        errors.append("channels must contain at least one source channel")

    if len(channels) != len(set(channels)):
        warnings.append("channels contains duplicate entries")

    youtube = profile.get("youtube") or {}
    channel_handle = str(youtube.get("channel_handle", "")).strip()
    token_file = str(youtube.get("token_file", "")).strip()
    upload_route = {
        "status": "ready" if channel_handle else "generation_only",
        "channel_handle": channel_handle,
        "token_file": token_file,
        "token_exists": False,
    }

    if token_file:
        token_path = token_file if os.path.isabs(token_file) else os.path.join(BASE_DIR, token_file)
        upload_route["token_file"] = token_path
        upload_route["token_exists"] = os.path.exists(token_path)

        if not channel_handle:
            warnings.append("youtube.token_file is configured but youtube.channel_handle is empty")
    elif channel_handle:
        warnings.append("youtube.channel_handle is configured but youtube.token_file is empty; OAuth will use the default theme token path")

    clip_rules = profile.get("clip_rules") or {}
    for key in REQUIRED_CLIP_RULE_KEYS:
        if key not in clip_rules:
            errors.append(f"clip_rules.{key} is missing")

    durations = clip_rules.get("candidate_durations", [])
    min_duration = _safe_number(clip_rules.get("min_clip_duration"))
    max_duration = _safe_number(clip_rules.get("max_clip_duration"))
    theme_budget = int(_safe_number(clip_rules.get("theme_clip_budget")))

    if not _is_nonempty_list(durations):
        errors.append("clip_rules.candidate_durations must be a non-empty list")
    elif any(_safe_number(item) <= 0 for item in durations):
        errors.append("clip_rules.candidate_durations must contain positive values")

    if min_duration <= 0 or max_duration <= 0 or min_duration > max_duration:
        errors.append("clip_rules min/max durations are invalid")

    if max_duration > 75:
        warnings.append("clip_rules.max_clip_duration is above Shorts-safe range")

    if theme_budget < 0:
        errors.append("clip_rules.theme_clip_budget must be zero for unlimited or a positive explicit cap")
    elif is_phase_one and theme_budget > 0:
        errors.append("phase-one clip_rules.theme_clip_budget must be 0; production generation is quality-threshold unlimited")
    elif theme_budget > 0:
        warnings.append("clip_rules.theme_clip_budget is an explicit cap; production defaults to unlimited quality-threshold selection")

    scoring_weights = profile.get("scoring_weights") or {}
    if not scoring_weights:
        errors.append("scoring_weights is empty")
    else:
        known_weight_keys = set(DEFAULT_SCORING_WEIGHTS.keys())
        configured_keys = set(scoring_weights.keys())
        missing_weight_keys = sorted(known_weight_keys - configured_keys)

        if missing_weight_keys:
            warnings.append(f"scoring_weights missing default keys: {', '.join(missing_weight_keys)}")

        weight_total = sum(max(0.0, _safe_number(value)) for value in scoring_weights.values())
        if weight_total <= 0:
            errors.append("scoring_weights must have a positive total")

    theme_signals = profile.get("theme_signals") or {}
    if not _is_nonempty_list(theme_signals.get("enabled")):
        warnings.append("theme_signals.enabled is empty")
    if not _is_nonempty_list(theme_signals.get("archetypes")):
        warnings.append("theme_signals.archetypes is empty")

    source_guard = theme_signals.get("source_guard") or {}
    source_guard_case_results, source_guard_case_errors = _validate_source_guard_cases(theme)

    if is_phase_one:
        if not isinstance(source_guard, dict) or not source_guard:
            errors.append("phase-one theme must define theme_signals.source_guard")
        else:
            guard_positive = source_guard.get("positive_keywords") or []
            guard_negative = source_guard.get("negative_keywords") or []
            guard_trusted = source_guard.get("trusted_source_terms") or []
            guard_tier_minimums = source_guard.get("min_positive_hits_by_tier") or {}

            if not _is_nonempty_list(guard_positive):
                errors.append("phase-one source_guard must define positive_keywords")

            if not _is_nonempty_list(guard_negative):
                warnings.append("phase-one source_guard has no negative_keywords")

            if not _is_nonempty_list(guard_trusted):
                warnings.append("phase-one source_guard has no trusted_source_terms")

            if not isinstance(guard_tier_minimums, dict) or not guard_tier_minimums:
                warnings.append("phase-one source_guard has no min_positive_hits_by_tier")

        if not SOURCE_GUARD_EXPECTATIONS.get(theme):
            errors.append("phase-one theme has no source_guard regression expectations")

    errors.extend(source_guard_case_errors)

    signal_module_found, signal_module = _theme_signal_module_exists(theme, profile.get("profile", "generic"))
    if not signal_module_found:
        errors.append("no importable theme_signals module found for theme/profile")

    packaging = profile.get("packaging") or {}
    for key in REQUIRED_PACKAGING_KEYS:
        if key not in packaging or not packaging.get(key):
            warnings.append(f"packaging.{key} is empty")

    intro_modes = packaging.get("intro_modes") or []
    default_intro = packaging.get("default_intro_mode", "")
    if intro_modes and default_intro and default_intro not in intro_modes:
        warnings.append("packaging.default_intro_mode is not listed in packaging.intro_modes")

    metadata_style = profile.get("metadata_style") or {}
    for key in REQUIRED_METADATA_KEYS:
        if key not in metadata_style or not metadata_style.get(key):
            warnings.append(f"metadata_style.{key} is empty")

    research = profile.get("research") or {}
    for key in REQUIRED_RESEARCH_KEYS:
        if key not in research or not str(research.get(key, "")).strip():
            warnings.append(f"research.{key} is empty")

    risk_controls = profile.get("risk_controls") or {}
    min_transformation = _safe_number(risk_controls.get("minimum_transformation_score"), 0.0)
    if min_transformation <= 0:
        warnings.append("risk_controls.minimum_transformation_score is not set")

    protected_requirements = PROTECTED_THEME_RISK_REQUIREMENTS.get(theme)

    if protected_requirements:
        for flag in protected_requirements.get("flags", []):
            if not risk_controls.get(flag):
                errors.append(f"protected theme must set risk_controls.{flag}=true")

        for keyword in protected_requirements.get("manual_keywords", []):
            if not _list_contains_keyword(risk_controls.get("manual_review_topics") or [], keyword):
                errors.append(f"protected theme manual_review_topics must include '{keyword}'")

        for keyword in protected_requirements.get("restricted_keywords", []):
            if not _list_contains_keyword(risk_controls.get("restricted_topics") or [], keyword):
                errors.append(f"protected theme restricted_topics must include '{keyword}'")

        required_min_transformation = _safe_number(
            protected_requirements.get("minimum_transformation_score"),
            0.0,
        )

        if min_transformation < required_min_transformation:
            errors.append(
                "protected theme minimum_transformation_score must be at least "
                f"{required_min_transformation:.2f}"
            )

    review_policy = profile.get("review_policy") or {}
    for key in REQUIRED_REVIEW_KEYS:
        if key not in review_policy:
            warnings.append(f"review_policy.{key} is missing")

    analytics = profile.get("analytics") or {}
    for key in REQUIRED_ANALYTICS_KEYS:
        if key not in analytics or not analytics.get(key):
            warnings.append(f"analytics.{key} is empty")

    experiments = profile.get("experiments") or {}
    for key in REQUIRED_EXPERIMENT_KEYS:
        if key not in experiments:
            warnings.append(f"experiments.{key} is missing")

    return {
        "theme": theme,
        "config_file": theme_config_path(theme),
        "status": "ok" if not errors else "error",
        "upload_route": upload_route,
        "channels": len(channels),
        "priority_channels": len(priority_channels),
        "secondary_channels": len(secondary_channels),
        "episode_routing_overrides": len(episode_routing_override),
        "phase": phase,
        "phase_one_active": bool(is_phase_one),
        "declared_phase_one_active": raw_phase_one_active,
        "candidate_duration_range": [min_duration, max_duration],
        "theme_clip_budget": theme_budget,
        "theme_signal_module": signal_module,
        "source_guard": {
            "configured": bool(source_guard),
            "positive_keywords": len(source_guard.get("positive_keywords") or []),
            "negative_keywords": len(source_guard.get("negative_keywords") or []),
            "trusted_source_terms": len(source_guard.get("trusted_source_terms") or []),
            "case_count": len(source_guard_case_results),
            "case_failures": sum(1 for item in source_guard_case_results if not item.get("passed")),
            "cases": source_guard_case_results,
        },
        "errors": errors,
        "warnings": warnings,
    }


def build_phase_scope_report(active_theme_names):
    all_themes = configured_theme_names()
    active_set = set(active_theme_names)
    expected_set = set(PHASE_ONE_ACTIVE_THEMES)
    future_themes = [theme for theme in all_themes if theme not in expected_set]
    missing_phase_one_configs = [
        theme
        for theme in PHASE_ONE_ACTIVE_THEMES
        if theme not in all_themes
    ]
    unexpected_active = [
        theme
        for theme in active_theme_names
        if theme not in expected_set
    ]
    future_reports = []
    future_errors = []

    for theme in future_themes:
        raw = load_json_file(theme_config_path(theme), {})
        phase = str(raw.get("phase") or "").strip()
        declared_active = raw.get("phase_one_active")
        phase_two_safe = phase != "phase_one" and declared_active is not True

        if not phase_two_safe:
            future_errors.append(
                f"{theme} is not in the phase-one slate but declares phase={phase!r} "
                f"and phase_one_active={declared_active!r}"
            )

        future_reports.append({
            "theme": theme,
            "phase": phase or "unset",
            "phase_one_active": declared_active,
            "production_blocked_by_default": theme not in active_set,
            "safe_phase_two_config": phase_two_safe,
        })

    return {
        "phase_one_active_themes": list(PHASE_ONE_ACTIVE_THEMES),
        "active_discovered_themes": list(active_theme_names),
        "all_configured_themes": all_themes,
        "future_configured_themes": future_reports,
        "missing_phase_one_configs": missing_phase_one_configs,
        "unexpected_active_themes": unexpected_active,
        "future_theme_errors": future_errors,
        "phase_scope_ok": not missing_phase_one_configs and not unexpected_active and not future_errors,
    }


def validate_theme_engine(theme=None, write_report=True):
    themes = [clean_theme_name(theme)] if theme else discover_themes()
    theme_reports = [validate_theme_profile(theme_name) for theme_name in themes]
    phase_scope = build_phase_scope_report(themes)
    error_count = sum(len(report["errors"]) for report in theme_reports)
    error_count += len(phase_scope["missing_phase_one_configs"])
    error_count += len(phase_scope["unexpected_active_themes"])
    error_count += len(phase_scope["future_theme_errors"])
    warning_count = sum(len(report["warnings"]) for report in theme_reports)
    generation_only_count = sum(1 for report in theme_reports if report["upload_route"]["status"] == "generation_only")
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "theme_count": len(theme_reports),
        "status": "ok" if error_count == 0 else "error",
        "error_count": error_count,
        "warning_count": warning_count,
        "generation_only_themes": generation_only_count,
        "phase_scope": phase_scope,
        "themes": theme_reports,
    }

    if write_report:
        write_json_file(REPORT_PATH, payload)

    return payload


def print_validation_summary(report):
    print(f"Theme engine validation: {report['status']}")
    print(
        f"Themes: {report['theme_count']}; "
        f"errors: {report['error_count']}; warnings: {report['warning_count']}; "
        f"generation-only: {report['generation_only_themes']}"
    )
    phase_scope = report.get("phase_scope") or {}
    future_configs = phase_scope.get("future_configured_themes") or []
    print(
        "Phase scope: "
        f"active={', '.join(phase_scope.get('active_discovered_themes') or [])}; "
        f"future-configs={len(future_configs)}; "
        f"scope-ok={bool(phase_scope.get('phase_scope_ok'))}"
    )

    for missing in phase_scope.get("missing_phase_one_configs") or []:
        print(f"   ERROR: missing phase-one config '{missing}'")

    for unexpected in phase_scope.get("unexpected_active_themes") or []:
        print(f"   ERROR: unexpected active production theme '{unexpected}'")

    for error in phase_scope.get("future_theme_errors") or []:
        print(f"   ERROR: {error}")

    for theme_report in report["themes"]:
        route = theme_report["upload_route"]
        route_label = route["channel_handle"] or route["status"]
        print(
            f" - {theme_report['theme']}: {theme_report['status']}, "
            f"phase={theme_report.get('phase') or 'unset'}, "
            f"channels={theme_report['channels']} "
            f"(priority={theme_report.get('priority_channels', 0)}, "
            f"secondary={theme_report.get('secondary_channels', 0)}, "
            f"routes={theme_report.get('episode_routing_overrides', 0)}), "
            f"source_guard_cases="
            f"{(theme_report.get('source_guard') or {}).get('case_count', 0)}, "
            f"source_guard_failures="
            f"{(theme_report.get('source_guard') or {}).get('case_failures', 0)}, "
            f"upload={route_label}, "
            f"errors={len(theme_report['errors'])}, warnings={len(theme_report['warnings'])}"
        )

        for error in theme_report["errors"]:
            print(f"   ERROR: {error}")

        for warning in theme_report["warnings"][:5]:
            print(f"   WARN: {warning}")

        if len(theme_report["warnings"]) > 5:
            print(f"   WARN: +{len(theme_report['warnings']) - 5} more warnings")

    print(f"Report: {REPORT_PATH}")


def parse_args():
    parser = argparse.ArgumentParser(description="Validate Shortform theme-engine configuration.")
    parser.add_argument("--theme", help="Optional theme to validate. Omit for every theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    validation_report = validate_theme_engine(theme=args.theme, write_report=True)
    print_validation_summary(validation_report)
    raise SystemExit(0 if validation_report["status"] == "ok" else 1)
