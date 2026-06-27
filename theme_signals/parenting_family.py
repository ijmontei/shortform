from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "parent", "parents", "kid", "child", "family", "school", "discipline",
    "mom", "dad", "teen", "behavior", "boundary", "homework", "tantrum",
}
ARCHETYPES = [
    ("parenting_reframe", ["reframe", "different way", "instead"]),
    ("family_conflict", ["fight", "argument", "conflict"]),
    ("child_development", ["development", "brain", "school"]),
    ("boundary_lesson", ["boundary", "discipline", "rules"]),
    ("emotional_moment", ["cry", "afraid", "love"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="practical_rule",
        default_intro_mode="clip_then_takeaway",
        concern_terms={"family safety review": {"abuse", "custody", "diagnosis"}},
        signal_name="parenting_hits",
    )
