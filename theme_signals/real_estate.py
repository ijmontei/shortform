from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "real estate", "property", "mortgage", "rent", "tenant", "cash flow",
    "interest rate", "cap rate", "deal", "housing", "landlord", "zoning",
    "broker", "appraisal", "vacancy",
}
ARCHETYPES = [
    ("deal_breakdown", ["deal", "cap rate", "cash flow"]),
    ("market_warning", ["market", "rates", "interest rate", "crash"]),
    ("operator_mistake", ["mistake", "tenant", "vacancy"]),
    ("housing_trend", ["housing", "rent", "zoning"]),
    ("financing_lesson", ["mortgage", "loan", "debt"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="deal_breakdown",
        default_intro_mode="context_card",
        concern_terms={"financial review suggested": {"guaranteed", "risk free", "buy now"}},
        signal_name="real_estate_hits",
    )
