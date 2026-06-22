# shortform

Version 1.1 short-form clip generation pipeline.

## Pipeline

`run.py` is the master runner. It runs:

1. `video_fetch.py` reads theme JSON files from `src/themes` and records latest videos in `src/pulled.json`.
2. `clip_generation.py` downloads/reuses media, scores clips, and renders vertical working clips.
3. `subtitle_generation.py` burns subtitles, saves finished clips, writes theme metadata, and marks completed videos in `src/executed_id.json`.
4. `upload.py` uploads ready clips to the theme's configured YouTube channel as private drafts.

Use `--skip-youtube` when you want to prepare upload-ready clips without uploading.

Run a health check before a long production run:

```powershell
.\venv_313\Scripts\python.exe .\run.py --doctor
```

Validate generated files and upload metadata after a run:

```powershell
.\venv_313\Scripts\python.exe .\run.py --validate-outputs
```

## Quality And Speed Controls

- `yt-dlp` fetches channel metadata without cookies for speed. Media downloads are authenticated by default so age-restricted videos do not get treated as ordinary skips. Use an exported, signed-in, age-verified YouTube cookie file for the most reliable age-gated downloads:

```powershell
$env:SHORTFORM_YTDLP_COOKIES="C:\Users\Admin\Desktop\shortform\cookies.txt"
```

Verify restricted-video access before a full run:

```powershell
.\venv_313\Scripts\python.exe .\ytdlp_auth.py
```

Set `SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA=0` only for quick public-video tests. Set `SHORTFORM_USE_COOKIES_FOR_FETCH=1` only if fetching channel metadata also needs authenticated cookies.
Restricted auth failures halt the clip stage by default because age-gated videos are considered required inputs. Set `SHORTFORM_HALT_ON_RESTRICTED_DOWNLOAD_FAILURE=0` only if you intentionally want to skip blocked videos during a test run.

For Visual Studio or other launchers that do not inherit PowerShell `$env:` values, add the setting to a local `.env` file:

```text
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

- Clip discovery transcription uses `faster-whisper` before scoring candidates. It defaults to the `base` model with beam `3` so clip selection has cleaner sentence boundaries than the old tiny pass. Use `tiny` for faster tests, or `small` for slower but stronger transcript quality:

```powershell
$env:SHORTFORM_CLIP_TRANSCRIBE_MODEL="tiny"
$env:SHORTFORM_CLIP_TRANSCRIBE_BEAM_SIZE="1"
```

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

Themes are JSON files in `src/themes`.

Current themes:

- `src/themes/self_improvement.json`
- `src/themes/sports.json`
- `src/themes/comedy.json`
- `src/themes/finance.json`

Example:

```json
{
    "theme": "sports",
    "channels": [
        "https://www.youtube.com/@newheightshow/videos"
    ]
}
```

## Run

Run all themes end-to-end. Each theme runs fetch, clip generation, ranked countdown generation, and upload before the next theme starts:

```powershell
.\venv_313\Scripts\python.exe run.py
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

Generate classic raw subtitled clips in addition to the ranked countdown package:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy --classic-clips
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
5. Cluster rendered clips into a top-five ranked countdown.
6. Rotate one daily reel angle automatically, such as `most surprising`, `most heated`, `smartest`, or `most controversial`.
7. Generate the AI setup line: `I watched XX hours of <theme> interviews this week, so you don't have to...`
8. Render countdown Shorts with an animated scan board, interview banners, top-five survivor board, played/future state, rank card, and full source audio after the setup.
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
$env:ELEVENLABS_VOICE_ID="hnhZe040y4V3QPXXZVDO"
$env:ELEVENLABS_MODEL_ID="eleven_v3"
$env:ELEVENLABS_OUTPUT_FORMAT="mp3_44100_128"
$env:SHORTFORM_EDITORIAL_INTRO_MAX_SECONDS="11.5"
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
```

ElevenLabs is the production default for the setup voice. The default voice ID is `hnhZe040y4V3QPXXZVDO`. The pipeline does not pitch that voice down by default; set `SHORTFORM_NARRATION_PITCH` only if you intentionally want post-processing. No alternate ElevenLabs voices are used by default. Set `SHORTFORM_ELEVENLABS_FALLBACK_VOICE_IDS` only if you intentionally want backup ElevenLabs voices. If `ELEVENLABS_API_KEY` is missing, the script falls back to the local Windows voice so test renders can still complete, but that fallback should not be used for channel uploads.

Popular-segment videos are controlled separately:

```powershell
$env:SHORTFORM_RENDER_POPULAR_SEGMENTS="1"
$env:SHORTFORM_ENABLE_POPULARITY_SCORING="1"
$env:SHORTFORM_POPULAR_SEGMENTS_PER_THEME="0"
$env:SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL="0"
$env:SHORTFORM_POPULAR_SEGMENT_MIN_SCORE="0.12"
```

`SHORTFORM_POPULAR_SEGMENTS_PER_THEME=0` means one popular-style short can be generated for every source interview that has rendered clips. When YouTube exposes replay heatmap, timestamp, or chapter signals, the video is labeled as replay/popularity-backed. Otherwise it falls back to the strongest internally scored moment and labels it as `BEST MOMENT`. Set `SHORTFORM_POPULAR_SEGMENT_REQUIRE_SIGNAL=1` if you only want public replay/popularity-backed shorts, or set `SHORTFORM_POPULAR_SEGMENTS_PER_THEME` to a positive number to cap the extra video type per theme.

Daily adjectives rotate through a 20-item queue per theme and are stored in:

```text
src/adjective_rotation.json
```

Each generated editorial Short consumes the next adjective and moves it to the end of the queue, so the same adjective is reused only after the other 19 have been used for that theme.

## Daily Upload Budget

YouTube can limit how many videos a channel uploads in a 24-hour period. The pipeline therefore defaults to a 15-clip budget per theme and a 15-upload cap per theme run.

To change the clip selection budget:

```powershell
$env:SHORTFORM_THEME_CLIP_BUDGET="15"
```

To change the number of top candidates retained from each source video before theme-wide ranking:

```powershell
$env:SHORTFORM_THEME_CANDIDATES_PER_VIDEO="8"
```

To disable theme-wide ranking and return to per-video clip generation:

```powershell
$env:SHORTFORM_ENABLE_THEME_GLOBAL_RANKING="0"
```

To change the upload cap, or set it to `0` for no local cap:

```powershell
$env:SHORTFORM_YOUTUBE_DAILY_UPLOAD_LIMIT="15"
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

YouTube uploads are created with `privacyStatus=private`, which makes them draft-like: they are uploaded with title, description, tags, and metadata, but are not public until you publish them in YouTube Studio.

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
