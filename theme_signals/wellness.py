from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if any(term in lower for term in ["sleep", "stress", "anxiety", "dopamine", "exercise", "nutrition"]):
        result["archetype"] = "health_mistake"
        result["theme_signal_score"] = min(1.0, float(result["theme_signal_score"]) + 0.14)
    elif any(term in lower for term in ["habit", "discipline", "routine", "consistency"]):
        result["archetype"] = "daily_protocol"
        result["theme_signal_score"] = min(1.0, float(result["theme_signal_score"]) + 0.12)

    result["recommended_intro_mode"] = "clip_then_takeaway"
    return result
