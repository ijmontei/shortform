from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "restaurant", "chef", "menu", "service", "kitchen", "hospitality",
    "recipe", "customer", "dish", "staff", "server", "reservation",
    "food cost", "margins", "wine", "bar",
}
ARCHETYPES = [
    ("chef_story", ["chef", "dish", "kitchen"]),
    ("restaurant_lesson", ["restaurant", "menu", "food cost", "margins"]),
    ("service_moment", ["service", "server", "customer"]),
    ("food_business", ["hospitality", "reservation", "staff"]),
    ("kitchen_mistake", ["mistake", "rush", "burned"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="restaurant_lesson",
        default_intro_mode="context_card",
        cold_open_terms={"mistake", "customer", "chef"},
        signal_name="food_hospitality_hits",
    )
