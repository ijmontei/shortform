from theme_signals.generic import score_theme_signals as generic_score


def score_keyword_profile(
    text,
    segments,
    audio_path,
    clip_start,
    clip_end,
    metadata=None,
    terms=None,
    archetype_rules=None,
    default_archetype="clean_explanation",
    default_intro_mode="context_card",
    cold_open_terms=None,
    concern_terms=None,
    signal_name="theme_hits",
):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()
    terms = terms or set()
    archetype_rules = archetype_rules or []
    cold_open_terms = cold_open_terms or set()
    concern_terms = concern_terms or {}
    hits = [term for term in terms if term in lower]
    cold_hits = [term for term in cold_open_terms if term in lower]
    score = min(1.0, float(result.get("theme_signal_score") or 0.0) + 0.045 * len(hits) + 0.12 * min(2, len(cold_hits)))
    archetype = result.get("archetype") or default_archetype

    for name, keywords in archetype_rules:
        if any(keyword in lower for keyword in keywords):
            archetype = name
            break

    concerns = result.setdefault("concerns", [])

    for label, keywords in concern_terms.items():
        found = [term for term in keywords if term in lower]

        if found:
            concerns.append(label)
            result.setdefault("signals", {})[f"{signal_name}_{label.replace(' ', '_')}"] = found[:8]

    result["theme_signal_score"] = score
    result.setdefault("signals", {})[signal_name] = sorted(hits)[:12]
    result["archetype"] = archetype
    result["recommended_intro_mode"] = "cold_open" if cold_hits else default_intro_mode
    return result
