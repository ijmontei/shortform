import os
FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

import csv
import json
import subprocess
import time
import re
import wave
from dataclasses import asdict, dataclass, field
import yt_dlp
import cv2
import numpy as np
from theme_config import (
    BASE_DIR,
    DEFAULT_THEME,
    EXECUTED_FILE,
    PULLED_FILE,
    discover_themes,
    ensure_theme,
    load_json_file,
    write_json_file,
)

try:
    cv2.ocl.setUseOpenCL(False)
except Exception:
    pass


# =========================
# Base directories and paths
# =========================

base_dir = BASE_DIR

CURRENT_THEME = None

videos_path = None
audio_path = None
transcriptions_path = None
clips_path = None
metadata_path = None


def configure_theme(theme_name):
    global CURRENT_THEME
    global videos_path, audio_path, transcriptions_path, clips_path, metadata_path

    theme_paths = ensure_theme(theme_name)
    CURRENT_THEME = theme_paths["theme"]
    videos_path = theme_paths["videos_path"]
    audio_path = theme_paths["audio_path"]
    transcriptions_path = theme_paths["transcriptions_path"]
    clips_path = theme_paths["clips_path"]
    metadata_path = theme_paths["metadata_path"]

    return theme_paths


# Keep this True while tuning reframing so older choppy clips are replaced.
REGENERATE_EXISTING_CLIPS = True

MAX_CLIPS_PER_VIDEO = 10
MIN_CLIP_DURATION = 30
MAX_CLIP_DURATION = 60
CANDIDATE_CLIP_DURATIONS = [35, 45, 55]
CANDIDATE_STRIDE_SECONDS = 5
MIN_SELECTED_CLIP_SCORE = 0.25
MIN_WORDS_PER_CANDIDATE = 22
MIN_CLIP_SPACING_SECONDS = 2
MAX_TOPIC_SIMILARITY = 0.58
SCORING_MODEL_VERSION = "2026-06-10-v5"
ENABLE_PERSON_FALLBACK = os.getenv("SHORTFORM_ENABLE_PERSON_FALLBACK") == "1"


# =========================
# Executables
# =========================

FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"

FFPROBE_EXE = os.path.join(FFMPEG_BIN, "ffprobe.exe")
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


# =========================
# yt-dlp configuration
# =========================

YTDL_COMMON_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "js_runtimes": {"node": {}},
    "allow_remote_features": True,
    "ignoreerrors": True,
}


def build_ytdl_opts(extra_opts=None):
    opts = {**YTDL_COMMON_OPTS}

    cookies_file = os.getenv(
        "SHORTFORM_YTDLP_COOKIES",
        os.path.join(base_dir, "cookies.txt"),
    )
    cookies_browser = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "")

    if os.path.exists(cookies_file):
        opts["cookiefile"] = cookies_file
    elif cookies_browser and os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") != "1":
        opts["cookiesfrombrowser"] = (cookies_browser,)

    if extra_opts:
        opts.update(extra_opts)

    return opts


# =========================
# Helpers
# =========================

def run_subprocess(cmd, label):
    """
    Runs a subprocess and prints useful FFmpeg errors instead of hiding them.
    """
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print(f"\n--- {label} failed ---")
        print("Command:")
        print(" ".join(str(x) for x in cmd))
        print("\nFFmpeg stderr:")
        print(result.stderr[-4000:])
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")

    return result


def try_subprocess(cmd, label):
    """
    Runs a subprocess and returns the completed result without raising.
    Used for fast-path commands that have a safe fallback.
    """
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        print(f" -> {label} fast path failed; falling back.")
        print(result.stderr[-1200:])

    return result


def clean_title_for_filename(title):
    cleaned = "".join(
        char for char in title
        if char.isalnum() or char in [" ", ".", "_", "-"]
    ).replace(" ", "_")

    # Avoid absurdly long Windows paths
    return cleaned[:140].strip("._-") or "Unknown_Video"


def assert_file_exists(filepath, label):
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        raise FileNotFoundError(f"{label} was not created or is empty: {filepath}")


# =========================
# Download media
# =========================

def download_media(video_url, cleaned_title):
    video_filename = os.path.join(videos_path, f"{cleaned_title}.mp4")
    audio_filename = os.path.join(audio_path, f"{cleaned_title}.m4a")

    ydl_opts_combined = build_ytdl_opts({
        "format": (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=1080][ext=mp4]/"
            "best[ext=mp4]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": video_filename,
    })

    start_download = time.time()

    if os.path.exists(video_filename) and os.path.getsize(video_filename) > 0:
        print(f"Reusing existing video package: {cleaned_title}.mp4")
    else:
        print(f"Downloading media package: {cleaned_title}.mp4")

        with yt_dlp.YoutubeDL(ydl_opts_combined) as ydl:
            ydl.download([video_url])

    assert_file_exists(video_filename, "Downloaded video")

    if os.path.exists(audio_filename) and os.path.getsize(audio_filename) > 0:
        print(f"Reusing existing audio package: {cleaned_title}.m4a")
        print(f"Total acquisition time: {time.time() - start_download:.2f} seconds\n")
        return video_filename, audio_filename

    print("Extracting audio locally...")
    a_start = time.time()

    # Copying is much faster when the source audio is already M4A/AAC.
    copy_result = try_subprocess([
        FFMPEG_EXE,
        "-y",
        "-i", video_filename,
        "-map", "0:a:0",
        "-vn",
        "-c:a", "copy",
        "-movflags", "+faststart",
        audio_filename,
    ], "Audio stream copy")

    if copy_result.returncode != 0:
        # Re-encode to AAC/M4A for reliability when stream copy is impossible.
        run_subprocess([
            FFMPEG_EXE,
            "-y",
            "-i", video_filename,
            "-vn",
            "-c:a", "aac",
            "-b:a", "192k",
            audio_filename,
        ], "Audio extraction")

    assert_file_exists(audio_filename, "Extracted audio")

    print(f" -> Local audio extraction took: {time.time() - a_start:.2f} seconds")
    print(f"Total acquisition time: {time.time() - start_download:.2f} seconds\n")

    return video_filename, audio_filename


# =========================
# OpenCV / YOLO reframing
# =========================

def load_face_cascades():
    cascade_dir = cv2.data.haarcascades
    cascade_files = [
        "haarcascade_frontalface_default.xml",
        "haarcascade_profileface.xml",
    ]
    cascades = []

    for cascade_file in cascade_files:
        cascade_path = os.path.join(cascade_dir, cascade_file)
        cascade = cv2.CascadeClassifier(cascade_path)

        if not cascade.empty():
            cascades.append(cascade)

    return cascades


