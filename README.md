# shortform

Version 1.1 short-form clip generation pipeline.

## Pipeline

`run.py` is the master runner. It runs:

1. `video_fetch.py` reads theme JSON files from `src/themes` and records latest videos in `src/pulled.json`.
2. `clip_generation.py` downloads/reuses media, scores clips, and renders vertical working clips.
3. `subtitle_generation.py` burns subtitles, saves finished clips, writes theme metadata, and marks completed videos in `src/executed_id.json`.
4. `upload.py` uploads ready clips to the theme's configured YouTube channel. Uploads are public by default unless `SHORTFORM_YOUTUBE_PRIVACY_STATUS` is set to `private` or `unlisted`.

Use `--skip-youtube` when you want to prepare upload-ready clips without uploading.

## Generation-Only Backlog Campaigns

Build a large local backlog without opening Google OAuth or uploading anything:

```powershell
.\venv_313\Scripts\python.exe .\backlog_campaign.py --target 500 --source-videos-per-channel 50
```

The campaign preserves existing `content` and `archive` packages, discovers older videos from every configured source channel, skips completed sources, and runs resumable generation cycles until every theme reaches the target. Historical depth expands after a stalled cycle, up to 200 videos per source channel by default. Progress is written to:

```text
logs/backlog_campaign_latest.json
```

Run one generation-only cycle instead of the automatic campaign loop:

```powershell
.\venv_313\Scripts\python.exe .\run.py --travel-safe --skip-youtube --backlog-target-per-theme 500 --source-videos-per-channel 50
```

Backlog mode cannot be combined with `--clean-slate`, and it forcibly disables YouTube uploads even when channel routes and tokens are configured.

## Travel-Safe / Resumable Runs

When internet may cut out, use travel-safe mode to front-load the network-heavy work across all themes before local rendering and packaging starts:

```powershell
.\venv_313\Scripts\python.exe .\run.py --travel-safe
```

For hotel/travel workflows, split the run into three resumable blocks:

```powershell
# 1. Good internet: fetch metadata, download audio, score, and prefetch selected video sections.
.\venv_313\Scripts\python.exe .\run.py --acquisition-only

# 2. Weak internet is okay: render, package, reconcile, and build the upload manifest.
.\venv_313\Scripts\python.exe .\run.py --package-only

# 3. Good internet again: upload the prepared queue.
.\venv_313\Scripts\python.exe .\run.py --upload-only
```

For a fresh production run, combine clean slate with the first block:

```powershell
.\venv_313\Scripts\python.exe .\run.py --clean-slate --acquisition-only
.\venv_313\Scripts\python.exe .\run.py --package-only
.\venv_313\Scripts\python.exe .\run.py --upload-only
```

`--clean-slate` preserves upload-ready backlog by default. For a true visual/output test reset
that deletes existing content and archive packages while retaining executed/pulled source
history and duplicate prevention, add `--discard-existing-backlog`.

Run a health check before a long production run:

```powershell
.\venv_313\Scripts\python.exe .\run.py --doctor
```

Validate generated files and upload metadata after a run:

```powershell
.\venv_313\Scripts\python.exe .\run.py --validate-outputs
```

Create a consolidated post-run QC/postmortem report:

```powershell
.\venv_313\Scripts\python.exe .\run.py --production-review
```

If a run is still active and you only want to package the latest logs without re-running heavier validation/quality checks:

```powershell
.\venv_313\Scripts\python.exe .\run.py --production-review --skip-review-validation --skip-review-quality
```

Generate the local manual-review dashboard:

```powershell
.\venv_313\Scripts\python.exe .\run.py --review-dashboard
```

Validate the theme-engine schema and upload-routing readiness without starting production:

```powershell
.\venv_313\Scripts\python.exe .\run.py --validate-theme-engine
```

Render visual regression previews for the ranked-countdown wheel-to-podium transition:

```powershell
.\venv_313\Scripts\python.exe .\run.py --visual-regression
```

This writes per-theme preview videos and contact sheets under `logs\visual_regression\...`, plus `logs\visual_regression_latest.json`. Use `--theme comedy` with the same command to inspect one theme.

Scaffold a new theme from the universal schema:

```powershell
.\venv_313\Scripts\python.exe .\run.py --scaffold-theme new_theme_name --scaffold-profile generic
```

Approve or reject generated packages before upload:

```powershell
.\venv_313\Scripts\python.exe .\review_queue.py list --theme comedy --all
.\venv_313\Scripts\python.exe .\review_queue.py approve --theme comedy --index 1 --notes "publishable"
.\venv_313\Scripts\python.exe .\review_queue.py reject --theme comedy --index 2 --reason "weak hook"
.\venv_313\Scripts\python.exe .\review_queue.py request --theme comedy --index 3 --action try_alternate_framing
```

Rejected clips and clips with open revision requests are always skipped by `upload.py`. Public uploading works without manual approvals by default; enable stricter gating when you want only approved clips to upload:

```powershell
$env:SHORTFORM_REQUIRE_REVIEW_APPROVAL_FOR_UPLOAD="1"
```

Collect YouTube Analytics metrics for uploaded videos and build experiment reports:

