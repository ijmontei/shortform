import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import parse_qs, urlparse


TIMESTAMP_PATTERN = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")
COMMENT_TOPIC_STOPWORDS = {
    "about", "after", "again", "also", "always", "amazing", "another", "around",
    "because", "before", "being", "better", "could", "didnt", "doesnt", "doing",
    "dont", "every", "first", "from", "getting", "going", "gonna", "great",
    "guess", "have", "having", "here", "just", "know", "like", "little",
    "look", "love", "made", "make", "makes", "many", "more", "much", "need",
    "never", "only", "people", "podcast", "really", "right", "same", "should",
    "something", "still", "take", "than", "that", "thats", "their", "them",
    "then", "there", "these", "thing", "things", "think", "this", "those",
    "through", "time", "today", "very", "want", "watch", "watching", "when",
    "where", "which", "while", "with", "would", "yeah", "year", "years",
    "your", "youre", "youtube", "video",
}


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def youtube_video_id(video_url):
    parsed = urlparse(str(video_url or "").strip())
    host = parsed.netloc.lower().replace("www.", "")

    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]

    query_video_id = parse_qs(parsed.query).get("v", [""])[0]

    if query_video_id:
        return query_video_id

    parts = [part for part in parsed.path.split("/") if part]

    for marker in ["shorts", "embed", "live", "v"]:
        if marker in parts:
            marker_index = parts.index(marker)

            if marker_index + 1 < len(parts):
                return parts[marker_index + 1]

    return ""


def clean_cache_key(value):
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "").strip())
    return cleaned.strip("._-") or "unknown_video"


def timestamp_to_seconds(match):
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def extract_timestamp_markers_from_text(text, duration=None, source="timestamp_text"):
    duration = safe_float(duration, 0)
    markers = {}

    for match in TIMESTAMP_PATTERN.finditer(str(text or "")):
        seconds = timestamp_to_seconds(match)

        if seconds < 4:
            continue

        if duration and seconds > duration + 90:
            continue

        marker = markers.setdefault(seconds, {"time": float(seconds), "count": 0, "source": source})
        marker["count"] += 1

    return list(markers.values())


def normalize_comment_text(value):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def words_from_text(text):
    return [
        token.strip("'").lower()
        for token in re.findall(r"[A-Za-z][A-Za-z']{2,}", str(text or ""))
        if token.strip("'").lower() not in COMMENT_TOPIC_STOPWORDS
    ]


def strip_timestamp_noise(text):
    text = TIMESTAMP_PATTERN.sub(" ", str(text or ""))
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def comment_interaction_weight(comment):
    like_count = int(comment.get("like_count") or comment.get("likeCount") or 0)
    reply_count = int(comment.get("reply_count") or comment.get("replyCount") or 0)
    order_source = str(comment.get("order_source") or "").lower()
    weight = 1.0 + math.log1p(max(0, like_count))
    weight += 0.55 * math.log1p(max(0, reply_count))

    if order_source == "relevance":
        weight += 0.45

    return weight


def comment_topic_phrases(text):
    words = words_from_text(strip_timestamp_noise(text))
    phrases = []

    for word in words:
        if len(word) >= 4:
            phrases.append(word)

    for left, right in zip(words, words[1:]):
        if len(left) >= 4 and len(right) >= 4 and left != right:
            phrases.append(f"{left} {right}")

    for first, second, third in zip(words, words[1:], words[2:]):
        if min(len(first), len(second), len(third)) >= 4:
            phrases.append(f"{first} {second} {third}")

    return phrases


