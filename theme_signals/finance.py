from theme_signals.generic import score_theme_signals as generic_score


FINANCE_TERMS = {
    "market", "markets", "cash flow", "interest", "inflation", "recession",
    "debt", "valuation", "startup", "founder", "margin", "revenue",
    "profit", "invest", "portfolio", "tax", "mortgage", "rate", "rates",
}


RISK_TERMS = {
    "buy this stock", "guaranteed", "risk free", "get rich", "100x", "can't lose",
}


def score_theme_signals(text, segments, audio_path, clip_start, clip_end, metadata=None):
    result = generic_score(text, segments, audio_path, clip_start, clip_end, metadata)
    lower = (text or "").lower()
    hits = [term for term in FINANCE_TERMS if term in lower]
    risk_hits = [term for term in RISK_TERMS if term in lower]
    number_bonus = 0.14 if any(char.isdigit() for char in text or "") else 0.0
    score = min(1.0, float(result["theme_signal_score"]) + 0.04 * len(hits) + number_bonus)

    if "recession" in lower or "risk" in lower or "warning" in lower:
        archetype = "market_warning"
    elif "valuation" in lower or "margin" in lower:
        archetype = "business_breakdown"
    elif "debt" in lower or "mortgage" in lower or "interest" in lower:
        archetype = "economic_explainer"
    elif "founder" in lower or "startup" in lower:
        archetype = "founder_lesson"
    else:
        archetype = result.get("archetype") or "investment_thesis"

    result["theme_signal_score"] = score
    result["signals"]["finance_hits"] = sorted(hits)[:10]
    result["signals"]["financial_risk_hits"] = risk_hits
    result["archetype"] = archetype
    result["recommended_intro_mode"] = "context_card"

    if risk_hits:
        result.setdefault("concerns", []).append("financial safety review suggested")

    return result