```powershell
.\venv_313\Scripts\python.exe .\run.py --collect-analytics --theme comedy --analytics-days 30
.\venv_313\Scripts\python.exe .\run.py --experiment-report --theme comedy
```

## Quality And Speed Controls

Production is optimized to finish an ordinary all-theme cycle in roughly 12 hours, but it does
not stop at an arbitrary wall-clock deadline. It targets at least 10 upload-ready clips per theme,
prefers 20 (15 queued plus 5 archived), and can keep producing exceptional overflow clips above
20. Cached audio, transcripts, candidate scores, selected sections, renders, and packages make
interrupted runs resumable without imposing a time cap on normal production.

```powershell
# Default optimized all-theme production run.
.\venv_313\Scripts\python.exe .\run.py --travel-safe

# Optional travel-day guard. Omit this for normal unlimited production.
.\venv_313\Scripts\python.exe .\run.py --travel-safe --max-runtime-hours 12
```

When the optional guard is enabled, the stage-major scheduler gives every theme a fair share of
acquisition, scoring, framing, and editorial time and preserves unfinished work for the next run.
Without that flag, all qualifying work continues until the candidate inventory is exhausted.

Long sources use approximately 12 minutes of high-signal audio windows selected from replay
heatmaps, chapters, timestamped comments, and transcript coverage. The pipeline reuses one
Whisper model instance and cached transcripts, scores promising sources first, downloads only
selected video sections, and uses Intel Quick Sync (`h264_qsv`) when a functional probe passes.
Set `SHORTFORM_HARDWARE_ENCODER=software` to force the `libx264` fallback.
Final upload preflight reuses signature-matched render/audio QC and does not repeat title or
content grading. Metadata is still sanitized and weak titles receive a supported fallback.
Set `SHORTFORM_RECHECK_EDITORIAL_GATES_ON_UPLOAD=1` only when deliberately auditing legacy
packages again.

Public replay heatmaps, chapters, and timestamped comments boost candidate rank but are not a
hard requirement for filling the 10-to-20 clip inventory. A clip without those signals must
still be a complete, engaging thought and pass the same framing, audio, subtitle, and duplicate
checks. Distinct moments from the same long interview may all qualify; the old one-clip-per-source
packaging bottleneck is removed. Set `SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL=1` for a narrower
signal-only run.

Editorial quota top-ups are incremental. Existing upload-ready packages in either `content` or
`archive` count toward the current date's target, and only newly rendered source moments are
packaged on the next pass. A top-up never rebuilds the same finished Short merely to recount it.

- `yt-dlp` fetches channel metadata without cookies for speed. Media downloads are authenticated by default so age-restricted videos do not get treated as ordinary skips. Firefox browser cookies are the default primary auth source; keep an exported, signed-in, age-verified `cookies.txt` only as the backup path when browser-cookie access is blocked. The local `.env` should pin the working Firefox profile and keep the cookie file as the second source:

```powershell
$env:SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK="1"
$env:SHORTFORM_YTDLP_AUTH_SOURCE_ORDER="browser,cookiefile"
$env:SHORTFORM_YTDLP_COOKIES_BROWSER="firefox:fPGLp4j9.Profile 1"
$env:SHORTFORM_YTDLP_COOKIES="C:\Users\Admin\Desktop\shortform\cookies.txt"  # backup only
```

Verify restricted-video access before a full run:

```powershell
.\venv_313\Scripts\python.exe .\ytdlp_auth.py
```

Strictly verify a newly exported cookie file before installing it:

```powershell
.\venv_313\Scripts\python.exe .\ytdlp_auth.py --diagnose-cookie-file "C:\Users\Admin\Downloads\www.youtube.com_cookies.txt"
.\venv_313\Scripts\python.exe .\ytdlp_auth.py --cookie-file "C:\Users\Admin\Downloads\www.youtube.com_cookies.txt"
.\venv_313\Scripts\python.exe .\ytdlp_auth.py --install-cookie-export "C:\Users\Admin\Downloads\www.youtube.com_cookies.txt"
```

You can also let the helper find the newest valid export in Downloads. It will only install a file after that exact file passes the restricted-video auth test:

```powershell
.\venv_313\Scripts\python.exe .\ytdlp_auth.py --scan-cookie-exports
.\venv_313\Scripts\python.exe .\ytdlp_auth.py --install-newest-cookie-export
```

`--cookie-file` and `--install-cookie-export` now prove that exact file unlocks the age-restricted test video. They do not silently pass because a browser-cookie fallback happened to work. `run.py --doctor` reports the strict project `cookies.txt` result and lists browser profiles for awareness. The pipeline reads the cookie file through a temporary copy and does not rewrite `cookies.txt`.

If the auth check still says `Sign in to confirm your age`, first make sure the selected Firefox profile can play the restricted test video and close Firefox fully before the run. If Firefox browser-cookie access is blocked, export a broader signed-in cookie file. A YouTube-only export can contain `SID`/`PSID` cookies and still fail age-gated videos; the most reliable export includes cookies for `youtube.com`, `google.com`, and `accounts.google.com` from the same signed-in, age-verified browser session. The project `cookies.txt` is the backup. The pipeline reads `cookies.txt` through a temporary copy and does not rewrite it. To disable browser-cookie access and use only the project cookie file, set:

