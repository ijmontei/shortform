from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "celebrity", "viral", "tiktok", "internet", "drama", "fans",
    "culture", "famous", "trend", "controversy", "rumor", "public",
}
ARCHETYPES = [
    ("viral_moment", ["viral", "trend", "internet"]),
    ("fandom_debate", ["fans", "fandom", "stan"]),
    ("celebrity_story", ["celebrity", "famous"]),
    ("public_reaction", ["backlash", "controversy", "reaction"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="culture_moment",
        default_intro_mode="cold_open",
        cold_open_terms={"viral", "backlash", "controversy"},
        concern_terms={"claim context review": {"rumor", "allegation", "accused"}},
        signal_name="culture_hits",
    )
