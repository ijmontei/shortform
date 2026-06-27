import argparse
import os

from theme_config import clean_theme_name, theme_config_path, write_json_file
from theme_profile import DEFAULT_THEME_PROFILE, get_scoring_weights, load_theme_profile


OPERATOR_QUESTIONS = [
    "Who is the viewer?",
    "What pain, curiosity, or desire makes them stop scrolling?",
    "What does this channel add that the original podcast does not?",
    "What makes a clip good in this theme?",
    "What makes a clip bad in this theme?",
    "What are the top 8 clip archetypes?",
    "What claims are risky?",
    "What must be manually reviewed?",
    "What intro mode fits this theme?",
    "What caption style fits this theme?",
    "What should the title feel like?",
    "What metric proves the theme is working?",
]


def blank_theme_payload(theme_name, profile_name="generic"):
    theme = clean_theme_name(theme_name)
    preset = load_theme_profile(profile_name if profile_name != "generic" else theme)
    default = DEFAULT_THEME_PROFILE
    clip_rules = dict(default["clip_rules"])
    clip_rules.update({
        "candidate_durations": [],
        "min_clip_duration": 0,
        "max_clip_duration": 0,
        "default_clip_count": 0,
        "theme_clip_budget": 15,
        "theme_candidates_per_video": 8,
        "min_readiness_score": 0.0,
        "min_selected_score": 0.0,
        "max_topic_similarity": 0.0,
    })
    return {
        "theme": theme,
        "profile": profile_name,
        "brand": {
            "channel_name": "",
            "positioning": "",
            "audience": "",
            "viewer_promise": "",
            "voice": "",
            "risk_tolerance": "medium",
        },
        "youtube": {
            "channel_handle": "",
            "token_file": "",
        },
        "channels": [],
        "research": {
            "priority": "unset",
            "community_thesis": "",
            "source_strategy": "",
            "operator_questions": {question: "" for question in OPERATOR_QUESTIONS},
        },
        "clip_rules": clip_rules,
        "scoring_weights": get_scoring_weights(profile_name if profile_name != "generic" else theme),
        "theme_signals": {
            "enabled": [],
            "required": [],
            "positive_keywords": [],
            "negative_keywords": [],
            "keyword_weights": {},
            "archetypes": [],
            "penalize_missing_theme_signal": True,
        },
        "packaging": {
            "intro_modes": [],
            "default_intro_mode": "",
            "max_intro_seconds": 0.0,
            "caption_style": (preset.get("packaging") or {}).get("caption_style", ""),
            "framing_style": (preset.get("packaging") or {}).get("framing_style", ""),
            "overlay_style": (preset.get("packaging") or {}).get("overlay_style", ""),
        },
        "metadata_style": {
            "title_style": "specific_curiosity",
            "title_templates": [],
            "description_style": "source_plus_context",
            "hashtags": [],
            "tags": [],
            "topic_tags": {},
        },
        "risk_controls": {
            "requires_fact_check": False,
            "requires_medical_review": False,
            "requires_financial_review": False,
            "requires_claim_context": False,
            "restricted_topics": [],
            "manual_review_topics": [],
            "minimum_transformation_score": 0.55,
        },
        "review_policy": dict(default["review_policy"]),
        "analytics": dict(default["analytics"]),
        "experiments": {
            "enabled": True,
            "active": [],
        },
    }


def create_theme_scaffold(theme_name, profile_name="generic", force=False):
    theme = clean_theme_name(theme_name)
    path = theme_config_path(theme)

    if os.path.exists(path) and not force:
        raise FileExistsError(f"{path} already exists. Use --force to overwrite.")

    payload = blank_theme_payload(theme, profile_name=profile_name)
    write_json_file(path, payload)
    print(f"Theme scaffold created: {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="Create a new Shortform theme JSON from the universal theme-engine schema.")
    parser.add_argument("theme", help="New theme name.")
    parser.add_argument("--profile", default="generic", help="Optional profile preset to borrow defaults from.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing theme JSON.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    create_theme_scaffold(args.theme, profile_name=args.profile, force=args.force)