```powershell
$env:SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK="0"
```

If you want a specific Firefox profile, set `SHORTFORM_YTDLP_COOKIES_BROWSER` to the full candidate shown by `.\venv_313\Scripts\python.exe .\ytdlp_auth.py --list-browser-profiles`, for example `firefox:fPGLp4j9.Profile 1`. You can also set `SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_PROFILE` to just the profile folder name. Do not run raw `yt-dlp --cookies .\cookies.txt` against the project cookie file during debugging; yt-dlp may rewrite the file. Use `ytdlp_auth.py --cookie-file ...` or copy the cookie file to `%TEMP%` first.

Video downloads may also require a YouTube PO-token provider. The pipeline auto-starts a local bgutil provider when this checkout exists:

```text
C:\Users\Admin\bgutil-ytdlp-pot-provider\server\build\main.js
```

Install/build it once with:

```powershell
git clone --single-branch --branch 1.3.1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$env:USERPROFILE\bgutil-ytdlp-pot-provider"
Push-Location "$env:USERPROFILE\bgutil-ytdlp-pot-provider\server"
npm ci
npx tsc
Pop-Location
.\venv_313\Scripts\python.exe -m pip install -U bgutil-ytdlp-pot-provider
```

`run.py --doctor` reports whether `http://127.0.0.1:4416/ping` is reachable.

The latest auth diagnostic is written to:

```text
logs/ytdlp_auth_latest.json
```

Set `SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA=0` only for quick public-video tests. Set `SHORTFORM_USE_COOKIES_FOR_FETCH=1` only if fetching channel metadata also needs authenticated cookies.
Restricted media auth is checked before a production run cleans or downloads anything. Restricted auth failures halt the run by default because age-gated videos are considered required inputs. Use `--skip-media-auth-preflight`, set `SHORTFORM_SKIP_MEDIA_AUTH_PREFLIGHT=1`, or set `SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA=0` only for quick public-video tests. Set `SHORTFORM_HALT_ON_RESTRICTED_DOWNLOAD_FAILURE=0` only if you intentionally want to skip blocked videos during a test run.

Media downloads default to `SHORTFORM_MEDIA_AUTH_POLICY=on_demand`: the run verifies age-gated cookie access first, then downloads public videos without cookies and retries with cookies only if YouTube asks for sign-in or returns an auth-like 403. This reduces authenticated request volume and helps preserve the session. Set `SHORTFORM_MEDIA_AUTH_POLICY=always` only if you intentionally want every media download to use cookies.

If you want to start the run before closing Firefox or installing a fresh backup cookie file, let the preflight wait instead of failing immediately:

```powershell
.\venv_313\Scripts\python.exe .\run.py --clean-slate --skip-youtube --wait-for-media-auth 900
```

The run will keep retrying restricted-video auth during that window. Close Firefox if the selected profile is locked, or install a stricter cookie export, and the same run will continue once the age-gated auth check passes.

If you want the run itself to watch Downloads for a fresh export while it waits, add `--watch-cookie-exports`:

```powershell
.\venv_313\Scripts\python.exe .\run.py --clean-slate --skip-youtube --wait-for-media-auth 900 --watch-cookie-exports
```

For Visual Studio or other launchers that do not inherit PowerShell `$env:` values, add the setting to a local `.env` file:

```text
SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK=1
SHORTFORM_YTDLP_AUTH_SOURCE_ORDER=browser,cookiefile
SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_BROWSER=firefox
SHORTFORM_YTDLP_COOKIES_BROWSER="firefox:fPGLp4j9.Profile 1"
SHORTFORM_YTDLP_COOKIES=C:\Users\Admin\Desktop\shortform\cookies.txt
SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA=1
```

- Face framing ignores low-frame hand/notebook false positives and locks only to plausible interview faces.
- Raw clips now run a pre-render visual QC pass. Clips with too many black frames or too little reliable face presence are skipped before the slower crop/mux/subtitle work. To force rendering while reviewing an edge case:

```powershell
$env:SHORTFORM_ALLOW_LOW_FACE_PREFLIGHT="1"
```

- Final renders are sampled after crop/mux and scored for black frames, low-information frames, dead/blank visual frames, alive-frame rate, face presence, face-box plausibility, off-center subjects, and camera jitter. Each render attempt writes a contact-sheet audit image here:

```text
output/temp/<theme>/metadata/frame_audits/
```

- Bad final renders are rejected by default after every crop strategy has been tried. Rejected clips keep QC details in the review JSON/CSV but do not count as generated clips and their bad working video is deleted. To loosen this while debugging:

```powershell
$env:SHORTFORM_HARD_REJECT_BAD_RENDERS="0"
$env:SHORTFORM_MIN_ACCEPTED_RENDER_VISUAL_QUALITY="0.55"
$env:SHORTFORM_DEAD_FRAME_RATIO_THRESHOLD="0.22"
$env:SHORTFORM_MIN_ALIVE_FRAME_RATE="0.68"
```

