from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "movie", "film", "scene", "actor", "actress", "director", "character",
    "script", "set", "audition", "role", "episode", "casting", "showrunner",
}
ARCHETYPES = [
    ("scene_breakdown", ["scene", "shot", "take"]),
    ("casting_story", ["audition", "casting", "role"]),
    ("behind_the_scenes", ["on set", "behind the scenes", "director"]),
    ("actor_story", ["actor", "actress", "character"]),
    ("fandom_moment", ["fans", "fan", "iconic"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="behind_the_scenes",
        default_intro_mode="cold_open",
        cold_open_terms={"iconic", "audition", "scene"},
        signal_name="screen_hits",
    )
