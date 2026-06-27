from theme_signals.generic import score_theme_signals as generic_score


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()

    if any(term in lower for term in ["agent", "model", "eval", "benchmark", "ai"]):
        result["archetype"] = "ai_limitation" if any(term in lower for term in ["hard", "fails", "limitation", "break"]) else "technical_explainer"
        result["theme_signal_score"] = min(1.0, float(result["theme_signal_score"]) + 0.12)
    elif any(term in lower for term in ["founder", "startup", "product", "customer"]):
        result["archetype"] = "product_strategy"
        result["theme_signal_score"] = min(1.0, float(result["theme_signal_score"]) + 0.10)

    result["recommended_intro_mode"] = "context_card"
    return result
