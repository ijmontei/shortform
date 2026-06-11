# shortform

Version 1.1 short-form clip generation pipeline.

## Pipeline

`run.py` is the master runner. It runs:

1. `video_fetch.py` reads theme JSON files from `src/themes` and records latest videos in `src/pulled.json`.
2. `clip_generation.py` downloads/reuses media, scores clips, and renders vertical working clips.
3. `subtitle_generation.py` burns subtitles, saves finished clips, writes theme metadata, and marks completed videos in `src/executed_id.json`.

Actual social uploading is intentionally separate for now.

## Quality And Speed Controls

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

## Themes

Themes are JSON files in `src/themes`.

Current themes:

- `src/themes/self_improvement.json`
- `src/themes/sports.json`
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

Run all themes:

```powershell
.\venv_313\Scripts\python.exe run.py
```

Run one theme:

```powershell
.\venv_313\Scripts\python.exe run.py --theme sports
```

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
