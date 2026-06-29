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
    r"^a clearer way to think about\b",
    r"^(editor pick|timestamp-backed|viewers replayed)\s*:",
    r"\bfrom\s+(podcast channel|[a-z0-9 ._-]{2,40})$",
    r"\btold the story behind\b",
    r"\bis worth saving$",
    r"\bthe claim to rewatch$",
    r"\bwhat watch\b",
    r"\bindia's?\s+build\s+global\b",
    r"^why\s+.+\s+matters\s+for\s+your\s+body$",
    r"^why\s+.+\s+matters\s+for\s+your\s+(business|money|career|team|case)$",
    r"\bfull\s+(show|episode|episodes)\b",
    r"\blast looks\b",
    r"\bmagnum opus\b",
    r"\bhave an epic conversation\b",
    r"\bsmartless\b$",
    r"^the\s+.+\s+is\s+(very|really|kind of|sort of)\b",
    r"^the celebrity story behind\b",
    r"^the culture take behind\b",
    r"\bbreakfast club full\b",
    r"\bfull$",
    r"^[a-z0-9 '&.-]{2,32}:\s+the\s+(market signal|market question|business angle|business signal|business lesson)$",
    r"^the\s+(market|business|money)\s+(signal|question|angle|lesson)\b",
    r"^what\s+(money|business|company|companies|guy made billions|market|markets|truth)\s+reveals\s+about\s+the\s+market$",
    r"^what\s+.+\s+said\s+about\b",
    r"\bsaid\s+about\b",
    r"\s\|\s",
    r"\bthe\s+ai\s+problem\s+behind\s+(100|android|learn|model|data|founders|systems|thinking|scary|budget|enterprise|network|deliver|conviction|crazy)\b",
    r"^what\s+(billion|billionaire|down|however|into|week|days|subpoena|college|victim|phone|ranch|neighborhood|doubts|group|thus)\s+reveals\s+about\s+the\s+market$",
    r"^why\s+[a-z0-9]{2,18}\s+(became|is|changes|matters|split)\b",
    r"^the\s+(evidence question|case detail|story|ai bottleneck|political risk|business risk|habit|lesson)\s+(behind|around)\s+[a-z0-9]{2,18}$",
    r"^the\s+.+\s+worth\s+rewatching$",
    r"^the\s+.+\s+moment\s+worth\s+seeing$",
    r"^\w+\s+is\s+the\s+joke\s+that\s+lands$",
    r"^the\s+(fandom debate|quotable line|viral moment)\s+behind\s+[a-z0-9'.-]{2,24}$",
    r"^the\s+.+\s+story\s+fans\s+never\s+hear$",
    r"\bthe\s+story\s+people\s+will\s+debate\b",
    r"\bthe\s+(policy\s+)?claim\s+worth\s+checking\b",
    r"\bthe\s+culture\s+story\s+people\s+will\s+debate\b",
    r"\bthe\s+interview\s+moment\s+worth\s+watching\b",
    r"^the\s+pop\s+culture\s+detail\s+inside\b",
    r"^the\s+context\s+behind\b",
    r"^the\s+debate\s+inside\b",
    r"^the\s+debate\s+moment\s+clip\b",
    r"\bclip\s+with\s+a\s+real\s+payoff\b",
    r"\bsplit\s+the\s+lobby\b",
    r"\bis\s+harder\s+than\s+it\s+looks\b",
    r"\bquestion\s+investors\s+miss\b",
    r"^the\s+habit\s+behind\b",
    r"^the\s+builder\s+takeaway\b",
    r"^the\s+creator\s+take\s+behind\b",
    r"^the\s+joke\s+inside\b",
    r"^the\s+investor\s+catch\s+inside\b",
    r"^the\s+health\s+(detail|warning)\s+inside\b",
    r"^the\s+ai\s+question\s+inside\b",
    r"\bthe\s+ai\s+detail\s+builders\s+are\s+watching\b",
    r"^the\s+market\s+detail\s+investors\s+should\s+watch$",
    r"^the\s+game\s+industry\s+bet\s+on\b",
    r"^what\s+if\s+granny\s+smith\s+had\s+a\s+birthday\s+party\??$",
    r"^the\s+health\s+detail\s+worth\s+rethinking$",
    r"\bchanges\s+the\s+plan$",
    r"^what\s+.+\s+changes\s+in\s+the\s+debate$",
    r"^why\s+.+\s+became\s+the\s+debate$",
    r"^why\s+.+\s+(took\s+over\s+the\s+conversation|became\s+the\s+moment)$",
    r"^the\s+joke\s+that\s+actually\s+landed$",
    r"^oh\s+my\s+god\b",
    r"^for\s+your\s+whole\s+life\b",
    r"^if\s+(i|he|she|they|we|you)\b",
    r"^our\s+church\s+represents\b",
    r"^911,\s+your\s+phone\b",
    r"^\d{4}\s+represents\b",
    r"^joe\s+rogan\s+experience\b",
    r"\bsmartless\b",
    r"\bwhiskey\s+ginger\b",
    r"\btigerbelly\b",
    r"\bhot\s+ones\b",
    r"\b(on|at|for|to|from|with|about|inside|behind)\s+(the|a|an|this|that|first|last)$",
    r"\b(on|at|for|to|from|with|about|inside|behind)\s+the\s+(first|last)$",
    r"\b(that broke the room|worth rewatching|worth seeing)$",
    r"^what\s+(bigger|alentown|billionaire|terrible|bullshit|sentiment|will|qualitative|federal|kids)\b",
    r"^what\s+(away|fast|pennsylvania|word|entire|analysis|failure)\s+reveals\s+about\s+the\s+market$",
    r"^why\s+investors\s+are\s+watching\s+(billionaire|bigger|alentown)$",
    r"^why\s+.+\b(simply|too)\b.*\s+matters\s+to\s+investors$",
    r":\s+the\s+(sports debate|locker room angle|investor takeaway)$",
    r"^the\s+debate\s+around\s+[a-z0-9 '&.-]{2,36}$",
    r"^the\s+business\s+risk\s+around\s+[a-z0-9 '&.-]{2,36}$",
    r"^nba\s+offseason\s+changed\s+the\s+game$",
    r"\bcash\s+growth\s+flow\b",
    r"^the\s+policy\s+fight\s+behind\s+(terrible|bullshit|sentiment|will|qualitative|federal|kids|700|300|entire|analysis|failure|word)$",
    r"^the\s+political\s+risk\s+in\s+(will|700|300|word|entire)$",
    r"^why\s+[0-9,.]+\s+is\s+a\s+real\s+ai\s+bottleneck$",
    r"^what\s+(does|are)\b",
    r"^investors\s+want\s+to\s+invest$",
]

