from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if "misconception" in lower or "wrong" in lower:
        result["archetype"] = "misconception_correction"
    elif "example" in lower or "analogy" in lower:
        result["archetype"] = "simple_analogy"
    elif "definition" in lower or "means" in lower:
        result["archetype"] = "definition"

    result["recommended_intro_mode"] = "explain_then_clip"
    return result
