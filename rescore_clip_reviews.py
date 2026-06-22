import argparse
import os
import time

import clip_generation
from popularity_signals import load_cached_popularity_profile
from theme_config import BASE_DIR, PULLED_FILE, ensure_theme, load_json_file, utc_timestamp, write_json_file


VERIFICATION_NAME_MARKERS = (
    "_verification",
    "_smoke",
    "_debug",
    "_test",
)


def is_verification_artifact(path):
    name = os.path.basename(str(path or "")).lower()
    return any(marker in name for marker in VERIFICATION_NAME_MARKERS)


def clean_title_from_review(path):
    filename = os.path.basename(path)
    suffix = "_clip_review.json"

    if filename.endswith(suffix):
        return filename[:-len(suffix)]

    return os.path.splitext(filename)[0]


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def overlap_seconds(left_start, left_end, right_start, right_end):
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def match_candidate(selected_clip, candidates):
    if not candidates:
        return None, {}

    selected_start = numeric(selected_clip.get("start_time"))
    selected_end = numeric(selected_clip.get("end_time"))

    if selected_end <= selected_start:
        selected_end = selected_start + numeric(selected_clip.get("duration"), 0.0)

    best_candidate = None
    best_match = None

    for candidate in candidates:
        candidate_start = float(candidate.start_time)
        candidate_end = float(candidate.end_time)
        overlap = overlap_seconds(selected_start, selected_end, candidate_start, candidate_end)
        start_delta = abs(selected_start - candidate_start)
        end_delta = abs(selected_end - candidate_end)
        span = max(1.0, selected_end - selected_start, candidate_end - candidate_start)
        overlap_ratio = overlap / span

        match_key = (
            overlap_ratio,
            -start_delta,
            -end_delta,
            clip_generation.candidate_ranking_key(candidate),
        )

        if best_match is None or match_key > best_match["match_key"]:
            best_candidate = candidate
            best_match = {
                "match_key": match_key,
                "overlap_seconds": round(overlap, 3),
                "overlap_ratio": round(overlap_ratio, 4),
                "start_delta_seconds": round(start_delta, 3),
                "end_delta_seconds": round(end_delta, 3),
            }

    if not best_match:
        return best_candidate, {}

    best_match.pop("match_key", None)
    return best_candidate, best_match


def merge_selected_clip(selected_clip, matched_candidate, match_details):
    if matched_candidate is None:
        enriched = dict(selected_clip)
        enriched["readiness_rescore_status"] = "no_candidate_match"
        return enriched

    enriched = clip_generation.candidate_to_dict(matched_candidate)
    preserved = dict(selected_clip)

    for key, value in preserved.items():
        if key in {
            "output_file",
            "render_qc",
            "source_state_key",
            "source_video_url",
            "source_title",
            "uploaded_at",
            "upload_response",
            "youtube_video_id",
        }:
            enriched[key] = value
            continue

        if key not in enriched or enriched.get(key) in (None, "", [], {}):
            enriched[key] = value

    enriched["readiness_rescore_status"] = "matched"
    enriched["readiness_rescore_match"] = match_details
    enriched["readiness_rescored_at"] = utc_timestamp()
    enriched["rescore_model_version"] = clip_generation.SCORING_MODEL_VERSION
    return enriched


def load_source_caches(paths, cleaned_title):
    transcript_path = os.path.join(paths["transcriptions_path"], f"{cleaned_title}_segments.json")
    audio_features_path = os.path.join(paths["transcriptions_path"], f"{cleaned_title}_audio_features.json")

    if not os.path.exists(transcript_path):
        return None, None, f"missing transcript cache: {transcript_path}"

    if not os.path.exists(audio_features_path):
        return None, None, f"missing audio feature cache: {audio_features_path}"

    return (
        load_json_file(transcript_path, {}),
        load_json_file(audio_features_path, {}),
        "",
    )


def source_record_for_review(theme_name, cleaned_title, selected):
    for clip in selected:
        video_url = clip.get("source_video_url", "")

        if video_url:
            return {
                "title": clip.get("source_title", "") or cleaned_title.replace("_", " "),
                "video_url": video_url,
                "state_key": clip.get("source_state_key", ""),
                "theme": theme_name,
            }

    pulled = load_json_file(PULLED_FILE, {})

    for key, record in pulled.items():
        if not isinstance(record, dict):
            continue

        if record.get("theme") != theme_name and not str(key).startswith(f"{theme_name}|"):
            continue

        if cleaned_title in {
            record.get("_last_cleaned_title", ""),
            record.get("clip_prefix", ""),
            record.get("cleaned_title", ""),
        }:
            return dict(record)

    return {
        "title": cleaned_title.replace("_", " "),
        "video_url": "",
        "state_key": "",
        "theme": theme_name,
    }


def load_cached_profile_for_source(paths, cleaned_title, source_record):
    cache_dir = os.path.join(paths["metadata_path"], "_popularity")
    video_url = source_record.get("video_url", "")
    cached = load_cached_popularity_profile(cache_dir, video_url, cleaned_title)

    if cached is None and video_url:
        cached = load_cached_popularity_profile(cache_dir, "", cleaned_title)

    return cached or {}


