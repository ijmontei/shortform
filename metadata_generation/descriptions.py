import re

from theme_profile import load_theme_profile


def compact_text(text, max_chars=320):
    text = re.sub(r"\s+", " ", str(text or "")).strip()

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip()
    return shortened or text[:max_chars].strip()


def generate_description(theme, clip, source_record=None, transformation_notes=None):
    profile = load_theme_profile(theme)
    source_record = source_record or {}
    transformation_notes = transformation_notes or []
    source_title = source_record.get("title") or clip.get("source_title") or "the original interview"
    channel = source_record.get("channel") or ""
    topic = clip.get("suggested_title") or clip.get("hook_reason") or "a high-signal moment"
    value_add = transformation_notes[:3] or [
        "curated for standalone context",
        "ranked for viewer retention",
        "packaged with source attribution",
    ]
    description = (
        f"{profile.get('brand', {}).get('channel_name') or theme.replace('_', ' ').title()} "
        f"curates {compact_text(topic, 90)} from {compact_text(source_title, 120)}."
    )

    if channel:
        description += f" Source channel: {channel}."

    description += f" Editorial value added: {', '.join(value_add)}."
    return compact_text(description, 480)
