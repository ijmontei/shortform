from theme_signals.generic import score_theme_signals as generic_score


SPORTS_TERMS = {
    "championship", "playoffs", "draft", "trade", "locker room", "coach",
    "quarterback", "nba", "nfl", "ufc", "fight", "legacy", "rivalry",
    "team", "teammate", "finals", "super bowl", "mvp",
}


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()
    hits = [term for term in SPORTS_TERMS if term in lower]
    debate_bonus = 0.14 if any(term in lower for term in ["better than", "greatest", "overrated", "underrated"]) else 0.0
    score = min(1.0, float(result["theme_signal_score"]) + 0.04 * len(hits) + debate_bonus)

    if "legacy" in lower or "greatest" in lower:
        archetype = "legacy_debate"
    elif "locker room" in lower:
        archetype = "locker_room_story"
    elif "rivalry" in lower or "trash" in lower:
        archetype = "rivalry"
    elif "draft" in lower:
        archetype = "draft_regret"
    else:
        archetype = result.get("archetype") or "hot_take"

    result["theme_signal_score"] = score
    result["signals"]["sports_hits"] = sorted(hits)[:10]
    result["archetype"] = archetype
    result["recommended_intro_mode"] = "cold_open" if debate_bonus else "context_card"
    return result
