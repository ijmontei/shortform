from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "training", "workout", "sleep", "nutrition", "protein", "mobility",
    "recovery", "cardio", "strength", "metabolism", "muscle", "zone 2",
    "calories", "supplement", "exercise",
}
ARCHETYPES = [
    ("training_mistake", ["mistake", "overtraining", "injury"]),
    ("nutrition_rule", ["nutrition", "protein", "calories"]),
    ("daily_protocol", ["protocol", "routine", "daily"]),
    ("recovery_lesson", ["sleep", "recovery", "mobility"]),
    ("health_myth", ["myth", "wrong", "misunderstood"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="performance_tip",
        default_intro_mode="clip_then_takeaway",
        concern_terms={"medical review suggested": {"cure", "diagnose", "disease", "hormone"}},
        signal_name="health_fitness_hits",
    )