def extract_comment_topic_terms(comments, limit=60):
    weighted_terms = {}

    for comment in comments or []:
        if not isinstance(comment, dict):
            comment = {"text": str(comment or "")}

        text = normalize_comment_text(comment.get("text") or comment.get("html") or comment.get("textOriginal") or "")

        if not text:
            continue

        weight = comment_interaction_weight(comment)
        seen_phrases = set()

        for phrase in comment_topic_phrases(text):
            if phrase in seen_phrases:
                continue

            seen_phrases.add(phrase)
            payload = weighted_terms.setdefault(phrase, {
                "term": phrase,
                "weight": 0.0,
                "count": 0,
                "examples": [],
            })
            length_bonus = 1.0 + min(0.55, 0.18 * (len(phrase.split()) - 1))
            payload["weight"] += weight * length_bonus
            payload["count"] += 1

            if len(payload["examples"]) < 2:
                payload["examples"].append(text[:180])

    ranked_terms = sorted(
        weighted_terms.values(),
        key=lambda item: (item["weight"], item["count"], len(item["term"].split())),
        reverse=True,
    )

    return [
        {
            "term": item["term"],
            "weight": round(float(item["weight"]), 4),
            "count": int(item["count"]),
            "examples": item["examples"],
        }
        for item in ranked_terms[:limit]
        if item["weight"] > 0
    ]


def fetch_json_url(url, timeout=18):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "shortform-pipeline/1.0"},
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace") or "{}")


def fetch_youtube_data_api_comments(video_id, api_key, pages_per_order=1, max_results=100):
    if not video_id or not api_key:
        return []

    comments = []
    seen_ids = set()
    base_url = "https://www.googleapis.com/youtube/v3/commentThreads"

    for order in ["relevance", "time"]:
        page_token = ""

        for _ in range(max(1, int(pages_per_order or 1))):
            query = {
                "part": "snippet",
                "videoId": video_id,
                "maxResults": max(1, min(100, int(max_results or 100))),
                "order": order,
                "textFormat": "plainText",
                "key": api_key,
            }

            if page_token:
                query["pageToken"] = page_token

            url = f"{base_url}?{urllib.parse.urlencode(query)}"
            payload = fetch_json_url(url)

            for item in payload.get("items") or []:
                snippet = item.get("snippet") or {}
                top_comment = (snippet.get("topLevelComment") or {}).get("snippet") or {}
                comment_id = item.get("id") or (snippet.get("topLevelComment") or {}).get("id") or ""

                if comment_id and comment_id in seen_ids:
                    continue

                if comment_id:
                    seen_ids.add(comment_id)

                text = normalize_comment_text(
                    top_comment.get("textOriginal")
                    or top_comment.get("textDisplay")
                    or ""
                )

                if not text:
                    continue

                comments.append({
                    "id": comment_id,
                    "text": text,
                    "like_count": int(top_comment.get("likeCount") or 0),
                    "reply_count": int(snippet.get("totalReplyCount") or 0),
                    "published_at": top_comment.get("publishedAt") or "",
                    "order_source": order,
                })

            page_token = payload.get("nextPageToken") or ""

            if not page_token:
                break

    return comments


def fetch_youtube_data_api_video_stats(video_id, api_key):
    if not video_id or not api_key:
        return {}

    query = {
        "part": "statistics,snippet",
        "id": video_id,
        "key": api_key,
    }
    url = f"https://www.googleapis.com/youtube/v3/videos?{urllib.parse.urlencode(query)}"
    payload = fetch_json_url(url)
    items = payload.get("items") or []

    if not items:
        return {}

    item = items[0]
    stats = item.get("statistics") or {}
    snippet = item.get("snippet") or {}

    return {
        "view_count": int(stats.get("viewCount") or 0),
        "like_count": int(stats.get("likeCount") or 0),
        "comment_count": int(stats.get("commentCount") or 0),
        "channel_title": snippet.get("channelTitle") or "",
        "published_at": snippet.get("publishedAt") or "",
        "category_id": snippet.get("categoryId") or "",
        "tags": snippet.get("tags") or [],
    }


