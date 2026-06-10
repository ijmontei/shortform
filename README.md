# shortform

Version 1.1 short-form clip generation pipeline.

## Pipeline

1. `video_fetch.py` reads theme JSON files from `src/themes` and records the latest videos in `src/pulled.json`.
2. `clip_generation.py` downloads/reuses media, scores non-overlapping clip candidates, and renders vertical working clips.
3. `subtitle_generation.py` burns upload-ready subtitles, saves finished videos, writes social metadata, and marks completed source videos in `src/executed_id.json`.

`run.py` runs fetch, clip generation, and subtitle generation. Actual social uploading is intentionally not part of the default run yet.

## Themes

Theme files live in `src/themes`.

Current themes:

- `src/themes/self_improvement.json`
- `src/themes/sports.json`
- `src/themes/finance.json`

Each theme JSON contains:

```json
{
    "theme": "sports",
    "channels": [
        "https://www.youtube.com/@newheightshow/videos"
    ]
}
```

Useful commands:

```powershell
.\venv_313\Scripts\python.exe manage_themes.py list
.\venv_313\Scripts\python.exe manage_themes.py create religion
.\venv_313\Scripts\python.exe manage_themes.py add-channel religion https://www.youtube.com/@Example/videos
```

Run all themes:

```powershell
Remove-Item Env:SHORTFORM_THEME -ErrorAction SilentlyContinue
.\venv_313\Scripts\python.exe run.py
```

Run one theme:

```powershell
$env:SHORTFORM_THEME="sports"
.\venv_313\Scripts\python.exe run.py
```

## Output

Finished outputs are organized by theme:

```text
output/
  self_improvement/
    videos/
    metadata/
  sports/
    videos/
    metadata/
  finance/
    videos/
    metadata/
  _work/
    <theme>/
      downloads/
      transcripts/
      clips/
      subtitles/
```

Final subtitled clips are saved in `output/<theme>/videos`.

Titles, captions, tags, hashtags, platform copy, hook reasons, score details, and upload manifests are saved in `output/<theme>/metadata`.

Generated media, runtime registries, transcripts, models, credentials, and runtime output are ignored by Git.