- If the face-locked crop looks risky, the renderer retries with stable-face-lock, group-face-lock, dual-speaker-stack, and center-safe crops, then keeps the attempt with the stronger visual quality score. `group_face_lock` only activates when multiple faces are visible together and close enough to fit. `dual_speaker_stack` uses a top/bottom split only while two strong speaker faces are visible and falls back to single framing when confidence drops. To disable these extra retries during speed-only tests:

```powershell
$env:SHORTFORM_ENABLE_ALTERNATE_FRAMING_RETRY="0"
```

- Clip review JSON now includes a `candidate_inventory` section that groups high-potential alternate clips by interview zone, signal type, and clip archetype. Source dossiers also include `clip_batch_plan.full_interview_milking_order`, a distinct ordered list of alternate clips for milking one strong interview without repeating the same topic.
- Comment relevance uses more than timestamps: liked/replied comments are reduced into weighted topic terms, then matched against transcript windows as `comment_topic_score`. This helps find moments people discussed even when comments do not include a timestamp.

- Optional YouTube Data API enrichment can add relevant/new comment threads, comment likes/replies, video stats, and timestamp mentions into the popularity profile. Add an API key when you want those public interaction signals:

```powershell
$env:YOUTUBE_DATA_API_KEY="your_api_key"
$env:SHORTFORM_ENABLE_YOUTUBE_DATA_API_SIGNALS="1"
$env:SHORTFORM_YOUTUBE_DATA_API_COMMENT_PAGES="1"
```

The pipeline still uses public replay heatmap metadata when yt-dlp exposes it. YouTube's private audience-retention analytics are generally only available for channels/content owners with permission, so third-party podcast selection uses public heatmaps, chapters, descriptions, comments, and transcript/audio quality instead.

Generate a quick quality-lab summary for clip reviews, source dossiers, visual QC flags, and interview-mining coverage:

```powershell
.\venv_313\Scripts\python.exe .\quality_lab.py --theme comedy
```

Reports are written to:

```text
logs/quality_lab/<theme>_quality_lab.json
logs/quality_lab_latest.json
```

The quality lab includes readiness metrics and a `source_mining_index`. Readiness tiers separate clips that are actually publishable (`elite` / `strong`) from clips that merely scored okay in a long transcript. Source mining tiers identify which interviews are worth milking deeply:

- `primary_milk_source`: already produced multiple selected publish-ready clips, or combines selected clips with strong external replay/timestamp evidence.
- `selective_source`: has at least one strong selected clip or unusually good candidate density, but should not automatically consume several upload slots.
- `thin_but_usable`: has some usable windows, but no selected publish-ready clips yet; only revisit after stronger sources are exhausted.
- `weak_source`: do not spend much daily upload budget here.

Verification/smoke-test artifacts are excluded by default so production reports are not polluted by calibration files. If `readiness_missing` is nonzero, those clips were scored before the readiness model existed and should be regenerated or rescored before making final production decisions. To backfill current readiness, topic, and candidate-inventory metadata into existing clip-review JSON files without re-downloading or re-rendering videos:

```powershell
.\venv_313\Scripts\python.exe .\rescore_clip_reviews.py --theme comedy
```

The rescore pass uses cached transcript/audio-feature files plus any cached public popularity profiles under `output/temp/<theme>/metadata/_popularity`. It refreshes clip reviews, candidate inventories, and source dossiers without re-downloading or re-rendering videos. The run report is written to:

```text
logs/rescore/<theme>_latest.json
```

To include verification artifacts while debugging:

```powershell
$env:SHORTFORM_QUALITY_LAB_INCLUDE_VERIFICATION="1"
.\venv_313\Scripts\python.exe .\quality_lab.py --theme comedy
```

That writes separate `*_with_verification.json` reports.

Source dossiers now include processing metrics, source-tier editorial decisions, and slow-source flags. A source is marked for slow review when scoring exceeds this threshold:

```powershell
$env:SHORTFORM_SLOW_SOURCE_REVIEW_SECONDS="1800"
```

Production review reports join the latest run log, run summary, output validation, quality-lab results, source dossiers, slowest sources, and visible failures:

```text
logs/production_reviews/production_review_latest.json
logs/production_reviews/production_review_<timestamp>.json
```

The production review also includes the latest theme-engine validation summary and links to per-theme analytics report files.

Run a local crop-strategy bakeoff on downloaded media to compare face-locked, stable-face-lock, group-face-lock, and center-safe framing:

```powershell
.\venv_313\Scripts\python.exe .\framing_lab.py --theme comedy --limit 1 --seconds 3
```

The framing lab writes a JSON report and per-strategy contact sheets:

```text
logs/framing_lab/<theme>/framing_lab_latest.json
logs/framing_lab/<theme>/audits/
```

- YOLO person fallback is disabled by default for speed and to avoid body/hand-driven framing. Enable it only when needed:

```powershell
$env:SHORTFORM_ENABLE_PERSON_FALLBACK="1"
```

- Clip discovery transcription uses `faster-whisper` before scoring candidates. Production defaults to the `base` model with beam `1`, reuses one loaded model, and caches by audio hash/model/version. Use `tiny` for faster tests, or `small` for slower but stronger transcript quality:

