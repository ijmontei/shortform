from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "creator", "youtube", "tiktok", "algorithm", "audience", "monetize",
    "brand deal", "newsletter", "views", "retention", "subscriber",
    "shorts", "viral", "content", "platform",
}
ARCHETYPES = [
    ("algorithm_lesson", ["algorithm", "retention", "watch time"]),
    ("monetization_breakdown", ["monetize", "brand deal", "sponsor"]),
    ("viral_format", ["viral", "format", "hook"]),
    ("platform_shift", ["platform", "youtube", "tiktok"]),
    ("creator_mistake", ["mistake", "burnout", "failed"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="creator_growth",
        default_intro_mode="cold_open",
        cold_open_terms={"viral", "algorithm", "mistake"},
        signal_name="creator_hits",
    )
