import argparse
import importlib.util
import os
import time

import ytdlp_auth
from theme_config import BASE_DIR, TEMP_PATH, THEMES_OUTPUT_PATH, PHASE_ONE_ACTIVE_THEMES, clean_theme_name, discover_themes, future_themes_allowed, load_json_file, load_theme_config, write_json_file
from theme_engine_validate import validate_theme_engine


REPORT_PATH = os.path.join(BASE_DIR, "logs", "theme_engine_audit_latest.json")


def path_exists(relative_path):
    return os.path.exists(os.path.join(BASE_DIR, relative_path))


def module_exists(module_name):
    return importlib.util.find_spec(module_name) is not None


def read_text(relative_path):
    path = os.path.join(BASE_DIR, relative_path)

    if not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def status_from(condition, partial=False):
    if condition:
        return "proved"
    if partial:
        return "partial"
    return "missing"


def make_item(requirement, status, evidence=None, gap=""):
    return {
        "requirement": requirement,
        "status": status,
        "evidence": evidence or [],
        "gap": gap,
    }


def audit_theme_configs():
    validation = validate_theme_engine(write_report=True)
    themes = validation.get("themes") or []
    phase_scope = validation.get("phase_scope") or {}
    themes_with_signal_modules = [
        item for item in themes
        if item.get("theme_signal_module")
    ]
    all_have_sources = all(
        item.get("priority_channels", 0) > 0
        and item.get("secondary_channels", 0) > 0
        and item.get("episode_routing_overrides", 0) > 0
        for item in themes
    )
    exact_phase_one = (
        validation.get("theme_count") == len(PHASE_ONE_ACTIVE_THEMES)
        and phase_scope.get("active_discovered_themes") == list(PHASE_ONE_ACTIVE_THEMES)
        and phase_scope.get("phase_scope_ok") is True
    )
    return make_item(
        "The live production slate is exactly the eight phase-one interview themes, with future themes blocked by default",
        status_from(
            validation.get("status") == "ok"
            and exact_phase_one
            and len(themes_with_signal_modules) == len(themes)
            and all_have_sources
            and validation.get("warning_count", 1) == 0
        ),
        evidence=[
            f"theme_count={validation.get('theme_count')}",
            f"phase_one_expected={','.join(PHASE_ONE_ACTIVE_THEMES)}",
            f"phase_one_discovered={','.join(phase_scope.get('active_discovered_themes') or [])}",
            f"future_configs={len(phase_scope.get('future_configured_themes') or [])}",
            f"phase_scope_ok={phase_scope.get('phase_scope_ok')}",
            f"errors={validation.get('error_count')}",
            f"warnings={validation.get('warning_count')}",
            f"themes_with_signal_modules={len(themes_with_signal_modules)}",
            f"all_have_priority_secondary_routing={all_have_sources}",
            "logs/theme_engine_validation_latest.json",
        ],
        gap="" if validation.get("status") == "ok" and exact_phase_one else "Fix phase-one theme scope or theme validation errors.",
    )


PHASE_ONE_PRIORITY_CHANNEL_FRAGMENTS = {
    "comedy": ["killtony", "theovon", "badfriends", "goodhang", "smartless"],
    "sports": ["clubshayshay", "newheightshow", "pardonmytake", "thepivotpodcast"],
    "finance": ["thediaryofaceo", "allin", "acquiredfm", "colinandsamir"],
    "technology_ai": ["lexfridman", "dwarkesh", "waveform", "tbpn"],
    "health_fitness": ["hubermanlab", "melrobbins", "jayshettypodcast", "thediaryofaceo"],
    "politics": ["breakingpoints", "megynkelly", "meidastouch", "shawnryanshow"],
    "popculture": ["firstwefeast", "callherdaddy", "ameliadimoldenberg", "breakfastclub", "smartless"],
    "truecrime": ["softwhiteunderbelly", "theemilydbaker", "shawnryanshow", "djvlad"],
}