```powershell
$env:SHORTFORM_CLIP_TRANSCRIBE_MODEL="tiny"
$env:SHORTFORM_CLIP_TRANSCRIBE_BEAM_SIZE="1"
```

You can also switch the scoring profile in one setting:

```powershell
$env:SHORTFORM_SPEED_PROFILE="debug"      # tiny model, beam 1
$env:SHORTFORM_SPEED_PROFILE="production" # base model, beam 1
$env:SHORTFORM_SPEED_PROFILE="premium"    # small model, beam 5
```

Normal production is tuned for a roughly 12-hour all-theme cycle without a hard runtime cutoff. The default policy targets 10 finished clips per theme, keeps the YouTube upload cap at 15, preserves existing backlog, scores four to six newly discovered sources per theme, uses speech-optimized analysis audio, and uses one primary crop plus one inexpensive fallback. Editorial intros render at 24 fps over a sampled video background while the finished Short remains 1080p. It still rejects missing audio, dead or black frames, probable background-face locks, duplicates, and incomplete or unpublishable moments. High-scoring candidates that are not needed for the daily target remain resumable instead of triggering unlimited render overflow.

The deeper, slower behavior remains available through environment overrides:

```powershell
$env:SHORTFORM_PREFERRED_FINISHED_PER_THEME="20"
$env:SHORTFORM_ENABLE_EXPENSIVE_FRAMING_FALLBACKS="1"
$env:SHORTFORM_ALLOW_QUALITY_OVERFLOW="1"
$env:SHORTFORM_MAX_UNSCORED_SOURCES_PER_THEME="12"
```

Very long interviews use a capped candidate-window policy by default: full scan for shorter sources, then a bounded mix of replay/timestamp/chapter windows, high-audio-energy windows, and evenly spaced coverage for long sources. This keeps daily production from spending hours scoring every possible window in a multi-hour interview.

```powershell
$env:SHORTFORM_ENABLE_SCORING_WINDOW_CAPS="1"
$env:SHORTFORM_FULL_SOURCE_SCAN_MAX_SECONDS="5400"
$env:SHORTFORM_MAX_SCORING_START_POINTS="120"
```

Set `SHORTFORM_ENABLE_SCORING_WINDOW_CAPS=0` for exhaustive scans, or use `SHORTFORM_SPEED_PROFILE=premium` for a deeper cap.

- Subtitle transcription uses `faster-whisper` with word timestamps. The default subtitle beam is `1` for speed. Increase it only if subtitle accuracy needs it:

```powershell
$env:SHORTFORM_SUBTITLE_BEAM_SIZE="5"
$env:SHORTFORM_SUBTITLE_BEST_OF="5"
```

- Finished upload clips are skipped on reruns by default. To regenerate subtitle burn-ins:

```powershell
$env:SHORTFORM_REGENERATE_UPLOAD_CLIPS="1"
```

- `src/pulled.json` and `src/executed_id.json` include stage timestamps for fetched videos, clip generation, and completed upload-ready clips.
- A source video is added to `src/executed_id.json` only after all rendered clips for that source have upload-ready outputs. Once complete, matching temp downloads, audio, transcripts, working clips, subtitle scratch files, and clip review files are deleted from `output/temp/<theme>`.
- If a source video is already listed in `src/executed_id.json`, later runs skip it and clean any leftover matching temp files.
- Downloads default to 1080p source files and first prefer fast MP4/H.264 + M4A/AAC packages when YouTube offers them. If not, the downloader falls back to any available 1080p package for success, including AV1/Opus. Extracted audio is stream-copied into a compatible analysis package such as `.m4a`, `.opus`, or `.mp3`; full audio transcoding is only a last-resort fallback. To lower source quality for faster testing:

```powershell
$env:SHORTFORM_SOURCE_MAX_HEIGHT="720"
```

- If YouTube/DNS starts failing repeatedly, clip generation stops the current theme after two consecutive network failures instead of slowly trying every remaining video. Override with:

```powershell
$env:SHORTFORM_MAX_NETWORK_FAILURES="4"
```

## Themes

Themes are JSON files in `src/themes`. They now use the theme-engine schema: every theme can define its own source list, clip duration rules, scoring signals, packaging/intro style, metadata style, risk controls, review policy, and analytics targets.

Phase-one production runs default to nine upload-routed themes: comedy, sports, gaming, finance/business, technology/AI, health and self-improvement, politics/news, pop culture/entertainment, and true crime/legal. Other JSON theme files are retained as future inventory. They do not run in default production, and even `--theme`, `SHORTFORM_ACTIVE_THEMES`, or `SHORTFORM_RUN_ALL_THEMES=1` stay phase-one unless `SHORTFORM_ALLOW_FUTURE_THEMES=1` is also set.

Example:

```json
{
    "theme": "sports",
    "profile": "sports",
    "brand": {
        "channel_name": "The Sports Archive",
        "positioning": "The best athlete debates, stories, rivalries, and legacy arguments clipped with context."
    },
    "channels": [
        "https://www.youtube.com/@newheightshow/videos"
    ],
    "clip_rules": {
        "candidate_durations": [15, 24, 35, 45],
        "min_clip_duration": 12,
        "max_clip_duration": 55,
        "min_readiness_score": 0.66
    },
    "packaging": {
        "default_intro_mode": "context_card",
        "caption_style": "bold_sports"
    }
}
```

