import importlib

from theme_profile import load_theme_profile


def _module_names(theme_name, profile_name):
    names = []

    for value in [theme_name, profile_name, "generic"]:
        value = (value or "generic").replace("-", "_")

        if value and value not in names:
            names.append(value)

    return names


def score_theme_signals(theme_name, text, segments, audio_path, clip_start, clip_end, metadata=None):
    metadata = metadata or {}
    profile = metadata.get("theme_profile") or load_theme_profile(theme_name)
    profile_name = profile.get("profile", "generic")
    metadata = {**metadata, "theme_profile": profile}

    for module_name in _module_names(theme_name, profile_name):
        try:
            module = importlib.import_module(f"theme_signals.{module_name}")
        except ModuleNotFoundError:
            continue

        if hasattr(module, "score_theme_signals"):
            return module.score_theme_signals(
                text=text,
                segments=segments,
                audio_path=audio_path,
                clip_start=clip_start,
                clip_end=clip_end,
                metadata=metadata,
            )

    return {
        "theme_signal_score": 0.0,
        "signals": {},
        "concerns": ["no theme signal module found"],
        "archetype": "",
        "recommended_intro_mode": profile.get("packaging", {}).get("default_intro_mode", ""),
        "recommended_title_templates": profile.get("metadata_style", {}).get("title_templates", []),
    }