PHASE_ONE_ROUTE_REQUIREMENTS = [
    {
        "source_fragment": "diaryofaceo",
        "themes": ["finance", "health_fitness", "technology_ai"],
    },
    {
        "source_fragment": "shawnryan",
        "themes": ["politics", "truecrime"],
    },
    {
        "source_fragment": "smartless",
        "themes": ["comedy", "popculture"],
    },
]


def normalized_source_text(value):
    return "".join(char for char in str(value or "").lower() if char.isalnum())


def route_matches_requirement(route, requirement):
    source = normalized_source_text(route.get("source"))
    route_to = {clean_theme_name(item) for item in route.get("route_to") or []}
    required_targets = {clean_theme_name(item) for item in requirement["themes"]}
    return requirement["source_fragment"] in source and bool(route_to & required_targets)


def audit_phase_one_source_map():
    missing_priority = {}
    route_hits = []
    missing_routes = []

    for theme in PHASE_ONE_ACTIVE_THEMES:
        config = load_theme_config(theme)
        priority_text = " ".join(normalized_source_text(channel) for channel in config.get("priority_channels") or [])
        missing = [
            fragment
            for fragment in PHASE_ONE_PRIORITY_CHANNEL_FRAGMENTS.get(theme, [])
            if fragment not in priority_text
        ]

        if missing:
            missing_priority[theme] = missing

    for requirement in PHASE_ONE_ROUTE_REQUIREMENTS:
        matching_themes = []

        for theme in PHASE_ONE_ACTIVE_THEMES:
            config = load_theme_config(theme)

            if any(route_matches_requirement(route, requirement) for route in config.get("episode_routing_override") or []):
                matching_themes.append(theme)

        required_theme_set = {clean_theme_name(item) for item in requirement["themes"]}
        if required_theme_set.issubset(set(matching_themes)):
            route_hits.append(f"{requirement['source_fragment']}={','.join(sorted(matching_themes))}")
        else:
            missing_routes.append(
                f"{requirement['source_fragment']} missing from "
                f"{','.join(sorted(required_theme_set - set(matching_themes)))}"
            )

    complete = not missing_priority and not missing_routes
    return make_item(
        "Phase-one source map matches the requested priority channels and episode-level routing",
        status_from(complete, partial=not missing_priority or not missing_routes),
        evidence=[
            f"priority_requirements={len(PHASE_ONE_PRIORITY_CHANNEL_FRAGMENTS)} themes",
            f"missing_priority={missing_priority}",
            f"route_hits={route_hits}",
            f"missing_routes={missing_routes}",
            "src/themes/*.json",
        ],
        gap="" if complete else "Update priority_channels or episode_routing_override for the listed phase-one themes.",
    )


def inactive_generated_dirs(root):
    if not os.path.isdir(root):
        return []

    active = set(PHASE_ONE_ACTIVE_THEMES)
    return [
        filename
        for filename in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, filename))
        and clean_theme_name(filename) not in active
    ]


def audit_generated_output_scope():
    inactive_output_dirs = inactive_generated_dirs(THEMES_OUTPUT_PATH)
    inactive_temp_dirs = inactive_generated_dirs(TEMP_PATH)
    inactive_dirs = inactive_output_dirs + inactive_temp_dirs
    future_mode = future_themes_allowed()
    complete = future_mode or not inactive_dirs

    return make_item(
        "Generated output and temp folders are scoped to phase-one themes by default",
        status_from(complete, partial=bool(inactive_dirs)),
        evidence=[
            f"future_themes_allowed={future_mode}",
            f"inactive_output_dirs={inactive_output_dirs}",
            f"inactive_temp_dirs={inactive_temp_dirs}",
            "run.py --clean-slate removes inactive generated folders by default for all-theme phase-one runs",
        ],
        gap="" if complete else "Run clean slate without --keep-inactive-output or remove stale future-theme generated folders.",
    )