def detect_faces(frame, face_cascades):
    if not face_cascades:
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    frame_width = gray.shape[1]
    faces = []

    for cascade in face_cascades:
        detections = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in detections:
            faces.append({
                "x": float(x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "center_x": float(x + w / 2),
                "area": float(w * h),
            })

        flipped = cv2.flip(gray, 1)
        flipped_detections = cascade.detectMultiScale(
            flipped,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in flipped_detections:
            real_x = frame_width - x - w
            faces.append({
                "x": float(real_x),
                "y": float(y),
                "w": float(w),
                "h": float(h),
                "center_x": float(real_x + w / 2),
                "area": float(w * h),
            })

    deduped_faces = []

    for face in sorted(faces, key=lambda item: item["area"], reverse=True):
        duplicate = any(
            abs(face["center_x"] - existing["center_x"]) < max(face["w"], existing["w"]) * 0.35
            and abs(face["y"] - existing["y"]) < max(face["h"], existing["h"]) * 0.35
            for existing in deduped_faces
        )

        if not duplicate:
            deduped_faces.append(face)

    return deduped_faces


def is_plausible_interview_face(face, frame_width, frame_height):
    aspect_ratio = face["w"] / max(1.0, face["h"])
    center_y = face["y"] + face["h"] / 2
    relative_height = face["h"] / max(1.0, frame_height)

    if aspect_ratio < 0.62 or aspect_ratio > 1.55:
        return False

    if relative_height < 0.055 or relative_height > 0.42:
        return False

    # Hands/notebooks often false-positive lower in the frame. Interview faces
    # should usually live in the upper/middle portion after the 1920px resize.
    if center_y > frame_height * 0.70:
        return False

    if face["center_x"] < frame_width * 0.04 or face["center_x"] > frame_width * 0.96:
        return False

    return True


def score_face_motion(current_gray, previous_gray, face):
    if previous_gray is None or current_gray is None:
        return 0.0

    height, width = current_gray.shape[:2]
    x1 = max(0, int(face["x"] + face["w"] * 0.18))
    x2 = min(width, int(face["x"] + face["w"] * 0.82))
    y1 = max(0, int(face["y"] + face["h"] * 0.48))
    y2 = min(height, int(face["y"] + face["h"] * 0.92))

    if x2 <= x1 or y2 <= y1:
        return 0.0

    current_roi = current_gray[y1:y2, x1:x2]
    previous_roi = previous_gray[y1:y2, x1:x2]

    if current_roi.shape != previous_roi.shape or current_roi.size == 0:
        return 0.0

    return float(np.mean(cv2.absdiff(current_roi, previous_roi)))


def clamp_center_x(center_x, resized_w, output_width):
    if resized_w >= output_width:
        return max(output_width / 2, min(center_x, resized_w - output_width / 2))

    return resized_w / 2


def smart_crop_to_shorts(temp_subclip, temp_tracked_avi, model):
    """
    Converts a horizontal clip into 1080x1920 vertical format with a restrained
    face-first virtual camera. Interview footage should stay centered around
    the speaker's face, with YOLO person tracking only used as a fallback.

    Uses AVI/MJPG as an intermediate because OpenCV's mp4 writing can crash
    or silently fail on Windows depending on codec availability.
    """

    cap = cv2.VideoCapture(temp_subclip)

    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open subclip: {temp_subclip}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or np.isnan(fps) or fps <= 0:
        fps = 24

    output_width = 1080
    output_height = 1920

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    out = cv2.VideoWriter(
        temp_tracked_avi,
        fourcc,
        fps,
        (output_width, output_height),
    )

    if not out.isOpened():
        cap.release()
        raise RuntimeError(f"OpenCV could not create output video: {temp_tracked_avi}")

    camera_center_x = None
    locked_speaker_center_x = None
    pending_speaker_center_x = None
    pending_speaker_hits = 0
    offcenter_hits = 0
    fallback_person_center_x = None
    frame_count = 0
    detection_checks = 0
    face_detection_hits = 0
    person_detection_hits = 0
    target_switches = 0
    speaker_switches = 0
    offcenter_reframes = 0
    previous_detected_source = None
    previous_detection_gray = None
    camera_positions = []

    face_cascades = load_face_cascades()

    detection_interval_seconds = 0.35
    skip_frames = max(1, int(round(fps * detection_interval_seconds)))
    detection_max_height = 640
    min_person_confidence = 0.35

    # Interview framing: hold a locked shot, then switch quickly when needed.
    material_offcenter_px = int(output_width * 0.24)
    fallback_dead_zone_px = int(output_width * 0.28)
    speaker_match_px = int(output_width * 0.26)
    speaker_switch_px = int(output_width * 0.32)
    switch_min_hits = 2
    offcenter_min_hits = 4
    motion_switch_margin = 3.0

    written_frames = 0

    try:
        while True:
            ret, frame = cap.read()

            if not ret or frame is None:
                break

            h, w = frame.shape[:2]
            if h <= 0 or w <= 0:
                continue

            # Resize by height first so the frame is always 1920px tall
            scale = output_height / h
            resized_w = max(1, int(w * scale))

            frame_resized = cv2.resize(
                frame,
                (resized_w, output_height),
                interpolation=cv2.INTER_AREA,
            )

            requested_center_x = None
            detected_source = None
            force_recenter = False

            if camera_center_x is None:
                camera_center_x = resized_w / 2

            if resized_w >= output_width and frame_count % skip_frames == 0:
                detection_checks += 1
                detection_scale = min(1.0, detection_max_height / output_height)
                detection_w = max(1, int(resized_w * detection_scale))

                if detection_scale < 1.0:
                    detection_frame = cv2.resize(
                        frame_resized,
                        (detection_w, int(output_height * detection_scale)),
                        interpolation=cv2.INTER_AREA,
                    )
                else:
                    detection_frame = frame_resized

                detection_gray = cv2.cvtColor(detection_frame, cv2.COLOR_BGR2GRAY)
                faces = [
                    face
                    for face in detect_faces(detection_frame, face_cascades)
                    if is_plausible_interview_face(
                        face,
                        frame_width=detection_w,
                        frame_height=detection_frame.shape[0],
                    )
                ]

                if faces:
                    face_detection_hits += 1

                    for face in faces:
                        face["motion_score"] = score_face_motion(
                            detection_gray,
                            previous_detection_gray,
                            face,
                        )
                        face["scaled_center_x"] = face["center_x"] / detection_scale

                    if len(faces) == 1:
                        selected_face = faces[0]
                    else:
                        if locked_speaker_center_x is not None:
                            current_face = min(
                                faces,
                                key=lambda item: abs(item["scaled_center_x"] - locked_speaker_center_x),
                            )
                        else:
                            current_face = None

                        motion_sorted = sorted(
                            faces,
                            key=lambda item: (
                                item["motion_score"],
                                item["area"],
                            ),
                            reverse=True,
                        )
                        selected_face = motion_sorted[0]

                        if current_face is not None:
                            current_motion = current_face["motion_score"]
                            selected_motion = selected_face["motion_score"]
                            selected_is_different_speaker = (
                                abs(selected_face["scaled_center_x"] - locked_speaker_center_x)
                                > speaker_switch_px
                            )

                            if (
                                not selected_is_different_speaker
                                or selected_motion < current_motion + motion_switch_margin
                            ):
                                selected_face = current_face

                    selected_center_x = selected_face["scaled_center_x"]

                    if locked_speaker_center_x is None:
                        locked_speaker_center_x = selected_center_x
                        requested_center_x = selected_center_x
                        detected_source = "face"
                        force_recenter = True
                    else:
                        speaker_delta = abs(selected_center_x - locked_speaker_center_x)

                        if speaker_delta > speaker_switch_px and len(faces) > 1:
                            if (
                                pending_speaker_center_x is not None
                                and abs(selected_center_x - pending_speaker_center_x) <= speaker_match_px
                            ):
                                pending_speaker_hits += 1
                                pending_speaker_center_x = (
                                    pending_speaker_center_x * 0.55
                                    + selected_center_x * 0.45
                                )
                            else:
                                pending_speaker_center_x = selected_center_x
                                pending_speaker_hits = 1

                            if pending_speaker_hits >= switch_min_hits:
                                locked_speaker_center_x = pending_speaker_center_x
                                requested_center_x = locked_speaker_center_x
                                detected_source = "face"
                                force_recenter = True
                                target_switches += 1
                                speaker_switches += 1
                                pending_speaker_center_x = None
                                pending_speaker_hits = 0
                        else:
                            pending_speaker_center_x = None
                            pending_speaker_hits = 0
                            face_offset = abs(selected_center_x - camera_center_x)

                            if face_offset > material_offcenter_px:
                                offcenter_hits += 1
                            else:
                                offcenter_hits = 0

                            if offcenter_hits >= offcenter_min_hits:
                                locked_speaker_center_x = selected_center_x
                                requested_center_x = locked_speaker_center_x
                                detected_source = "face"
                                force_recenter = True
                                offcenter_reframes += 1
                                offcenter_hits = 0

                    previous_detection_gray = detection_gray

                elif ENABLE_PERSON_FALLBACK and locked_speaker_center_x is None and model is not None:
                    results = model.predict(
                        detection_frame,
                        verbose=False,
                        conf=min_person_confidence,
                    )

                    largest_area = 0
                    largest_box = None

                    for result in results:
                        if result.boxes is None:
                            continue

                        for box in result.boxes:
                            cls_id = int(box.cls.item())

                            # COCO class 0 = person
                            if cls_id == 0:
                                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().tolist()
                                confidence = float(box.conf.item()) if box.conf is not None else 0.0

                                if confidence < min_person_confidence:
                                    continue

                                box_width = max(0, x2 - x1)
                                box_height = max(0, y2 - y1)
                                area = box_width * box_height

                                if area > largest_area:
                                    largest_area = area
                                    largest_box = [x1, y1, x2, y2]

                    if largest_box is not None:
                        person_detection_hits += 1
                        raw_person_center_x = (
                            (largest_box[0] + largest_box[2]) / 2
                        ) / detection_scale

                        if fallback_person_center_x is None:
                            fallback_person_center_x = raw_person_center_x

                        requested_center_x = fallback_person_center_x
                        detected_source = "person"

            if requested_center_x is not None:
                if previous_detected_source and previous_detected_source != detected_source:
                    target_switches += 1

                previous_detected_source = detected_source
                requested_center_x = clamp_center_x(requested_center_x, resized_w, output_width)

                if force_recenter:
                    camera_center_x = requested_center_x
                elif abs(requested_center_x - camera_center_x) > fallback_dead_zone_px:
                    camera_center_x = requested_center_x

            camera_center_x = clamp_center_x(camera_center_x, resized_w, output_width)

            camera_positions.append(float(camera_center_x))

            # Calculate crop window
            start_x = int(camera_center_x - output_width / 2)

            if resized_w >= output_width:
                start_x = max(0, min(start_x, resized_w - output_width))
                end_x = start_x + output_width
                cropped_frame = frame_resized[:, start_x:end_x]
            else:
                # Extremely narrow/tall video: resize to 1080x1920
                cropped_frame = cv2.resize(
                    frame_resized,
                    (output_width, output_height),
                    interpolation=cv2.INTER_AREA,
                )

            # Safety check before writing into OpenCV C++ layer
            if cropped_frame is None or cropped_frame.size == 0:
                frame_count += 1
                continue

            if cropped_frame.shape[:2] != (output_height, output_width):
                cropped_frame = cv2.resize(
                    cropped_frame,
                    (output_width, output_height),
                    interpolation=cv2.INTER_AREA,
                )

            cropped_frame = np.ascontiguousarray(cropped_frame, dtype=np.uint8)

            out.write(cropped_frame)
            written_frames += 1
            frame_count += 1

    finally:
        cap.release()
        out.release()

    if written_frames == 0:
        raise RuntimeError(f"No frames were written for: {temp_subclip}")

    assert_file_exists(temp_tracked_avi, "Tracked intermediate video")

    if len(camera_positions) > 1:
        camera_deltas = np.abs(np.diff(np.asarray(camera_positions, dtype=np.float32)))
        avg_camera_move = float(np.mean(camera_deltas))
        max_camera_jump = float(np.max(camera_deltas))
    else:
        avg_camera_move = 0.0
        max_camera_jump = 0.0

    face_detection_rate = face_detection_hits / detection_checks if detection_checks else 0.0
    person_detection_rate = person_detection_hits / detection_checks if detection_checks else 0.0
    camera_stability = max(0.0, min(1.0, 1.0 - (avg_camera_move / 7.0)))
    detection_quality = max(face_detection_rate, person_detection_rate * 0.65)
    framing_score = max(0.0, min(1.0, 0.68 * camera_stability + 0.32 * detection_quality))

    return {
        "frames_written": int(written_frames),
        "detection_checks": int(detection_checks),
        "face_detection_rate": float(face_detection_rate),
        "person_detection_rate": float(person_detection_rate),
        "avg_camera_move_px": float(avg_camera_move),
        "max_camera_jump_px": float(max_camera_jump),
        "target_switches": int(target_switches),
        "speaker_switches": int(speaker_switches),
        "offcenter_reframes": int(offcenter_reframes),
        "framing_score": float(framing_score),
    }


def probe_video_file(video_path):
    metadata = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "has_audio": False,
    }

    cmd = [
        FFPROBE_EXE,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        video_path,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            return metadata

        payload = json.loads(result.stdout or "{}")
    except Exception:
        return metadata

    format_info = payload.get("format", {})
    metadata["duration"] = float(format_info.get("duration") or 0.0)

    for stream in payload.get("streams", []):
        codec_type = stream.get("codec_type")

        if codec_type == "video" and not metadata["width"]:
            metadata["width"] = int(stream.get("width") or 0)
            metadata["height"] = int(stream.get("height") or 0)
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"

            try:
                numerator, denominator = rate.split("/")
                metadata["fps"] = float(numerator) / max(1.0, float(denominator))
            except Exception:
                metadata["fps"] = 0.0

        if codec_type == "audio":
            metadata["has_audio"] = True

    return metadata


def estimate_black_frame_ratio(video_path, max_samples=18):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        return 1.0

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    samples = []

    if frame_count <= 0:
        cap.release()
        return 1.0

    for frame_index in np.linspace(0, max(0, frame_count - 1), num=min(max_samples, frame_count), dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ret, frame = cap.read()

        if not ret or frame is None:
            continue

        samples.append(float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))))

    cap.release()

    if not samples:
        return 1.0

    black_samples = sum(1 for value in samples if value < 8.0)
    return black_samples / len(samples)


