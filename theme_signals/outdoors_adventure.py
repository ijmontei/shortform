from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "hunting", "fishing", "trail", "mountain", "survival", "gear",
    "wild", "camp", "weather", "risk", "backcountry", "climb", "river",
}
ARCHETYPES = [
    ("survival_lesson", ["survival", "risk", "danger"]),
    ("gear_choice", ["gear", "pack", "rifle", "rod"]),
    ("wild_story", ["wild", "bear", "mountain", "river"]),
    ("field_mistake", ["mistake", "lost", "weather"]),
    ("adventure_payoff", ["summit", "caught", "finished"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="wild_story",
        default_intro_mode="context_card",
        cold_open_terms={"danger", "lost", "caught"},
        signal_name="outdoors_hits",
    )
