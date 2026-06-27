import re

from theme_profile import get_metadata_style, load_theme_profile


GENERIC_BAD_PATTERNS = [
    r"^#\d+\s*:",
    r"\bmost interesting podcast moments\b",
    r"\b(best|top|viral|crazy)\s+podcast\s+(clip|moment|moments)\b",
    r"\bpodcast moments?\b$",
    r"\bdaily podcast recap\b",
    r"^today'?s\s+.+\s+podcast recap$",
    r"^top\s+\d+\s+.+\s+moments\s+this\s+week$",
    r"^ranking\s+the\s+.+\s+moments$",
    r"^this\s+(clip|moment|interview)\b",
    r"^best moment from podcast channel$",
    r"^the founder lesson behind\b",
    r"^the startup bet behind\b",
    r"^the business mistake hidden in\b",
    r"^how .{1,32} became the growth lever$",
    r"^why founders obsess over\b",
    r"^why .{1,32} changed this business$",
    r"^this startup mistake compounds fast$",
]

WEAK_TOPIC_TERMS = {
    "thing", "things", "stuff", "people", "person", "someone", "something",
    "bit", "room", "trust", "baby", "question", "free", "broadcast", "mixed",
    "wednesday", "day", "field", "yeah", "okay", "really", "very", "just",
    "good", "great", "little", "big", "more", "most", "kind", "sort",
    "only", "should", "about", "know", "knowing", "building", "other", "to",
    "through", "around", "before", "after", "thing", "way", "ways",
}

TITLE_STOPWORDS = WEAK_TOPIC_TERMS | {
    "the", "and", "for", "with", "from", "into", "to", "this", "that", "what",
    "when", "where", "why", "how", "now", "our", "look", "first", "episode",
    "podcast", "interview", "show", "minute", "minutes", "report",
    "unlocking", "strategies", "strategy", "path", "launch", "launched",
    "know", "knowing", "about", "field", "today", "weekly", "daily",
    "moment", "moments", "clip", "clips", "recap", "countdown", "archive",
}

THEME_ALIASES = {
    "business": "finance",
    "business_money": "finance",
    "business_startups": "finance",
    "money": "finance",
    "investing": "finance",
    "technology": "technology_ai",
    "tech": "technology_ai",
    "ai": "technology_ai",
    "wellness": "health_fitness",
    "health": "health_fitness",
    "psychology": "health_fitness",
    "crime": "truecrime",
    "legal": "truecrime",
    "entertainment": "popculture",
    "celebrity": "popculture",
    "culture": "popculture",
}

THEME_TITLE_WORDS = {
    "comedy": {
        "laugh", "joke", "roast", "comic", "comedian", "bit", "punchline",
        "awkward", "riff", "crowd", "story", "setup", "payoff", "room",
        "funny", "wild",
    },
    "sports": {
        "game", "team", "season", "coach", "locker", "rivalry", "legacy",
        "draft", "trade", "playoff", "championship", "quarterback", "nba",
        "nfl", "athlete", "career", "teammate", "ring", "debate",
    },
    "finance": {
        "business", "money", "market", "markets", "cash", "margin",
        "revenue", "profit", "valuation", "founder", "investor", "debt",
        "inflation", "recession", "startup", "operator", "company",
        "customer", "growth", "pricing", "deal",
    },
    "technology_ai": {
        "ai", "model", "agent", "agents", "startup", "builder", "builders",
        "product", "code", "software", "chip", "data", "research", "robot",
        "workflow", "security", "platform", "eval", "engineer", "developer",
    },
    "health_fitness": {
        "sleep", "stress", "habit", "training", "nutrition", "protein",
        "recovery", "metabolism", "anxiety", "focus", "therapy", "exercise",
        "workout", "protocol", "mindset", "body", "health", "wellness",
    },
    "politics": {
        "election", "policy", "border", "court", "congress", "senate",
        "president", "campaign", "war", "media", "vote", "law", "hearing",
        "debate", "poll", "corruption", "foreign", "administration",
    },
    "truecrime": {
        "case", "trial", "court", "confession", "witness", "victim",
        "testimony", "investigation", "detective", "prison", "jury",
        "verdict", "evidence", "lawyer", "legal", "crime", "survivor",
    },
    "popculture": {
        "celebrity", "actor", "movie", "music", "song", "album", "hollywood",
        "culture", "artist", "interview", "dating", "fame", "career",
        "viral", "scene", "tour", "red carpet", "fan", "reveal",
    },
}

DOMAIN_TOPIC_WORDS = {
    word
    for words in THEME_TITLE_WORDS.values()
    for term in words
    for word in re.findall(r"[a-zA-Z][a-zA-Z']+", term.lower())
}


CLICKBAIT_TERMS = [
    "will shock you",
    "you won't believe",
    "you wont believe",
    "destroyed",
    "exposed",
    "insane truth",
    "secret they don't want",
    "secret they dont want",
    "breaks silence",
    "caught on camera",
    "left everyone speechless",
]


