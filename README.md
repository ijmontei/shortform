# shortform

Version 1.1 short-form clip generation pipeline.

## Pipeline

`run.py` is the master runner. It runs:

1. `video_fetch.py` reads theme JSON files from `src/themes` and records latest videos in `src/pulled.json`.
2. `clip_generation.py` downloads/reuses media, scores clips, and renders vertical working clips.
3. `subtitle_generation.py` burns subtitles, saves finished clips, writes theme metadata, and marks completed videos in `src/executed_id.json`.
4. `upload.py` uploads ready clips to the theme's configured YouTube channel as private drafts.

Use `--skip-youtube` when you want to prepare upload-ready clips without uploading.

## Quality And Speed Controls

- `yt-dlp` uses Chrome cookies by default, then Edge and Firefox if Chrome cookies are locked, so signed-in or age-gated videos can download when your browser is logged into YouTube. Close the browser if Windows locks its cookie database, or use an exported cookie file:

```powershell
$env:SHORTFORM_YTDLP_COOKIES_BROWSER="chrome,edge,firefox"
$env:SHORTFORM_YTDLP_COOKIES="C:\Users\Admin\Desktop\shortform\cookies.txt"
```

Set `SHORTFORM_DISABLE_BROWSER_COOKIES=1` to disable browser cookie access.

- Face framing ignores low-frame hand/notebook false positives and locks only to plausible interview faces.
- Raw clips now run a pre-render visual QC pass. Clips with too many black frames or too little reliable face presence are skipped before the slower crop/mux/subtitle work. To force rendering while reviewing an edge case:

```powershell
$env:SHORTFORM_ALLOW_LOW_FACE_PREFLIGHT="1"
```

- YOLO person fallback is disabled by default for speed and to avoid body/hand-driven framing. Enable it only when needed:

```powershell
$env:SHORTFORM_ENABLE_PERSON_FALLBACK="1"
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
- Downloads default to 720p source files for speed and use shorter network timeouts, retries, resume support, chunking, and IPv4 by default. To force heavier source quality:

```powershell
$env:SHORTFORM_SOURCE_MAX_HEIGHT="1080"
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

Run all themes end-to-end. Each theme runs fetch, clip generation, subtitle generation, and upload before the next theme starts:

```powershell
.\venv_313\Scripts\python.exe run.py
```

The runner prints per-theme and overall timing summaries for pull, clip, subtitle, upload, and total runtime.

Run one theme through fetch, clip generation, subtitle generation, and YouTube upload:

```powershell
.\venv_313\Scripts\python.exe run.py --theme comedy
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

The comedy theme uses `youtube_token_comedy.json`, so it can stay authorized to the @TheJokeArchive channel separately from other themes. The uploader checks the authenticated channel before uploading comedy clips.

The finance theme uses `youtube_token_finance.json`, so it can stay authorized to the @TheEconomistArchive channel separately from other themes. The uploader checks the authenticated channel before uploading finance clips.

Every uploading theme must be configured in `THEME_CHANNEL_HANDLES` and `THEME_TOKEN_FILES` in `upload.py`; this prevents a theme from accidentally uploading to the wrong channel.

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
