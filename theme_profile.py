import copy
import os
import re

from theme_config import DEFAULT_THEME, clean_theme_name, load_json_file, theme_config_path


DEFAULT_SCORING_WEIGHTS = {
    "hook": 0.16,
    "payoff": 0.14,
    "standalone_context": 0.14,
    "theme_signal": 0.14,
    "public_popularity": 0.10,
    "captionability": 0.08,
    "visual_quality": 0.07,
    "pacing": 0.07,
    "transformation": 0.10,
}

RELAX_CONFIGURED_SOURCE_GUARD = os.getenv("SHORTFORM_RELAX_CONFIGURED_SOURCE_GUARD", "1") != "0"
STRICT_SOURCE_GUARD = os.getenv("SHORTFORM_STRICT_SOURCE_GUARD", "0") == "1"
CONFIGURED_SOURCE_TIERS = {"priority", "secondary", "legacy"}

DEFAULT_THEME_PROFILE = {
    "theme": DEFAULT_THEME,
    "profile": "generic",
    "brand": {
        "channel_name": "",
        "positioning": "Curated high-signal moments from long-form interviews.",
        "audience": "Curious YouTube Shorts viewers who want the useful part fast.",
        "viewer_promise": "The strongest ideas and moments without sitting through the full episode.",
        "voice": "sharp curator",
        "risk_tolerance": "medium",
    },
    "youtube": {
        "channel_handle": "",
        "token_file": "",
    },
    "channels": [],
    "clip_rules": {
        "candidate_durations": [20, 32, 45, 58],
        "min_clip_duration": 14,
        "max_clip_duration": 60,
        "default_clip_count": 10,
        "theme_clip_budget": 0,
        "theme_candidates_per_video": 8,
        "min_readiness_score": 0.62,
        "min_selected_score": 0.27,
        "max_topic_similarity": 0.58,
        "candidate_stride_seconds": 4,
        "allow_cold_open": True,
        "prefer_context": True,
        "prefer_fast_payoff": False,
        "prefer_practicality": False,
        "prefer_explanation": False,
    },
    "scoring_weights": DEFAULT_SCORING_WEIGHTS,
    "theme_signals": {
        "enabled": ["hook", "standalone_context", "payoff"],
        "required": [],
        "positive_keywords": [],
        "negative_keywords": [],
        "keyword_weights": {},
        "archetypes": ["clean_explanation", "surprising_reveal", "quotable_line"],
        "penalize_missing_theme_signal": True,
    },
    "packaging": {
        "intro_modes": ["context_card", "cold_open", "clip_then_takeaway"],
        "default_intro_mode": "context_card",
        "max_intro_seconds": 2.5,
        "caption_style": "clean_emphasis",
        "framing_style": "speaker_context",
        "overlay_style": "context_card",
    },
    "metadata_style": {
        "title_style": "specific_curiosity",
        "title_templates": [
            "{topic} In {duration}s",
            "The {archetype} People Miss",
            "Why {topic} Matters",
        ],
        "description_style": "source_plus_context",
        "hashtags": ["#podcast", "#shorts"],
        "tags": ["podcast clips", "interview clips", "shorts"],
        "topic_tags": {},
    },
    "risk_controls": {
        "requires_fact_check": False,
        "requires_medical_review": False,
        "requires_financial_review": False,
        "requires_claim_context": False,
        "restricted_topics": [],
        "manual_review_topics": [],
        "minimum_transformation_score": 0.55,
    },
    "review_policy": {
        "require_manual_approval_before_public": True,
        "reject_if_reused_risk_high": True,
        "reject_if_first_second_fails": True,
        "reject_if_no_clear_viewer_value": True,
    },
    "analytics": {
        "primary_metric": "engaged_view_rate",
        "secondary_metrics": [
            "average_percent_viewed",
            "likes_per_engaged_view",
            "comments_per_engaged_view",
            "subs_gained_per_1000_engaged_views",
        ],
        "review_after_hours": [2, 24, 72, 168],
        "success_thresholds": {
            "min_average_percent_viewed": 0.70,
            "min_engaged_view_rate": 0.55,
            "min_like_rate": 0.025,
        },
    },
    "experiments": {
        "enabled": True,
        "active": [],
    },
}