def normalize_theme_key(theme):
    key = str(theme or "").strip().lower().replace("-", "_").replace(" ", "_")
    return THEME_ALIASES.get(key, key)


def theme_title_words(theme):
    return THEME_TITLE_WORDS.get(normalize_theme_key(theme), set())


def theme_signal_terms(theme, lower_title):
    hits = []

    for term in theme_title_words(theme):
        term_lower = term.lower()

        if " " in term_lower:
            if term_lower in lower_title:
                hits.append(term_lower)
            continue

        if re.search(rf"\b{re.escape(term_lower)}\b", lower_title):
            hits.append(term_lower)

    return sorted(set(hits))


def title_repetition_flags(words):
    meaningful = [
        word
        for word in words
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]
    repeated_words = sorted({
        word
        for word in meaningful
        if meaningful.count(word) >= 3
    })
    bigrams = [
        " ".join(meaningful[index:index + 2])
        for index in range(len(meaningful) - 1)
    ]
    repeated_bigrams = sorted({
        bigram
        for bigram in bigrams
        if bigrams.count(bigram) >= 2
    })

    return repeated_words, repeated_bigrams


def is_mechanical_title(lower_title):
    mechanical_patterns = [
        r"^#\d+\s*[:|-]",
        r"\|\s*(funniest|strangest|most surprising|best|top)\s+.+\s+podcast moments?$",
        r"\bpodcast\s+(clip|moment|moments|recap)\b",
        r"^most\s+(replayed|popular)\s+from\s+.+\|\s+.+\s+podcast clip$",
    ]
    return any(re.search(pattern, lower_title) for pattern in mechanical_patterns)


def compact_text(text, max_chars=92):
    text = re.sub(r"\s+", " ", str(text or "")).strip(" -._")

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip(" -._")
    return shortened or text[:max_chars].strip(" -._")


def topic_from_terms(topic_terms, fallback="This Moment"):
    terms = [
        str(term).replace("_", " ").strip()
        for term in topic_terms or []
        if is_strong_topic_term(str(term).replace("_", " "))
    ]

    if terms:
        return compact_text(terms[0].title(), 46)

    return fallback


def is_strong_topic_term(term):
    normalized = re.sub(r"[^a-zA-Z0-9\s%-]", " ", str(term or "").lower())
    words = [word for word in normalized.split() if word]

    if not words:
        return False

    if all(word in WEAK_TOPIC_TERMS for word in words):
        return False

    return any(len(word) >= 4 or any(char.isdigit() for char in word) for word in words)


def is_domain_topic_term(term, theme=None):
    words = set(re.findall(r"[a-zA-Z][a-zA-Z']+", str(term or "").lower()))
    theme_words = theme_title_words(theme)
    theme_word_tokens = {
        word
        for item in theme_words
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+", item.lower())
    }
    return bool(words & (theme_word_tokens or DOMAIN_TOPIC_WORDS))


def topic_terms_from_source_title(source_title, limit=4):
    title = re.sub(r"[\[\](){}|#]", " ", str(source_title or ""))
    title = re.sub(r"\b(ep|episode|podcast|interview|show|minute|report)\b\.?\s*\d*", " ", title, flags=re.I)
    chunks = [
        re.sub(r"\s+", " ", chunk).strip(" -:._!?")
        for chunk in re.split(r"[:|/,-]", title)
    ]
    terms = []

    for chunk in chunks:
        words = [
            word
            for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", chunk)
            if word.lower() not in TITLE_STOPWORDS and not word.isdigit()
        ]

        if len(words) >= 2:
            terms.append(" ".join(words[:3]))
        elif len(words) == 1 and is_strong_topic_term(words[0]):
            terms.append(words[0])

        if len(terms) >= limit:
            break

    return terms


def render_template(template, values):
    text = str(template or "").format(**{
        key: str(value or "")
        for key, value in values.items()
    })
    text = re.sub(r"\s+", " ", text).strip(" -:|")
    return text