Research notes and the portfolio rationale live here:

```text
docs/theme_engine_research_2026.md
```

Only themes with `youtube.channel_handle` and an authenticated token file are allowed to upload. Generation can run for phase-one themes without upload routing; those themes skip YouTube upload until their theme JSON has a configured `youtube.channel_handle`. Restricted media auth still runs for production generation unless you intentionally disable it for public-video tests.

## Run

Run all themes end-to-end. Each theme runs fetch, clip generation, ranked countdown generation, and upload before the next theme starts:

```powershell
.\venv_313\Scripts\python.exe run.py
```

Start from a clean generated-output slate for the active phase-one themes:

```powershell
.\venv_313\Scripts\python.exe run.py --clean-slate --skip-youtube
```

To only clear generated final clips, working clips, subtitle scratch files, editorial metadata, and funnel state without starting production:

```powershell
.\venv_313\Scripts\python.exe run.py --clean-slate-only --skip-youtube
```

The runner prints per-theme and overall timing summaries for pull, clip, countdown/editorial, subtitle, upload, and total runtime. It also writes full run logs:

```text
logs/run_latest.log
logs/run_latest_summary.json
logs/runs/run_<timestamp>.log
```

`run_latest.log` resets on every run. The timestamped files keep the long-term history.

Run one theme through fetch, clip generation, ranked countdown generation, and YouTube upload:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy
```

Audit the implementation against the phase-one theme-engine brief:

```powershell
.\venv_313\Scripts\python.exe run.py --theme-engine-audit
```

The audit also checks the latest visual regression pack, so run `--visual-regression` after changing intro animation code.

Generate classic raw subtitled clips in addition to the ranked countdown package:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy --classic-clips
```

Classic raw subtitled clips are review/debug artifacts by default. The production editorial gate blocks raw recycler clips from upload metadata unless you intentionally set:

```powershell
$env:SHORTFORM_ALLOW_RAW_CLIP_UPLOADS="1"
```

Skip the editorial recap and run the older classic clip packaging path:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy --skip-editorial
```

Run one theme without uploading:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy --skip-youtube
```

Upload only existing finished clips without rerunning fetch/clip/subtitle work:

```powershell
.\venv_313\Scripts\python.exe upload.py --theme sports
```

Limit a first upload test to one clip:

```powershell
.\venv_313\Scripts\python.exe upload.py --theme sports --limit 1
```

Upload the comedy theme to the @TheJokeArchive channel:

```powershell
.\venv_313\Scripts\python.exe upload.py --theme comedy --limit 1
```

Upload every discovered theme intentionally:

```powershell
.\venv_313\Scripts\python.exe upload.py --all
```

## Daily Editorial Recaps

By default, each theme/channel produces an original ranked countdown package instead of uploading raw podcast clips. The flow is:

1. Download audio only for each candidate source video.
2. Transcribe and score clips across the whole theme.
3. Keep the strongest evidence clips.
4. Download only the selected video timestamp sections.
5. Cluster rendered clips into a ranked countdown package.
6. Rotate one daily reel angle automatically, such as `most surprising`, `most heated`, `smartest`, or `most controversial`.
7. Generate a short AI setup hook that tees up the specific clip topic instead of repeating watched-hours narration.
8. Render countdown Shorts with an animated scan board, interview banners, survivor board, played/future state, rank card, and full source audio after the setup. The watched-hours/source-count context stays visual only.
9. Render a separate popular-segment video type when replay/popularity signals exist for a source interview.
10. Optionally stitch the countdown Shorts into a full daily recap compilation.

Generated files:

```text
output/temp/<theme>/metadata/editorial/<date>/daily_brief.json
output/themes/<theme>/content/*_countdown_*_upload.mp4
output/themes/<theme>/content/*_popular_*_upload.mp4
output/themes/<theme>/content/*_full_daily_recap_upload.mp4
output/themes/<theme>/metadata.json
```

Controls:

```powershell
$env:SHORTFORM_DAILY_TOPIC_COUNT="10"
$env:SHORTFORM_EDITORIAL_COUNTDOWN_SIZE="5"
$env:SHORTFORM_EDITORIAL_CLIPS_PER_SHORT="1"
$env:SHORTFORM_EDITORIAL_RENDER_RECAP="1"
$env:SHORTFORM_EDITORIAL_APPEND_METADATA="0"
$env:SHORTFORM_TTS_PROVIDER="elevenlabs"
$env:ELEVENLABS_API_KEY="your_elevenlabs_api_key"
$env:ELEVENLABS_VOICE_ID="HAM2nE4sbHnPgMji6JqB"
$env:ELEVENLABS_MODEL_ID="eleven_v3"
$env:ELEVENLABS_OUTPUT_FORMAT="mp3_44100_192"
$env:SHORTFORM_EDITORIAL_INTRO_SECONDS="5.2"
$env:SHORTFORM_EDITORIAL_INTRO_MAX_SECONDS="6.25"
$env:SHORTFORM_EDITORIAL_RANK_CARD_SECONDS="1"
$env:SHORTFORM_EDITORIAL_INTRO_SOURCE_AUDIO_VOLUME="0.025"
$env:SHORTFORM_EDITORIAL_CLIP_AUDIO_VOLUME="1.0"
$env:SHORTFORM_EDITORIAL_PERIOD_LABEL="this week"
$env:SHORTFORM_EDITORIAL_TRANSITION_SECONDS="0.45"
$env:SHORTFORM_EDITORIAL_BOARD_SOURCE_LIMIT="12"
$env:SHORTFORM_DOWNLOAD_VIDEO_SECTIONS="1"
$env:SHORTFORM_VIDEO_SECTION_PADDING_SECONDS="1.25"
$env:SHORTFORM_CLEANUP_VIDEO_SECTIONS="1"
```

