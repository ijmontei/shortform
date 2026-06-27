from theme_signals.generic import score_theme_signals as generic_score


HIGH_REVIEW_TERMS = {
    "election", "war", "crime", "illegal", "court", "judge", "lawsuit",
    "fraud", "corrupt", "terrorist", "classified", "vaccine", "border",
}


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()
    review_hits = [term for term in HIGH_REVIEW_TERMS if term in lower]

    if review_hits:
        result.setdefault("concerns", []).append("claim context/fact-check required")
        result["signals"]["politics_review_terms"] = review_hits[:10]
        result["theme_signal_score"] = min(1.0, float(result["theme_signal_score"]) + 0.08)

    if "policy" in lower:
        result["archetype"] = "policy_explainer"
    elif "election" in lower:
        result["archetype"] = "source_context"
    elif "debate" in lower or "disagree" in lower:
        result["archetype"] = "debate_moment"

    result["recommended_intro_mode"] = "context_card"
    return result