def audit_code_artifacts():
    artifacts = {
        "theme_profile": path_exists("theme_profile.py"),
        "theme_signals": path_exists("theme_signals/generic.py"),
        "metadata_generation": path_exists("metadata_generation/titles.py"),
        "review_dashboard": path_exists("review_dashboard.py"),
        "review_queue": path_exists("review_queue.py"),
        "analytics_metrics": path_exists("analytics/youtube_metrics.py"),
        "analytics_feedback": path_exists("analytics/feedback_prior.py"),
        "experiment_analysis": path_exists("analytics/experiment_analysis.py"),
        "production_review": path_exists("production_review.py"),
        "editorial_gates": path_exists("editorial_gates.py"),
    }
    return make_item(
        "Core theme-engine modules exist for profiles, signals, metadata, review, analytics, experiments, and gates",
        status_from(all(artifacts.values()), partial=any(artifacts.values())),
        evidence=[f"{key}={value}" for key, value in artifacts.items()],
        gap="Missing module files must be created." if not all(artifacts.values()) else "",
    )


def audit_theme_visual_styles():
    text = read_text("daily_editorial.py")
    missing_themes = [
        theme
        for theme in PHASE_ONE_ACTIVE_THEMES
        if f'"{theme}"' not in text and f"'{theme}'" not in text
    ]
    has_style_map = "THEME_VISUAL_STYLES" in text
    theme_aware_call = "visual_style(rank, theme)" in text or "visual_style(index, theme)" in text
    expected_names = [
        "comedy_arcade_countdown",
        "sports_scoreboard_countdown",
        "operator_notebook_countdown",
        "builder_brief_countdown",
        "wellness_takeaway_countdown",
        "civic_context_countdown",
        "case_file_countdown",
        "culture_spotlight_countdown",
    ]
    missing_names = [name for name in expected_names if name not in text]
    complete = has_style_map and theme_aware_call and not missing_themes and not missing_names

    return make_item(
        "Phase-one themes have differentiated visual packaging profiles",
        status_from(complete, partial=has_style_map),
        evidence=[
            f"style_map={has_style_map}",
            f"theme_aware_call={theme_aware_call}",
            f"missing_themes={missing_themes}",
            f"missing_style_names={missing_names}",
            "daily_editorial.py",
        ],
        gap="" if complete else "Add theme-specific visual styles and make render paths pass the theme into visual_style().",
    )


def audit_visual_regression_pack():
    report_path = os.path.join(BASE_DIR, "logs", "visual_regression_latest.json")
    report = load_json_file(report_path, {})
    results = report.get("results") or []
    result_themes = sorted(clean_theme_name(item.get("theme")) for item in results if item.get("theme"))
    expected_themes = sorted(PHASE_ONE_ACTIVE_THEMES)
    missing_themes = sorted(set(expected_themes) - set(result_themes))
    non_ok = [
        f"{item.get('theme')}={item.get('status')}"
        for item in results
        if item.get("status") != "ok"
    ]
    contact_sheets_missing = [
        item.get("theme")
        for item in results
        if not item.get("contact_sheet") or not os.path.exists(item.get("contact_sheet", ""))
    ]
    complete = (
        report.get("status") == "ok"
        and result_themes == expected_themes
        and not non_ok
        and not contact_sheets_missing
    )
    return make_item(
        "Countdown intro visual regression pack covers every active phase-one theme",
        status_from(complete, partial=bool(results)),
        evidence=[
            f"report_status={report.get('status')}",
            f"themes={','.join(result_themes)}",
            f"missing_themes={missing_themes}",
            f"non_ok={non_ok}",
            f"missing_contact_sheets={contact_sheets_missing}",
            f"root_dir={report.get('root_dir', '')}",
            "logs/visual_regression_latest.json",
        ],
        gap="" if complete else "Run run.py --visual-regression and inspect any needs_review/error contact sheets.",
    )


