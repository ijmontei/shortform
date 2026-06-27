from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if any(term in lower for term in ["forgiveness", "moral", "good", "evil"]):
        result["archetype"] = "moral_dilemma"
    elif any(term in lower for term in ["god", "faith", "theology", "church"]):
        result["archetype"] = "theological_explainer"
    elif "philosophy" in lower or "meaning" in lower:
        result["archetype"] = "philosophical_argument"

    result["recommended_intro_mode"] = "context_card"
    return result