def build_render_qc(video_path, crop_stats, expected_duration):
    probe = probe_video_file(video_path)
    black_frame_ratio = estimate_black_frame_ratio(video_path)
    flags = []

    if probe["width"] != 1080 or probe["height"] != 1920:
        flags.append("unexpected resolution")

    if not probe["has_audio"]:
        flags.append("missing audio")

    if expected_duration and abs(probe["duration"] - expected_duration) > 1.25:
        flags.append("duration drift")

    if black_frame_ratio > 0.08:
        flags.append("possible black frames")

    if crop_stats.get("framing_score", 1.0) < 0.55:
        flags.append("low framing confidence")

    intentional_reframes = (
        crop_stats.get("speaker_switches", 0)
        + crop_stats.get("offcenter_reframes", 0)
    )

    if crop_stats.get("max_camera_jump_px", 0.0) > 22 and intentional_reframes == 0:
        flags.append("noticeable camera jump")

    return {
        **probe,
        "black_frame_ratio": float(black_frame_ratio),
        "crop": crop_stats,
        "flags": flags,
        "passed": not flags,
    }


# =========================
# Viral clip scoring
# =========================

@dataclass
class CandidateClip:
    start_time: float
    end_time: float
    score: float
    audio_score: float
    text_score: float
    opening_score: float
    comment_score: float
    pacing_score: float
    duration_score: float
    boundary_score: float
    diversity_score: float
    rank_signals: dict
    transcript_excerpt: str
    hook_reason: str = ""
    topic_fingerprint: list = field(default_factory=list)
    suggested_title: str = ""
    suggested_caption: str = ""
    hashtags: list = field(default_factory=list)
    render_qc: dict = field(default_factory=dict)
    output_file: str = ""
    source_state_key: str = ""
    source_video_url: str = ""
    source_title: str = ""