def rescore_review(path, paths, top_candidate_count):
    started_at = time.time()
    cleaned_title = clean_title_from_review(path)
    payload = load_json_file(path, {})
    selected = payload.get("selected") or []
    source_record = source_record_for_review(paths["theme"], cleaned_title, selected)
    popularity_profile = load_cached_profile_for_source(paths, cleaned_title, source_record)

    transcript_payload, audio_payload, skip_reason = load_source_caches(paths, cleaned_title)

    if skip_reason:
        return {
            "file": path,
            "cleaned_title": cleaned_title,
            "status": "skipped",
            "reason": skip_reason,
        }

    candidates = clip_generation.build_candidate_clips(
        transcript_payload=transcript_payload,
        audio_payload=audio_payload,
        popularity_profile=popularity_profile,
    )
    sorted_candidates = sorted(candidates, key=clip_generation.candidate_ranking_key, reverse=True)
    enriched_selected = []
    matched_candidates = []
    matched_count = 0

    for selected_clip in selected:
        matched_candidate, match_details = match_candidate(selected_clip, candidates)
        enriched_clip = merge_selected_clip(selected_clip, matched_candidate, match_details)
        enriched_selected.append(enriched_clip)

        if enriched_clip.get("readiness_rescore_status") == "matched":
            matched_count += 1
            matched_candidates.append(matched_candidate)

    payload["selected"] = enriched_selected
    payload["top_candidates"] = [
        clip_generation.compact_candidate_summary(candidate)
        for candidate in sorted_candidates[:top_candidate_count]
    ]
    payload["candidate_inventory"] = clip_generation.build_candidate_inventory(candidates)
    payload["source"] = {
        "title": source_record.get("title", ""),
        "video_url": source_record.get("video_url", ""),
        "state_key": source_record.get("state_key", ""),
    }
    payload["popularity_signal_sources"] = popularity_profile.get("sources", [])
    payload["readiness_rescored_at"] = utc_timestamp()
    payload["rescore_model_version"] = clip_generation.SCORING_MODEL_VERSION

    write_json_file(path, payload)
    dossier_path = clip_generation.write_source_dossier(
        cleaned_title=cleaned_title,
        source_record=source_record,
        popularity_profile=popularity_profile,
        candidates=candidates,
        selected_clips=matched_candidates,
    )

    return {
        "file": path,
        "cleaned_title": cleaned_title,
        "status": "updated",
        "selected_count": len(selected),
        "matched_count": matched_count,
        "candidate_count": len(candidates),
        "popularity_signal_sources": popularity_profile.get("sources", []),
        "source_dossier": dossier_path,
        "seconds": round(time.time() - started_at, 2),
    }


def iter_review_files(metadata_path, include_verification):
    if not os.path.isdir(metadata_path):
        return []

    review_files = []

    for filename in sorted(os.listdir(metadata_path)):
        if not filename.endswith("_clip_review.json"):
            continue

        path = os.path.join(metadata_path, filename)

        if not include_verification and is_verification_artifact(path):
            continue

        review_files.append(path)

    return review_files


def rescore_theme(theme_name, limit=None, include_verification=False, top_candidate_count=40):
    paths = ensure_theme(theme_name)
    clip_generation.configure_theme(theme_name)

    review_files = iter_review_files(paths["metadata_path"], include_verification)

    if limit is not None:
        review_files = review_files[:max(0, int(limit))]

    started_at = time.time()
    results = []

    for index, path in enumerate(review_files, 1):
        print(f"[{index}/{len(review_files)}] rescoring {os.path.basename(path)}")
        result = rescore_review(path, paths, top_candidate_count)
        results.append(result)

        if result["status"] == "updated":
            print(
                " -> updated "
                f"{result['matched_count']}/{result['selected_count']} selected clips "
                f"from {result['candidate_count']} candidates in {result['seconds']}s"
            )
        else:
            print(f" -> skipped: {result.get('reason', '')}")

    report = {
        "theme": paths["theme"],
        "generated_at": utc_timestamp(),
        "include_verification": include_verification,
        "scoring_model_version": clip_generation.SCORING_MODEL_VERSION,
        "review_files_considered": len(review_files),
        "updated_count": sum(1 for result in results if result.get("status") == "updated"),
        "skipped_count": sum(1 for result in results if result.get("status") == "skipped"),
        "matched_selected_count": sum(int(result.get("matched_count") or 0) for result in results),
        "total_selected_count": sum(int(result.get("selected_count") or 0) for result in results),
        "seconds": round(time.time() - started_at, 2),
        "results": results,
    }

    report_path = os.path.join(BASE_DIR, "logs", "rescore", f"{paths['theme']}_latest.json")
    write_json_file(report_path, report)
    print(f"report: {report_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Backfill current clip-readiness metadata into existing clip review JSON files.")
    parser.add_argument("--theme", required=True, help="Theme to rescore.")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of review files to process.")
    parser.add_argument("--include-verification", action="store_true", help="Include smoke/debug/verification review files.")
    parser.add_argument("--top-candidates", type=int, default=40, help="Number of top candidates to store per review.")
    args = parser.parse_args()

    rescore_theme(
        theme_name=args.theme,
        limit=args.limit,
        include_verification=args.include_verification,
        top_candidate_count=args.top_candidates,
    )


if __name__ == "__main__":
    main()
