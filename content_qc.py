import argparse
import json
import math
import os
import re
import subprocess
import time
import wave
from collections import Counter, defaultdict

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from theme_config import BASE_DIR, clean_theme_name, discover_themes, load_json_file


FFMPEG_BIN = r"C:\ffmpeg\bin"
FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")

if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


REPORT_DIR = os.path.join(BASE_DIR, "logs", "content_qc")
CONTACT_DIR = os.path.join(REPORT_DIR, "contact_sheets")
LATEST_JSON = os.path.join(REPORT_DIR, "content_qc_latest.json")
LATEST_MD = os.path.join(REPORT_DIR, "content_qc_latest.md")

GENERIC_TITLE_PHRASES = {
    "most popular moment",
    "this is the part worth watching",
    "became #",
    "behind #",
    "the context behind",
    "the guest reveal behind",
    "the operator signal behind",
    "the practical health signal",
    "the testimony signal",
    "reveals about the market",
    "investors are watching",
    "the habit to rethink",
    "the builder takeaway",
    "story people will debate",
    "detail that changes the case",
    "the claim worth checking",
    "needs specific",
    "case moment inside",
    "evidence question around",
    "debate clip with real context",
    "evidence detail worth rechecking",
    "pop culture detail people missed",
    "ai detail builders are debating",
    "market detail investors should watch",
    "health habit worth rethinking",
    "trial credit deny",
    "prime crime",
    "room credit deny",
    "crime tony early",
    "prison crime dakota",
    "evidence both passenger",
}

WEAK_TOPIC_STARTS = {
    "i",
    "you",
    "we",
    "they",
    "he",
    "she",
    "it",
    "that",
    "this",
    "so",
    "and",
    "but",
    "then",
    "more",
}

REQUIRE_MEDIAPIPE_FACE_VERIFY = os.getenv("SHORTFORM_REQUIRE_MEDIAPIPE_FACE_VERIFY", "1") != "0"
MEDIAPIPE_FACE_CONFIDENCE = float(os.getenv("SHORTFORM_MEDIAPIPE_FACE_CONFIDENCE", "0.56"))
_MEDIAPIPE_FACE_DETECTOR = None


def safe_name(value):
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "")).strip("._")
    return value[:160] or "untitled"


def report_paths(report_suffix=""):
    suffix = safe_name(report_suffix)[:48] if report_suffix else "latest"
    return (
        os.path.join(REPORT_DIR, f"content_qc_{suffix}.json"),
        os.path.join(REPORT_DIR, f"content_qc_{suffix}.md"),
    )


def ffprobe_media(path):
    result = subprocess.run(
        [
            FFPROBE_EXE,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    duration = float((payload.get("format") or {}).get("duration") or video_stream.get("duration") or 0.0)
    return {
        "duration": duration,
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "has_audio": bool(audio_stream),
        "video_codec": video_stream.get("codec_name") or "",
        "audio_codec": audio_stream.get("codec_name") or "",
        "audio_sample_rate": int(audio_stream.get("sample_rate") or 0),
    }


def theme_from_path(path):
    parts = os.path.normpath(path).split(os.sep)

    try:
        index = parts.index("temp")
        return clean_theme_name(parts[index + 1])
    except (ValueError, IndexError):
        return ""


def theme_from_output_path(path):
    parts = os.path.normpath(path).split(os.sep)

    try:
        index = parts.index("themes")
        return clean_theme_name(parts[index + 1])
    except (ValueError, IndexError):
        return ""


def classify_asset(path):
    lower = path.lower()

    if os.sep + "output" + os.sep + "themes" + os.sep in lower and os.sep + "content" + os.sep in lower:
        return "final_upload"

    if "_countdown_intro.mp4" in lower:
        return "countdown_intro"

    if os.sep + "captioned_sources" + os.sep in lower:
        return "captioned_source"

    if os.sep + "clips" + os.sep in lower:
        return "raw_clip"

    return "other"


def discover_assets(themes=None, asset_types=None):
    selected = {clean_theme_name(theme) for theme in themes or []}
    selected_asset_types = set(asset_types or [])
    roots = [
        os.path.join(BASE_DIR, "output", "temp"),
        os.path.join(BASE_DIR, "output", "themes"),
    ]
    assets = []

    for root in roots:
        if not os.path.isdir(root):
            continue

        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.lower().endswith(".mp4"):
                    continue

                path = os.path.join(dirpath, filename)
                asset_type = classify_asset(path)

                if asset_type == "other":
                    continue

                if selected_asset_types and asset_type not in selected_asset_types:
                    continue

                theme = theme_from_path(path) or theme_from_output_path(path)

                if selected and theme not in selected:
                    continue

                assets.append({
                    "path": path,
                    "theme": theme,
                    "asset_type": asset_type,
                    "filename": filename,
                })

    return sorted(assets, key=lambda item: (item["theme"], item["asset_type"], item["filename"]))


def load_face_cascades():
    cascade_dir = cv2.data.haarcascades
    cascades = []

    for filename in ["haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"]:
        cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, filename))

        if not cascade.empty():
            cascades.append(cascade)

    return cascades


