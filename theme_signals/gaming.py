from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "game", "gaming", "developer", "studio", "esports", "console", "design",
    "player", "launch", "streamer", "patch", "xbox", "playstation",
    "nintendo", "pc", "server", "quest", "fps",
}
ARCHETYPES = [
    ("developer_insight", ["developer", "studio", "design"]),
    ("launch_drama", ["launch", "delay", "patch", "broken"]),
    ("industry_debate", ["console", "exclusive", "publisher"]),
    ("esports_moment", ["esports", "tournament", "pro player"]),
    ("creator_lesson", ["streamer", "youtube", "audience"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="game_design",
        default_intro_mode="cold_open",
        cold_open_terms={"broken", "overrated", "underrated", "launch"},
        signal_name="gaming_hits",
    )
