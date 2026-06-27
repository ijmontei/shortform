from theme_signals.keyword_profile import score_keyword_profile


TERMS = {
    "case", "court", "trial", "detective", "evidence", "timeline", "motive",
    "witness", "investigation", "verdict", "police", "judge", "jury",
}
ARCHETYPES = [
    ("case_timeline", ["timeline", "before", "after"]),
    ("courtroom_moment", ["court", "trial", "judge", "jury"]),
    ("evidence_context", ["evidence", "dna", "phone records"]),
    ("investigator_insight", ["detective", "investigation", "police"]),
    ("legal_turn", ["verdict", "appeal", "charged"]),
]


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    return score_keyword_profile(
        text, segments, audio_path, clip_start, clip_end, metadata,
        terms=TERMS,
        archetype_rules=ARCHETYPES,
        default_archetype="case_context",
        default_intro_mode="context_card",
        concern_terms={"legal claim review": {"murdered", "killer", "guilty", "accused", "alleged"}},
        signal_name="truecrime_hits",
    )
