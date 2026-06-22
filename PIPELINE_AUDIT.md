# Shortform Pipeline Audit

Last updated: 2026-06-21

## Implemented Improvements

1. Atomic JSON state writes
   - `theme_config.write_json_file` now writes through a temporary file and replaces the target atomically.
   - Protects `src/pulled.json`, `src/executed_id.json`, and theme metadata from partial writes if a long run is interrupted.

2. Strict restricted-video authentication
   - `ytdlp_auth.py` centralizes cookie file and browser-cookie fallback behavior.
   - `run.py` runs a restricted-video auth preflight before production work.
   - `clip_generation.py` halts on restricted-video auth failure by default instead of silently skipping required age-gated sources.

3. Theme-level YouTube routing
   - Theme JSON files can now include:

```json
{
  "youtube": {
    "channel_handle": "@TheChannelHandle",
    "token_file": "youtube_token_theme.json"
  }
}
```

   - `upload.py` reads that config and falls back to `youtube_token_<theme>.json` when no explicit token file is set.
   - Comedy and finance are configured this way.

4. Pipeline doctor
   - `run.py --doctor` checks Python, FFmpeg, FFprobe, yt-dlp, theme config, YouTube routing, and restricted-video authentication.
   - This prevents wasting hours before discovering a missing dependency or bad auth source.

5. Clearer run failure output
   - Restricted-video auth failures now exit with the actionable message, and the run summary stores that message instead of only `"1"`.

6. Output validation
   - `validate_outputs.py` checks generated video paths, dimensions, duration, and upload-ready metadata status.
   - It is available through:

```powershell
.\venv_313\Scripts\python.exe .\run.py --validate-outputs
```

## Current Blockers

1. Restricted-video authentication does not pass on this machine yet.
   - `cookies.txt` is present but does not unlock the known age-gated test video.
   - Chrome browser-cookie extraction cannot copy the cookie database.
   - Edge browser-cookie extraction fails DPAPI decryption.
   - Fix: export a fresh signed-in, age-verified YouTube Netscape cookie file to `C:\Users\Admin\Desktop\shortform\cookies.txt`, then run:

```powershell
.\venv_313\Scripts\python.exe .\ytdlp_auth.py
```

2. New themes need YouTube channel routing before upload.
   - `gaming`, `lifestyle`, and `sports` have channels to pull from, but no upload destination yet.
   - Add `youtube.channel_handle` to each theme JSON once those channels exist.

## Recommended Next Enhancements

1. Add per-theme upload caps and daily selection policy in theme JSON.
2. Add a compact historical QC report artifact for every output validation run.
3. Add a source-level retry queue for temporary HTTP 403/network failures.
4. Add a quota-aware upload scheduler so YouTube upload caps do not require manual reruns.
5. Add lightweight unit tests for theme config loading, upload routing, and auth-source selection.
