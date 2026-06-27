from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "history", "war", "empire", "king", "ancient", "century", "battle",
    "revolution", "archive", "myth", "civilization", "invasion", "treaty",
}
ARCHETYPES = [
    ("forgotten_detail", ["forgotten", "nobody remembers", "archive"]),
    ("historical_turn", ["changed", "turning point", "revolution"]),
    ("myth_correction", ["myth", "not true", "misunderstood"]),
    ("timeline_explainer", ["before", "after", "century"]),
    ("character_story", ["king", "queen", "general", "leader"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="historical_explanation",
        default_intro_mode="explain_then_clip",
        signal_name="history_hits",
    )