def transcript_sentence_title(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""

    signal_words = {
        "why", "how", "what", "mistake", "truth", "money", "revenue",
        "customer", "customers", "growth", "product", "business", "founder",
        "market", "cost", "costs", "million", "billion", "problem",
        "joke", "laugh", "coach", "team", "agent", "model", "sleep",
        "stress", "court", "case", "election", "policy", "movie", "artist",
    }

    for sentence in re.split(r"(?<=[.?!])\s+", text):
        candidate = compact_text(sentence, 92).strip(" .,:;")
        words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", candidate)
        lower_words = {word.lower() for word in words}

        if 4 <= len(words) <= 16 and len(candidate) >= 24:
            if "?" in candidate or any(any(char.isdigit() for char in word) for word in words) or lower_words & signal_words:
                return candidate

    return ""


def generate_title(theme, archetype, clip, source_record=None, signals=None):
    profile = load_theme_profile(theme)
    metadata_style = get_metadata_style(theme)
    source_record = source_record or {}
    signals = signals or {}
    source_title = source_record.get("title") or clip.get("source_title") or ""
    raw_topic_terms = signals.get("topic_terms") or clip.get("topic_fingerprint") or []
    source_topic_terms = topic_terms_from_source_title(source_title)
    raw_strong_terms = [
        term
        for term in raw_topic_terms
        if is_strong_topic_term(term) and str(term).replace("_", " ").strip().lower() not in {
            source_term.lower() for source_term in source_topic_terms
        }
    ]
    domain_terms = [term for term in raw_strong_terms if is_domain_topic_term(term, theme)]
    topic_terms = domain_terms[:2] + source_topic_terms + [
        term for term in raw_strong_terms if term not in domain_terms
    ]
    topic = topic_from_terms(topic_terms, fallback=compact_text(clip.get("transcript_excerpt", ""), 48) or "This Moment")

    if topic == "This Moment" and source_title:
        topic = compact_text(source_title, 46)

    values = {
        "theme": profile.get("brand", {}).get("channel_name") or theme.replace("_", " ").title(),
        "topic": topic,
        "archetype": str(archetype or "moment").replace("_", " "),
        "source": source_record.get("channel") or clip.get("source_title") or "the interview",
        "duration": int(round(float(clip.get("duration") or 45))),
    }

    for template in metadata_style.get("title_templates") or []:
        title = compact_text(render_template(template, values), 96)
        quality = score_title_quality(theme, title, topic_terms=topic_terms)

        if (
            quality["length_ok"]
            and quality["specificity"] >= 0.35
            and quality.get("honesty", 0.0) >= 0.70
            and not quality.get("generic_title")
            and not quality.get("repetitive_title")
            and quality.get("theme_native_title", True)
            and quality["not_clickbait"]
        ):
            return title

    transcript_fallback = transcript_sentence_title(clip.get("transcript_excerpt", ""))
    if transcript_fallback:
        return transcript_fallback

    source_fallback = compact_text(source_title, 90)
    source_words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", source_fallback)
    if len(source_words) >= 4:
        return source_fallback

    fallback = compact_text(topic, 90)

    if fallback and len(fallback.split()) >= 3:
        return fallback

    return compact_text(f"{values['archetype'].title()} From {values['source']}", 92)


def score_title_quality(theme, title, topic_terms=None):
    title = str(title or "").strip()
    lower = title.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", lower)
    topic_terms = [str(term).replace("_", " ").lower() for term in topic_terms or []]
    topic_hit = any(term and term in lower for term in topic_terms)
    has_number = any(any(char.isdigit() for char in word) for word in words)
    generic = any(re.search(pattern, lower) for pattern in GENERIC_BAD_PATTERNS)
    theme_hits = theme_signal_terms(theme, lower)
    repeated_words, repeated_bigrams = title_repetition_flags(words)
    repetitive_title = bool(repeated_words or repeated_bigrams)
    mechanical_title = is_mechanical_title(lower)
    matters_match = re.search(r"^why\s+(.+?)\s+matters\b", lower)

    if matters_match:
        subject_words = [
            word
            for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", matters_match.group(1))
            if word not in TITLE_STOPWORDS
        ]
        has_subject_number = any(any(char.isdigit() for char in word) for word in subject_words)

        if len(subject_words) < 2 and not has_subject_number:
            generic = True
    clickbait_hits = [term for term in CLICKBAIT_TERMS if term in lower]
    meaningful_words = [
        word
        for word in words
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]
    theme_native_title = bool(topic_hit or theme_hits or len(meaningful_words) >= 4)
    specificity = min(
        1.0,
        0.14 * len(set(meaningful_words))
        + (0.25 if topic_hit else 0.0)
        + (0.16 if theme_hits else 0.0)
        + (0.12 if has_number else 0.0),
    )
    curiosity = min(
        1.0,
        (0.22 if any(word in lower for word in ["why", "how", "what", "mistake", "truth", "secret", "cost"]) else 0.0)
        + 0.07 * len(words),
    )
    theme_fit = 0.86 if topic_hit and theme_hits else (0.74 if topic_hit or theme_hits else (0.58 if theme_native_title else 0.36))
    honest_title = not (generic or mechanical_title or repetitive_title or clickbait_hits)

    return {
        "specificity": specificity,
        "curiosity": curiosity,
        "honesty": 0.35 if not honest_title else 0.86,
        "theme_fit": theme_fit,
        "length_ok": 8 <= len(title) <= 96,
        "not_clickbait": not clickbait_hits,
        "generic_title": bool(generic or mechanical_title),
        "theme_native_title": theme_native_title,
        "repetitive_title": repetitive_title,
        "mechanical_title": mechanical_title,
        "topic_hit": topic_hit,
        "theme_signal_terms": theme_hits,
        "meaningful_word_count": len(set(meaningful_words)),
        "repeated_words": repeated_words,
        "repeated_bigrams": repeated_bigrams,
        "clickbait_terms": clickbait_hits,
    }