`SHORTFORM_EDITORIAL_APPEND_METADATA=0` replaces upload metadata with the daily editorial outputs so old raw clips do not get uploaded by accident.

Finished editorial countdowns, popular-segment shorts, and recap compilations also run a post-render visual gate before upload metadata is saved. Files with dead frames or low editorial visual quality are marked failed, deleted by default, and listed in `daily_brief.json` under `rejected_items`. To keep rejected files while debugging:

```powershell
$env:SHORTFORM_EDITORIAL_HARD_REJECT_BAD_OUTPUTS="0"
$env:SHORTFORM_MIN_EDITORIAL_VISUAL_QUALITY="0.55"
$env:SHORTFORM_ENABLE_SECONDARY_FINAL_FRAME_QC="1"
$env:SHORTFORM_SECONDARY_FINAL_FRAME_QC_MAX_FRAMES="10"
```

The secondary final-frame QC samples the completed upload package with the same contact-sheet analyzer used by `content_qc.py`. It catches issues such as off-center speakers, weak face/speaker continuity, and background/object locks that may not be obvious from the source clip alone.

Editorial gating prioritizes watchability over perfect brand/topic purity. `SHORTFORM_RELAX_THEME_RELEVANCE_GATES=1` is the default: configured source channels are treated as enough brand context, so clips are not rejected just because the transcript does not contain theme keywords. Title/caption QA, burned captions, duplicate source prevention, dead/black frames, obvious background locks, and intro-audio safety remain hard gates. A final source segment ending without a strong face is recorded for review, but it is no longer a standalone upload blocker.

`run.py --validate-outputs` fails if final metadata still contains `needs_revision` or `rejected` packages, because those are not upload-ready. To inspect revision artifacts during debugging without failing validation:

```powershell
$env:SHORTFORM_VALIDATE_ALLOW_REVISION_OUTPUTS="1"
```

ElevenLabs is the production default for the setup voice. The default voice ID is `HAM2nE4sbHnPgMji6JqB`. Countdown setup narration is intentionally short and clear: `Number X: [short hook]`, then the viewer reads the on-screen title and the source audio takes over. Popular-segment shorts use the same restraint with a brief `Standout: [short hook]` line. The pipeline no longer speeds narration aggressively, pitches it down, or adds artificial bass; `SHORTFORM_NARRATION_MAX_TEMPO` defaults to natural speed and is capped to keep speech understandable, while `SHORTFORM_NARRATION_PITCH=1.0` and `SHORTFORM_NARRATION_BASS_GAIN=0.0` preserve the cloned voice. It still adds a preserved lead-in, fade-in, and tail pad so the first and last syllables are not clipped. Tune those with `SHORTFORM_NARRATION_LEAD_IN_SECONDS`, `SHORTFORM_NARRATION_FADE_IN_SECONDS`, and `SHORTFORM_NARRATION_TAIL_PAD_SECONDS`. Set `SHORTFORM_ELEVENLABS_FALLBACK_VOICE_IDS` only if you intentionally want backup ElevenLabs voices. If `ELEVENLABS_API_KEY` is missing, the script falls back to the local Windows voice so test renders can still complete, but that fallback should not be used for channel uploads.

Popular-segment videos are controlled separately:

```powershell
$env:SHORTFORM_RENDER_POPULAR_SEGMENTS="1"
$env:SHORTFORM_ENABLE_POPULARITY_SCORING="1"
$env:SHORTFORM_POPULAR_SEGMENTS_PER_THEME="0"
$env:SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL="1"
$env:SHORTFORM_POPULAR_SEGMENT_MIN_SCORE="0.12"
```

`SHORTFORM_POPULAR_SEGMENTS_PER_THEME=0` means there is no fixed per-theme cap for this extra video type. By default, popular-style shorts require a real public replay/timestamp/chapter signal above `SHORTFORM_POPULAR_SEGMENT_MIN_SCORE`; fallback-only internal picks stay in the normal editorial queue instead of being packaged as popular/replayed clips. Set `SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL=0` only for debugging, or set `SHORTFORM_POPULAR_SEGMENTS_PER_THEME` to a positive number if you intentionally want a cap for this extra video type.

Daily adjectives rotate through a 20-item queue per theme and are stored in:

```text
src/adjective_rotation.json
```

Each generated editorial Short consumes the next adjective and moves it to the end of the queue, so the same adjective is reused only after the other 19 have been used for that theme.