VIRAL_KEYWORD_WEIGHTS = {
    # Conflict, stakes, and controversy
    "scam": 3.0,
    "fraud": 3.0,
    "lie": 2.5,
    "lying": 2.5,
    "wrong": 2.0,
    "mistake": 1.8,
    "problem": 1.7,
    "danger": 2.2,
    "risk": 1.8,
    "debt": 2.2,
    "broke": 2.2,
    "bankrupt": 2.5,
    "tax": 1.6,
    "lawsuit": 2.5,
    "illegal": 2.6,
    "controversial": 2.4,
    "exposed": 2.8,
    "truth": 2.0,
    "secret": 2.4,
    "insane": 2.2,
    "crazy": 2.0,
    "shocking": 2.4,
    "death threat": 3.2,
    "default": 2.2,
    "defaults": 2.2,
    "evil": 2.0,
    "victim": 1.8,
    "victims": 1.8,
    "offended": 1.8,
    "angry": 1.8,
    "terrifying": 2.3,
    "scary": 2.1,
    "panic": 2.1,
    "crisis": 2.4,
    "collapse": 2.2,
    "destroy": 2.1,
    "ruin": 2.1,
    "failure": 1.8,
    "trap": 2.2,
    "predatory": 2.6,

    # Strong positive/negative emotion
    "amazing": 1.6,
    "best": 1.5,
    "love": 1.5,
    "hate": 1.8,
    "terrible": 1.8,
    "awful": 1.8,
    "fear": 1.8,
    "angry": 1.8,
    "sad": 1.5,
    "happy": 1.2,
    "excited": 1.5,
    "passion": 1.5,
    "brutal": 2.0,
    "embarrassing": 1.9,
    "humiliating": 2.0,
    "regret": 1.8,
    "obsessed": 1.5,
    "hilarious": 1.6,
    "wild": 1.8,

    # Mainstream topics that often travel well
    "money": 2.0,
    "million": 2.0,
    "billion": 2.2,
    "rich": 1.7,
    "poor": 1.7,
    "business": 1.4,
    "ai": 2.0,
    "artificial intelligence": 2.4,
    "crypto": 2.0,
    "bitcoin": 2.0,
    "government": 1.8,
    "politics": 1.8,
    "war": 2.3,
    "crime": 2.2,
    "health": 1.5,
    "diet": 1.4,
    "addiction": 2.0,
    "dating": 1.8,
    "marriage": 1.7,
    "religion": 2.0,
    "celebrity": 1.8,
    "credit card": 2.2,
    "credit cards": 2.2,
    "student loan": 2.2,
    "student loans": 2.2,
    "interest rate": 1.8,
    "car payment": 1.9,
    "electric car": 1.7,
    "housing": 1.7,
    "rent": 1.5,
    "job": 1.3,
    "jobs": 1.3,
    "college": 1.7,
    "degree": 1.6,
    "degrees": 1.6,
    "wealth gap": 2.0,
    "gender wealth gap": 2.4,
    "minimum payment": 1.8,
    "porsche": 1.5,
    "audi": 1.4,
}

HOOK_PATTERNS = [
    r"\bhere'?s why\b",
    r"\bthe reason\b",
    r"\bwhat people don'?t understand\b",
    r"\bnobody talks about\b",
    r"\byou have to understand\b",
    r"\bthe truth is\b",
    r"\bthis is why\b",
    r"\bthink about\b",
    r"\bhow do you\b",
    r"\bwhy would\b",
    r"\bwhat if\b",
    r"\byou won'?t believe\b",
    r"\bthis is the part\b",
    r"\bmost people\b",
    r"\beveryone thinks\b",
    r"\bthe biggest\b",
    r"\bthe problem is\b",
    r"\bfirst of all\b",
    r"\blook at this\b",
    r"\bthat'?s crazy\b",
    r"\bthat'?s insane\b",
    r"\bthe actual reality\b",
]

TOPIC_KEYWORDS = {
    "money", "debt", "credit", "loan", "loans", "college", "job", "jobs",
    "ai", "government", "politics", "tax", "crime", "health", "dating",
    "marriage", "religion", "business", "crypto", "bitcoin", "housing",
    "rent", "wealth", "income", "car", "cars", "porsche", "audi",
}

EMOTION_KEYWORDS = {
    "crazy", "insane", "shocking", "scary", "terrifying", "brutal", "angry",
    "offended", "hate", "love", "amazing", "awful", "terrible", "evil",
    "hilarious", "wild", "embarrassing", "humiliating", "regret", "fear",
}

CONFLICT_KEYWORDS = {
    "wrong", "problem", "lie", "lying", "scam", "fraud", "illegal", "risk",
    "danger", "lawsuit", "death", "threat", "default", "defaults", "victim",
    "victims", "predatory", "trap", "failure", "mistake", "destroy", "ruin",
}

FILLER_WORDS = {
    "yeah", "okay", "like", "just", "really", "actually", "basically", "kind",
    "sort", "stuff", "thing", "things", "know", "mean", "right", "well",
    "um", "uh", "you", "i", "we",
}

COMMENT_TRIGGER_WORDS = {
    "should", "shouldn't", "wrong", "right", "why", "how", "what", "agree",
    "disagree", "crazy", "insane", "scary", "evil", "victim", "victims",
    "default", "defaults", "debt", "money", "rich", "poor", "government",
    "college", "tax", "illegal", "fraud", "scam", "fair", "unfair",
    "freedom", "problem", "truth", "reality", "angry", "offended",
}

WEAK_START_WORDS = {
    "and", "but", "so", "because", "then", "that", "this", "those", "these",
    "they", "them", "their", "he", "she", "his", "her", "him", "it", "its",
    "we", "you", "i", "there", "which", "who", "when", "where",
}

FILLER_OPENERS = {
    "yeah", "yes", "no", "okay", "well", "like", "um", "uh", "right",
    "actually", "basically", "literally", "honestly",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that",
    "this", "these", "those", "is", "are", "was", "were", "be", "been",
    "being", "to", "of", "for", "with", "in", "on", "at", "by", "from",
    "as", "it", "its", "i", "you", "we", "they", "he", "she", "them",
    "him", "her", "my", "your", "our", "their", "me", "us", "do", "does",
    "did", "have", "has", "had", "not", "so", "just", "like", "know",
    "think", "really", "right", "yeah", "well", "what", "when", "where",
    "why", "how",
}

HASHTAG_KEYWORDS = {
    "money": "#money",
    "debt": "#debt",
    "credit": "#credit",
    "college": "#college",
    "business": "#business",
    "ai": "#ai",
    "crypto": "#crypto",
    "bitcoin": "#bitcoin",
    "government": "#politics",
    "politics": "#politics",
    "health": "#health",
    "dating": "#dating",
    "marriage": "#relationships",
    "crime": "#truecrime",
    "job": "#career",
    "jobs": "#career",
}


def normalize_array(values):
    values = np.asarray(values, dtype=np.float32)

    if values.size == 0:
        return values

    low = float(np.percentile(values, 5))
    high = float(np.percentile(values, 95))

    if high <= low:
        return np.zeros_like(values, dtype=np.float32)

    return np.clip((values - low) / (high - low), 0, 1)


def saturating_score(value, scale):
    if value <= 0:
        return 0.0

    return float(1 - np.exp(-value / scale))


def words_from_text(text):
    return re.findall(r"[a-zA-Z][a-zA-Z']+|\b\d+[\d,.]*%?\b", text.lower())


def first_spoken_word(text):
    words = words_from_text(text)
    return words[0] if words else ""


def compact_text(text, max_chars=90):
    text = re.sub(r"\s+", " ", text).strip(" -._")

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars].rsplit(" ", 1)[0].strip(" -._")
    return shortened or text[:max_chars].strip(" -._")


def extract_topic_fingerprint(text, max_terms=10):
    words = words_from_text(text)
    weighted_terms = {}

    for word in words:
        if word in STOPWORDS or len(word) < 3:
            continue

        weight = 1.0

        if word in TOPIC_KEYWORDS:
            weight += 2.0
        if word in EMOTION_KEYWORDS or word in CONFLICT_KEYWORDS:
            weight += 1.4
        if word in COMMENT_TRIGGER_WORDS:
            weight += 0.8

        weighted_terms[word] = weighted_terms.get(word, 0.0) + weight

    for phrase, weight in VIRAL_KEYWORD_WEIGHTS.items():
        if " " in phrase and phrase in text.lower():
            weighted_terms[phrase.replace(" ", "_")] = weighted_terms.get(phrase.replace(" ", "_"), 0.0) + weight

    return [
        term
        for term, _ in sorted(weighted_terms.items(), key=lambda item: item[1], reverse=True)[:max_terms]
    ]


def topic_similarity(left_terms, right_terms):
    left = set(left_terms)
    right = set(right_terms)

    if not left or not right:
        return 0.0

    return len(left & right) / len(left | right)


def explain_hook(text, text_details, opening_score, audio_score):
    normalized_text = text.lower()

    for pattern in HOOK_PATTERNS:
        match = re.search(pattern, normalized_text)

        if match:
            return f"hook phrase: {match.group(0)}"

    if text.count("?"):
        return "question creates curiosity"

    for word in words_from_text(text):
        if word in CONFLICT_KEYWORDS:
            return f"conflict word: {word}"
        if word in EMOTION_KEYWORDS:
            return f"emotion word: {word}"
        if word in TOPIC_KEYWORDS:
            return f"mainstream topic: {word}"

    if text_details.get("specificity_score", 0) >= 0.45:
        return "specific numbers or money"

    if opening_score >= 0.65:
        return "strong opening"

    if audio_score >= 0.65:
        return "high audio energy"

    return "balanced interest signals"