def build_youtube_data_api_profile(video_url, api_key, duration=None, pages_per_order=1):
    video_id = youtube_video_id(video_url)

    if not video_id or not api_key:
        return {}

    comments = fetch_youtube_data_api_comments(
        video_id,
        api_key,
        pages_per_order=pages_per_order,
    )
    stats = fetch_youtube_data_api_video_stats(video_id, api_key)
    duration = safe_float(duration or 0, 0)
    timestamp_markers = []
    comment_topic_terms = extract_comment_topic_terms(comments)

    for comment in comments:
        markers = extract_timestamp_markers_from_text(
            comment.get("text", ""),
            duration=duration,
            source="youtube_data_api_comment_timestamp",
        )
        interaction_weight = 1 + math.log1p(int(comment.get("like_count") or 0))
        interaction_weight += 0.55 * math.log1p(int(comment.get("reply_count") or 0))

        for marker in markers:
            marker["count"] = max(1, int(round(marker.get("count", 1) * interaction_weight)))
            marker["like_count"] = int(comment.get("like_count") or 0)
            marker["reply_count"] = int(comment.get("reply_count") or 0)
            timestamp_markers.append(marker)

    return {
        "video_id": video_id,
        "youtube_data_api": {
            "stats": stats,
            "comment_count_sampled": len(comments),
            "comment_timestamp_marker_count": len(timestamp_markers),
            "comment_topic_term_count": len(comment_topic_terms),
            "comments": comments[:80],
        },
        "timestamp_markers": timestamp_markers,
        "comment_topic_terms": comment_topic_terms,
        "sources": ["youtube_data_api_comments"] if comments else [],
    }


def merge_popularity_profiles(base_profile, extra_profile):
    merged = dict(base_profile or {})
    extra_profile = extra_profile or {}

    if not extra_profile:
        return merged

    marker_counts = {}

    for marker in (merged.get("timestamp_markers") or []) + (extra_profile.get("timestamp_markers") or []):
        key = int(safe_float(marker.get("time"), 0))

        if key <= 0:
            continue

        existing = marker_counts.setdefault(key, {"count": 0, "sources": {}})
        count = int(marker.get("count") or 1)
        existing["count"] += count

        if marker.get("source_counts"):
            for source, source_count in marker.get("source_counts", {}).items():
                existing["sources"][source] = existing["sources"].get(source, 0) + int(source_count or 0)
        else:
            source = marker.get("source", "timestamp_text")
            existing["sources"][source] = existing["sources"].get(source, 0) + count

    merged["timestamp_markers"] = [
        {
            "time": float(key),
            "count": payload["count"],
            "source": "timestamp_text",
            "source_counts": payload["sources"],
        }
        for key, payload in sorted(marker_counts.items())
    ]

    sources = set(merged.get("sources") or [])
    sources.update(extra_profile.get("sources") or [])

    if any("youtube_data_api_comment_timestamp" in marker.get("source_counts", {}) for marker in merged["timestamp_markers"]):
        sources.add("youtube_data_api_comment_timestamps")

    if extra_profile.get("youtube_data_api"):
        merged["youtube_data_api"] = extra_profile["youtube_data_api"]

    term_counts = {}

    for term_payload in (merged.get("comment_topic_terms") or []) + (extra_profile.get("comment_topic_terms") or []):
        term = str(term_payload.get("term") or "").strip().lower()

        if not term:
            continue

        existing = term_counts.setdefault(term, {
            "term": term,
            "weight": 0.0,
            "count": 0,
            "examples": [],
        })
        existing["weight"] += safe_float(term_payload.get("weight"), 0.0)
        existing["count"] += int(term_payload.get("count") or 0)

        for example in term_payload.get("examples") or []:
            if example and example not in existing["examples"] and len(existing["examples"]) < 2:
                existing["examples"].append(example)

    if term_counts:
        merged["comment_topic_terms"] = [
            {
                "term": item["term"],
                "weight": round(float(item["weight"]), 4),
                "count": int(item["count"]),
                "examples": item["examples"],
            }
            for item in sorted(term_counts.values(), key=lambda value: value["weight"], reverse=True)[:80]
        ]
        sources.add("comment_topic_terms")

    merged["sources"] = sorted(sources)
    return merged


def normalize_heatmap_markers(markers):
    normalized = []

    for marker in markers or []:
        start = safe_float(marker.get("start_time", marker.get("start", marker.get("time"))), None)
        end = safe_float(marker.get("end_time", marker.get("end")), None)
        value = safe_float(marker.get("value", marker.get("score", marker.get("heat"))), 0.0)

        if start is None:
            continue

        if end is None or end <= start:
            end = start + 1

        normalized.append({
            "start_time": float(start),
            "end_time": float(end),
            "value": max(0.0, min(1.0, float(value))),
        })

    return sorted(normalized, key=lambda item: item["start_time"])


