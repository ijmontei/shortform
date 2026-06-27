from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if any(term in lower for term in ["mistake", "avoid", "don't do"]):
        result["archetype"] = "travel_mistake"
    elif any(term in lower for term in ["custom", "culture", "local"]):
        result["archetype"] = "local_custom"
    elif any(term in lower for term in ["food", "restaurant", "street food"]):
        result["archetype"] = "food_discovery"

    result["recommended_intro_mode"] = "context_card"
    return result
