from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "discipline", "habit", "mindset", "confidence", "focus", "goal",
    "identity", "failure", "motivation", "routine", "consistency",
    "procrastination", "attention", "practice",
}
ARCHETYPES = [
    ("mindset_shift", ["mindset", "reframe", "identity"]),
    ("discipline_rule", ["discipline", "consistency", "routine"]),
    ("habit_loop", ["habit", "daily", "practice"]),
    ("failure_lesson", ["failure", "failed", "mistake"]),
    ("focus_rule", ["focus", "attention", "procrastination"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="mindset_shift",
        default_intro_mode="clip_then_takeaway",
        cold_open_terms={"mistake", "failure", "discipline"},
        concern_terms={"mental health review": {"depression", "trauma", "diagnose"}},
        signal_name="self_improvement_hits",
    )