def score_boundary_quality(matching_segments, clip_start, clip_end):
    if not matching_segments:
        return 0.0, ["no transcript segments"]

    flags = []
    score = 1.0
    opening_word = first_spoken_word(matching_segments[0]["text"])
    closing_text = matching_segments[-1]["text"].strip()

    if opening_word in WEAK_START_WORDS:
        score -= 0.22
        flags.append(f"context opener: {opening_word}")

    if opening_word in FILLER_OPENERS:
        score -= 0.12
        flags.append(f"soft opener: {opening_word}")

    if closing_text and closing_text[-1] not in ".?!":
        score -= 0.10
        flags.append("ending may be mid-thought")

    duration = clip_end - clip_start

    if duration > 56:
        score -= 0.08
        flags.append("near max duration")

    if duration < 34:
        score -= 0.08
        flags.append("short context window")

    return max(0.0, min(1.0, score)), flags


def naturalize_clip_window(segments, provisional_start, duration, total_duration):
    window_end = min(provisional_start + duration, total_duration)
    window_segments = [
        segment
        for segment in segments
        if segment["end"] > provisional_start and segment["start"] < window_end
    ]

    if not window_segments:
        return None

    first_segment = next(
        (
            segment
            for segment in window_segments
            if segment["end"] > provisional_start + 0.25 and segment["text"].strip()
        ),
        window_segments[0],
    )
    first_index = segments.index(first_segment)
    opening_word = first_spoken_word(first_segment["text"])

    if opening_word in WEAK_START_WORDS or opening_word in FILLER_OPENERS:
        if first_index > 0:
            previous_segment = segments[first_index - 1]
            gap = float(first_segment["start"]) - float(previous_segment["end"])

            if gap <= 1.8 and float(first_segment["start"]) - float(previous_segment["start"]) <= 9:
                first_segment = previous_segment

    clip_start = max(0.0, float(first_segment["start"]) - 0.22)
    clip_end_limit = min(clip_start + duration, total_duration)
    matching_segments = [
        segment
        for segment in segments
        if segment["end"] > clip_start and segment["start"] < clip_end_limit
    ]

    completed_segments = [
        segment
        for segment in matching_segments
        if segment["end"] <= clip_end_limit
    ]

    if completed_segments:
        clip_end = min(total_duration, float(completed_segments[-1]["end"]) + 0.24)
    else:
        clip_end = clip_end_limit

    matching_segments = [
        segment
        for segment in matching_segments
        if segment["start"] < clip_end and segment["end"] <= clip_end + 0.05
    ]

    if clip_end - clip_start > MAX_CLIP_DURATION:
        clip_end = clip_start + MAX_CLIP_DURATION
        matching_segments = [
            segment
            for segment in matching_segments
            if segment["end"] <= clip_end + 0.05
        ]

    return clip_start, clip_end, matching_segments


def build_suggested_copy(text, hook_reason, topic_terms):
    sentences = [
        compact_text(sentence, 78)
        for sentence in re.split(r"(?<=[.?!])\s+", text)
        if len(sentence.strip()) >= 18
    ]

    title = ""

    for sentence in sentences[:5]:
        sentence_terms = set(words_from_text(sentence))
        signal_terms = CONFLICT_KEYWORDS | EMOTION_KEYWORDS | TOPIC_KEYWORDS

        if "?" in sentence or bool(sentence_terms & signal_terms):
            title = sentence
            break

    if not title:
        title = sentences[0] if sentences else compact_text(text, 78)

    if title and title[-1] not in ".?!":
        title = title.rstrip(",;:")

    hook_label = hook_reason.replace("hook phrase: ", "").replace("mainstream topic: ", "")
    caption = compact_text(f"{title} ({hook_label})", 120)

    hashtags = []
    for term in topic_terms:
        normalized = term.replace("_", " ")
        tag = HASHTAG_KEYWORDS.get(normalized) or HASHTAG_KEYWORDS.get(normalized.split(" ")[0])

        if tag and tag not in hashtags:
            hashtags.append(tag)

        if len(hashtags) >= 4:
            break

    for fallback in ["#podcast", "#shorts"]:
        if fallback not in hashtags:
            hashtags.append(fallback)

    return title, caption, hashtags[:5]


def candidate_to_dict(candidate):
    return asdict(candidate)


def write_clip_review_exports(cleaned_title, selected_clips, candidates=None):
    review_json = os.path.join(metadata_path, f"{cleaned_title}_clip_review.json")
    review_csv = os.path.join(metadata_path, f"{cleaned_title}_clip_review.csv")

    selected_payload = [candidate_to_dict(clip) for clip in selected_clips]
    top_candidate_payload = []

    if candidates is not None:
        top_candidate_payload = [
            candidate_to_dict(clip)
            for clip in sorted(candidates, key=lambda item: item.score, reverse=True)[:50]
        ]
    elif os.path.exists(review_json) and os.path.getsize(review_json) > 0:
        try:
            with open(review_json, "r", encoding="utf-8") as f:
                top_candidate_payload = json.load(f).get("top_candidates", [])
        except Exception:
            top_candidate_payload = []

    with open(review_json, "w", encoding="utf-8") as f:
        json.dump({
            "scoring_model_version": SCORING_MODEL_VERSION,
            "selected": selected_payload,
            "top_candidates": top_candidate_payload,
        }, f, indent=4)

    columns = [
        "clip_number",
        "start_time",
        "end_time",
        "duration",
        "score",
        "text_score",
        "audio_score",
        "opening_score",
        "comment_score",
        "pacing_score",
        "duration_score",
        "boundary_score",
        "diversity_score",
        "hook_reason",
        "topic_fingerprint",
        "suggested_title",
        "suggested_caption",
        "hashtags",
        "output_file",
        "qc_passed",
        "qc_flags",
        "transcript_excerpt",
    ]

    with open(review_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()

        for index, clip in enumerate(selected_clips, start=1):
            qc_flags = clip.render_qc.get("flags", []) if clip.render_qc else []
            writer.writerow({
                "clip_number": index,
                "start_time": f"{clip.start_time:.2f}",
                "end_time": f"{clip.end_time:.2f}",
                "duration": f"{clip.end_time - clip.start_time:.2f}",
                "score": f"{clip.score:.4f}",
                "text_score": f"{clip.text_score:.4f}",
                "audio_score": f"{clip.audio_score:.4f}",
                "opening_score": f"{clip.opening_score:.4f}",
                "comment_score": f"{clip.comment_score:.4f}",
                "pacing_score": f"{clip.pacing_score:.4f}",
                "duration_score": f"{clip.duration_score:.4f}",
                "boundary_score": f"{clip.boundary_score:.4f}",
                "diversity_score": f"{clip.diversity_score:.4f}",
                "hook_reason": clip.hook_reason,
                "topic_fingerprint": ", ".join(clip.topic_fingerprint),
                "suggested_title": clip.suggested_title,
                "suggested_caption": clip.suggested_caption,
                "hashtags": " ".join(clip.hashtags),
                "output_file": clip.output_file,
                "qc_passed": clip.render_qc.get("passed", "") if clip.render_qc else "",
                "qc_flags": ", ".join(qc_flags),
                "transcript_excerpt": clip.transcript_excerpt,
            })

    return review_json, review_csv


def transcribe_audio_segments(audio_filename, cleaned_title, lang_code="en"):
    transcript_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_segments.json",
    )

    if os.path.exists(transcript_filepath) and os.path.getsize(transcript_filepath) > 0:
        print("Reusing segment-level transcript cache...")

        with open(transcript_filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    import torch
    from faster_whisper import WhisperModel

    if torch.cuda.is_available():
        print("Initializing faster-whisper (Model: tiny | GPU Accelerated)...")
        device_type = "cuda"
        compute_type = "float16"
    else:
        print("Initializing faster-whisper (Model: tiny | CPU)...")
        device_type = "cpu"
        compute_type = "int8"

    model = WhisperModel(
        "tiny",
        device=device_type,
        compute_type=compute_type,
    )

    print(f"Transcribing segment text only (Language forced to: {lang_code})...")
    start_transcribe = time.time()

    segments_iter, info = model.transcribe(
        audio_filename,
        language=lang_code,
        beam_size=1,
        best_of=1,
        vad_filter=True,
        word_timestamps=False,
        condition_on_previous_text=False,
    )

    segments = []

    for segment in segments_iter:
        segments.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text.strip(),
        })

    payload = {
        "language": getattr(info, "language", lang_code),
        "duration": float(getattr(info, "duration", 0) or 0),
        "segments": segments,
    }

    with open(transcript_filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f" -> Segment transcription took: {time.time() - start_transcribe:.2f} seconds\n")

    return payload