def normalize_chapters(chapters, duration=None):
    duration = safe_float(duration, 0)
    normalized = []

    for chapter in chapters or []:
        start = safe_float(chapter.get("start_time", chapter.get("start")), None)

        if start is None:
            continue

        end = safe_float(chapter.get("end_time", chapter.get("end")), 0)

        if end <= start:
            end = duration if duration > start else start + 60

        normalized.append({
            "start_time": float(start),
            "end_time": float(end),
            "title": str(chapter.get("title") or "Chapter").strip(),
        })

    return sorted(normalized, key=lambda item: item["start_time"])


def build_popularity_profile_from_info(info):
    info = info or {}
    duration = safe_float(info.get("duration"), 0)
    heatmap = normalize_heatmap_markers(info.get("heatmap") or [])
    chapters = normalize_chapters(info.get("chapters") or [], duration=duration)
    text_blobs = [
        info.get("title", ""),
        info.get("description", ""),
    ]
    comment_blobs = []
    comment_records = []

    for chapter in chapters:
        text_blobs.append(chapter.get("title", ""))

    for comment in info.get("comments") or []:
        if isinstance(comment, dict):
            comment_text = comment.get("text") or comment.get("html") or ""
            comment_blobs.append(comment_text)
            comment_records.append({
                "text": comment_text,
                "like_count": int(comment.get("like_count") or comment.get("likeCount") or 0),
                "reply_count": int(comment.get("reply_count") or comment.get("replyCount") or 0),
                "order_source": "yt_dlp",
            })

    timestamp_markers = []

    for blob in text_blobs:
        timestamp_markers.extend(extract_timestamp_markers_from_text(blob, duration=duration, source="metadata_timestamp"))

    for blob in comment_blobs:
        timestamp_markers.extend(extract_timestamp_markers_from_text(blob, duration=duration, source="comment_timestamp"))

    marker_counts = {}

    for marker in timestamp_markers:
        key = int(marker["time"])
        existing = marker_counts.setdefault(key, {"count": 0, "sources": {}})
        count = int(marker.get("count") or 1)
        source = marker.get("source", "timestamp_text")
        existing["count"] += count
        existing["sources"][source] = existing["sources"].get(source, 0) + count

    timestamp_markers = [
        {
            "time": float(key),
            "count": payload["count"],
            "source": "timestamp_text",
            "source_counts": payload["sources"],
        }
        for key, payload in sorted(marker_counts.items())
    ]
    sources = []

    if heatmap:
        sources.append("youtube_heatmap")
    if timestamp_markers:
        sources.append("timestamp_mentions")
    if any("comment_timestamp" in marker.get("source_counts", {}) for marker in timestamp_markers):
        sources.append("comment_timestamp_mentions")
    if chapters:
        sources.append("chapters")

    comment_topic_terms = extract_comment_topic_terms(comment_records)

    if comment_topic_terms:
        sources.append("comment_topic_terms")

    return {
        "video_id": info.get("id", ""),
        "title": info.get("title", ""),
        "duration": duration,
        "heatmap": heatmap,
        "timestamp_markers": timestamp_markers,
        "comment_topic_terms": comment_topic_terms,
        "chapters": chapters,
        "sources": sources,
    }


def popularity_profile_cache_path(cache_dir, video_url, cleaned_title=""):
    os.makedirs(cache_dir, exist_ok=True)
    key = youtube_video_id(video_url) or cleaned_title or video_url
    return os.path.join(cache_dir, f"{clean_cache_key(key)}_popularity.json")


def load_cached_popularity_profile(cache_dir, video_url, cleaned_title=""):
    path = popularity_profile_cache_path(cache_dir, video_url, cleaned_title)

    if not os.path.exists(path) or os.path.getsize(path) <= 0:
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def save_popularity_profile(cache_dir, video_url, profile, cleaned_title=""):
    path = popularity_profile_cache_path(cache_dir, video_url, cleaned_title)

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile or {}, f, indent=4)
    except OSError:
        pass

    return path


