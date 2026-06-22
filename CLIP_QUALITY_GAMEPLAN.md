# Clip Quality Gameplan

Last updated: 2026-06-21

## Core Thesis

A strong short-form podcast clip is not just an energetic excerpt. It needs a complete retention arc:

1. Immediate hook: the first 1-3 seconds create a question, conflict, surprise, or clear stakes.
2. Standalone context: a viewer who has never seen the full interview understands who/what is being discussed.
3. Escalation: the middle develops the idea instead of circling filler.
4. Payoff: the ending resolves, shocks, reframes, or leaves a clean click-through curiosity gap.
5. Visual continuity: the crop keeps the active speaker or subject in frame without wandering to blank space.

The current full format is usable. The quality bottleneck is selection and framing, so the pipeline should become more like an editorial judge than a generic transcript slicer.

## External Signal Stack

Use every public signal that can point to important moments:

1. YouTube replay heatmap
   - Use yt-dlp `heatmap` data when exposed.
   - Treat as the strongest public replay proxy.

2. Timestamp mentions
   - Extract timestamp references from descriptions, chapters, and comments.
   - Multiple independent mentions near the same time imply replay/comment interest.

3. Comment-thread timestamps
   - YouTube Data API `commentThreads.list` can return comment threads for a video and has a documented quota cost of 1 unit per call.
   - When `YOUTUBE_DATA_API_KEY` is present, the pipeline samples both relevance-ordered and newest comment threads.
   - Comment timestamp mentions are weighted by top-level comment likes and reply counts, turning interacted comments into stronger moment signals.
   - Non-timestamped comments are reduced into weighted topic terms and matched against transcript windows as `comment_topic_score`.
   - yt-dlp can also fetch comments with `--write-comments` / `--get-comments`, but this may be slower or incomplete depending on YouTube experiments.

4. Chapter starts
   - Chapters are weaker than replay data, but they still reveal creator-identified topic boundaries.

5. Internal model fallback
   - When public signals are missing, select based on retention-arc score, text quality, debate/comment potential, audio movement, and visual viability.

## Implemented In This Pass

1. Retention-arc scoring
   - Added `arc_score` to `CandidateClip`.
   - Scores hook, escalation, payoff, standalone context, sentence completeness, dialogue momentum, and curiosity gap.
   - Integrated `arc_score` into the final candidate ranking formula.
   - Exported `arc_score` to review JSON/CSV.

2. Comment timestamp signals
   - Popularity profiles now distinguish metadata timestamps from comment timestamps.
   - `SHORTFORM_FETCH_COMMENT_TIMESTAMP_SIGNALS=1` enables comment extraction through yt-dlp.
   - Popularity cache refreshes when comment timestamps have not yet been fetched.

3. Final-frame visual QA
   - Added actual rendered-output sampling after crop/mux.
   - Checks black frames, low-information frames, final face presence, face center offset, face height, and subject-position jitter.
   - Stores results in `render_qc.frame_path`.

4. Candidate inventory exports
   - Each clip review JSON now includes `candidate_inventory`.
   - Inventory groups best alternates by interview zone: opening, early middle, late middle, ending.
   - Inventory also groups best alternates by signal: retention arc, public popularity, comment timestamps, comment-topic relevance, audio energy, and clean boundaries.
   - Inventory now groups by clip archetype too: replay-backed, comment-sparking, comment-relevance match, cold-open hook, retention arc, payoff/reframe, explainer, debate/exchange, high-energy, and general quality.

5. Source dossiers
   - Each scored interview writes a source dossier under `output/temp/<theme>/metadata/source_dossiers`.
   - Dossiers summarize signal coverage, YouTube stats when available, top timestamp markers, score distribution, topic summary, selected clips, and alternate clip inventory.
   - Dossiers include `clip_batch_plan.full_interview_milking_order`, a deduplicated set of recommended alternates across selected clips, replay-backed clips, comment sparks, clean arcs, high-energy clips, explainers, and late payoffs.
   - Dossiers now include a readiness distribution (`elite`, `strong`, `usable`, `review`, `weak`, `reject`) so one long interview can be judged by how many publishable moments it actually contains, not just by total candidate count.
   - Existing review files can be rescored with `rescore_clip_reviews.py`, which reuses cached transcript/audio-feature files plus cached public popularity profiles. This backfills current readiness scores, candidate inventories, and source dossiers without re-downloading or re-rendering videos.
   - Candidate topics are anchored by the selected title/hook sentence and filtered for low-value transcript glue words, producing more useful source-level topic summaries.