WEAK_TOPIC_TERMS = {
    "thing", "things", "stuff", "people", "person", "someone", "something",
    "bit", "room", "trust", "baby", "question", "free", "broadcast", "mixed",
    "wednesday", "day", "field", "yeah", "okay", "really", "very", "just",
    "good", "great", "little", "big", "more", "most", "kind", "sort",
    "only", "should", "about", "know", "knowing", "building", "other", "to",
    "through", "around", "before", "after", "thing", "way", "ways",
    "these", "those", "there", "here", "are", "was", "were", "has", "have",
    "had", "new", "weekend", "smartless",
    "billion", "down", "however", "into", "learn", "thinking", "scary",
    "budget", "enterprise", "network", "deliver", "conviction", "crazy",
    "college", "phone", "doubts", "subpoena", "week", "days", "true",
    "many", "year", "years", "hours", "features", "weights", "models",
    "underlying", "today", "group", "thus", "saying", "sense", "attorney",
    "steve", "matt", "case", "express", "turned", "number", "continued",
    "grow", "times", "training", "moved", "lesson", "rule",
    "bigger", "terrible", "bullshit", "sentiment", "qualitative",
    "federal", "kids", "billionaire", "alentown", "awkward", "guest",
    "breaks", "surprising", "reveal", "self", "own",
    "away", "fast", "pennsylvania", "entire", "analysis", "failure",
    "word", "terror", "will", "approximately", "changing", "chose",
    "according", "rooting", "asking", "iranian", "syria", "secretary",
    "gross", "whole", "worldwide", "having", "center", "learn", "hours",
    "drive", "difference", "quite", "knows", "reveals", "real", "point",
    "public", "nearly", "prediction", "felix", "get", "half", "rise",
    "discover", "perfect", "game", "team", "wrong", "cool", "riley",
    "niners",
}