def audit_candidate_fields():
    text = read_text("clip_generation.py")
    fields = [
        "theme_signal_score",
        "theme_signals",
        "first_second_qc",
        "transformation_score",
        "reused_content_risk",
        "experiment",
        "rank_signals",
        "suggested_title",
        "suggested_caption",
        "suggested_description",
        "hashtags",
        "render_qc",
    ]
    present = [field for field in fields if field in text]
    missing = sorted(set(fields) - set(present))
    return make_item(
        "CandidateClip carries theme, QC, transformation, experiment, metadata, and render fields",
        status_from(len(present) == len(fields), partial=bool(present)),
        evidence=[f"present={len(present)}/{len(fields)}", "clip_generation.py"],
        gap=f"Missing fields: {', '.join(missing)}" if missing else "",
    )


def audit_gates():
    gate_text = read_text("editorial_gates.py")
    upload_text = read_text("upload.py")
    validate_text = read_text("validate_outputs.py")
    required_gate_terms = [
        "first_second",
        "transformation_below_theme_minimum",
        "high_reused_content_risk",
        "weak_theme_signal",
        "weak_captionability",
        "generic_title",
        "mechanical_title",
        "repetitive_title",
        "weak_theme_native_title",
        "clickbait_title",
        "missing_burned_captions",
        "raw_recycler_clip_not_transformed",
        "missing_claim_source_url",
        "missing_claim_source_title",
        "missing_claim_transcript_excerpt",
        "missing_claim_clip_timing",
        "missing_fact_check_source_identity",
        "missing_fact_check_quote_context",
        "financial_claim_context_missing",
        "medical_claim_context_missing",
    ]
    present = [term for term in required_gate_terms if term in gate_text]
    upload_enforced = "editorial gates failed" in upload_text and "manual review approval required" in upload_text
    validation_enforced = "editorial gates failed" in validate_text and "requires manual review approval" in validate_text
    complete = len(present) == len(required_gate_terms) and upload_enforced and validation_enforced
    return make_item(
        "Universal quality gates block weak/generic/reused outputs before validation or upload",
        status_from(complete, partial=bool(present)),
        evidence=[
            f"gate_terms={len(present)}/{len(required_gate_terms)}",
            f"upload_enforced={upload_enforced}",
            f"validation_enforced={validation_enforced}",
            "editorial_gates.py",
            "upload.py",
            "validate_outputs.py",
        ],
        gap="" if complete else "Gate terms must be enforced in output validation and upload.",
    )


def audit_upload_ready_caption_contract():
    files = {
        "daily_editorial.py": read_text("daily_editorial.py"),
        "subtitle_generation.py": read_text("subtitle_generation.py"),
        "upload.py": read_text("upload.py"),
        "validate_outputs.py": read_text("validate_outputs.py"),
        "run.py": read_text("run.py"),
    }
    terms = {
        "editorial_marks_burned_captions": (
            '"content_has_burned_captions": True' in files["daily_editorial.py"]
            and '"upload_ready_requires_burned_captions": True' in files["daily_editorial.py"]
        ),
        "classic_subtitle_marks_burned_captions": (
            '"content_has_burned_captions": True' in files["subtitle_generation.py"]
            and '"upload_ready_requires_burned_captions": True' in files["subtitle_generation.py"]
        ),
        "upload_blocks_missing_captions": "missing burned-in captions" in files["upload.py"],
        "validation_blocks_missing_captions": "ready/uploaded package is missing burned-in captions flag" in files["validate_outputs.py"],
        "manifest_downgrades_uncaptioned_ready": "moved_uncaptioned_ready" in files["run.py"],
    }
    complete = all(terms.values())
    return make_item(
        "Upload-ready clips must already be burned-captioned and uncaptioned ready items are downgraded",
        status_from(complete, partial=any(terms.values())),
        evidence=[f"{key}={value}" for key, value in terms.items()],
        gap="" if complete else "Harden package generation, manifest reconciliation, validation, or upload gating for burned captions.",
    )