def mediapipe_face_detector():
    global _MEDIAPIPE_FACE_DETECTOR

    if not hasattr(mp, "solutions"):
        return None

    if _MEDIAPIPE_FACE_DETECTOR is None:
        _MEDIAPIPE_FACE_DETECTOR = mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=MEDIAPIPE_FACE_CONFIDENCE,
        )

    return _MEDIAPIPE_FACE_DETECTOR


def face_iou(left, right):
    left_x2 = left[0] + left[2]
    left_y2 = left[1] + left[3]
    right_x2 = right[0] + right[2]
    right_y2 = right[1] + right[3]
    inter_x1 = max(left[0], right[0])
    inter_y1 = max(left[1], right[1])
    inter_x2 = min(left_x2, right_x2)
    inter_y2 = min(left_y2, right_y2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    union = left[2] * left[3] + right[2] * right[3] - inter_area
    return inter_area / max(1, union)


def face_center_close(left, right):
    left_cx = left[0] + left[2] / 2
    left_cy = left[1] + left[3] / 2
    right_cx = right[0] + right[2] / 2
    right_cy = right[1] + right[3] / 2
    return (
        abs(left_cx - right_cx) < max(left[2], right[2]) * 0.62
        and abs(left_cy - right_cy) < max(left[3], right[3]) * 0.62
    )


def detect_mediapipe_faces(frame):
    try:
        detector = mediapipe_face_detector()

        if detector is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = detector.process(rgb)
    except Exception:
        return []

    height, width = frame.shape[:2]
    faces = []

    for detection in getattr(results, "detections", []) or []:
        box = detection.location_data.relative_bounding_box
        x = max(0, int(box.xmin * width))
        y = max(0, int(box.ymin * height))
        w = max(0, min(int(box.width * width), width - x))
        h = max(0, min(int(box.height * height), height - y))

        if w > 1 and h > 1:
            faces.append((x, y, w, h))

    return faces


def detect_faces(gray, cascades):
    faces = []

    for cascade in cascades:
        detected = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(32, 32),
        )

        for face in detected:
            faces.append(tuple(int(value) for value in face))

    return faces


def verified_faces(frame, cascades):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade_faces = detect_faces(gray, cascades)
    mp_faces = detect_mediapipe_faces(frame)

    if REQUIRE_MEDIAPIPE_FACE_VERIFY and mediapipe_face_detector() is not None:
        if not mp_faces:
            return []

        cascade_faces = [
            face
            for face in cascade_faces
            if any(face_iou(face, mp_face) >= 0.06 or face_center_close(face, mp_face) for mp_face in mp_faces)
        ]

    faces = cascade_faces + mp_faces
    deduped = []

    for face in sorted(faces, key=lambda box: box[2] * box[3], reverse=True):
        if any(face_iou(face, existing) >= 0.18 or face_center_close(face, existing) for existing in deduped):
            continue

        deduped.append(face)

    return deduped


def sample_times(duration, interval_seconds=2.0, max_frames=36):
    duration = max(0.0, float(duration or 0.0))

    if duration <= 0:
        return []

    times = []
    current = 0.25

    while current < max(0.26, duration - 0.15):
        times.append(current)
        current += interval_seconds

    if duration > 1.5:
        times.append(max(0.25, duration - 0.35))

    unique = []

    for value in times:
        rounded = round(min(max(0.0, value), duration), 2)

        if rounded not in unique:
            unique.append(rounded)

    if len(unique) > max_frames:
        indexes = np.linspace(0, len(unique) - 1, max_frames).round().astype(int)
        unique = [unique[index] for index in indexes]

    return unique


