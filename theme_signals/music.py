from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "song", "album", "artist", "studio", "producer", "tour", "label",
    "record", "lyrics", "beat", "rapper", "singer", "band", "concert",
}
ARCHETYPES = [
    ("song_story", ["song", "lyrics", "hook"]),
    ("studio_moment", ["studio", "producer", "beat"]),
    ("artist_origin", ["started", "first record", "origin"]),
    ("industry_truth", ["label", "deal", "royalty"]),
    ("career_turn", ["tour", "album", "hit"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="artist_story",
        default_intro_mode="cold_open",
        cold_open_terms={"hit", "label", "first song"},
        concern_terms={"music rights review": {"lyrics", "music video"}},
        signal_name="music_hits",
    )