def analyze_audio_features(audio_filename, cleaned_title):
    features_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_audio_features.json",
    )

    if os.path.exists(features_filepath) and os.path.getsize(features_filepath) > 0:
        print("Reusing audio feature cache...")

        with open(features_filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    analysis_wav = os.path.join(audio_path, f"{cleaned_title}_analysis_16k.wav")

    print("Mapping audio energy and frequency movement...")
    start_audio = time.time()

    run_subprocess([
        FFMPEG_EXE,
        "-y",
        "-i", audio_filename,
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        analysis_wav,
    ], "Audio analysis WAV extraction")

    rms_values = []
    peak_values = []
    zcr_values = []
    centroid_values = []
    flux_values = []

    previous_magnitude = None

    with wave.open(analysis_wav, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        chunk_size = sample_rate

        while True:
            raw = wav_file.readframes(chunk_size)

            if not raw:
                break

            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            if samples.size == 0:
                continue

            rms = float(np.sqrt(np.mean(samples * samples)))
            peak = float(np.max(np.abs(samples)))
            zcr = float(np.mean(samples[:-1] * samples[1:] < 0)) if samples.size > 1 else 0.0

            windowed = samples * np.hanning(samples.size)
            magnitude = np.abs(np.fft.rfft(windowed))
            freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)
            mag_sum = float(np.sum(magnitude))
            centroid = float(np.sum(freqs * magnitude) / mag_sum) if mag_sum > 0 else 0.0

            if previous_magnitude is None:
                flux = 0.0
            else:
                shared = min(previous_magnitude.size, magnitude.size)
                flux = float(np.mean(np.abs(magnitude[:shared] - previous_magnitude[:shared])))

            previous_magnitude = magnitude

            rms_values.append(rms)
            peak_values.append(peak)
            zcr_values.append(zcr)
            centroid_values.append(centroid)
            flux_values.append(flux)

    try:
        os.remove(analysis_wav)
    except Exception:
        pass

    rms_norm = normalize_array(rms_values)
    peak_norm = normalize_array(peak_values)
    zcr_norm = normalize_array(zcr_values)
    centroid_norm = normalize_array(centroid_values)
    flux_norm = normalize_array(flux_values)
    rms_delta_norm = normalize_array(np.abs(np.diff(rms_norm, prepend=rms_norm[:1] if rms_norm.size else [0])))

    excitement = (
        0.38 * rms_norm
        + 0.20 * peak_norm
        + 0.22 * flux_norm
        + 0.12 * rms_delta_norm
        + 0.05 * centroid_norm
        + 0.03 * zcr_norm
    )

    payload = {
        "seconds": [
            {
                "time": index,
                "energy": float(rms_norm[index]),
                "peak": float(peak_norm[index]),
                "frequency_flux": float(flux_norm[index]),
                "tone_shift": float(rms_delta_norm[index]),
                "excitement": float(excitement[index]),
            }
            for index in range(len(rms_values))
        ]
    }

    with open(features_filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)

    print(f" -> Audio feature mapping took: {time.time() - start_audio:.2f} seconds\n")

    return payload


def score_text_window(text):
    normalized_text = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", normalized_text)
    word_count = max(1, len(words))

    weighted_keyword_total = 0.0

    for phrase, weight in VIRAL_KEYWORD_WEIGHTS.items():
        if " " in phrase:
            weighted_keyword_total += normalized_text.count(phrase) * weight
        else:
            weighted_keyword_total += words.count(phrase) * weight

    topic_hits = sum(1 for word in words if word in TOPIC_KEYWORDS)
    emotion_hits = sum(1 for word in words if word in EMOTION_KEYWORDS)
    conflict_hits = sum(1 for word in words if word in CONFLICT_KEYWORDS)
    filler_hits = sum(1 for word in words if word in FILLER_WORDS)

    hook_hits = sum(
        1
        for pattern in HOOK_PATTERNS
        if re.search(pattern, normalized_text)
    )

    question_hits = text.count("?")
    number_hits = len(re.findall(r"\b\d+[\d,.]*%?\b", text))
    money_hits = len(re.findall(r"\$\s?\d+|\b\d+[\d,.]*\s?(dollars?|bucks?)\b", text, re.IGNORECASE))
    percent_hits = len(re.findall(r"\b\d+[\d,.]*\s?%\b|\bpercent\b", normalized_text))
    specificity_hits = number_hits + money_hits + percent_hits

    payoff_hits = len(re.findall(
        r"\b(because|therefore|so that means|that means|the reason|that's why|this is why|which means|as a result)\b",
        normalized_text,
    ))
    contrast_hits = len(re.findall(r"\b(but|however|instead|actually|the problem is|the truth is)\b", normalized_text))

    density_base = max(35, word_count)
    keyword_density = weighted_keyword_total * 100 / density_base
    topic_density = topic_hits * 100 / density_base
    emotion_density = emotion_hits * 100 / density_base
    conflict_density = conflict_hits * 100 / density_base

    first_words = " ".join(words[:28])
    opener_hook_hits = sum(
        1
        for pattern in HOOK_PATTERNS
        if re.search(pattern, first_words)
    )
    opener_question = 1 if "?" in text[:220] else 0

    hook_score = min(1.0, hook_hits * 0.24 + opener_hook_hits * 0.34 + opener_question * 0.16)
    keyword_score = saturating_score(keyword_density, 8.0)
    topic_score = saturating_score(topic_density, 5.5)
    emotion_score = saturating_score(emotion_density, 4.0)
    conflict_score = saturating_score(conflict_density, 4.3)
    specificity_score = saturating_score(specificity_hits, 3.2)
    payoff_score = saturating_score(payoff_hits + contrast_hits * 0.65, 3.0)

    filler_ratio = filler_hits / word_count
    filler_penalty = min(0.35, max(0.0, filler_ratio - 0.22) * 1.8)
    clarity_score = max(0.0, 1.0 - filler_penalty)

    text_score = (
        0.20 * hook_score
        + 0.16 * keyword_score
        + 0.15 * conflict_score
        + 0.14 * emotion_score
        + 0.13 * topic_score
        + 0.11 * specificity_score
        + 0.07 * payoff_score
        + 0.04 * clarity_score
    )

    text_score = max(0.0, min(0.98, text_score * clarity_score))

    return {
        "score": float(text_score),
        "hook_score": float(hook_score),
        "keyword_score": float(keyword_score),
        "conflict_score": float(conflict_score),
        "emotion_score": float(emotion_score),
        "topic_score": float(topic_score),
        "specificity_score": float(specificity_score),
        "payoff_score": float(payoff_score),
        "clarity_score": float(clarity_score),
        "filler_ratio": float(filler_ratio),
        "word_count": int(word_count),
    }


def score_opening_text(text):
    if not text.strip():
        return 0.0

    details = score_text_window(text)
    normalized_text = text.lower()

    first_line_bonus = 0.0

    if re.search(r"\b(why|what|how|here'?s|look|first of all|the truth|the problem|nobody|most people)\b", normalized_text):
        first_line_bonus += 0.25

    if re.search(r"\b\d+[\d,.]*%?\b|\$\s?\d+", text):
        first_line_bonus += 0.15

    if any(word in normalized_text for word in ["crazy", "insane", "scary", "brutal", "wrong", "debt", "money"]):
        first_line_bonus += 0.18

    return min(1.0, details["score"] * 0.75 + details["hook_score"] * 0.25 + first_line_bonus)


def score_comment_potential(text):
    normalized_text = text.lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", normalized_text)

    if not words:
        return 0.0

    trigger_hits = sum(1 for word in words if word in COMMENT_TRIGGER_WORDS)
    question_hits = text.count("?")
    contrast_hits = len(re.findall(r"\b(but|however|actually|instead|first of all|the truth is|the problem is)\b", normalized_text))
    absolute_hits = len(re.findall(r"\b(always|never|everyone|nobody|all|none|everybody|impossible|guaranteed)\b", normalized_text))
    money_or_number_hits = len(re.findall(r"\$\s?\d+|\b\d+[\d,.]*%?\b|\b\d+[\d,.]*\s?(dollars?|bucks?)\b", text, re.IGNORECASE))
    debate_phrase_hits = len(re.findall(
        r"\b(do you think|would you|should you|is it fair|is this fair|hot take|unpopular opinion|people don'?t understand)\b",
        normalized_text,
    ))

    raw_score = (
        trigger_hits * 0.22
        + question_hits * 0.55
        + contrast_hits * 0.30
        + absolute_hits * 0.28
        + money_or_number_hits * 0.16
        + debate_phrase_hits * 0.75
    )

    return min(1.0, saturating_score(raw_score, 2.6))


def score_spoken_pacing(text, duration):
    words = re.findall(r"[a-zA-Z][a-zA-Z']+", text)

    if duration <= 0 or not words:
        return 0.0

    words_per_minute = len(words) / duration * 60

    if words_per_minute < 95:
        return max(0.0, words_per_minute / 95 * 0.65)

    if words_per_minute > 245:
        return max(0.2, 1.0 - ((words_per_minute - 245) / 180))

    return max(0.0, 1.0 - abs(words_per_minute - 170) / 120)


def score_duration(duration):
    if duration < MIN_CLIP_DURATION or duration > MAX_CLIP_DURATION:
        return 0.0

    ideal_duration = 42
    return max(0.35, 1.0 - abs(duration - ideal_duration) / 35)


def build_candidate_clips(transcript_payload, audio_payload):
    seconds = audio_payload.get("seconds", [])
    segments = transcript_payload.get("segments", [])

    if not seconds:
        return []

    total_duration = len(seconds)
    candidates = []

    for start in range(0, max(1, total_duration - MIN_CLIP_DURATION + 1), CANDIDATE_STRIDE_SECONDS):
        for duration in CANDIDATE_CLIP_DURATIONS:
            naturalized = naturalize_clip_window(
                segments=segments,
                provisional_start=start,
                duration=duration,
                total_duration=total_duration,
            )

            if naturalized is None:
                continue

            clip_start, clip_end, matching_segments = naturalized
            actual_duration = clip_end - clip_start

            if actual_duration < MIN_CLIP_DURATION or not matching_segments:
                continue

            text = " ".join(segment["text"] for segment in matching_segments)
            words = re.findall(r"[a-zA-Z][a-zA-Z']+", text)

            if len(words) < MIN_WORDS_PER_CANDIDATE:
                continue

            opening_segments = [
                segment
                for segment in matching_segments
                if segment["start"] < clip_start + 12
            ]
            opening_text = " ".join(segment["text"] for segment in opening_segments)

            start_index = max(0, int(clip_start))
            end_index = min(total_duration, max(start_index + 1, int(np.ceil(clip_end))))
            excitement_values = [
                second["excitement"]
                for second in seconds[start_index:end_index]
            ]
            tone_shift_values = [
                second["tone_shift"]
                for second in seconds[start_index:end_index]
            ]
            opening_audio_values = [
                second["excitement"]
                for second in seconds[start_index:min(end_index, start_index + 10)]
            ]

            mean_excitement = float(np.mean(excitement_values))
            peak_excitement = float(np.percentile(excitement_values, 90))
            tone_shift = float(np.percentile(tone_shift_values, 85))
            opening_audio = float(np.mean(opening_audio_values)) if opening_audio_values else mean_excitement

            audio_score = (
                0.42 * mean_excitement
                + 0.30 * peak_excitement
                + 0.18 * tone_shift
                + 0.10 * opening_audio
            )
            audio_score = max(0.0, min(1.0, audio_score))

            text_details = score_text_window(text)
            text_score = text_details["score"]
            opening_text_score = score_opening_text(opening_text or text[:320])
            opening_score = max(0.0, min(1.0, 0.68 * opening_text_score + 0.32 * opening_audio))
            comment_score = score_comment_potential(text)
            pacing_score = score_spoken_pacing(text, actual_duration)
            duration_score = score_duration(actual_duration)
            boundary_score, boundary_flags = score_boundary_quality(
                matching_segments=matching_segments,
                clip_start=clip_start,
                clip_end=clip_end,
            )
            topic_terms = extract_topic_fingerprint(text)
            hook_reason = explain_hook(
                text=text,
                text_details=text_details,
                opening_score=opening_score,
                audio_score=audio_score,
            )
            suggested_title, suggested_caption, hashtags = build_suggested_copy(
                text=text,
                hook_reason=hook_reason,
                topic_terms=topic_terms,
            )

            score = (
                0.30 * text_score
                + 0.24 * audio_score
                + 0.17 * opening_score
                + 0.10 * comment_score
                + 0.07 * pacing_score
                + 0.04 * duration_score
                + 0.08 * boundary_score
            )

            candidates.append(CandidateClip(
                start_time=float(clip_start),
                end_time=float(clip_end),
                score=float(score),
                audio_score=float(audio_score),
                text_score=float(text_score),
                opening_score=float(opening_score),
                comment_score=float(comment_score),
                pacing_score=float(pacing_score),
                duration_score=float(duration_score),
                boundary_score=float(boundary_score),
                diversity_score=1.0,
                rank_signals={
                    **text_details,
                    "boundary_flags": boundary_flags,
                },
                transcript_excerpt=text[:260].strip(),
                hook_reason=hook_reason,
                topic_fingerprint=topic_terms,
                suggested_title=suggested_title,
                suggested_caption=suggested_caption,
                hashtags=hashtags,
            ))

    return candidates


def select_non_overlapping_clips(candidates, max_clips=MAX_CLIPS_PER_VIDEO):
    selected = []

    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if candidate.score < MIN_SELECTED_CLIP_SCORE:
            continue

        overlaps = any(
            candidate.start_time < clip.end_time + MIN_CLIP_SPACING_SECONDS
            and candidate.end_time + MIN_CLIP_SPACING_SECONDS > clip.start_time
            for clip in selected
        )

        if overlaps:
            continue

        max_topic_overlap = max(
            (
                topic_similarity(candidate.topic_fingerprint, clip.topic_fingerprint)
                for clip in selected
            ),
            default=0.0,
        )
        candidate.diversity_score = float(1.0 - max_topic_overlap)

        if max_topic_overlap > MAX_TOPIC_SIMILARITY:
            continue

        selected.append(candidate)

        if len(selected) >= max_clips:
            break

    return sorted(selected, key=lambda item: item.start_time)


def find_viral_clips(audio_filename, cleaned_title, lang_code="en"):
    start_finding = time.time()

    transcript_payload = transcribe_audio_segments(audio_filename, cleaned_title, lang_code)
    audio_payload = analyze_audio_features(audio_filename, cleaned_title)
    candidates = build_candidate_clips(transcript_payload, audio_payload)
    clips = select_non_overlapping_clips(candidates)

    scoring_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}_clip_scores.json",
    )

    with open(scoring_filepath, "w", encoding="utf-8") as f:
        json.dump({
            "scoring_model_version": SCORING_MODEL_VERSION,
            "selected": [candidate_to_dict(clip) for clip in clips],
            "top_candidates": [
                candidate_to_dict(clip)
                for clip in sorted(candidates, key=lambda item: item.score, reverse=True)[:25]
            ],
        }, f, indent=4)

    review_json, review_csv = write_clip_review_exports(cleaned_title, clips, candidates)

    print(f" -> Viral clip scoring took: {time.time() - start_finding:.2f} seconds")
    print(f" -> Selected {len(clips)} non-overlapping clips\n")
    print(f" -> Clip review JSON: {review_json}")
    print(f" -> Clip review CSV: {review_csv}\n")

    for index, clip in enumerate(clips, start=1):
        print(
            f"    Clip {index}: {clip.start_time:.1f}s-{clip.end_time:.1f}s "
            f"| score={clip.score:.3f} text={clip.text_score:.3f} "
            f"audio={clip.audio_score:.3f} opening={clip.opening_score:.3f} "
            f"comment={clip.comment_score:.3f} boundary={clip.boundary_score:.3f} "
            f"diversity={clip.diversity_score:.3f}"
        )
        print(f"        Hook: {clip.hook_reason}")
        print(f"        Title: {clip.suggested_title}")

    if clips:
        print("")

    return clips