def frame_metrics(frame, faces):
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_luma = float(np.mean(gray))
    std_luma = float(np.std(gray))
    laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 80, 160)
    edge_density = float(np.mean(edges > 0))
    face_count = len(faces)
    largest_face_area = 0.0
    largest_face_height_ratio = 0.0
    largest_face_skin_ratio = 0.0
    largest_face_edge_density = 0.0
    center_offset = None

    if faces:
        largest = max(faces, key=lambda box: box[2] * box[3])
        x, y, w, h = largest
        largest_face_area = (w * h) / max(1, width * height)
        largest_face_height_ratio = h / max(1, height)
        face_center_x = x + w / 2
        face_center_y = y + h / 2
        center_offset = math.sqrt(
            ((face_center_x - width / 2) / width) ** 2
            + ((face_center_y - height / 2) / height) ** 2
        )
        x1 = max(0, int(x - w * 0.12))
        y1 = max(0, int(y - h * 0.12))
        x2 = min(width, int(x + w * 1.12))
        y2 = min(height, int(y + h * 1.12))

        if x2 > x1 and y2 > y1:
            face_roi = frame[y1:y2, x1:x2]
            face_gray = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
            face_edges = cv2.Canny(face_gray, 80, 160)
            largest_face_edge_density = float(np.mean(face_edges > 0))
            largest_face_skin_ratio = estimate_skin_tone_ratio(face_roi)

    is_black = mean_luma < 8.0
    low_info = edge_density < 0.010 and laplacian < 18.0
    plausible_face = largest_face_area >= 0.012
    return {
        "mean_luma": round(mean_luma, 3),
        "std_luma": round(std_luma, 3),
        "laplacian": round(laplacian, 3),
        "edge_density": round(edge_density, 5),
        "face_count": face_count,
        "largest_face_area": round(largest_face_area, 5),
        "largest_face_height_ratio": round(largest_face_height_ratio, 4),
        "largest_face_skin_ratio": round(largest_face_skin_ratio, 4),
        "largest_face_edge_density": round(largest_face_edge_density, 5),
        "face_center_offset": round(center_offset, 4) if center_offset is not None else None,
        "is_black": is_black,
        "low_info": low_info,
        "plausible_face": plausible_face,
    }


def draw_label(draw, xy, text, font):
    x, y = xy
    draw.rectangle((x, y, x + 260, y + 34), fill=(0, 0, 0, 185))
    draw.text((x + 6, y + 6), text, fill=(255, 255, 255), font=font)


