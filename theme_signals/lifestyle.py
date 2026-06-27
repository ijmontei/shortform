from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "style", "routine", "home", "travel", "food", "taste", "habit",
    "design", "city", "culture", "fashion", "morning", "apartment",
}
ARCHETYPES = [
    ("routine_tip", ["routine", "morning", "habit"]),
    ("taste_signal", ["style", "taste", "design"]),
    ("identity_moment", ["identity", "confidence", "personal"]),
    ("culture_lesson", ["culture", "city", "travel"]),
    ("life_upgrade", ["upgrade", "better", "simple"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="life_upgrade",
        default_intro_mode="cold_open",
        cold_open_terms={"simple", "mistake", "better"},
        signal_name="lifestyle_hits",
    )