6. Framing bakeoff and audit artifacts
   - The renderer first tries the normal face-locked crop.
   - If final-frame QA flags drift, low face presence, off-center subjects, or unstable movement, it tries stable-face-lock, group-face-lock, and center-safe fallbacks.
   - Stable-face-lock scans the clip first, picks the most reliable face cluster, and renders with a locked crop to reduce wandering.
   - Group-face-lock only activates when multiple faces are visible in the same sampled frames and close enough to plausibly fit in the vertical crop.
   - Dual-speaker-stack is an enhancement strategy for moments where two plausible speaker faces are visible together. It creates a top/bottom split to keep both speakers in focus, then falls back to single-speaker framing when the pair is no longer confident.
   - Face selection now weighs a `speaker_zone_score` in addition to raw face plausibility and motion, reducing false locks on background art/furniture and favoring seated speaker positions.
   - The selected render is chosen by an objective render quality score, not by render order.
   - Each attempt writes a contact-sheet audit image with sampled frames, center guide, face boxes, and warning labels.

7. Final output validation
   - `validate_outputs.py` now optionally samples finished output frames.
   - It writes validation contact sheets under `logs/frame_validation/<theme>`.
   - It treats black/low-information frames as hard failures, and applies strict face/crop flags to raw/classic clip outputs.
   - The main clip renderer now hard-rejects bad final renders after all crop strategies have been tried. Rejected clips keep QC details in review exports, do not count as generated, and the bad working video is deleted.
   - Final-frame QA now also reports dead-frame ratio, alive-frame rate, blank-background ratio, average edge density, average Laplacian/detail score, face-box plausibility, `alive_no_face_frame_ratio`, and `longest_no_face_run_ratio`.
   - Jitter is now cut-aware: the audit tracks `visual_cut_ratio`, `avg_sample_visual_change`, and `continuity_center_jitter_ratio` so normal podcast camera cuts are not treated the same as within-shot crop drift.
   - Contact sheets label sampled frames as `BLACK`, `DEAD`, `LOW INFO`, `NO FACE`, or `OK`, so visual failures can be reviewed quickly without watching every render.
   - The crop-strategy bakeoff now penalizes dead frames and weak alive-frame rate, not just off-center face boxes.
   - The editorial renderer now runs the same post-render gate before saving upload metadata. Countdown, popular-segment, and recap files with dead frames or low editorial visual quality are marked failed, optionally deleted, and listed in `daily_brief.json` as rejected instead of becoming upload candidates.

8. Quality lab report
   - `quality_lab.py` summarizes clip review coverage, source dossiers, visual QC flags, candidate inventory, archetype coverage, and full-interview batch recommendations.
   - Reports are written under `logs/quality_lab`.
   - It now writes `source_mining_index`, ranking source interviews as `primary_milk_source`, `selective_source`, `thin_but_usable`, or `weak_source`.
   - Source tiers are deliberately stricter than raw candidate volume. `primary_milk_source` requires multiple selected publish-ready clips, or selected clips plus strong external replay/timestamp evidence. Long interviews with many okay windows but no selected clips are capped as `thin_but_usable` or `selective_source`.

9. Framing lab report
   - `framing_lab.py` runs a bounded local crop-strategy bakeoff across downloaded media.
   - It renders the same sample through face-locked, stable-face-lock, group-face-lock, and center-safe strategies.
   - It writes per-strategy contact sheets plus `logs/framing_lab/<theme>/framing_lab_latest.json` with strategy wins, quality scores, and visual flags.

## Scoring Model

The candidate score now favors:

- Text substance: claim, conflict, specificity, payoff, clarity.
- Audio movement: sustained energy, peaks, tone changes.
- Opening strength: hook quality in the first seconds.
- Comment potential: debate, questions, absolutes, controversial phrasing.
- Retention arc: beginning-middle-ending shape.
- Popularity signal: replay heatmap, timestamps, comments, chapters.
- Natural boundaries: no weak opener, no mid-thought ending.
- Diversity: avoid making five clips about the same idea.

