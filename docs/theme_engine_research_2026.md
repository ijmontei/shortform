# Theme Engine Research Notes - 2026

## Launch Scope

The live production slate is intentionally limited to nine YouTube-native, interview-led themes:

1. `comedy`
2. `sports`
3. `gaming`
4. `finance`
5. `technology_ai`
6. `health_fitness`
7. `politics`
8. `truecrime`
9. `popculture`

All other theme configs under `src/themes/` are phase-two inventory only. They are kept so the engine can grow later, but they are not active publishing priorities and should not be included in default production runs. Agriculture, lifestyle, travel, religion, and general education are examples of future-compatible configs, not phase-one themes.

## Platform Constraints

The theme engine is designed around two YouTube realities:

- Monetization risk: reused content needs meaningful original commentary, substantive modification, or added value. Raw clip factories are the wrong target.
- Shorts discovery: the first one to two seconds must communicate why the viewer should stay.

The pipeline should optimize for:

- engaged view rate
- average percent viewed
- likes, comments, and subscriber lift per engaged view
- source-specific repeatability
- original transformation score
- theme-specific viewer promise

Each theme needs to behave like a different editor, not like a different folder name.

Reference URLs used for the operating assumptions:

- YouTube reused/repetitious content guidance: https://support.google.com/youtube/answer/1311392
- YouTube Culture and Trends hub: https://www.youtube.com/trends/report/
- YouTube Fandom report: https://www.youtube.com/trends/report/fandom-2024/
- YouTube 2025 creator economy note: https://blog.youtube/inside-youtube/our-big-bets-for-2025/
- Edison Infinite Dial 2025 video podcast reporting: https://www.edisonresearch.com/the-infinite-dial-2025/

## Phase-One Theme Promises

| Theme | Primary editorial promise |
| --- | --- |
| `comedy` | Fast payoff, surprise, awkwardness, roast energy, and clean punchlines. |
| `sports` | Rivalry, stakes, legacy debates, athlete stories, and locker-room perspective. |
| `finance` | Useful business, market, money, and operator frameworks with financial-claim review. |
| `technology_ai` | Concrete builder insight, AI/product mechanisms, tradeoffs, and future-facing disagreement. |
| `health_fitness` | Practical behavior change, psychology, wellness, and fitness ideas with medical-risk review. |
| `politics` | Source/date-aware explanation, debate, and claim context instead of rage bait. |
| `truecrime` | Humane legal, crime, and confessional moments with dignity and defamation review. |
| `popculture` | Celebrity, entertainment, music, and culture moments with recognizable guests plus actual standalone value. |

## Source Registry Requirements

Each phase-one theme config should include:

- `priority_channels`
- `secondary_channels`
- `episode_routing_override`
- theme-specific `clip_rules`
- theme-specific `theme_signals`
- metadata, risk, review, and analytics rules

Shared channels must be routed at the episode level when topic, guest, or detected archetype points to another theme. A channel such as Diary of a CEO, Shawn Ryan, or SmartLess should not be permanently hard-bound to only one theme.

## Production Rule

Default discovery and production must only use the eight phase-one themes. Future themes are allowed only when `SHORTFORM_ALLOW_FUTURE_THEMES=1` is set intentionally for testing or later expansion.

Upload-ready clips must already be transformed and must have burned-in captions. Validation and upload routing should reject raw or uncaptioned ready items.