# =========================
# Process clips
# =========================

def process_clips(video_filename, audio_filename, cleaned_title, source_record, source_state_key, lang_code="en"):
    audio_filename = os.path.abspath(audio_filename)
    video_filename = os.path.abspath(video_filename)

    assert_file_exists(audio_filename, "Audio file")
    assert_file_exists(video_filename, "Video file")

    print("Finding viral clips from audio + transcript scoring...")
    clips = find_viral_clips(
        audio_filename=audio_filename,
        cleaned_title=cleaned_title,
        lang_code=lang_code,
    )

    if not clips:
        print("No clips found for this video.\n")
        return 0

    for clip in clips:
        clip.source_state_key = source_state_key
        clip.source_video_url = source_record.get("video_url", "")
        clip.source_title = source_record.get("title", "")

    write_clip_review_exports(cleaned_title, clips)

    model = None

    if ENABLE_PERSON_FALLBACK:
        print("Loading YOLO model for opt-in person fallback...")
        from ultralytics import YOLO

        model = YOLO("yolov9c.pt")
    else:
        print("YOLO person fallback disabled; framing will lock only to plausible faces.")

    clip_number = 1
    rendered_count = 0

    for clip in clips:
        duration = clip.end_time - clip.start_time

        if not (MIN_CLIP_DURATION <= duration <= MAX_CLIP_DURATION):
            continue

        print(f"--- Processing Clip {clip_number} (Duration: {duration:.2f}s) ---")
        start_clip_total = time.time()

        temp_subclip = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}_sub.mp4",
        )

        # OpenCV writes more safely to AVI/MJPG first
        temp_tracked_avi = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}_tracked.avi",
        )

        final_filename = os.path.join(
            clips_path,
            f"{cleaned_title}_{clip_number}.mp4",
        )

        if (
            not REGENERATE_EXISTING_CLIPS
            and os.path.exists(final_filename)
            and os.path.getsize(final_filename) > 0
        ):
            print(f" -> Final clip already exists, skipping: {final_filename}\n")
            rendered_count += 1
            clip_number += 1
            continue

        try:
            # STEP 1: Extract raw subclip using FFmpeg
            start_step1 = time.time()

            run_subprocess([
                FFMPEG_EXE,
                "-y",
                "-ss", str(clip.start_time),
                "-i", video_filename,
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                temp_subclip,
            ], "FFmpeg accurate cutting")

            assert_file_exists(temp_subclip, "Temporary subclip")

            print(f" -> Step 1 (FFmpeg Cutting) took: {time.time() - start_step1:.2f} seconds")

            # STEP 2: Smart crop / reframe with OpenCV + YOLO
            start_step2 = time.time()

            crop_stats = smart_crop_to_shorts(
                temp_subclip=temp_subclip,
                temp_tracked_avi=temp_tracked_avi,
                model=model,
            )

            print(f" -> Step 2 (OpenCV Smart Cropping) took: {time.time() - start_step2:.2f} seconds")

            # STEP 3: Merge original audio + reframed video
            start_step3 = time.time()

            run_subprocess([
                FFMPEG_EXE,
                "-y",
                "-i", temp_tracked_avi,
                "-i", temp_subclip,
                "-map", "0:v:0",
                "-map", "1:a?",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-movflags", "+faststart",
                final_filename,
            ], "FFmpeg audio muxing")

            assert_file_exists(final_filename, "Final clip")
            rendered_count += 1
            clip.output_file = os.path.abspath(final_filename)
            clip.render_qc = build_render_qc(
                video_path=final_filename,
                crop_stats=crop_stats,
                expected_duration=duration,
            )

            print(f" -> Step 3 (FFmpeg Audio Muxing) took: {time.time() - start_step3:.2f} seconds")

            if clip.render_qc.get("passed"):
                print(
                    " -> QC passed "
                    f"(framing={clip.render_qc['crop']['framing_score']:.2f}, "
                    f"face={clip.render_qc['crop']['face_detection_rate']:.2f})"
                )
            else:
                print(f" -> QC warnings: {', '.join(clip.render_qc.get('flags', []))}")

        except Exception as clip_err:
            clip.render_qc = {
                "passed": False,
                "flags": [f"processing failed: {clip_err}"],
            }
            print(f" -> Failed while processing clip {clip_number}: {clip_err}")

        finally:
            # Cleanup temporary processing files
            for temp_file in [temp_subclip, temp_tracked_avi]:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass

        print(f" -> Clip {clip_number} finished processing in: {time.time() - start_clip_total:.2f} seconds\n")
        write_clip_review_exports(cleaned_title, clips)

        clip_number += 1

    return rendered_count


