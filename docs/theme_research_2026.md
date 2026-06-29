# Shortform Theme Research 2026

This memo is the launch-scope source of truth for the current Shortform theme engine.

## Active Launch Slate

Phase one uses exactly nine YouTube interview ecosystems:

| Theme | Community thesis | Source strategy | Primary editorial promise |
| --- | --- | --- | --- |
| `comedy` | Large repeat audience for jokes, roasts, stories, and reactions. | Comedy podcasts and visible multi-speaker formats. | The funniest moments without watching the full episode. |
| `sports` | Durable debate culture around athletes, teams, legacy, and rivalry. | Athlete podcasts, debate shows, and high-signal sports interviews. | The argument or story fans want to react to. |
| `gaming` | Fast-moving gaming, esports, creator, and developer culture with heavy repeat fandom. | Gaming podcasts, esports desks, creator-led channels, developer talks, and game-industry interviews. | The sharpest gaming creator, esports, developer, or industry moment with context. |
| `finance` | High-value audience for business, markets, economics, and money frameworks. | Founder, investor, economics, and operator interviews. | A useful idea, risk, or framework per clip. |
| `technology_ai` | Fast-moving builder and AI audience with high curiosity. | Builder, researcher, investor, and product-operator interviews. | One concrete technical or operator insight. |
| `health_fitness` | Huge wellness and self-improvement demand with higher claim risk. | Evidence-aware fitness, nutrition, psychology, sleep, and longevity sources. | Practical behavior change with review gates. |
| `politics` | Dense debate audience with strong comment velocity and context risk. | Current-affairs, policy, debate, and interview sources. | A context-first political moment, not rage bait. |
| `truecrime` | Deep retention around crime, legal, courtroom, and confessional stories. | Legal, case-analysis, and human-story interview sources. | Case or testimony context without irresponsible packaging. |
| `popculture` | Celebrity, entertainment, music, and internet-culture clips with shareability. | Entertainment interviews, celebrity formats, and culture outlets. | A recognizable cultural moment with real standalone value. |

## Future-Compatible Configs

The repository may contain extra JSON configs for future expansion, including agriculture, lifestyle, travel, religion, education, real estate, food, history, music, film/TV, and similar niches. These are not active phase-one themes. They should remain blocked from default production unless `SHORTFORM_ALLOW_FUTURE_THEMES=1` is deliberately set for testing.

## Selection Criteria

Each active theme must pass five tests before it belongs in the launch slate:

1. Dense community: viewers have a repeat interest, not only casual curiosity.
2. Interview supply: enough long-form source material exists to refresh daily.
3. Clipability: good moments can stand alone in 15-60 seconds with hook, context, and payoff.
4. Transformation surface: the system can add value through ranking, context cards, source attribution, comparison, or visual packaging.
5. Risk control: claims, rights, and reused-content risk can be handled with theme-specific gates and review.

## Source Maintenance Rules

- Prefer long-form interview channels with visible speakers, clean audio, and recurring topic density.
- Prefer sources with chapters, comments, replay/heatmap signals, or timestamps because those give the scorer external evidence.
- Avoid sources that are mostly montage, news packages, copyrighted clips, or low-context B-roll unless the theme explicitly supports a higher-transformation format.
- Replace channels that regularly produce no viable clips, fail downloads, or trigger repeated framing QC.
- Track source performance by selected clips per hour processed, accepted render rate, review approval rate, and engaged-view performance.

## Launch Guardrail

The default run path should discover only the nine active launch themes. Old phase-two output folders can exist on disk from prior experiments, but they should not be treated as current production inventory or upload-ready unless the future-theme gate is intentionally opened.
