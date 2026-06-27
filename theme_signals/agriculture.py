from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if any(term in lower for term in ["cost", "margin", "cash flow", "commodity"]):
        result["archetype"] = "farm_economics"
    elif any(term in lower for term in ["weather", "rain", "drought"]):
        result["archetype"] = "weather_risk"
    elif any(term in lower for term in ["equipment", "tractor", "combine"]):
        result["archetype"] = "equipment_decision"

    result["recommended_intro_mode"] = "context_card"
    return result