# =========================
# Process one video
# =========================

def process_video(video_record):
    try:
        start_video_total = time.time()
        video_url = video_record["video_url"]

        with yt_dlp.YoutubeDL(build_ytdl_opts()) as ydl:
            info = ydl.extract_info(video_url, download=False)

            if info is None:
                print(f"Skipping unreadable/throttled video: {video_url}")
                return False

            video_title = info.get("title", "Unknown_Video")

        cleaned_title = clean_title_for_filename(video_title)

        video_filename, audio_filename = download_media(video_url, cleaned_title)

        assert_file_exists(video_filename, "Downloaded video")
        assert_file_exists(audio_filename, "Extracted audio")

        rendered_count = process_clips(
            video_filename=video_filename,
            audio_filename=audio_filename,
            cleaned_title=cleaned_title,
            source_record=video_record,
            source_state_key=video_record["state_key"],
            lang_code="en",
        )

        print(f"=== Total workflow duration for video: {time.time() - start_video_total:.2f} seconds ===\n")
        return bool(rendered_count)

    except Exception as e:
        print(f"Failed to process video: {video_record.get('video_url')}\n{e}\n")
        return False


# =========================
# Main batch runner
# =========================

def run_clip_generation(theme=None):
    if theme:
        return run_clip_generation_for_theme(theme)

    requested_theme = os.getenv("SHORTFORM_THEME")

    if requested_theme:
        return run_clip_generation_for_theme(requested_theme)

    for theme_name in discover_themes():
        run_clip_generation_for_theme(theme_name)


def run_clip_generation_for_theme(theme_name):
    configure_theme(theme_name)
    run_start = time.time()
    pulled_data = load_json_file(PULLED_FILE, {})
    executed_data = load_json_file(EXECUTED_FILE, {})

    if not isinstance(pulled_data, dict):
        pulled_data = {}

    if not isinstance(executed_data, dict):
        executed_data = {}

    theme_records = [
        (state_key, record)
        for state_key, record in pulled_data.items()
        if record.get("theme") == CURRENT_THEME and record.get("video_url")
    ]
    videos_to_process = [
        (state_key, record)
        for state_key, record in theme_records
        if state_key not in executed_data and not record.get("clips_generated_at")
    ]

    print(f"=== Generating clips for theme: {CURRENT_THEME} ===")
    print(f"Videos found: {len(theme_records)}")
    print(f"Already completed: {sum(1 for key in executed_data if key.startswith(CURRENT_THEME + '|'))}")
    print(f"Clips already generated: {sum(1 for _, record in theme_records if record.get('clips_generated_at'))}")
    print(f"Videos left to process: {len(videos_to_process)}\n")

    for state_key, record in videos_to_process:
        record["state_key"] = state_key
        if process_video(record):
            pulled_data[state_key]["clips_generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_json_file(PULLED_FILE, pulled_data)

    print(f"Updated pulled registry: {PULLED_FILE}")
    print(f"Theme '{CURRENT_THEME}' finished. Total run time: {time.time() - run_start:.2f} seconds\n")


if __name__ == "__main__":
    run_clip_generation()