def audit_restricted_media_preflight_gate():
    run_text = read_text("run.py")
    readme_text = read_text("README.md")
    has_gate_function = "def run_requires_media_auth_preflight" in run_text
    gate_check_index = run_text.find("if run_requires_media_auth_preflight(args):")
    auth_call_index = run_text.find("run_restricted_media_auth_preflight(", gate_check_index)
    clean_slate_index = run_text.find("if args.clean_slate:")
    first_stage_call_indexes = [
        index for index in [
            run_text.find("run_pipeline_by_stage(", auth_call_index),
            run_text.find("run_pipeline_by_theme(", auth_call_index),
            run_text.find("run_stage_for_theme(", auth_call_index),
        ]
        if index >= 0
    ]
    first_stage_call_index = min(first_stage_call_indexes) if first_stage_call_indexes else -1
    has_pre_clean_call = (
        gate_check_index >= 0
        and auth_call_index > gate_check_index
        and clean_slate_index > auth_call_index
    )
    has_pre_download_call = (
        gate_check_index >= 0
        and auth_call_index > gate_check_index
        and first_stage_call_index > auth_call_index
    )
    upload_route_decoupled = "YouTube upload routing is configured" in run_text
    skip_escape_documented = (
        "SHORTFORM_SKIP_MEDIA_AUTH_PREFLIGHT" in readme_text
        and "--skip-media-auth-preflight" in readme_text
        and "public-video tests" in readme_text
    )
    complete = (
        has_gate_function
        and has_pre_clean_call
        and has_pre_download_call
        and upload_route_decoupled
        and skip_escape_documented
    )
    return make_item(
        "Production runs verify restricted media auth before clean slate or downloads",
        status_from(complete, partial=has_gate_function or has_pre_clean_call or has_pre_download_call),
        evidence=[
            f"gate_function={has_gate_function}",
            f"pre_clean_call={has_pre_clean_call}",
            f"pre_download_call={has_pre_download_call}",
            f"upload_route_decoupled={upload_route_decoupled}",
            f"skip_escape_documented={skip_escape_documented}",
            "run.py",
            "README.md",
        ],
        gap="" if complete else "Move restricted media auth preflight before clean slate and document the explicit test-only bypass.",
    )


def audit_analytics_loop():
    files = {
        "youtube_metrics": read_text("analytics/youtube_metrics.py"),
        "performance_scoring": read_text("analytics/performance_scoring.py"),
        "theme_report": read_text("analytics/theme_report.py"),
        "feedback_prior": read_text("analytics/feedback_prior.py"),
        "clip_generation": read_text("clip_generation.py"),
    }
    terms = {
        "engagedViews": "engagedViews" in files["youtube_metrics"],
        "performance_score": "performance_score" in files["performance_scoring"],
        "theme_reports": "build_theme_analytics_report" in files["theme_report"],
        "feedback_prior": "score_analytics_feedback_prior" in files["feedback_prior"],
        "scoring_integration": "analytics_feedback_prior" in files["clip_generation"],
    }
    return make_item(
        "Analytics loop tracks engaged-view performance and feeds source/archetype/format priors back into scoring",
        status_from(all(terms.values()), partial=any(terms.values())),
        evidence=[f"{key}={value}" for key, value in terms.items()],
        gap="" if all(terms.values()) else "Analytics collection/reporting/prior integration is incomplete.",
    )


def audit_research():
    docs = [
        "docs/theme_research_2026.md",
        "docs/theme_engine_research_2026.md",
    ]
    existing = [doc for doc in docs if path_exists(doc)]
    source_mentions = sum(read_text(doc).count("https://") for doc in existing)
    return make_item(
        "Theme selection research is documented with external sources",
        status_from(len(existing) >= 1 and source_mentions >= 4, partial=bool(existing)),
        evidence=[f"research_docs={existing}", f"source_mentions={source_mentions}"],
        gap="Add or expand research memo with cited sources." if source_mentions < 4 else "",
    )


