import re

from theme_profile import theme_hashtags, theme_topic_tags


def normalize_hashtag(value):
    value = str(value or "").strip()

    if not value:
        return ""

    if not value.startswith("#"):
        value = f"#{value}"

    value = "#" + re.sub(r"[^a-zA-Z0-9_]", "", value[1:])
    return value[:40]


def generate_hashtags(theme, archetype="", topic_terms=None, limit=8):
    tags = []
    topic_lookup = theme_topic_tags(theme)

    for term in topic_terms or []:
        normalized = str(term).replace("_", " ").lower().strip()
        tag = topic_lookup.get(normalized) or topic_lookup.get(normalized.split(" ")[0])

        if not tag and normalized:
            tag = "#" + re.sub(r"[^a-zA-Z0-9_]", "", normalized.title().replace(" ", ""))

        tag = normalize_hashtag(tag)

        if tag and tag.lower() not in [existing.lower() for existing in tags]:
            tags.append(tag)

        if len(tags) >= 3:
            break

    if archetype:
        archetype_tag = normalize_hashtag(str(archetype).replace("_", " "))

        if archetype_tag and archetype_tag.lower() not in [existing.lower() for existing in tags]:
            tags.append(archetype_tag)

    for fallback in theme_hashtags(theme):
        tag = normalize_hashtag(fallback)

        if tag and tag.lower() not in [existing.lower() for existing in tags]:
            tags.append(tag)

        if len(tags) >= limit:
            break

    return tags[:limit]