def create_contact_sheet(path, theme, asset_type, media, interval_seconds=2.0, max_frames=36):
    os.makedirs(os.path.join(CONTACT_DIR, asset_type, theme), exist_ok=True)
    output_path = os.path.join(
        CONTACT_DIR,
        asset_type,
        theme,
        f"{safe_name(os.path.splitext(os.path.basename(path))[0])}_sheet.jpg",
    )
    capture = cv2.VideoCapture(path)

    if not capture.isOpened():
        return "", []

    cascades = load_face_cascades()
    frames = []
    metrics = []
    font = ImageFont.load_default()

    for timestamp in sample_times(media["duration"], interval_seconds=interval_seconds, max_frames=max_frames):
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()

        if not ok or frame is None:
            continue

        faces = verified_faces(frame, cascades)
        item_metrics = frame_metrics(frame, faces)
        item_metrics["time"] = timestamp
        metrics.append(item_metrics)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb).resize((216, 384), Image.Resampling.LANCZOS).convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA")
        draw_label(draw, (0, 0), f"{timestamp:.1f}s F:{item_metrics['face_count']}", font)

        if not item_metrics["plausible_face"]:
            draw.rectangle((0, 344, 216, 384), fill=(180, 20, 20, 170))
            draw.text((6, 354), "NO STRONG FACE", fill=(255, 255, 255), font=font)

        if item_metrics["low_info"] or item_metrics["is_black"]:
            draw.rectangle((0, 306, 216, 344), fill=(220, 150, 0, 170))
            draw.text((6, 316), "LOW VISUAL INFO", fill=(0, 0, 0), font=font)

        frames.append(image)

    capture.release()

    if not frames:
        return "", metrics

    columns = min(6, len(frames))
    rows = int(math.ceil(len(frames) / columns))
    sheet = Image.new("RGB", (columns * 216, rows * 384), (12, 12, 14))

    for index, image in enumerate(frames):
        x = (index % columns) * 216
        y = (index // columns) * 384
        sheet.paste(image, (x, y))

    sheet.save(output_path, quality=88)
    return output_path, metrics


def longest_false_run(values):
    longest = 0
    current = 0

    for value in values:
        if value:
            current = 0
        else:
            current += 1
            longest = max(longest, current)

    return longest


def estimate_skin_tone_ratio(frame):
    if frame is None or frame.size <= 0:
        return 0.0

    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    y_channel, cr_channel, cb_channel = cv2.split(ycrcb)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    _, saturation, value = cv2.split(hsv)
    skin_mask = (
        (y_channel > 28)
        & (cr_channel >= 118)
        & (cr_channel <= 190)
        & (cb_channel >= 58)
        & (cb_channel <= 158)
        & (saturation >= 12)
        & (value >= 32)
    )

    return float(np.count_nonzero(skin_mask) / max(1, skin_mask.size))


def summarize_frame_metrics(metrics, asset_type):
    count = len(metrics)

    if not count:
        return {
            "sample_count": 0,
            "flags": ["no sampled frames"],
        }

    plausible = [bool(item.get("plausible_face")) for item in metrics]
    face_count = sum(1 for value in plausible if value)
    black_count = sum(1 for item in metrics if item.get("is_black"))
    low_info_count = sum(1 for item in metrics if item.get("low_info"))
    offsets = [float(item["face_center_offset"]) for item in metrics if item.get("face_center_offset") is not None]
    face_heights = [float(item["largest_face_height_ratio"]) for item in metrics if item.get("largest_face_height_ratio")]
    flat_skin_false_faces = [
        item
        for item in metrics
        if float(item.get("largest_face_height_ratio") or 0.0) >= 0.14
        and float(item.get("largest_face_skin_ratio") or 0.0) > 0.82
        and float(item.get("largest_face_edge_density") or 0.0) < 0.04
    ]
    small_face_count = sum(1 for height in face_heights if height < 0.12)
    flags = []
    face_presence_rate = face_count / count
    no_face_run_ratio = longest_false_run(plausible) / count
    low_info_ratio = low_info_count / count
    black_ratio = black_count / count
    avg_offset = sum(offsets) / len(offsets) if offsets else None
    max_offset = max(offsets) if offsets else None
    avg_face_height = sum(face_heights) / len(face_heights) if face_heights else None
    flat_skin_false_face_ratio = len(flat_skin_false_faces) / count
    small_face_ratio_of_faces = small_face_count / len(face_heights) if face_heights else 0.0

    if black_ratio > 0.04:
        flags.append("black/dead frames present")

    if low_info_ratio > 0.18:
        flags.append("too many low-information frames")

    if asset_type in {"raw_clip", "captioned_source", "final_upload"}:
        min_face = 0.35 if asset_type != "final_upload" else 0.42
        max_no_face_run = 0.32 if asset_type != "final_upload" else 0.36
        avg_offset_limit = 0.22 if asset_type != "final_upload" else 0.26
        severe_offset_limit = 0.35 if asset_type != "final_upload" else 0.40

        if face_presence_rate < min_face:
            flags.append("low speaker/face presence")

        if no_face_run_ratio > max_no_face_run:
            flags.append("extended run without a strong face")

        if avg_offset is not None and avg_offset > avg_offset_limit:
            flags.append("subject often off center")

        if max_offset is not None and max_offset > severe_offset_limit:
            flags.append("severe off-center frames")

        if (
            avg_face_height is not None
            and avg_face_height < 0.085
            and face_presence_rate >= 0.30
            and (
                face_presence_rate < 0.68
                or (avg_offset is not None and avg_offset > avg_offset_limit)
                or (max_offset is not None and max_offset > severe_offset_limit)
            )
        ):
            flags.append("probable tiny/background face lock")

        if (
            avg_face_height is not None
            and avg_face_height < 0.10
            and (
                face_presence_rate < 0.34
                or no_face_run_ratio > 0.40
            )
            and (
                (max_offset is not None and max_offset > 0.48)
                or no_face_run_ratio > 0.52
                or (avg_face_height < 0.075 and no_face_run_ratio > 0.48)
            )
        ):
            flags.append("probable picture-in-picture/background lock")

        if (
            small_face_ratio_of_faces > 0.55
            and face_presence_rate > 0.50
            and avg_face_height is not None
            and avg_face_height < 0.13
        ):
            flags.append("probable small-object/background face lock")

    return {
        "sample_count": count,
        "face_presence_rate": round(face_presence_rate, 4),
        "longest_no_face_run_ratio": round(no_face_run_ratio, 4),
        "black_frame_ratio": round(black_ratio, 4),
        "low_info_frame_ratio": round(low_info_ratio, 4),
        "avg_face_center_offset": round(avg_offset, 4) if avg_offset is not None else None,
        "max_face_center_offset": round(max_offset, 4) if max_offset is not None else None,
        "avg_face_height_ratio": round(avg_face_height, 4) if avg_face_height is not None else None,
        "flat_skin_false_face_ratio": round(flat_skin_false_face_ratio, 4),
        "small_face_ratio_of_faces": round(small_face_ratio_of_faces, 4),
        "avg_edge_density": round(sum(item.get("edge_density", 0.0) for item in metrics) / count, 5),
        "avg_laplacian": round(sum(item.get("laplacian", 0.0) for item in metrics) / count, 3),
        "flags": flags,
    }


def analyze_audio_start(path):
    os.makedirs(REPORT_DIR, exist_ok=True)
    temp_wav = os.path.join(REPORT_DIR, f"{safe_name(os.path.basename(path))}_audio_qc.wav")
    result = subprocess.run(
        [
            FFMPEG_EXE,
            "-y",
            "-v",
            "error",
            "-i",
            path,
            "-t",
            "5",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            temp_wav,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0 or not os.path.exists(temp_wav):
        return {
            "flags": [f"audio probe failed: {(result.stderr or '').strip()[:160]}"],
        }

    try:
        with wave.open(temp_wav, "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            samples = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        try:
            os.remove(temp_wav)
        except OSError:
            pass

    if samples.size == 0:
        return {"flags": ["audio start is empty"]}

    window = max(1, int(sample_rate * 0.05))
    rms = []

    for start in range(0, samples.size, window):
        segment = samples[start:start + window]

        if segment.size:
            rms.append(float(np.sqrt(np.mean(segment * segment))))

    threshold = max(0.012, min(0.045, np.percentile(rms, 75) * 0.22 if rms else 0.018))
    onset = None

    for index, value in enumerate(rms):
        if value >= threshold:
            onset = index * 0.05
            break

    first_200ms = samples[:max(1, int(sample_rate * 0.2))]
    first_500ms = samples[:max(1, int(sample_rate * 0.5))]
    flags = []

    if onset is None:
        flags.append("no clear audio onset in first five seconds")
    elif onset > 1.65:
        flags.append("slow audio/narration start")
    elif onset < 0.04 and float(np.sqrt(np.mean(first_200ms * first_200ms))) > 0.08:
        flags.append("audio starts abruptly at frame zero")

    clipping_ratio = float(np.mean(np.abs(samples) > 0.98))

    if clipping_ratio > 0.002:
        flags.append("possible clipped/distorted intro audio")

    return {
        "onset_seconds": round(onset, 3) if onset is not None else None,
        "first_200ms_rms": round(float(np.sqrt(np.mean(first_200ms * first_200ms))), 5),
        "first_500ms_rms": round(float(np.sqrt(np.mean(first_500ms * first_500ms))), 5),
        "max_abs_first_5s": round(float(np.max(np.abs(samples))), 5),
        "clipping_ratio": round(clipping_ratio, 6),
        "flags": flags,
    }


def title_flags(text):
    text = str(text or "").strip()
    lowered = text.lower()
    words = re.findall(r"[a-zA-Z0-9']+", lowered)
    flags = []

    if not text:
        return ["missing title/topic"]

    if len(words) < 4:
        flags.append("too short/generic")

    if len(words) > 15:
        flags.append("too long")

    if any(phrase in lowered for phrase in GENERIC_TITLE_PHRASES):
        flags.append("mechanical/generic phrasing")

    if re.search(r"^(editor pick|timestamp-backed|viewers replayed)\s*:", lowered):
        flags.append("internal scoring label in public title")

    if re.search(r"\s+from\s+[a-z0-9 ._-]{2,40}$", lowered):
        flags.append("source suffix in public title")

    if any(phrase in lowered for phrase in ["told the story behind", "the claim to rewatch", "is worth saving"]):
        flags.append("template-like public title")

    if re.search(r":\s+the\s+[^:]{4,60}:\s+the\s+", lowered):
        flags.append("stacked template suffix")

    if re.search(r"^what\s+.+?:\s+the\s+.+?\s+reveals\s+about\s+the\s+market$", lowered):
        flags.append("stacked finance template")

    if re.search(r":\s+the\s+(investor takeaway|habit to rethink|builder takeaway|story people will debate|detail that changes the case)$", lowered):
        flags.append("template suffix in public title")

    if re.search(r"\b[A-Za-z]+['’]S\b", text):
        flags.append("malformed title casing")

    if re.search(r"^(what|why|how)\s+\1\b", lowered):
        flags.append("duplicated question word")

    if words and words[0] in WEAK_TOPIC_STARTS and "?" not in text:
        flags.append("looks like raw transcript fragment")

    if re.search(r"\b(i|you|we|they|he|she)\s+(said|thought|think|mean|guess)\b", lowered):
        flags.append("raw dialogue fragment")

    if re.search(r"^what\s+if\s+\b(i|you|we|they|he|she|it)\b", lowered):
        flags.append("raw dialogue fragment")

    if re.search(r"\b\d+\s*,?\s*\d*\s*(years?|hours?|minutes?)\s+ago\b", lowered):
        flags.append("contextless time fragment")

    if text.count("?") > 1:
        flags.append("too many questions")

    return flags


def audit_titles(themes=None):
    selected = {clean_theme_name(theme) for theme in themes or []}
    output_root = os.path.join(BASE_DIR, "output", "themes")
    records = []
    seen = defaultdict(set)
    support_audit_themes = {"health_fitness", "sports", "finance", "technology_ai"}

    try:
        import daily_editorial
    except Exception:
        daily_editorial = None

    if not os.path.isdir(output_root):
        return []

    for theme in sorted(os.listdir(output_root)):
        theme_name = clean_theme_name(theme)

        if selected and theme_name not in selected:
            continue

        metadata_path = os.path.join(output_root, theme, "metadata.json")
        metadata = load_json_file(metadata_path, {})
        daily = metadata.get("daily_editorial") or {}
        upload_candidate_outputs = set()
        quarantined_outputs = set()

        for index, item in enumerate(metadata.get("content") or [], start=1):
            status = ((item.get("posting_status") or {}).get("youtube_shorts") or "").lower()
            output_file = item.get("video_file", "")
            upload_candidate = status in {"ready", "failed", "uploaded"}

            if output_file and upload_candidate:
                upload_candidate_outputs.add(os.path.abspath(output_file))
            elif output_file:
                quarantined_outputs.add(os.path.abspath(output_file))

            if not upload_candidate:
                continue

            youtube_package = (item.get("platforms") or {}).get("youtube_shorts") or {}
            text = youtube_package.get("title") or item.get("title") or ""
            flags = title_flags(text)

            if daily_editorial and item.get("transcript_excerpt"):
                if not daily_editorial.clip_has_theme_relevance(theme_name, item):
                    flags.append("transcript appears off-theme for channel")

                if theme_name in support_audit_themes and not daily_editorial.topic_supported_by_clip(text, item):
                    flags.append("title not supported by clip transcript")

            seen[text.lower()].add(output_file or f"{theme_name}:final_metadata:{index}")
            records.append({
                "theme": theme_name,
                "kind": "final_metadata",
                "rank": index,
                "text": text,
                "source": item.get("source_title", ""),
                "output_file": output_file,
                "flags": sorted(set(flags)),
            })

        for item in daily.get("items") or []:
            output_file = item.get("output_file", "")

            if output_file:
                absolute_output = os.path.abspath(output_file)

                if absolute_output in quarantined_outputs:
                    continue

                if not os.path.exists(absolute_output) and absolute_output not in upload_candidate_outputs:
                    continue

            topic = item.get("topic") or ""
            source = ", ".join(item.get("sources") or [])
            text = item.get("title") or topic
            flags = title_flags(text)
            seen[text.lower()].add(output_file or f"{theme_name}:countdown_topic:{item.get('rank')}")
            records.append({
                "theme": theme_name,
                "kind": "countdown_topic",
                "rank": item.get("rank"),
                "countdown_slot": item.get("countdown_slot"),
                "text": text,
                "source": source,
                "output_file": output_file,
                "flags": sorted(set(flags)),
            })

        popular_items = list(daily.get("popular_segments") or [])
        popular_items.extend(daily.get("popular_segment_items") or [])

        for item in popular_items:
            output_file = item.get("output_file", "")

            if output_file:
                absolute_output = os.path.abspath(output_file)

                if absolute_output in quarantined_outputs:
                    continue

                if not os.path.exists(absolute_output) and absolute_output not in upload_candidate_outputs:
                    continue

            script = item.get("script") or ""
            text = item.get("title") or script
            flags = title_flags(text)
            seen[text.lower()].add(output_file or f"{theme_name}:popular_segment:{item.get('rank')}")
            records.append({
                "theme": theme_name,
                "kind": "popular_segment_script",
                "rank": item.get("rank"),
                "text": text,
                "source": item.get("source_title", ""),
                "output_file": output_file,
                "flags": sorted(set(flags)),
            })

    for record in records:
        if len(seen[record["text"].lower()]) > 1:
            record["flags"] = sorted(set(record["flags"] + ["repeated title/topic text"]))

    return records


def audit_prospective_titles(themes=None, max_per_theme=30):
    selected = {clean_theme_name(theme) for theme in themes or []}
    root = os.path.join(BASE_DIR, "output", "temp")
    records = []
    seen = Counter()

    if not os.path.isdir(root):
        return []

    try:
        import daily_editorial
    except Exception as error:
        return [{
            "theme": "",
            "kind": "prospective_title_audit",
            "rank": None,
            "text": "prospective title audit unavailable",
            "source": "",
            "output_file": "",
            "flags": [f"prospective audit import failed: {error}"],
        }]

    for theme in sorted(os.listdir(root)):
        theme_name = clean_theme_name(theme)

        if selected and theme_name not in selected:
            continue

        metadata_dir = os.path.join(root, theme, "metadata")

        if not os.path.isdir(metadata_dir):
            continue

        clips = []

        for filename in sorted(os.listdir(metadata_dir)):
            if not filename.endswith("_clip_review.json"):
                continue

            payload = load_json_file(os.path.join(metadata_dir, filename), {})

            for clip in payload.get("selected") or []:
                output_file = clip.get("output_file", "")

                if output_file and not os.path.exists(output_file):
                    continue

                if not daily_editorial.clip_is_editorial_usable(clip):
                    continue

                clips.append(clip)

        grouped = daily_editorial.group_clips_by_topic(clips, theme=theme_name)

        for inspected, group in enumerate(grouped[:max_per_theme], start=1):
            clip = (group.get("clips") or [{}])[0]
            topic = group.get("topic") or daily_editorial.topic_label_from_clip(clip, theme=theme_name)
            title = daily_editorial.build_theme_native_editorial_title(
                theme_name,
                topic,
                "most surprising",
                countdown_slot=max(1, 6 - inspected),
                total_count=5,
            )
            seen[title.lower()] += 1
            records.append({
                "theme": theme_name,
                "kind": "prospective_countdown_title",
                "rank": inspected,
                "text": title,
                "topic": topic,
                "source": clip.get("source_title", ""),
                "output_file": clip.get("output_file", ""),
                "flags": title_flags(title),
            })

    for record in records:
        if seen[record["text"].lower()] > 1:
            record["flags"] = sorted(set(record["flags"] + ["repeated prospective title text"]))

    return records


def analyze_asset(asset, interval_seconds=2.0, max_frames=36):
    path = asset["path"]
    media = ffprobe_media(path)
    contact_sheet, frame_samples = create_contact_sheet(
        path,
        asset["theme"],
        asset["asset_type"],
        media,
        interval_seconds=interval_seconds,
        max_frames=max_frames,
    )
    frame_qc = summarize_frame_metrics(frame_samples, asset["asset_type"])
    if media.get("has_audio"):
        audio_qc = analyze_audio_start(path)
    elif asset["asset_type"] == "countdown_intro":
        audio_qc = {"skipped": True, "reason": "countdown intro visual has no standalone audio", "flags": []}
    else:
        audio_qc = {"flags": ["missing audio stream"]}
    flags = sorted(set(frame_qc.get("flags", []) + audio_qc.get("flags", [])))
    return {
        **asset,
        "media": media,
        "contact_sheet": contact_sheet,
        "frame_qc": frame_qc,
        "audio_qc": audio_qc,
        "flags": flags,
    }


def build_markdown(report):
    lines = [
        "# Content QC Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Assets checked: {report['asset_count']}",
        "",
        "## Summary",
        "",
    ]

    for theme, summary in sorted(report["themes"].items()):
        lines.append(
            f"- {theme}: assets={summary['asset_count']}, flagged={summary['flagged_count']}, "
            f"avg_face_presence={summary.get('avg_face_presence_rate')}, "
            f"avg_low_info={summary.get('avg_low_info_frame_ratio')}"
        )

    lines.extend(["", "## Worst Visual/Audio Flags", ""])

    for item in report["worst_assets"][:30]:
        lines.append(f"- {item['theme']} / {item['asset_type']} / {item['filename']}")
        lines.append(f"  - flags: {', '.join(item.get('flags') or ['none'])}")
        lines.append(f"  - sheet: {item.get('contact_sheet', '')}")

    lines.extend(["", "## Title/Topic Flags", ""])

    for item in report["title_audit_flagged"][:60]:
        lines.append(f"- {item['theme']} / {item['kind']} / rank {item.get('rank')}: {item['text']}")
        lines.append(f"  - flags: {', '.join(item.get('flags') or ['none'])}")
        if item.get("source"):
            lines.append(f"  - source: {item['source']}")

    lines.extend(["", "## Prospective Title Flags", ""])

    if not report["prospective_title_audit_flagged"]:
        lines.append("- none")

    for item in report["prospective_title_audit_flagged"][:60]:
        lines.append(f"- {item['theme']} / rank {item.get('rank')}: {item['text']}")
        lines.append(f"  - flags: {', '.join(item.get('flags') or ['none'])}")
        if item.get("topic"):
            lines.append(f"  - topic: {item['topic']}")
        if item.get("source"):
            lines.append(f"  - source: {item['source']}")

    return "\n".join(lines).rstrip() + "\n"


def aggregate_report(asset_reports, title_records, prospective_title_records=None):
    themes = {}

    for item in asset_reports:
        theme = item["theme"]
        summary = themes.setdefault(theme, {
            "asset_count": 0,
            "flagged_count": 0,
            "face_presence_rates": [],
            "low_info_ratios": [],
            "black_ratios": [],
        })
        summary["asset_count"] += 1

        if item.get("flags"):
            summary["flagged_count"] += 1

        frame_qc = item.get("frame_qc") or {}

        if frame_qc.get("face_presence_rate") is not None:
            summary["face_presence_rates"].append(float(frame_qc["face_presence_rate"]))

        if frame_qc.get("low_info_frame_ratio") is not None:
            summary["low_info_ratios"].append(float(frame_qc["low_info_frame_ratio"]))

        if frame_qc.get("black_frame_ratio") is not None:
            summary["black_ratios"].append(float(frame_qc["black_frame_ratio"]))

    for summary in themes.values():
        for source_key, output_key in [
            ("face_presence_rates", "avg_face_presence_rate"),
            ("low_info_ratios", "avg_low_info_frame_ratio"),
            ("black_ratios", "avg_black_frame_ratio"),
        ]:
            values = summary.pop(source_key)
            summary[output_key] = round(sum(values) / len(values), 4) if values else None

    def severity(item):
        frame_qc = item.get("frame_qc") or {}
        audio_qc = item.get("audio_qc") or {}
        return (
            len(item.get("flags") or []) * 10
            + float(frame_qc.get("low_info_frame_ratio") or 0) * 6
            + float(frame_qc.get("longest_no_face_run_ratio") or 0) * 5
            + float(frame_qc.get("max_face_center_offset") or 0) * 3
            + (2 if audio_qc.get("flags") else 0)
        )

    flagged_titles = [record for record in title_records if record.get("flags")]
    prospective_title_records = prospective_title_records or []
    flagged_prospective_titles = [
        record
        for record in prospective_title_records
        if record.get("flags")
    ]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "asset_count": len(asset_reports),
        "flagged_asset_count": sum(1 for item in asset_reports if item.get("flags")),
        "themes": themes,
        "assets": asset_reports,
        "worst_assets": sorted(asset_reports, key=severity, reverse=True)[:60],
        "title_audit": title_records,
        "title_audit_flagged": flagged_titles,
        "title_flag_count": len(flagged_titles),
        "prospective_title_audit": prospective_title_records,
        "prospective_title_audit_flagged": flagged_prospective_titles,
        "prospective_title_flag_count": len(flagged_prospective_titles),
    }


def run_content_qc(
    themes=None,
    interval_seconds=2.0,
    max_frames=36,
    limit=None,
    titles_only=False,
    asset_types=None,
    report_suffix="",
    skip_title_audit=False,
):
    os.makedirs(REPORT_DIR, exist_ok=True)
    assets = [] if titles_only else discover_assets(themes=themes, asset_types=asset_types)

    if limit:
        assets = assets[:int(limit)]

    reports = []

    for index, asset in enumerate(assets, start=1):
        print(f"[{index}/{len(assets)}] QC {asset['theme']} {asset['asset_type']}: {asset['filename']}")

        try:
            reports.append(analyze_asset(asset, interval_seconds=interval_seconds, max_frames=max_frames))
        except Exception as error:
            reports.append({
                **asset,
                "flags": [f"qc failed: {error}"],
                "error": str(error),
            })

    if skip_title_audit:
        title_records = []
        prospective_title_records = []
    else:
        title_records = audit_titles(themes=themes)
        prospective_title_records = audit_prospective_titles(themes=themes)
    report = aggregate_report(reports, title_records, prospective_title_records)
    json_path, md_path = report_paths(report_suffix)

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(build_markdown(report))

    print(f"Content QC JSON: {json_path}")
    print(f"Content QC report: {md_path}")
    print(
        f"Assets checked: {report['asset_count']}; "
        f"flagged: {report['flagged_asset_count']}; "
        f"title flags: {report['title_flag_count']}; "
        f"prospective title flags: {report['prospective_title_flag_count']}"
    )
    return report


def parse_args():
    parser = argparse.ArgumentParser(description="Review generated clips with frame-contact sheets, audio intro checks, and title audits.")
    parser.add_argument("--theme", action="append", help="Theme to inspect. Repeat for multiple themes. Defaults to all themes.")
    parser.add_argument("--asset-type", action="append", choices=["final_upload", "countdown_intro", "captioned_source", "raw_clip"], help="Asset type to inspect. Repeat for multiple types.")
    parser.add_argument("--final-only", action="store_true", help="Inspect only final upload files.")
    parser.add_argument("--interval-seconds", type=float, default=2.0, help="Frame sampling interval.")
    parser.add_argument("--max-frames", type=int, default=36, help="Maximum sampled frames per video.")
    parser.add_argument("--limit", type=int, help="Limit assets for quick smoke tests.")
    parser.add_argument("--titles-only", action="store_true", help="Only audit existing and prospective titles; skip frame/audio sampling.")
    parser.add_argument("--skip-title-audit", action="store_true", help="Skip title/prospective-title audits for faster frame/audio sampling.")
    parser.add_argument("--report-suffix", help="Write content_qc_SUFFIX.json/.md instead of content_qc_latest.*")
    return parser.parse_args()


def main():
    args = parse_args()
    themes = args.theme or discover_themes()
    run_content_qc(
        themes=themes,
        interval_seconds=args.interval_seconds,
        max_frames=args.max_frames,
        limit=args.limit,
        titles_only=args.titles_only,
        asset_types=["final_upload"] if args.final_only else args.asset_type,
        report_suffix=args.report_suffix or "",
        skip_title_audit=args.skip_title_audit,
    )


if __name__ == "__main__":
    main()