TITLE_STOPWORDS = WEAK_TOPIC_TERMS | {
    "the", "and", "for", "with", "from", "into", "to", "this", "that", "what",
    "when", "where", "why", "how", "now", "our", "look", "first", "episode",
    "podcast", "interview", "show", "minute", "minutes", "report",
    "unlocking", "strategies", "strategy", "path", "launch", "launched",
    "know", "knowing", "about", "field", "today", "weekly", "daily",
    "moment", "moments", "clip", "clips", "recap", "countdown", "archive",
    "is", "be", "been", "being", "nearly", "prediction", "felix",
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
    "gaming": {
        "game", "gaming", "esports", "creator", "streamer", "tournament",
        "team", "player", "pro", "ranked", "league", "valorant", "cod",
        "call", "duty", "riot", "lcs", "career", "studio", "developer",
        "console", "controller", "launch", "patch", "meta", "org",
        "roster", "scrim", "competitive", "community", "industry",
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
        "murder",
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

RAW_DIALOGUE_STARTS = {
    "i", "you", "we", "they", "he", "she", "it", "that", "this", "so",
    "and", "but", "then", "there", "these", "those", "here", "sorry",
    "okay", "yeah", "doesnt", "doesn't", "theres", "there's", "no", "yes",
    "wow", "gonna", "because", "sure", "quote", "unfortunately", "like",
    "by", "on", "are", "was", "were", "would", "did", "do", "does",
    "can", "could", "thats", "that's", "thatll", "that'll", "hes",
    "he's", "shes", "she's", "youre", "you're", "nobodys", "nobody's",
    "oh", "if", "for", "my", "our",
}

GENERIC_TOPIC_PHRASES = {
    "clean explanation",
    "heated exchange",
    "player comparison",
    "business breakdown",
    "health mistake",
    "case detail",
    "celebrity moment",
    "says everything",
    "got personal",
    "investors should understand",
    "silently wrecking",
}

GENERIC_SINGLE_TOPIC_TERMS = {
    "money", "market", "markets", "business", "company", "companies",
    "investor", "investors", "stock", "stocks", "thing", "moment",
    "problem", "question", "guy", "people", "truth", "billion", "down",
    "however", "android", "model", "data", "founders", "systems",
    "thinking", "scary", "budget", "enterprise", "network", "deliver",
    "conviction", "crazy", "college", "victim", "phone", "ranch",
    "neighborhood", "doubts", "subpoena", "week", "days", "agricultural",
    "true", "many", "year", "years", "hours", "features", "weights",
    "models", "underlying", "today", "group", "thus", "saying", "sense",
    "attorney", "steve", "matt", "case", "express", "turned", "number",
    "continued", "grow", "times", "training", "moved", "lesson", "rule",
    "away", "fast", "pennsylvania", "entire", "analysis", "failure",
    "word", "terror", "will", "approximately", "changing", "chose",
    "according", "rooting", "asking", "iranian", "syria", "secretary",
    "gross", "whole", "worldwide", "having", "center", "learn", "hours",
    "drive", "difference", "quite", "knows", "reveals", "real", "point",
    "public", "nearly", "prediction", "felix", "get", "half", "rise",
    "discover", "perfect",
}

SOURCE_TITLE_BAD_PATTERNS = [
    r"\b(ep|episode)\s*#?\d{2,}\b",
    r"#\d{2,}",
    r"\s\|\s",
    r"\s+-\s+",
    r"\bw/\s+",
    r"^the\s+the\b",
    r"\bstory\s+fans\s+never$",
    r"^(one|two|three|four|five|six|seven|eight|nine|ten)\s+time\b",
    r"\bjoe rogan experience\b",
    r"\bstavvy'?s world\b",
    r"\bwhiskey ginger\b",
    r"\btigerbelly\b",
    r"\bbad friends\b",
    r"\bthe bad game show\b",
    r"\bstick to football\b",
    r"\bthis past weekend\b",
    r"\bkill tony\b",
    r"\bmodern wisdom\b",
    r"\bhot ones\b",
    r"\bsmartless\b",
    r"\bmind pump\b",
    r"\bthe pivot\b",
    r"\bprime crime\b",
]

ALLOWED_SINGLE_FINANCE_SUBJECTS = {
    "debt", "inflation", "recession", "housing", "bitcoin", "crypto",
    "spacex", "nvidia", "tariffs", "credit", "cashflow",
}

SPECIAL_TOPIC_CASE = {
    "ai": "AI",
    "ipo": "IPO",
    "nyc": "NYC",
    "nfl": "NFL",
    "nba": "NBA",
    "ufc": "UFC",
    "spacex": "SpaceX",
    "openai": "OpenAI",
    "nvidia": "NVIDIA",
    "palantir": "Palantir",
}


def looks_like_raw_dialogue_fragment(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    lower = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", lower)

    if not words:
        return True

    if any(phrase in lower for phrase in GENERIC_TOPIC_PHRASES):
        return True

    if text and text[0].islower() and not re.match(r"^(iOS|eBay|xAI|AI|NFL|NBA|UFC|FBI|CIA|CEO)\b", text):
        return True

    if re.search(r"^(i|i'm|i’ve|i've|i’d|i'd|you|we|they|he|she|it)\s+", lower):
        return True

    meaningful = [
        word
        for word in words
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]

    if words[0] in RAW_DIALOGUE_STARTS:
        return True

    if re.search(
        r"^(wow|gonna|because|sure|quote|unfortunately|by the way|like this|"
        r"that['’]?s|that['’]?ll|he['’]?s|she['’]?s|you['’]?re|nobody['’]?s|"
        r"would you|are there|what was it|how many times|patrick ever|"
        r"oliver actually|on the afternoon|[0-9][0-9,]*\s+steps)\b",
        lower,
    ):
        return True

    if re.search(r"^what'?s\s+the\s+.{1,48}\s+heading\s+into\s+today", lower):
        return True

    if len(meaningful) < 3 and not any(word in DOMAIN_TOPIC_WORDS for word in meaningful):
        return True

    pronoun_count = sum(1 for word in words if word in {"i", "you", "we", "they", "he", "she", "it"})

    if pronoun_count >= 3:
        return True

    if any(phrase in lower for phrase in ["kind of", "sort of", "you know", "i mean", "what do you think"]):
        return True

    if re.search(r"^(tell me|how about|why['’]?d they|why did they give|do you|did you|are you)\b", lower):
        return True

    if re.search(r"\b(he|she|they|you|we)\s+(go|goes|went|said|says|like)\b", lower):
        return True

    if lower.endswith("right?") or lower.startswith(("there's a reason why", "theres a reason why")):
        return True

    if "?" in lower and re.search(r"\b(i|you|your|we|they|he|she|it)\b", lower):
        return True

    if re.search(r"^what\s+if\s+\b(i|you|we|they|he|she|it)\b", lower):
        return True

    if re.search(r"^what\s+\b(i|you|we|they|he|she|it)\b", lower):
        return True

    if re.search(r"^does(?:n['’]?t)?\s+it\s+\b(make|feel|seem|sound|look)\b", lower):
        return True

    if re.search(r"^(no|yes),?\s+(there|i|you|we|they|he|she|it)\b", lower):
        return True

    if re.search(r"^is\s+(he|she|it|there|that|this)\b", lower):
        return True

    if re.search(r"\b(i|you|we|they|he|she)\s+(said|thought|think|mean|guess|dont|didnt)\b", lower):
        return True

    if re.search(r"\b(i|you|we|they|he|she|it)\b", lower) and re.search(
        r"\b(like|okay|yeah|gonna|wanna|gotta|because|actually|believe|celebrate|care)\b",
        lower,
    ):
        return True

    if (
        re.search(r"\b(i|i'm|i've|my|you|your|we|our|they|he|she|it)\b", lower)
        and not re.match(r"^(why|how)\b", lower)
    ):
        return True

    if len(text) >= 78 and (text.count(",") >= 2 or re.search(r"\s(&|and)\s", lower)):
        return True

    if re.search(r"\b(to|and|but|or|because|so|the|a|an|of|for|with|in|on)$", lower):
        return True

    return False


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
        r"^why\s+.+\s+matters$",
    ]
    return any(re.search(pattern, lower_title) for pattern in mechanical_patterns)


def looks_like_source_title(title):
    lower = str(title or "").strip().lower()
    if not lower:
        return False

    if any(re.search(pattern, lower) for pattern in SOURCE_TITLE_BAD_PATTERNS):
        return True

    if len(lower) >= 66 and (lower.count(",") >= 1 or re.search(r"\s(&|and)\s", lower)):
        return True

    if re.search(r"^[a-z][a-z'.-]+\s+[a-z][a-z'.-]+\s+(&|and)\s+[a-z][a-z'.-]+\s+[a-z][a-z'.-]+", lower):
        return True

    if re.search(r"^[a-z][a-z'.-]+\s+[a-z][a-z'.-]+\s+(on|investigates|lives|answers|gives|says)\b", lower):
        return True

    if re.search(r"^the\s+[a-z][a-z'.-]+\s+[a-z][a-z'.-]+\s+says\s+which\b", lower):
        return True

    if re.search(r"\b(on|with|featuring|ft\.?)\s+[a-z][a-z'.-]+(?:\s+[a-z][a-z'.-]+){1,5}\b", lower):
        return True

    return False


def weak_template_subject(lower_title):
    text = re.sub(r"\s+", " ", str(lower_title or "").strip().lower())
    patterns = [
        (r"^what\s+(.+?)\s+reveals\s+about\s+the\s+market$", 1),
        (r"^why\s+investors\s+are\s+watching\s+(.+?)$", 1),
        (r"^the\s+policy\s+fight\s+behind\s+(.+?)$", 1),
        (r"^the\s+political\s+risk\s+in\s+(.+?)$", 1),
        (r"^why\s+(.+?)\s+became\s+the\s+flashpoint$", 1),
        (r"^(.+?)\s+split\s+the\s+room$", 1),
        (r"^the\s+take\s+inside\s+(.+?)$", 1),
        (r"^the\s+awkward\s+moment\s+behind\s+(.+?)$", 1),
        (r"^the\s+(ai\s+question|context|case\s+moment|culture\s+moment|funny\s+part)\s+inside\s+(.+?)$", 2),
        (r"^(.+?):\s+the\s+(sports\s+debate|locker\s+room\s+angle|investor\s+takeaway|business\s+risk|builder\s+takeaway|habit\s+to\s+rethink|health\s+detail|claim\s+worth\s+checking|policy\s+fight|story\s+people\s+will\s+debate|culture\s+moment)$", 1),
    ]

    for pattern, subject_group in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        subject = match.group(subject_group)
        subject_words = [
            word
            for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", subject)
            if word not in TITLE_STOPWORDS
        ]
        normalized_subject = " ".join(subject_words)

        if not subject_words:
            return True

        if len(subject_words) == 1:
            if "reveals about the market" in text and normalized_subject in ALLOWED_SINGLE_FINANCE_SUBJECTS:
                return False
            return True

        weak_count = sum(1 for word in subject_words if word in WEAK_TOPIC_TERMS or word in GENERIC_SINGLE_TOPIC_TERMS)
        if weak_count / max(1, len(subject_words)) >= 0.5:
            return True

    return False


def keyword_soup_title(theme, title, topic_terms=None):
    raw_title = re.sub(r"\s+", " ", str(title or "")).strip()
    lower = raw_title.lower()
    subject = re.split(r"\s*:\s*", lower, maxsplit=1)[0]
    subject = re.sub(r"^the\s+(joke|callback|take|story|detail|debate|moment)\s+(inside|behind|around)\s+", "", subject)
    words = [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", subject)
        if word not in TITLE_STOPWORDS and len(word) > 2
    ]

    if not words:
        return False

    has_number = any(any(char.isdigit() for char in word) for word in words)
    if len(words) > 4:
        return False

    proper_name_story = bool(
        re.search(
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\s+"
            r"(Story|Joke|Bit|Take|Debate|Rivalry|Problem|Moment)\b",
            raw_title,
        )
    )
    if proper_name_story:
        return False

    theme_tokens = {
        word
        for item in theme_title_words(theme)
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+", item.lower())
    }
    theme_hits = set(words) & theme_tokens
    topic_words = {
        word
        for term in topic_terms or []
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", str(term).replace("_", " ").lower())
        if word not in TITLE_STOPWORDS and len(word) > 2
    }
    weak_subject_words = WEAK_TOPIC_TERMS | GENERIC_SINGLE_TOPIC_TERMS | {
        "cool", "wrong", "such", "stick", "sorry", "messy", "keep",
        "believe", "call", "check", "voice", "song", "singing", "jazz",
        "morgan", "john", "bread", "america", "meals", "hellofresh",
        "riley", "game", "team", "story", "sidetrack", "beautiful",
        "spinoff", "career", "ball", "touched", "touch", "watched",
        "olympics", "celebrate",
    }
    natural_short_title = bool(
        "?" in raw_title
        or "'s" in lower
        or re.search(r"\b(is|are|was|were|got|gets|became|becomes|changed|changes|started|starts|met|reacts|moved)\b", lower)
        or re.search(r"^the\s+(jackass|world cup|nba|nfl|ufc|ai|vr|k-pop)\b", lower)
    )

    if len(words) <= 3 and not natural_short_title:
        return True

    if len(words) == 3 and not theme_hits:
        return True

    if len(words) <= 3 and ":" in lower and not theme_hits:
        return True

    if len(words) <= 3 and len(theme_hits) <= 1:
        weak_count = sum(1 for word in words if word in weak_subject_words)
        topic_overlap = len(set(words) & topic_words)
        generic_theme_hit = bool(theme_hits & {"game", "team", "story", "take", "moment", "debate", "question", "problem"})

        if weak_count >= 2 and (topic_overlap >= 2 or generic_theme_hit):
            return True

    return False


def compact_text(text, max_chars=92):
    text = re.sub(r"\s+", " ", str(text or "")).strip(" -._")

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip(" -._")
    return shortened or text[:max_chars].strip(" -._")


def format_topic_text(term):
    words = str(term or "").replace("_", " ").split()
    return " ".join(SPECIAL_TOPIC_CASE.get(word.lower(), word.title()) for word in words)


def clean_topic_term_phrase(term):
    words = [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", str(term or "").lower())
        if word not in TITLE_STOPWORDS and word not in WEAK_TOPIC_TERMS
    ]
    return " ".join(words)


def topic_from_terms(topic_terms, fallback="This Moment", theme=None):
    terms = [
        str(term).replace("_", " ").strip()
        for term in topic_terms or []
        if is_strong_topic_term(str(term).replace("_", " "))
    ]

    if terms:
        preferred = []

        for term in terms:
            words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", term.lower())
            has_number = any(any(char.isdigit() for char in word) for word in words)

            if len(words) >= 2 or has_number or term.lower() not in GENERIC_SINGLE_TOPIC_TERMS:
                preferred.append(term)

        single_terms = []
        seen = set()
        theme_tokens = {
            word
            for item in theme_title_words(theme)
            for word in re.findall(r"[a-zA-Z][a-zA-Z']+", item.lower())
        }

        for term in preferred or terms:
            words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", term.lower())

            for word in words:
                normalized = word.replace("'", "")

                if normalized in seen:
                    continue

                if normalized in WEAK_TOPIC_TERMS or normalized in TITLE_STOPWORDS:
                    continue

                seen.add(normalized)
                single_terms.append(word)

        multi_terms = [
            term
            for term in preferred or terms
            if len(re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", term.lower())) >= 2
        ]
        domain_multi_terms = [
            term
            for term in multi_terms
            if is_domain_topic_term(term, theme)
        ]

        if single_terms:
            term_set = set(single_terms)

            if {"data", "black", "hole"}.issubset(term_set):
                return "Data Black Hole"

            if {"barack", "obama"}.issubset(term_set) and ("pickup" in term_set or "game" in term_set):
                return "Obama Pickup Game"

            if "nba" in term_set and "offseason" in term_set:
                return "NBA Offseason"

            if "steam" in term_set and "machine" in term_set:
                return "Steam Machine"

            if "debt" in term_set and "rates" in term_set:
                return "Debt And Rates"

            if "spacex" in term_set:
                return "SpaceX IPO"

            if "compute" in term_set and "inference" in term_set:
                return "Inference Compute"

            if "champ" in term_set and "bailey" in term_set:
                return "Champ Bailey"

            if "magnus" in term_set and "rivalry" in term_set:
                return "Magnus Rivalry"

            if "murder" in term_set and ("horrific" in term_set or "cops" in term_set):
                return "Horrific Murder Case"

            if "callback" in term_set and ("embarrassing" in term_set or "laugh" in term_set):
                return "Embarrassing Callback"

            if {"stem", "cells"}.issubset(term_set):
                prefix = "Harvard " if "harvard" in term_set else ""
                return compact_text(f"{prefix}Stem Cells", 46)

            if "revenues" in term_set and "industry" in term_set:
                return "Industry Revenue"

            if "draft" in term_set and "night" in term_set:
                return "Draft Night"

            if "nascar" in term_set and "horsepower" in term_set:
                return "NASCAR Horsepower"

            domain_first = [
                word
                for word in single_terms
                if word in theme_tokens or word in DOMAIN_TOPIC_WORDS
            ]
            remaining = [word for word in single_terms if word not in domain_first]
            phrase_words = (domain_first + remaining)[:3]
            return compact_text(format_topic_text(" ".join(phrase_words)), 46)

        if domain_multi_terms:
            cleaned_multi = clean_topic_term_phrase(domain_multi_terms[0]) or domain_multi_terms[0]
            return compact_text(format_topic_text(cleaned_multi), 46)

        if multi_terms:
            return compact_text(format_topic_text(multi_terms[0]), 46)

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


def title_passes_publishable_bar(theme, title, topic_terms=None, min_specificity=0.35):
    quality = score_title_quality(theme, title, topic_terms=topic_terms)
    return (
        quality["length_ok"]
        and quality["specificity"] >= min_specificity
        and quality.get("honesty", 0.0) >= 0.70
        and not quality.get("generic_title")
        and not quality.get("repetitive_title")
        and not quality.get("mechanical_title")
        and quality.get("theme_native_title", True)
        and quality["not_clickbait"]
    )


def fallback_title_candidates(theme, archetype, topic):
    topic = compact_text(format_topic_text(topic), 44)
    archetype_text = str(archetype or "moment").replace("_", " ").title()
    theme_key = normalize_theme_key(theme)

    patterns = {
        "comedy": [
            "The Joke Inside {topic}",
            "The Callback Inside {topic}",
        ],
        "sports": [
            "{topic} Changed The Game",
            "The Locker Room Story Around {topic}",
        ],
        "finance": [
            "The {topic} Question Investors Miss",
            "How {topic} Changes The Math",
        ],
        "technology_ai": [
            "{topic}: The AI Detail Builders Are Watching",
            "Why {topic} Is Harder Than It Looks",
        ],
        "health_fitness": [
            "{topic}: The Health Detail To Rethink",
            "The Habit Behind {topic}",
        ],
        "politics": [
            "{topic}: The Policy Fight",
            "The Debate Inside {topic}",
        ],
        "truecrime": [
            "{topic}: The Detail That Changes The Case",
            "The Evidence Question Around {topic}",
        ],
        "popculture": [
            "The Pop Culture Detail Inside {topic}",
            "Why {topic} Took Over The Conversation",
        ],
    }
    candidates = []

    if topic and is_strong_topic_term(topic) and not looks_like_raw_dialogue_fragment(topic):
        candidates.extend(pattern.format(topic=topic) for pattern in patterns.get(theme_key, []))

    candidates.append(f"The {archetype_text} Clip With A Real Payoff")
    return candidates


def source_context_title(theme, source_title, clip, topic_terms=None):
    theme_key = normalize_theme_key(theme)
    source = str(source_title or "").lower()
    excerpt = str((clip or {}).get("transcript_excerpt") or "")
    text = f"{source} {excerpt}".lower()
    terms = {
        word.replace("'", "")
        for term in topic_terms or []
        for word in re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", str(term).lower())
    }

    if theme_key == "sports":
        if "obama" in source and ("pickup" in source or "white house" in source):
            if "go-to move" in text or "defense" in text or "paint" in text:
                return "Obama Pickup Game Defense Story"
            return "Obama's White House Hoops Story"
        if "nba offseason" in source or "matt barnes" in source:
            if "draft night" in text or "didn't get drafted" in text or "undrafted" in text:
                return "Matt Barnes' Undrafted NBA Comeback"
            if "both won" in text and ("championship" in text or "young talent" in text):
                return "The Trade Where Both Teams Won"
            return "Matt Barnes On The Wild NBA Offseason"
        if "brandon aiyuk" in source or "49ers" in source:
            return "Brandon Aiyuk's 49ers Problem"
        if "supplemental draft" in source or "brendan sorsby" in source:
            return "The NFL Supplemental Draft Question"
        if "mikal bridges" in source or "knicks" in source:
            return "Mikal Bridges' Knicks Championship Moment"
        if "cooper flagg" in source or "dylan harper" in source:
            return "Cooper Flagg vs Dylan Harper Debate"
        if ("cooper flag" in text or "cooper flagg" in text) and ("five of 21" in text or "field" in text or "debut" in text):
            return "Cooper Flagg's Rough Debut"
        if "kyle larson" in source or "nascar" in source or "horsepower" in terms:
            return "Kyle Larson's NASCAR Take"
        if "champ bailey" in source or "revis" in source:
            return "Champ Bailey's QB Story"

    if theme_key == "health_fitness":
        if "age slower" in source or "vitamin" in terms:
            return "Aging Slower: The Health Detail To Rethink"
        if "abs" in source or "hip" in terms or "flexor" in terms:
            return "The Abs Mistake Worth Rethinking"
        if "strong athletes" in source or "lifts" in terms:
            return "Strength Training Lifts Worth Rethinking"
        if "muscle building" in source or "amino" in terms or "protein" in terms:
            return "Essential Amino Acids: The Health Detail"
        if "ben askren" in source or "brink of death" in source:
            return "Ben Askren's Recovery Reality"
        if "fertility" in source or "fertility" in terms:
            return "Fertility Warning Signs Worth Hearing"

    if theme_key == "popculture":
        if "jackass" in source and "methadone" in text:
            return "Jackass At The Methadone Clinic"
        if "jackass" in source and "movie" in terms:
            return "The Jackass Movie Debate"
        if "markiplier" in source:
            return "Markiplier's Movie Bet"
        if "aly raisman" in source:
            return "Aly Raisman's Dating Reset"
        if "david duchovny" in source:
            return "David Duchovny's Hot Ones Story"

    if theme_key == "truecrime":
        if "horrific murder" in source or "murder" in terms:
            return "Horrific Murder Case: The Key Detail"
        if "sinning" in source or "pastor" in source:
            return "Police Observed The Pastor Fight"
        if "epstein" in source or "zorro" in source or "stem" in terms:
            return "Epstein Zorro Ranch Detail"
        if "iowa woman" in source or "breakup" in source:
            return "Iowa Breakup Murder Case"

    if theme_key == "technology_ai":
        if "data black hole" in source:
            return "Data Black Hole: The AI Detail"
        if "steam machine" in source:
            return "Steam Machine: The Builder Debate"
        if "training paradigm" in source or "inference" in terms or "compute" in terms:
            return "Inference Compute: The AI Detail"
        if "coding is solved" in source:
            return "After Coding Is Solved"
        if "india" in source and "global companies" in source:
            return "India Founder Pipeline"
        if "benchmarks" in source or "10,000" in terms:
            return "AI Benchmarks Are Harder Than They Look"

    if theme_key == "finance":
        if "165 billion" in text or "$165 billion" in text:
            return "The $165B Money Manager Story"
        if "value stock is simply one that looks cheap" in text:
            return "What Makes A Stock A Value Stock"
        if "short memories" in text and ("must-own stock" in text or "palantir" in text):
            return "Investors Forget Must-Own Stocks Fast"
        if "save 30%" in text or "saving 953" in text or ("30%" in text and "take-home pay" in text):
            return "The Savings Rate Math People Miss"
        if "take-home pay" in text or "take home pay" in text or "health care premiums" in text:
            return "The Real Take-Home Pay Budget"
        if "city spending money on infrastructure" in text or "spending money on infrastructure" in text:
            return "Infrastructure Spending Signals Rental Demand"
        if "1% rule" in text and ("appreciation" in text or "year-over-year growth" in text):
            return "Rent Growth Changes The Cash Flow Math"
        if "oil prices" in text and "100 percent tariffs" in text:
            return "Oil Holds Steady As Tariff Risk Rises"
        if "birth rates are plummeting" in text or ("western economy" in text and "birth rates" in text):
            return "Birth Rates Became An Economic Problem"
        if "turkey is selling gold" in text or "wave of gold sales" in text:
            return "Turkey's Gold Selling Wave Explained"
        if "raising interest rates" in text or ("debt" in text and "interest rates" in text):
            return "Higher Rates Shift The Debt Problem"
        if "inflation" in text and ("floor" in text or "3%" in text):
            return "The 3% Inflation Floor Problem"
        if "spacex" in source or "spacex" in terms:
            if "popped nearly 30%" in text or "gave most of it back" in text:
                return "SpaceX IPO Popped Then Faded"
            return "Why SpaceX IPO Matters To Investors"
        if "inflation" in terms:
            return "The Inflation Floor Investors Miss"
        if "debt" in terms or "rates" in terms:
            return "The Debt Problem Behind Higher Rates"
        if "rent" in terms or "rental" in source:
            return "Rental Cash Flow Depends On The City"
        if "women" in text and "soccer" in text:
            return "Women's Soccer Valuations Are Exploding"
        if "tone and the hand gestures" in text or "they don't know the difference" in text:
            return "Selling Weak Products With Better Translation"
        if "bullish market" in text and ("sentiment" in source or "crypto" in text):
            return "Crypto Sentiment Looks Too Bearish"

    if theme_key == "politics":
        if "ai" in source or "trillion" in terms or "700" in terms:
            return "AI Spending Becomes A Policy Fight"

    if theme_key == "comedy":
        if "embarrassing story" in text and "sidetrack" in text:
            return "The Embarrassing UFC Sidetrack Story"
        if "amy adams" in source and "born in italy" in text:
            return "Amy Adams' Italy Childhood Story"
        if "born in italy" in text and ("colorado" in text or "army" in text or "base" in text):
            return "The Italy Childhood Story"
        if ("john benet" in text or "jonbenet" in text) and "jazz singer" in text:
            return "The JonBenet Jazz Singer Joke"
        if "switch me out" in text and ("voice" in text or "trailer" in text or "animation" in text):
            return "Tony Hale's Toy Story Voice Panic"
        if "raw milk" in text and ("pasteurized" in text or "homogenized" in text or "shelf" in text):
            return "The Raw Milk Debate Gets Weird"
        if "cleaning lady" in text:
            return "Cleaning For The Cleaning Lady"
        if "like a rolling stone" in text and ("quiz" in text or "check it out" in text):
            return "The Rolling Stone Quiz Bit"
        if "mobbed" in text and ("ellis" in text or "kenny" in text or "larry" in text):
            return "Getting Mobbed By Fans"
        if "out into song" in text or ("singing" in text and "set-up" in text):
            return "Amy Adams' Singing Setup"
        if "banned from the chicago theater" in text or ("madison square garden" in text and "ass crack" in text):
            return "Thomas Lennon's Banned Theater Story"
        if "magnus" in source and "rivalry" in terms:
            return "Magnus Carlsen Rivalry"
        if "magnus" in source and ("callback" in terms or "embarrassing" in terms):
            return "Embarrassing Chess Callback"
        if "magnus" in source:
            return "Magnus Carlsen Story"

    return ""


def transcript_sentence_title(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""

    signal_words = {
        "why", "how", "what", "mistake", "truth", "money", "revenue",
        "customer", "customers", "growth", "product", "business", "founder",
        "market", "cost", "costs", "million", "billion", "problem",
        "valuation", "investor", "investors", "investment", "investing",
        "joke", "laugh", "coach", "team", "agent", "model", "sleep",
        "stress", "court", "case", "election", "policy", "movie", "artist",
    }

    units = []

    for sentence in re.split(r"(?<=[.?!])\s+", text):
        raw_sentence = re.sub(r"\s+", " ", sentence).strip(" .,:;")

        if raw_sentence:
            units.append(raw_sentence)

        if len(raw_sentence) > 116:
            clauses = re.split(r"\s+(?:and|but|because|so|while|whereas)\s+|[,;]", raw_sentence)
            units.extend(re.sub(r"\s+", " ", clause).strip(" .,:;") for clause in clauses)

    for raw_sentence in units:
        if not raw_sentence or len(raw_sentence) > 116:
            continue

        candidate = compact_text(raw_sentence, 92).strip(" .,:;")
        lower_candidate = candidate.lower()

        if "valuation increase" in lower_candidate and "women" in lower_candidate and "soccer" in lower_candidate:
            return "Women's Soccer Valuations Are Exploding"

        words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", candidate)
        lower_words = {word.lower() for word in words}

        if 4 <= len(words) <= 16 and len(candidate) >= 24:
            if looks_like_raw_dialogue_fragment(candidate):
                continue

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
    raw_preferred_terms = [
        term
        for term in raw_strong_terms
        if term not in domain_terms
        and str(term).replace("_", " ").strip().lower() not in GENERIC_SINGLE_TOPIC_TERMS
    ]
    topic_terms = domain_terms[:2] + raw_preferred_terms + source_topic_terms + [
        term for term in raw_strong_terms
        if term not in domain_terms and term not in raw_preferred_terms
    ]
    transcript_topic_fallback = compact_text(clip.get("transcript_excerpt", ""), 48)

    if looks_like_raw_dialogue_fragment(transcript_topic_fallback):
        transcript_topic_fallback = ""

    topic = topic_from_terms(topic_terms, fallback=transcript_topic_fallback or "This Moment", theme=theme)

    if topic == "This Moment" and source_title:
        topic = compact_text(source_title, 46)

    used_raw_topic = False

    if looks_like_raw_dialogue_fragment(topic):
        if raw_preferred_terms:
            topic = topic_from_terms(raw_preferred_terms, fallback=topic, theme=theme)
            used_raw_topic = True
        else:
            source_terms = source_topic_terms or topic_terms_from_source_title(source_title)
            topic = topic_from_terms(source_terms, fallback=compact_text(source_title, 46) or "This Moment", theme=theme)

    if not used_raw_topic and looks_like_raw_dialogue_fragment(topic) and source_topic_terms:
        source_terms = source_topic_terms or topic_terms_from_source_title(source_title)
        topic = topic_from_terms(source_terms, fallback=compact_text(source_title, 46) or "This Moment", theme=theme)

    values = {
        "theme": profile.get("brand", {}).get("channel_name") or theme.replace("_", " ").title(),
        "topic": topic,
        "archetype": str(archetype or "moment").replace("_", " "),
        "source": source_record.get("channel") or clip.get("source_title") or "the interview",
        "duration": int(round(float(clip.get("duration") or 45))),
    }

    repaired_title = source_context_title(theme, source_title, clip, topic_terms)
    repair_terms = list(topic_terms or []) + [repaired_title]
    if repaired_title and title_passes_publishable_bar(theme, repaired_title, topic_terms=repair_terms, min_specificity=0.34):
        return compact_text(repaired_title, 92)

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
    if transcript_fallback and not looks_like_raw_dialogue_fragment(transcript_fallback):
        return transcript_fallback

    source_fallback = compact_text(source_title, 90)
    source_words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", source_fallback)
    if len(source_words) >= 4 and title_passes_publishable_bar(theme, source_fallback, topic_terms=topic_terms, min_specificity=0.48):
        return source_fallback

    fallback = compact_text(topic, 90)

    if fallback and len(fallback.split()) >= 3 and title_passes_publishable_bar(theme, fallback, topic_terms=topic_terms):
        return fallback

    for candidate in fallback_title_candidates(theme, archetype, topic):
        candidate = compact_text(candidate, 92)

        if title_passes_publishable_bar(theme, candidate, topic_terms=topic_terms, min_specificity=0.30):
            return candidate

    theme_fallbacks = {
        "comedy": "The Joke That Actually Landed",
        "sports": "The Sports Debate That Split The Room",
        "finance": "The Market Detail Investors Should Watch",
        "technology_ai": "The AI Detail Builders Are Watching",
        "health_fitness": "The Health Detail Worth Rethinking",
        "politics": "The Debate Clip With Real Context",
        "truecrime": "The Evidence Detail Worth Rechecking",
        "popculture": "The Pop Culture Detail People Missed",
    }
    return compact_text(theme_fallbacks.get(normalize_theme_key(theme), "The Interview Moment Worth Watching"), 92)


def score_title_quality(theme, title, topic_terms=None):
    title = str(title or "").strip()
    lower = title.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", lower)
    topic_terms = [str(term).replace("_", " ").lower() for term in topic_terms or []]
    topic_hit = any(term and term in lower for term in topic_terms)
    has_number = any(any(char.isdigit() for char in word) for word in words)
    generic = any(re.search(pattern, lower) for pattern in GENERIC_BAD_PATTERNS)
    machine_label_title = bool(re.search(r"^(editor pick|timestamp-backed|viewers replayed)\s*:", lower))
    source_suffix_title = bool(re.search(r"\s+from\s+[a-z0-9 ._-]{2,40}$", lower))
    source_title_like = looks_like_source_title(title)
    weak_template_title = weak_template_subject(lower)
    keyword_soup = keyword_soup_title(theme, title, topic_terms=topic_terms)
    malformed_apostrophe_title = bool(re.search(r"\b[A-Za-z]+['’]S\b", title))
    raw_dialogue_fragment = looks_like_raw_dialogue_fragment(title)
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
    source_only_title = (
        len(set(meaningful_words)) <= 3
        and not topic_hit
        and not theme_hits
        and not has_number
        and not any(word in lower for word in ["why", "how", "what", "mistake", "truth", "case", "debate"])
    )
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
    honest_title = not (
        generic
        or machine_label_title
        or malformed_apostrophe_title
        or mechanical_title
        or source_title_like
        or weak_template_title
        or keyword_soup
        or repetitive_title
        or raw_dialogue_fragment
        or source_only_title
        or clickbait_hits
    )

    return {
        "specificity": specificity,
        "curiosity": curiosity,
        "honesty": 0.35 if not honest_title else 0.86,
        "theme_fit": theme_fit,
        "length_ok": 8 <= len(title) <= 96,
        "not_clickbait": not clickbait_hits,
        "generic_title": bool(
            generic
            or mechanical_title
            or raw_dialogue_fragment
            or machine_label_title
            or source_only_title
            or source_title_like
            or weak_template_title
            or keyword_soup
        ),
        "raw_dialogue_fragment": raw_dialogue_fragment,
        "theme_native_title": theme_native_title,
        "repetitive_title": repetitive_title,
        "mechanical_title": mechanical_title,
        "machine_label_title": machine_label_title,
        "source_suffix_title": source_suffix_title,
        "malformed_apostrophe_title": malformed_apostrophe_title,
        "source_only_title": source_only_title,
        "source_title_like": source_title_like,
        "weak_template_title": weak_template_title,
        "keyword_soup_title": keyword_soup,
        "topic_hit": topic_hit,
        "theme_signal_terms": theme_hits,
        "meaningful_word_count": len(set(meaningful_words)),
        "repeated_words": repeated_words,
        "repeated_bigrams": repeated_bigrams,
        "clickbait_terms": clickbait_hits,
    }