def audit_review_workflow():
    dashboard = read_text("review_dashboard.py")
    queue = read_text("review_queue.py")
    upload = read_text("upload.py")
    actions = ["Approve", "Reject", "regenerate_title", "try_alternate_framing"]
    present_actions = [action for action in actions if action.lower() in (dashboard + queue).lower()]
    manual_policy = "manual review approval required" in upload
    return make_item(
        "Manual review workflow supports approval, rejection, revisions, and publication gating",
        status_from(len(present_actions) == len(actions) and manual_policy, partial=bool(present_actions)),
        evidence=[
            f"review_actions={present_actions}",
            f"manual_policy_enforced={manual_policy}",
            "review_dashboard.py",
            "review_queue.py",
            "upload.py",
        ],
        gap="" if manual_policy else "Upload must block public/unlisted output until manually approved.",
    )


def audit_outputs():
    validation_report = load_json_file(os.path.join(BASE_DIR, "logs", "output_validation_latest.json"), {})
    checked = validation_report.get("checked", 0)
    issues = validation_report.get("issue_count", 0)
    return make_item(
        "Rendered upload-ready outputs are validated as vertical, transformed, gated, and burned-captioned",
        status_from(checked > 0 and issues == 0, partial=checked == 0 or issues > 0),
        evidence=[
            f"checked={checked}",
            f"issues={issues}",
            "logs/output_validation_latest.json",
        ],
        gap=(
            "No rendered outputs exist yet; run production after restricted-video auth passes."
            if checked == 0
            else ("Some generated outputs still fail editorial or render validation." if issues else "")
        ),
    )


def audit_youtube_auth():
    diagnostics = ytdlp_auth.cookie_file_diagnostics()
    auth_ready = False
    auth_error = ""

    try:
        ytdlp_auth.verify_youtube_auth()
        auth_ready = True
    except Exception as error:
        auth_error = str(error).splitlines()[0]

    return make_item(
        "Restricted/age-gated YouTube media auth is verified before full production",
        status_from(auth_ready),
        evidence=[
            f"auth_ready={auth_ready}",
            f"cookie_exists={diagnostics.get('exists')}",
            f"cookie_lines={diagnostics.get('non_comment_lines')}",
            f"cookie_size_kb={diagnostics.get('size_kb')}",
            f"cookie_domains={','.join((diagnostics.get('domains') or [])[:6])}",
            f"cookie_warnings={'; '.join(diagnostics.get('warnings') or [])}",
            f"auth_error={auth_error[:220]}",
        ],
        gap="" if auth_ready else "Export fresh signed-in, age-verified cookies or close Chrome fully and rerun ytdlp_auth.py.",
    )


def build_audit():
    items = [
        audit_theme_configs(),
        audit_phase_one_source_map(),
        audit_generated_output_scope(),
        audit_code_artifacts(),
        audit_theme_visual_styles(),
        audit_visual_regression_pack(),
        audit_candidate_fields(),
        audit_gates(),
        audit_upload_ready_caption_contract(),
        audit_restricted_media_preflight_gate(),
        audit_analytics_loop(),
        audit_research(),
        audit_review_workflow(),
        audit_outputs(),
        audit_youtube_auth(),
    ]
    status_counts = {}

    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "complete" if status_counts.get("missing", 0) == 0 and status_counts.get("partial", 0) == 0 else "incomplete",
        "status_counts": status_counts,
        "themes": discover_themes(),
        "requirements": items,
    }
    write_json_file(REPORT_PATH, report)
    return report


def print_audit(report):
    print(f"Theme engine audit: {report['status']}")
    print(f"Status counts: {report['status_counts']}")

    for item in report["requirements"]:
        print(f" - {item['status']}: {item['requirement']}")

        if item.get("gap"):
            print(f"   gap: {item['gap']}")

    print(f"Report: {REPORT_PATH}")


def parse_args():
    parser = argparse.ArgumentParser(description="Audit Shortform theme-engine implementation against the blueprint.")
    return parser.parse_args()


if __name__ == "__main__":
    parse_args()
    audit_report = build_audit()
    print_audit(audit_report)
    raise SystemExit(0 if audit_report["status"] == "complete" else 1)