## Framing QA Plan

Current checks:

- Preflight checks source subclip for face presence and black frames.
- Smart crop uses face-first tracking with YOLO person fallback disabled by default.
- Final-frame QA checks the actual vertical output.
- Plausible face boxes are filtered by geometry plus ROI texture/detail so microphones, banners, or dark objects are less likely to pass as valid interview faces.
- Dead visual frames are rejected when they are black, low-information, or blank-background frames with no plausible subject.
- Validation exports `dead_frame_ratio`, `alive_frame_rate`, `avg_edge_density`, and `avg_face_plausibility` so long runs can be sorted by actual visual risk.

Next improvements:

1. More crop strategies
   - Current bakeoff compares face-locked, stable-face-lock, group-face-lock, and center-safe.
   - Add a speaker-cut strategy next: hold one speaker until a confident speaker change, then cut/recenter instead of drifting.
   - Add a two-person split-safe strategy for interview clips where both faces matter.

2. Hard visual gates
   - Reject outputs with high black-frame ratio, unstable subject position, or low final face presence.
   - Keep a retry path that tries a different crop strategy before rejecting.

3. Human-style frame review loop
   - Sort rendered clips by low `visual_quality_score` and inspect the generated contact sheets first.
   - Use those failures to tighten thresholds by source/channel over time.
   - Use `framing_lab.py` on local source sections whenever a show layout repeatedly fails, then tune thresholds/strategy order from the report.

4. Speaker-aware switching
   - Avoid panning across the frame during fast conversational cuts.
   - Prefer a clean cut/recenter when the active speaker changes clearly.

## Full Interview Milking Strategy

For each source interview, create a source dossier:

1. Pull signals
   - Transcript segments.
   - Audio energy/tone changes.
   - Heatmap if available.
   - Description/chapter timestamps.
   - Comment timestamp mentions.
   - Weighted comment topic terms from liked/replied comments.
   - Comment sentiment and repeated topic phrases.

2. Generate candidate inventory
   - Hook clips.
   - Explanation clips.
   - Debate/comment clips.
   - Most replayed clips.
   - Weird/surprising clips.
   - Clean standalone answer clips.

3. Rank and diversify
   - One source can produce multiple shorts only if each clip has a distinct topic fingerprint.
   - Avoid repeated openings, repeated topic clusters, and unresolved filler.

4. Package
   - Countdown reel uses best cross-theme moments.
   - Popular segment short uses replay/comment/timestamp-backed moments.
   - Source-specific batch can milk one interview when it has enough high-quality distinct moments.

## API Reality Check

- Public YouTube Data API data can expose video statistics and comment threads, including relevance-ordered comments.
- Public comment/thread APIs do not expose exact second-by-second audience retention.
- YouTube Analytics audience-retention reports are permissioned analytics for owned/authorized channels, not a general public API for any podcast.
- For third-party podcasts, the practical stack is therefore: public heatmap when exposed, chapters, descriptions, timestamped comments, comment interactions, transcript quality, audio energy, and final visual QA.

## Sources Used

- YouTube Help: key moments for audience retention explains that moment-level retention data identifies which parts held attention and that retention data is video-level analytics.
  https://support.google.com/youtube/answer/9314415
- YouTube Data API: `commentThreads.list` returns comment threads for videos and has documented quota cost.
  https://developers.google.com/youtube/v3/docs/commentThreads/list
- YouTube Data API: `videos.list` can return public video statistics such as views, likes, and comments.
  https://developers.google.com/youtube/v3/docs/videos/list
- YouTube Analytics API reports are scoped to authenticated channel/content-owner analytics.
  https://developers.google.com/youtube/analytics/reference/reports/query
- yt-dlp docs: `--write-comments` / `--get-comments` can retrieve comments into info JSON.
  https://github.com/yt-dlp/yt-dlp
- yt-dlp issue history documents YouTube "most replayed" heatmap availability as a metadata signal.
  https://github.com/yt-dlp/yt-dlp/issues/3888
