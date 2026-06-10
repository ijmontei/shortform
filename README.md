# shortform

Version 1 short-form clip generation pipeline.

## Pipeline

1. `video_fetch.py` collects the latest videos from `src/channels.txt`.
2. `clip_generation.py` downloads/reuses media, scores non-overlapping clip candidates, and renders vertical clips.
3. `subtitle_generation.py` burns upload-ready subtitles into clips and writes finished videos to `output/upload`.
4. `upload.py` can upload finished videos when YouTube API credentials and dependencies are configured.

## V1 Quality Features

- Face-first interview framing with YOLO fallback.
- Audio + transcript scoring for high-interest clips.
- Comment-potential scoring for polarizing or debate-worthy moments.
- Segment-boundary clip starts/ends to avoid mid-thought cuts.
- Natural boundary repair when a candidate starts with weak context words.
- Duplicate-topic avoidance so a batch of clips covers more distinct moments.
- Render QC for duration, resolution, audio presence, black frames, and framing stability.
- Review exports in `output/metadata` with score breakdowns, hook reasons, suggested titles, captions, hashtags, and QC flags.
- Montserrat captions bundled in `assets/fonts`.
- High-contrast word-timed subtitles with subtle active-word scaling.

Generated media, transcripts, models, credentials, and runtime output are ignored by Git.
