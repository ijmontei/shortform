from theme_signals.generic import score_theme_signals as generic_score


COMEDY_KEYWORDS = {
    "laugh", "laughing", "laughter", "funny", "hilarious", "joke", "roast",
    "awkward", "ridiculous", "insane", "wild", "crazy", "bit", "punchline",
    "broke", "loses it", "room", "crowd",
}


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()
    hits = [keyword for keyword in COMEDY_KEYWORDS if keyword in lower]
    reaction_bonus = 0.16 if any(word in lower for word in ["laugh", "hahaha", "that's crazy", "no way"]) else 0.0
    score = min(1.0, float(result["theme_signal_score"]) + 0.035 * len(hits) + reaction_bonus)

    if "roast" in lower:
        archetype = "roast"
    elif "awkward" in lower:
        archetype = "awkward_moment"
    elif "laugh" in lower or "hilarious" in lower:
        archetype = "guest_breaks"
    elif "story" in lower:
        archetype = "wild_story"
    else:
        archetype = result.get("archetype") or "punchline"

    result["theme_signal_score"] = score
    result["signals"]["comedy_hits"] = sorted(hits)[:10]
    result["archetype"] = archetype
    result["recommended_intro_mode"] = "cold_open" if score >= 0.35 else "context_card"
    return result