def interval_overlap(left_start, left_end, right_start, right_end):
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def saturating_score(value, scale):
    if value <= 0:
        return 0.0
    return float(1 - math.exp(-value / max(0.001, scale)))


def heatmap_score_for_window(heatmap, start_time, end_time):
    weighted_total = 0.0
    overlap_total = 0.0
    peak_value = 0.0

    for marker in heatmap or []:
        overlap = interval_overlap(
            start_time,
            end_time,
            safe_float(marker.get("start_time")),
            safe_float(marker.get("end_time")),
        )

        if overlap <= 0:
            continue

        value = max(0.0, min(1.0, safe_float(marker.get("value"))))
        weighted_total += value * overlap
        overlap_total += overlap
        peak_value = max(peak_value, value)

    if overlap_total <= 0:
        return 0.0

    average_value = weighted_total / overlap_total
    return max(0.0, min(1.0, 0.72 * average_value + 0.28 * peak_value))


def timestamp_score_for_window(markers, start_time, end_time):
    midpoint = (start_time + end_time) / 2
    raw_score = 0.0

    for marker in markers or []:
        marker_time = safe_float(marker.get("time"))
        count = max(1, int(marker.get("count") or 1))

        if start_time <= marker_time <= end_time:
            raw_score += count * 1.35
            continue

        distance = min(abs(marker_time - start_time), abs(marker_time - end_time), abs(marker_time - midpoint))
        raw_score += count * math.exp(-distance / 28.0)

    return saturating_score(raw_score, 2.8)


def chapter_score_for_window(chapters, start_time, end_time):
    best = 0.0

    for chapter in chapters or []:
        chapter_start = safe_float(chapter.get("start_time"))

        if start_time <= chapter_start <= end_time:
            best = max(best, 0.72)
            continue

        distance = min(abs(chapter_start - start_time), abs(chapter_start - end_time))
        best = max(best, 0.48 * math.exp(-distance / 22.0))

    return best


def score_comment_topic_match(profile, text):
    terms = profile.get("comment_topic_terms") or []
    normalized_text = " ".join(words_from_text(text))
    raw_score = 0.0
    matched_terms = []

    if not terms or not normalized_text:
        return {
            "score": 0.0,
            "matched_terms": [],
        }

    padded_text = f" {normalized_text} "

    for term_payload in terms[:80]:
        term = str(term_payload.get("term") or "").strip().lower()

        if not term:
            continue

        normalized_term = " ".join(words_from_text(term))

        if not normalized_term:
            continue

        if f" {normalized_term} " not in padded_text:
            continue

        weight = safe_float(term_payload.get("weight"), 0.0)
        phrase_bonus = 1.0 + min(0.45, 0.15 * (len(normalized_term.split()) - 1))
        raw_score += weight * phrase_bonus
        matched_terms.append({
            "term": term,
            "weight": round(weight, 4),
            "count": int(term_payload.get("count") or 0),
        })

        if len(matched_terms) >= 8:
            break

    return {
        "score": saturating_score(raw_score, 9.0),
        "matched_terms": matched_terms,
    }


def score_popularity_for_window(profile, start_time, end_time):
    profile = profile or {}
    start_time = safe_float(start_time)
    end_time = max(start_time + 1, safe_float(end_time))
    heatmap_score = heatmap_score_for_window(profile.get("heatmap", []), start_time, end_time)
    timestamp_score = timestamp_score_for_window(profile.get("timestamp_markers", []), start_time, end_time)
    chapter_score = chapter_score_for_window(profile.get("chapters", []), start_time, end_time)
    score = max(heatmap_score, 0.82 * timestamp_score, 0.42 * chapter_score)
    source = ""

    if score == heatmap_score and heatmap_score > 0:
        source = "youtube_heatmap"
    elif score == 0.82 * timestamp_score and timestamp_score > 0:
        source = "timestamp_mentions"
    elif chapter_score > 0:
        source = "chapters"

    return {
        "score": max(0.0, min(1.0, score)),
        "heatmap_score": heatmap_score,
        "timestamp_score": timestamp_score,
        "chapter_score": chapter_score,
        "source": source,
        "profile_sources": profile.get("sources", []),
    }
