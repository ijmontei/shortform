from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "founder", "startup", "customer", "customers", "growth", "revenue",
    "fundraise", "fundraising", "product market fit", "sales", "hiring",
    "operator", "margin", "churn", "launch", "pricing",
}
ARCHETYPES = [
    ("product_market_fit", ["product market fit", "pmf"]),
    ("first_customers", ["first customer", "first customers"]),
    ("fundraising_moment", ["fundraise", "fundraising", "seed round", "series a"]),
    ("operator_mistake", ["mistake", "failed", "wrong", "churn"]),
    ("growth_loop", ["growth", "distribution", "retention"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="founder_lesson",
        default_intro_mode="context_card",
        cold_open_terms={"mistake", "failed", "first customer"},
        signal_name="startup_hits",
    )