PROFILE_PRESETS = {
    "comedy": {
        "clip_rules": {
            "candidate_durations": [8, 12, 18, 24, 32, 45],
            "min_clip_duration": 7,
            "max_clip_duration": 50,
            "min_readiness_score": 0.68,
            "min_selected_score": 0.30,
            "max_topic_similarity": 0.52,
            "prefer_fast_payoff": True,
            "prefer_context": False,
        },
        "scoring_weights": {
            "hook": 0.20,
            "payoff": 0.24,
            "standalone_context": 0.10,
            "theme_signal": 0.22,
            "public_popularity": 0.08,
            "captionability": 0.05,
            "visual_quality": 0.07,
            "pacing": 0.04,
        },
        "theme_signals": {
            "enabled": ["laughter", "reaction", "punchline", "story_escalation"],
            "positive_keywords": [
                "funny", "joke", "laugh", "hilarious", "roast", "awkward",
                "ridiculous", "insane", "wild", "bit", "punchline",
            ],
            "keyword_weights": {
                "funny": 2.2,
                "joke": 2.2,
                "laugh": 2.0,
                "hilarious": 2.1,
                "roast": 1.9,
                "awkward": 1.7,
                "punchline": 2.2,
                "story": 1.4,
            },
            "archetypes": [
                "roast", "self_own", "wild_story", "awkward_moment",
                "guest_breaks", "host_loses_it", "callback", "argument_as_comedy",
            ],
        },
        "packaging": {
            "intro_modes": ["cold_open", "context_card", "editorial_countdown"],
            "default_intro_mode": "cold_open",
            "max_intro_seconds": 1.8,
            "caption_style": "comedy_punchline",
            "framing_style": "speaker_reaction",
            "overlay_style": "bold_arcade",
        },
        "risk_controls": {
            "minimum_transformation_score": 0.45,
        },
    },
    "finance": {
        "clip_rules": {
            "candidate_durations": [24, 35, 45, 58],
            "min_clip_duration": 18,
            "max_clip_duration": 60,
            "min_readiness_score": 0.70,
            "prefer_context": True,
            "prefer_explanation": True,
        },
        "scoring_weights": {
            "hook": 0.14,
            "payoff": 0.12,
            "standalone_context": 0.18,
            "theme_signal": 0.18,
            "public_popularity": 0.08,
            "captionability": 0.06,
            "visual_quality": 0.06,
            "pacing": 0.04,
            "transformation": 0.14,
        },
        "theme_signals": {
            "enabled": ["specific_number", "market_claim", "risk_warning", "business_breakdown"],
            "positive_keywords": [
                "cash flow", "investing", "valuation", "market", "inflation",
                "interest rate", "recession", "founder", "margin", "debt",
            ],
            "negative_keywords": [
                "democratic nominee", "republican super pac", "mike lawler",
                "dsa candidates", "wimbledon", "movie premiere", "red carpet",
            ],
            "source_guard": {
                "hard_negative_keywords": [
                    "democratic nominee", "republican super pac", "mike lawler",
                    "dsa candidates", "socialists sweep", "wimbledon",
                ],
                "negative_keywords": [
                    "movie premiere", "red carpet", "fitness protocol",
                    "murder trial", "true crime",
                ],
                "positive_keywords": [
                    "finance", "money", "market", "markets", "investing",
                    "investor", "cash flow", "valuation", "interest rate",
                    "interest rates", "rates", "fed", "inflation", "debt", "recession", "business", "economy",
                    "economic", "founder", "startup", "revenue", "profit",
                ],
                "min_positive_hits_by_tier": {
                    "priority": 1,
                    "secondary": 1,
                    "legacy": 1,
                },
                "negative_override_min_positive_hits": 2,
            },
            "keyword_weights": {
                "cash flow": 2.1,
                "valuation": 2.0,
                "recession": 2.2,
                "inflation": 2.0,
                "interest rates": 2.0,
                "margin": 1.8,
                "debt": 1.8,
            },
            "archetypes": [
                "market_warning", "investment_thesis", "business_breakdown",
                "personal_finance_mistake", "economic_explainer", "founder_lesson",
            ],
        },
        "packaging": {
            "intro_modes": ["context_card", "explain_then_clip", "clip_then_takeaway", "editorial_countdown"],
            "default_intro_mode": "context_card",
            "max_intro_seconds": 2.8,
            "caption_style": "precise_numbers",
            "framing_style": "speaker_data_card",
            "overlay_style": "credible_context",
        },
        "risk_controls": {
            "requires_financial_review": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.60,
            "restricted_topics": [
                "specific stock recommendation", "get-rich-quick language",
                "unsupported prediction", "crypto hype",
            ],
        },
    },
    "sports": {
        "clip_rules": {
            "candidate_durations": [15, 24, 35, 45],
            "min_clip_duration": 12,
            "max_clip_duration": 55,
            "prefer_fast_payoff": True,
        },
        "scoring_weights": {
            "hook": 0.18,
            "payoff": 0.18,
            "standalone_context": 0.12,
            "theme_signal": 0.22,
            "public_popularity": 0.10,
            "captionability": 0.05,
            "visual_quality": 0.08,
            "pacing": 0.07,
        },
        "theme_signals": {
            "enabled": ["debate", "legacy", "rivalry", "locker_room_story"],
            "positive_keywords": [
                "championship", "playoffs", "draft", "trade", "locker room",
                "coach", "quarterback", "nba", "nfl", "legacy", "rivalry",
            ],
            "keyword_weights": {
                "championship": 2.2,
                "playoffs": 2.0,
                "rivalry": 2.0,
                "locker room": 2.0,
                "legacy": 1.8,
                "draft": 1.8,
            },
            "archetypes": [
                "legacy_debate", "locker_room_story", "rivalry", "hot_take",
                "film_room_insight", "trash_talk", "player_comparison",
            ],
        },
        "packaging": {
            "intro_modes": ["cold_open", "context_card", "clip_then_takeaway"],
            "default_intro_mode": "context_card",
            "max_intro_seconds": 2.2,
            "caption_style": "bold_sports",
            "framing_style": "debate_reaction",
            "overlay_style": "scoreboard",
        },
    },
    "wellness": {
        "clip_rules": {
            "candidate_durations": [18, 28, 40, 55],
            "min_clip_duration": 14,
            "max_clip_duration": 60,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["practical_takeaway", "emotional_relevance", "health_behavior"],
            "positive_keywords": [
                "sleep", "stress", "anxiety", "habit", "discipline", "health",
                "exercise", "nutrition", "therapy", "confidence", "dopamine",
            ],
            "archetypes": [
                "practical_rule", "mindset_shift", "health_mistake",
                "daily_protocol", "emotional_reframe",
            ],
        },
        "packaging": {
            "default_intro_mode": "clip_then_takeaway",
            "caption_style": "calm_takeaway",
            "framing_style": "clean_speaker",
            "overlay_style": "takeaway_card",
        },
        "risk_controls": {
            "requires_medical_review": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.60,
        },
    },
    "politics": {
        "clip_rules": {
            "candidate_durations": [24, 35, 45, 58],
            "min_clip_duration": 20,
            "max_clip_duration": 60,
            "prefer_context": True,
        },
        "scoring_weights": {
            "hook": 0.10,
            "payoff": 0.10,
            "standalone_context": 0.20,
            "theme_signal": 0.12,
            "public_popularity": 0.04,
            "captionability": 0.06,
            "visual_quality": 0.04,
            "pacing": 0.04,
            "transformation": 0.16,
            "claim_safety": 0.14,
        },
        "theme_signals": {
            "enabled": ["policy_claim", "source_context", "debate", "accountability"],
            "positive_keywords": [
                "election", "policy", "border", "congress", "senate",
                "president", "media", "corruption", "court", "war",
            ],
            "archetypes": [
                "policy_explainer", "heated_exchange", "source_context",
                "accountability_claim", "debate_moment",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "source_precise",
            "framing_style": "source_identity",
            "overlay_style": "fact_context",
        },
        "risk_controls": {
            "requires_fact_check": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.70,
            "manual_review_topics": [
                "election claims", "war claims", "crime allegations",
                "health policy claims", "legal accusations",
            ],
        },
    },
    "technology": {
        "clip_rules": {
            "candidate_durations": [20, 32, 45, 58],
            "min_clip_duration": 16,
            "max_clip_duration": 60,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["technical_tradeoff", "builder_insight", "ai_limitation", "product_strategy"],
            "positive_keywords": [
                "ai", "model", "agent", "startup", "developer", "security",
                "workflow", "eval", "product", "research", "open source",
            ],
            "archetypes": [
                "builder_insight", "ai_limitation", "product_strategy",
                "technical_explainer", "startup_lesson", "security_risk",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "technical_clean",
            "framing_style": "speaker_diagram",
            "overlay_style": "diagram_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "restricted_topics": ["security exploit detail", "privacy-invasive advice"],
        },
    },
    "education": {
        "clip_rules": {
            "candidate_durations": [25, 40, 58],
            "min_clip_duration": 20,
            "max_clip_duration": 60,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["definition", "mental_model", "example", "misconception"],
            "positive_keywords": [
                "definition", "example", "because", "misconception", "history",
                "science", "study", "framework", "analogy", "model",
            ],
            "archetypes": [
                "definition", "misconception_correction", "mental_model",
                "historical_explanation", "simple_analogy", "framework",
            ],
        },
        "packaging": {
            "default_intro_mode": "explain_then_clip",
            "caption_style": "clean_learning",
            "framing_style": "speaker_context",
            "overlay_style": "definition_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "minimum_transformation_score": 0.65,
        },
    },
    "agriculture": {
        "clip_rules": {
            "candidate_durations": [24, 35, 45, 58],
            "min_clip_duration": 18,
            "max_clip_duration": 60,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["farm_economics", "equipment_decision", "weather_risk", "crop_insight"],
            "positive_keywords": [
                "input costs", "yield", "weather", "equipment", "soil",
                "crop", "labor", "commodity", "insurance", "irrigation",
            ],
            "archetypes": [
                "farm_economics", "equipment_decision", "weather_risk",
                "soil_crop_insight", "cash_flow_problem", "market_pricing",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "practical_operator",
            "framing_style": "speaker_context",
            "overlay_style": "cost_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "restricted_topics": ["chemical claims", "crop treatment claims", "financial advice"],
        },
    },
    "business_startups": {
        "clip_rules": {
            "candidate_durations": [20, 32, 45, 58],
            "min_clip_duration": 16,
            "max_clip_duration": 60,
            "prefer_context": True,
            "prefer_explanation": True,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["founder_lesson", "growth_loop", "fundraising_moment", "operator_mistake"],
            "positive_keywords": [
                "founder", "startup", "customer", "growth", "revenue",
                "fundraise", "product", "market", "sales", "hiring",
            ],
            "archetypes": [
                "founder_lesson", "operator_mistake", "growth_loop",
                "fundraising_moment", "product_market_fit", "sales_breakthrough",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "operator_takeaway",
            "framing_style": "speaker_data_card",
            "overlay_style": "founder_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "minimum_transformation_score": 0.62,
        },
    },
    "creator_economy": {
        "clip_rules": {
            "candidate_durations": [16, 24, 35, 50],
            "min_clip_duration": 12,
            "max_clip_duration": 58,
            "prefer_fast_payoff": True,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["creator_growth", "platform_shift", "monetization_lesson", "audience_insight"],
            "positive_keywords": [
                "creator", "youtube", "tiktok", "algorithm", "audience",
                "monetize", "brand deal", "newsletter", "views", "retention",
            ],
            "archetypes": [
                "algorithm_lesson", "creator_mistake", "monetization_breakdown",
                "platform_shift", "audience_insight", "viral_format",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "creator_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "creator_dashboard",
        },
    },
    "film_tv": {
        "clip_rules": {
            "candidate_durations": [10, 16, 24, 35, 50],
            "min_clip_duration": 8,
            "max_clip_duration": 58,
            "prefer_fast_payoff": True,
            "prefer_context": True,
        },
        "theme_signals": {
            "enabled": ["behind_the_scenes", "actor_story", "director_insight", "scene_breakdown", "fandom_moment"],
            "positive_keywords": [
                "movie", "scene", "actor", "director", "character",
                "script", "set", "audition", "role", "episode",
            ],
            "archetypes": [
                "behind_the_scenes", "actor_story", "director_insight",
                "scene_breakdown", "fandom_moment", "casting_story",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "cinematic_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "premiere_card",
        },
    },
    "food_hospitality": {
        "clip_rules": {
            "candidate_durations": [14, 22, 35, 50],
            "min_clip_duration": 10,
            "max_clip_duration": 58,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["restaurant_lesson", "chef_story", "service_moment", "food_business"],
            "positive_keywords": [
                "restaurant", "chef", "menu", "service", "kitchen",
                "hospitality", "recipe", "customer", "dish", "staff",
            ],
            "archetypes": [
                "chef_story", "restaurant_lesson", "service_moment",
                "food_business", "kitchen_mistake", "taste_memory",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "sensory_takeaway",
            "framing_style": "speaker_context",
            "overlay_style": "menu_card",
        },
    },
    "gaming": {
        "clip_rules": {
            "candidate_durations": [14, 22, 35, 50],
            "min_clip_duration": 10,
            "max_clip_duration": 58,
            "prefer_fast_payoff": True,
            "prefer_context": True,
        },
        "theme_signals": {
            "enabled": ["developer_insight", "industry_debate", "creator_lesson", "game_design", "esports_moment"],
            "positive_keywords": [
                "game", "developer", "studio", "esports", "console",
                "design", "player", "launch", "streamer", "patch",
            ],
            "archetypes": [
                "developer_insight", "industry_debate", "creator_lesson",
                "game_design", "esports_moment", "launch_drama",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "gaming_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "arcade_card",
        },
    },
    "health_fitness": {
        "clip_rules": {
            "candidate_durations": [18, 28, 40, 58],
            "min_clip_duration": 14,
            "max_clip_duration": 60,
            "prefer_practicality": True,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["protocol", "training_mistake", "nutrition_rule", "health_claim"],
            "positive_keywords": [
                "training", "workout", "sleep", "nutrition", "protein",
                "mobility", "recovery", "cardio", "strength", "metabolism",
            ],
            "archetypes": [
                "training_mistake", "nutrition_rule", "daily_protocol",
                "recovery_lesson", "health_myth", "performance_tip",
            ],
        },
        "packaging": {
            "default_intro_mode": "clip_then_takeaway",
            "caption_style": "protocol_takeaway",
            "framing_style": "clean_speaker",
            "overlay_style": "protocol_card",
        },
        "risk_controls": {
            "requires_medical_review": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.68,
        },
    },
    "history": {
        "clip_rules": {
            "candidate_durations": [24, 38, 55],
            "min_clip_duration": 18,
            "max_clip_duration": 60,
            "prefer_context": True,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["historical_turn", "forgotten_detail", "cause_effect", "myth_correction"],
            "positive_keywords": [
                "history", "war", "empire", "king", "ancient",
                "century", "battle", "revolution", "archive", "myth",
            ],
            "archetypes": [
                "forgotten_detail", "historical_turn", "myth_correction",
                "cause_effect", "character_story", "timeline_explainer",
            ],
        },
        "packaging": {
            "default_intro_mode": "explain_then_clip",
            "caption_style": "history_context",
            "framing_style": "speaker_context",
            "overlay_style": "archive_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "minimum_transformation_score": 0.68,
        },
    },
    "lifestyle": {
        "clip_rules": {
            "candidate_durations": [12, 22, 35, 50],
            "min_clip_duration": 10,
            "max_clip_duration": 58,
            "prefer_practicality": True,
            "prefer_fast_payoff": True,
        },
        "theme_signals": {
            "enabled": ["taste_signal", "routine_tip", "identity_moment", "culture_lesson"],
            "positive_keywords": [
                "style", "routine", "home", "travel", "food",
                "taste", "habit", "design", "city", "culture",
            ],
            "archetypes": [
                "routine_tip", "taste_signal", "identity_moment",
                "culture_lesson", "life_upgrade", "personal_story",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "lifestyle_hook",
            "framing_style": "speaker_context",
            "overlay_style": "magazine_card",
        },
    },
    "music": {
        "clip_rules": {
            "candidate_durations": [10, 18, 28, 45],
            "min_clip_duration": 8,
            "max_clip_duration": 55,
            "prefer_fast_payoff": True,
        },
        "theme_signals": {
            "enabled": ["song_story", "artist_origin", "studio_moment", "industry_truth"],
            "positive_keywords": [
                "song", "album", "artist", "studio", "producer",
                "tour", "label", "record", "lyrics", "beat",
            ],
            "archetypes": [
                "song_story", "studio_moment", "artist_origin",
                "industry_truth", "lyric_explanation", "career_turn",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "music_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "stage_card",
        },
        "risk_controls": {
            "restricted_topics": ["song lyrics", "music-video footage"],
            "minimum_transformation_score": 0.62,
        },
    },
    "self_improvement": {
        "clip_rules": {
            "candidate_durations": [18, 28, 40, 58],
            "min_clip_duration": 14,
            "max_clip_duration": 60,
            "prefer_practicality": True,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["mindset_shift", "discipline_rule", "identity_reframe", "habit_loop"],
            "positive_keywords": [
                "discipline", "habit", "mindset", "confidence", "focus",
                "goal", "identity", "failure", "motivation", "routine",
            ],
            "archetypes": [
                "mindset_shift", "discipline_rule", "identity_reframe",
                "habit_loop", "failure_lesson", "focus_rule",
            ],
        },
        "packaging": {
            "default_intro_mode": "clip_then_takeaway",
            "caption_style": "sharp_takeaway",
            "framing_style": "clean_speaker",
            "overlay_style": "principle_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["mental health claims", "trauma claims", "medical advice"],
            "minimum_transformation_score": 0.64,
        },
    },
    "outdoors_adventure": {
        "clip_rules": {
            "candidate_durations": [16, 28, 40, 58],
            "min_clip_duration": 12,
            "max_clip_duration": 60,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["survival_lesson", "gear_choice", "wild_story", "risk_decision"],
            "positive_keywords": [
                "hunting", "fishing", "trail", "mountain", "survival",
                "gear", "wild", "camp", "weather", "risk",
            ],
            "archetypes": [
                "survival_lesson", "gear_choice", "wild_story",
                "risk_decision", "field_mistake", "adventure_payoff",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "field_story",
            "framing_style": "speaker_context",
            "overlay_style": "field_card",
        },
    },
    "parenting_family": {
        "clip_rules": {
            "candidate_durations": [18, 28, 40, 58],
            "min_clip_duration": 14,
            "max_clip_duration": 60,
            "prefer_context": True,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["parenting_reframe", "family_conflict", "child_development", "practical_rule"],
            "positive_keywords": [
                "parent", "kid", "child", "family", "school",
                "discipline", "mom", "dad", "teen", "behavior",
            ],
            "archetypes": [
                "parenting_reframe", "family_conflict", "child_development",
                "practical_rule", "emotional_moment", "boundary_lesson",
            ],
        },
        "packaging": {
            "default_intro_mode": "clip_then_takeaway",
            "caption_style": "warm_takeaway",
            "framing_style": "clean_speaker",
            "overlay_style": "family_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["child health", "custody", "abuse allegations"],
        },
    },
    "popculture": {
        "clip_rules": {
            "candidate_durations": [10, 18, 28, 42, 55],
            "min_clip_duration": 8,
            "max_clip_duration": 58,
            "prefer_fast_payoff": True,
            "prefer_context": True,
        },
        "theme_signals": {
            "enabled": ["celebrity_story", "fandom_debate", "viral_moment", "industry_context"],
            "positive_keywords": [
                "celebrity", "viral", "tiktok", "internet", "drama",
                "fans", "culture", "famous", "trend", "controversy",
            ],
            "archetypes": [
                "celebrity_story", "fandom_debate", "viral_moment",
                "industry_context", "public_reaction", "trend_explainer",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "culture_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "tabloid_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["celebrity allegations", "private life claims", "harassment"],
            "minimum_transformation_score": 0.62,
        },
    },
    "real_estate": {
        "clip_rules": {
            "candidate_durations": [22, 35, 45, 58],
            "min_clip_duration": 16,
            "max_clip_duration": 60,
            "prefer_context": True,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["deal_breakdown", "market_warning", "operator_mistake", "cash_flow"],
            "positive_keywords": [
                "real estate", "property", "mortgage", "rent", "tenant",
                "cash flow", "interest rate", "cap rate", "deal", "housing",
            ],
            "archetypes": [
                "deal_breakdown", "market_warning", "operator_mistake",
                "cash_flow", "housing_trend", "financing_lesson",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "precise_numbers",
            "framing_style": "speaker_data_card",
            "overlay_style": "property_card",
        },
        "risk_controls": {
            "requires_financial_review": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.65,
        },
    },
    "relationships_dating": {
        "clip_rules": {
            "candidate_durations": [12, 22, 35, 50],
            "min_clip_duration": 10,
            "max_clip_duration": 58,
            "prefer_fast_payoff": True,
        },
        "theme_signals": {
            "enabled": ["dating_rule", "relationship_conflict", "green_flag", "red_flag"],
            "positive_keywords": [
                "dating", "relationship", "marriage", "breakup", "red flag",
                "green flag", "texting", "love", "partner", "boundaries",
            ],
            "archetypes": [
                "red_flag", "green_flag", "dating_rule", "relationship_conflict",
                "boundary_lesson", "awkward_date",
            ],
        },
        "packaging": {
            "default_intro_mode": "cold_open",
            "caption_style": "social_hook",
            "framing_style": "speaker_reaction",
            "overlay_style": "social_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["abuse claims", "mental health diagnosis", "gender-group claims"],
        },
    },
    "truecrime": {
        "clip_rules": {
            "candidate_durations": [24, 35, 45, 58],
            "min_clip_duration": 20,
            "max_clip_duration": 60,
            "prefer_context": True,
            "prefer_explanation": True,
        },
        "theme_signals": {
            "enabled": ["case_timeline", "courtroom_moment", "evidence_context", "investigator_insight"],
            "positive_keywords": [
                "case", "court", "trial", "detective", "evidence",
                "timeline", "motive", "witness", "investigation", "verdict",
            ],
            "archetypes": [
                "case_timeline", "courtroom_moment", "evidence_context",
                "investigator_insight", "victim_context", "legal_turn",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "case_context",
            "framing_style": "source_identity",
            "overlay_style": "case_file",
        },
        "risk_controls": {
            "requires_fact_check": True,
            "requires_claim_context": True,
            "minimum_transformation_score": 0.72,
            "manual_review_topics": [
                "criminal allegations", "victim details", "active case",
                "minor involved", "graphic crime detail",
            ],
        },
    },
    "travel": {
        "clip_rules": {
            "candidate_durations": [18, 28, 40, 55],
            "min_clip_duration": 12,
            "max_clip_duration": 60,
            "prefer_practicality": True,
        },
        "theme_signals": {
            "enabled": ["specific_place", "local_custom", "travel_mistake", "story"],
            "positive_keywords": [
                "city", "country", "local", "custom", "transport", "budget",
                "safety", "food", "culture", "mistake", "visa",
            ],
            "archetypes": [
                "travel_mistake", "local_custom", "food_discovery",
                "budget_tip", "transport_hack", "cultural_insight",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "place_specific",
            "framing_style": "speaker_context",
            "overlay_style": "map_card",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["visa claims", "border claims", "safety claims", "prices"],
        },
    },
    "religion": {
        "clip_rules": {
            "candidate_durations": [25, 40, 58],
            "min_clip_duration": 20,
            "max_clip_duration": 60,
            "prefer_context": True,
        },
        "theme_signals": {
            "enabled": ["moral_question", "theological_explanation", "philosophical_dilemma"],
            "positive_keywords": [
                "faith", "god", "moral", "forgiveness", "ritual", "meaning",
                "philosophy", "theology", "belief", "soul", "virtue",
            ],
            "negative_keywords": ["mock", "hate", "inferior"],
            "archetypes": [
                "moral_dilemma", "theological_explainer", "philosophical_argument",
                "spiritual_practice", "historical_context", "debate_moment",
            ],
        },
        "packaging": {
            "default_intro_mode": "context_card",
            "caption_style": "respectful_clear",
            "framing_style": "speaker_context",
            "overlay_style": "quote_context",
        },
        "risk_controls": {
            "requires_claim_context": True,
            "manual_review_topics": ["claims about religious groups", "extremism", "political religion claims"],
            "minimum_transformation_score": 0.65,
        },
    },
}


PROFILE_ALIASES = {
    "self_improvement": "wellness",
    "lifestyle": "wellness",
    "health": "wellness",
    "health_fitness": "wellness",
    "tech": "technology",
    "technology_ai": "technology",
    "ai": "technology",
    "education_science": "education",
    "science": "education",
    "agriculture_farming": "agriculture",
    "travel_culture": "travel",
    "religion_philosophy": "religion",
    "legal_crime": "truecrime",
}


def deep_merge(base, override):
    result = copy.deepcopy(base)

    for key, value in (override or {}).items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)

    return result


def profile_preset_name(profile_name):
    profile = clean_theme_name(profile_name or "generic")
    return PROFILE_ALIASES.get(profile, profile)


def normalized_string_list(values):
    normalized = []

    for value in values or []:
        if not isinstance(value, str):
            continue

        value = value.strip()

        if value and value not in normalized:
            normalized.append(value)

    return normalized


def channel_trusted_terms(channel_url):
    text = str(channel_url or "").strip()
    if not text:
        return []

    text = re.sub(r"^https?://(www\.)?youtube\.com/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"/videos/?$", "", text, flags=re.IGNORECASE).strip("/")
    terms = []

    if text.startswith("@"):
        handle = text[1:]
        terms.extend([handle, f"@{handle}"])
    elif text:
        terms.append(text)

    cleaned = re.sub(r"[^a-z0-9]+", "", text.lower())
    if cleaned:
        terms.append(cleaned)

    return normalized_string_list(terms)


def profile_channel_trusted_terms(profile):
    terms = []

    for channel in (
        normalized_string_list(profile.get("priority_channels") or [])
        + normalized_string_list(profile.get("secondary_channels") or [])
        + normalized_string_list(profile.get("channels") or [])
    ):
        terms.extend(channel_trusted_terms(channel))

    return normalized_string_list(terms)


def normalized_route_override_items(items):
    routes = []

    for item in items or []:
        if not isinstance(item, dict):
            continue

        source = str(item.get("source") or "").strip()
        route_to = normalized_string_list(item.get("route_to") or [])
        when = str(item.get("when") or "").strip()

        if not source or not route_to:
            continue

        routes.append({
            **item,
            "source": source,
            "route_to": route_to,
            "when": when,
        })

    return routes


def route_match_token(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def keyword_in_text(text, keyword):
    key = str(keyword or "").strip().lower()
    if not key:
        return False

    haystack = f" {str(text or '').lower()} "
    if " " in key:
        return key in haystack

    return re.search(rf"\b{re.escape(key)}\b", haystack) is not None


def load_theme_profile(theme_name):
    theme = clean_theme_name(theme_name or DEFAULT_THEME)
    raw = load_json_file(theme_config_path(theme), {"theme": theme, "channels": []})
    profile_name = raw.get("profile") or theme
    preset = PROFILE_PRESETS.get(profile_preset_name(profile_name), {})
    profile = deep_merge(DEFAULT_THEME_PROFILE, preset)
    profile = deep_merge(profile, raw)
    profile["theme"] = theme
    profile["profile"] = profile_preset_name(profile.get("profile") or profile_name)
    priority_channels = normalized_string_list(profile.get("priority_channels") or [])
    secondary_channels = normalized_string_list(profile.get("secondary_channels") or [])
    channels = normalized_string_list(profile.get("channels") or [])
    merged_channels = []

    for channel in priority_channels + secondary_channels + channels:
        if channel not in merged_channels:
            merged_channels.append(channel)

    profile["priority_channels"] = priority_channels
    profile["secondary_channels"] = secondary_channels
    profile["channels"] = merged_channels
    profile["episode_routing_override"] = normalized_route_override_items(
        profile.get("episode_routing_override") or []
    )
    return profile


def episode_route_targets(theme_name, *source_texts, detected_archetype=""):
    profile = load_theme_profile(theme_name)
    theme = profile["theme"]
    text_tokens = [
        route_match_token(value)
        for value in source_texts
        if str(value or "").strip()
    ]
    detected_token = route_match_token(detected_archetype)
    targets = [theme]
    matches = []

    for route in profile.get("episode_routing_override") or []:
        source_token = route_match_token(route.get("source"))

        if not source_token:
            continue

        source_matched = any(
            source_token in token or token in source_token
            for token in text_tokens
            if token
        )
        when_token = route_match_token(route.get("when"))
        archetype_matched = bool(
            detected_token
            and when_token
            and (detected_token in when_token or when_token in detected_token)
        )

        if not source_matched and not archetype_matched:
            continue

        for target in route.get("route_to") or []:
            target = clean_theme_name(target)

            if target and target not in targets:
                targets.append(target)

        matches.append({
            "source": route.get("source", ""),
            "route_to": route.get("route_to", []),
            "when": route.get("when", ""),
            "match_type": "source" if source_matched else "archetype",
        })

    return {
        "theme": theme,
        "targets": targets,
        "matches": matches,
    }


def source_guard_disqualification(profile, source_record):
    profile = profile or {}
    source_record = source_record or {}
    signal_config = profile.get("theme_signals") or {}
    source_guard = signal_config.get("source_guard") or {}
    hard_negative_keywords = list(source_guard.get("hard_negative_keywords") or [])
    negative_keywords = list(signal_config.get("negative_keywords") or [])
    negative_keywords.extend(source_guard.get("negative_keywords") or [])
    source_text = " ".join(
        str(source_record.get(key) or "")
        for key in (
            "title",
            "description",
            "channel",
            "uploader",
            "channel_url",
            "video_url",
        )
    )
    source_tier = str(source_record.get("source_tier") or "").strip().lower()
    relaxed_configured_source = (
        RELAX_CONFIGURED_SOURCE_GUARD
        and not STRICT_SOURCE_GUARD
        and source_tier in CONFIGURED_SOURCE_TIERS
    )
    hard_hits = [keyword for keyword in hard_negative_keywords if keyword_in_text(source_text, keyword)]

    if hard_hits and not relaxed_configured_source:
        return True, hard_hits[:6]

    hits = [keyword for keyword in negative_keywords if keyword_in_text(source_text, keyword)]
    positive_keywords = list(signal_config.get("positive_keywords") or [])
    positive_keywords.extend(source_guard.get("positive_keywords") or [])
    positive_hits = [keyword for keyword in positive_keywords if keyword_in_text(source_text, keyword)]

    if hits and not relaxed_configured_source:
        # Block clear source-level mismatches, while allowing sources whose
        # title strongly declares the target theme despite a stray negative term.
        override_min_hits = int(source_guard.get("negative_override_min_positive_hits") or 2)
        if len(positive_hits) < override_min_hits:
            return True, hits[:6]

    min_positive_hits = int(source_guard.get("min_positive_hits") or 0)
    tier_minimums = source_guard.get("min_positive_hits_by_tier") or {}

    if source_tier in tier_minimums:
        min_positive_hits = int(tier_minimums.get(source_tier) or 0)

    explicit_trusted_terms = normalized_string_list(source_guard.get("trusted_source_terms") or [])
    explicit_trusted_source = any(keyword_in_text(source_text, term) for term in explicit_trusted_terms)

    if (
        min_positive_hits
        and not relaxed_configured_source
        and not explicit_trusted_source
        and len(positive_hits) < min_positive_hits
    ):
        return True, [f"missing_source_positive_signal:{len(positive_hits)}/{min_positive_hits}"]

    return False, hits[:6]


def source_disqualified_by_theme_name(theme_name, source_record):
    return source_guard_disqualification(load_theme_profile(theme_name), source_record)


def get_clip_rules(theme_name):
    return load_theme_profile(theme_name).get("clip_rules", {})


def get_scoring_weights(theme_name):
    weights = load_theme_profile(theme_name).get("scoring_weights", {})
    return {**DEFAULT_SCORING_WEIGHTS, **weights}


def get_packaging_rules(theme_name):
    return load_theme_profile(theme_name).get("packaging", {})


def get_review_policy(theme_name):
    return load_theme_profile(theme_name).get("review_policy", {})


def get_analytics_targets(theme_name):
    return load_theme_profile(theme_name).get("analytics", {})


def get_theme_signals(theme_name):
    return load_theme_profile(theme_name).get("theme_signals", {})


def get_metadata_style(theme_name):
    return load_theme_profile(theme_name).get("metadata_style", {})


def get_risk_controls(theme_name):
    return load_theme_profile(theme_name).get("risk_controls", {})


def theme_hashtags(theme_name):
    return list(get_metadata_style(theme_name).get("hashtags") or ["#podcast", "#shorts"])


def theme_tags(theme_name):
    return list(get_metadata_style(theme_name).get("tags") or ["podcast clips", "shorts"])


def theme_topic_tags(theme_name):
    return dict(get_metadata_style(theme_name).get("topic_tags") or {})


def theme_keyword_weights(theme_name):
    signals = get_theme_signals(theme_name)
    weights = dict(signals.get("keyword_weights") or {})

    for keyword in signals.get("positive_keywords") or []:
        weights.setdefault(str(keyword).lower(), 1.45)

    return weights