## Clip Volume And Upload Limits

The pipeline defaults to quality-threshold selection: each theme generates every clip that clears the scoring, framing, title, caption, and editorial upload gates. `theme_clip_budget: 0` means unlimited, and production theme validation requires this value. The goal is to make every publishable clip, not to stop at a fixed number.

Debug-only local caps still exist for short smoke tests, but they should not be enabled for production runs:

```powershell
$env:SHORTFORM_ENFORCE_THEME_CLIP_BUDGET="1"
$env:SHORTFORM_ALLOW_THEME_CLIP_CAP="1"
$env:SHORTFORM_THEME_CLIP_BUDGET="3"
```

Source candidate pruning is also disabled by default. This lets one exceptional interview contribute every distinct clip that clears the minimum upload threshold instead of stopping at an arbitrary top 10 or top 15. For a short debugging smoke test, you can intentionally cap the number of ranked candidates retained from each source:

```powershell
$env:SHORTFORM_SOURCE_CANDIDATE_CAP="8"
```

Legacy `theme_candidates_per_video` values in theme JSON are kept for metadata compatibility, but production ignores them unless `SHORTFORM_RESPECT_LEGACY_THEME_CANDIDATES_PER_VIDEO=1` is explicitly set.

To disable theme-wide ranking and return to per-video clip generation:

```powershell
$env:SHORTFORM_ENABLE_THEME_GLOBAL_RANKING="0"
```

YouTube can still enforce its own upload limits. The local uploader defaults to a 15-video upload queue per theme/channel so production does not intentionally run into the known daily API/channel limit. Generation can still create more than 15 qualified clips; overflow clips are moved into:

```text
output/themes/<theme>/archive
```

Those archived clips keep their metadata in `output/themes/<theme>/metadata.json` under `archive`. When the live `content` queue is empty, the manifest/uploader promotes archived clips back into `content` for the next upload batch, and uploaded files are deleted locally after YouTube accepts them. To change the local upload queue cap, set:

```powershell
$env:SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT="15"
```

When YouTube returns `uploadLimitExceeded`, the uploader records a conservative cooldown in:

```text
logs/youtube_upload_cooldowns.json
```

The default retry estimate is 24 hours after the limit error. During that window, `run.py` and `upload.py` skip upload attempts for the affected theme/channel so a production run does not waste time on guaranteed failures. To change or bypass that behavior for a deliberate manual test:

```powershell
$env:SHORTFORM_YOUTUBE_UPLOAD_LIMIT_COOLDOWN_HOURS="24"
$env:SHORTFORM_IGNORE_YOUTUBE_UPLOAD_COOLDOWN="1"
```

Sources that are scored but do not make the theme-wide cut are marked as `clips_ranked_not_selected` so future runs do not repeatedly spend hours on the same weaker sources. To reconsider them after tuning the scoring model:

```powershell
$env:SHORTFORM_RECONSIDER_UNSELECTED="1"
```

## YouTube OAuth

Install the upload dependencies once:

```powershell
.\venv_313\Scripts\python.exe -m pip install -r requirements.txt
```

The uploader uses this OAuth client ID by default:

```text
690163065093-9l55nu1kn2te6k1eqltn69bnpj872lke.apps.googleusercontent.com
```

The most reliable setup is to download the OAuth client JSON from Google Cloud and save it as:

```text
client_secrets.json
```

That file and the generated `youtube_token*.json` files are ignored by Git. On the first upload, a browser OAuth window will open and the token will be saved locally for future runs.

If you do not use `client_secrets.json`, set both `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` in your environment. Google Desktop app OAuth clients still require the client secret during token exchange.

Upload routing can live in each theme file. For example:

```json
{
  "theme": "comedy",
  "youtube": {
    "channel_handle": "@TheJokeArchive",
    "token_file": "youtube_token_comedy.json"
  },
  "channels": []
}
```

The uploader checks the authenticated YouTube channel before uploading. If a theme has a `youtube.channel_handle`, it uses that handle and stores OAuth in the theme's configured `token_file`. If `token_file` is omitted, the uploader defaults to `youtube_token_<theme>.json`.

Every uploading theme must have a `youtube.channel_handle` in its theme JSON; this prevents a theme from accidentally uploading to the wrong channel.

YouTube uploads are created with `privacyStatus=public` by default so they are instantly viewable. Set `SHORTFORM_YOUTUBE_PRIVACY_STATUS=private` or `SHORTFORM_YOUTUBE_PRIVACY_STATUS=unlisted` when you intentionally want a non-public test run.

## Output

The output folder is organized into temp work and finished theme content:

```text
output/
  temp/
    <theme>/
      downloads/
      transcripts/
      clips/
      subtitles/
      metadata/
  themes/
    <theme>/
      content/
      metadata.json
```

Final subtitled clips live in:

```text
output/themes/<theme>/content
```

Titles, descriptions, captions, tags, hashtags, platform copy, review fields, metrics placeholders, hook reasons, and score details live in:

```text
output/themes/<theme>/metadata.json
```

Generated media, runtime registries, transcripts, models, credentials, and runtime output are ignored by Git.
