from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "dating", "relationship", "marriage", "breakup", "red flag",
    "green flag", "texting", "love", "partner", "boundaries", "date",
    "single", "commitment", "attraction",
}
ARCHETYPES = [
    ("red_flag", ["red flag", "toxic", "avoid"]),
    ("green_flag", ["green flag", "healthy"]),
    ("dating_rule", ["dating", "date", "texting"]),
    ("relationship_conflict", ["argument", "fight", "breakup"]),
    ("boundary_lesson", ["boundary", "boundaries"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="dating_rule",
        default_intro_mode="cold_open",
        cold_open_terms={"red flag", "green flag", "breakup"},
        concern_terms={"sensitive relationship review": {"abuse", "diagnosed", "narcissist"}},
        signal_name="relationship_hits",
    )
