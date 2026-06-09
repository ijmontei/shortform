import os
FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

import json
import subprocess
import time
import re
import wave
from dataclasses import dataclass
import yt_dlp
import cv2
import numpy as np
from faster_whisper import WhisperModel
from ultralytics import YOLO


# =========================
# Base directories and paths
# =========================

base_dir = os.path.dirname(os.path.abspath(__file__))

json_filename = os.path.join(base_dir, "src", "id.json")
executed_json_filename = os.path.join(base_dir, "src", "executed_id.json")

videos_path = os.path.join(base_dir, "output", "temp", "videos")
audio_path = os.path.join(base_dir, "output", "temp", "audios")
transcriptions_path = os.path.join(base_dir, "output", "temp", "transcripts")
clips_path = os.path.join(base_dir, "output", "clips")

for path in [videos_path, audio_path, transcriptions_path, clips_path]:
    os.makedirs(path, exist_ok=True)

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
SCORING_MODEL_VERSION = "2026-06-10-v4"


# =========================
# Executables
# =========================

FFMPEG_EXE = os.path.join(FFMPEG_BIN, "ffmpeg.exe")
if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"


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

    ydl_opts_combined = {
        **YTDL_COMMON_OPTS,
        "format": (
            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
            "best[height<=1080][ext=mp4]/"
            "best[ext=mp4]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": video_filename,
    }

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


def detect_face_center_x(frame, face_cascades):
    if not face_cascades:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    frame_width = gray.shape[1]
    best_face = None
    best_area = 0

    for cascade in face_cascades:
        detections = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in detections:
            area = w * h

            if area > best_area:
                best_area = area
                best_face = (x, y, w, h)

        flipped = cv2.flip(gray, 1)
        flipped_detections = cascade.detectMultiScale(
            flipped,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(42, 42),
        )

        for x, y, w, h in flipped_detections:
            area = w * h

            if area > best_area:
                best_area = area
                best_face = (frame_width - x - w, y, w, h)

    if best_face is None:
        return None

    x, _, w, _ = best_face
    return x + w / 2


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
    target_center_x = None
    frame_count = 0

    face_cascades = load_face_cascades()

    detection_interval_seconds = 0.75
    skip_frames = max(1, int(round(fps * detection_interval_seconds)))
    detection_max_height = 640
    min_person_confidence = 0.35

    # Tuned for interviews: keep the face steady and avoid body-driven drift.
    face_dead_zone_px = int(output_width * 0.09)
    fallback_dead_zone_px = int(output_width * 0.20)
    smoothing_factor = 0.026
    max_center_move_per_frame = max(5, int(output_width * 0.007))

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

            detected_center_x = None
            detected_source = None

            if camera_center_x is None:
                camera_center_x = resized_w / 2
                target_center_x = camera_center_x

            if resized_w >= output_width and frame_count % skip_frames == 0:
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

                face_center_x = detect_face_center_x(detection_frame, face_cascades)

                if face_center_x is not None:
                    detected_center_x = face_center_x / detection_scale
                    detected_source = "face"
                else:
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
                        detected_center_x = (
                            (largest_box[0] + largest_box[2]) / 2
                        ) / detection_scale
                        detected_source = "person"

            if detected_center_x is not None:
                drift = abs(detected_center_x - camera_center_x)
                dead_zone_px = face_dead_zone_px if detected_source == "face" else fallback_dead_zone_px

                if drift > dead_zone_px:
                    target_center_x = detected_center_x

            if target_center_x is None:
                target_center_x = resized_w / 2

            if resized_w >= output_width:
                target_center_x = max(
                    output_width / 2,
                    min(target_center_x, resized_w - output_width / 2),
                )
            else:
                target_center_x = resized_w / 2

            if camera_center_x is None:
                camera_center_x = target_center_x
            else:
                center_delta = target_center_x - camera_center_x

                if abs(center_delta) > 1:
                    center_step = center_delta * smoothing_factor
                    center_step = max(
                        -max_center_move_per_frame,
                        min(center_step, max_center_move_per_frame),
                    )
                    camera_center_x += center_step

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
    rank_signals: dict
    transcript_excerpt: str


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
            provisional_end = min(start + duration, total_duration)

            window_segments = [
                segment
                for segment in segments
                if segment["end"] > start and segment["start"] < provisional_end
            ]

            if not window_segments:
                continue

            first_segment = next(
                (
                    segment
                    for segment in window_segments
                    if segment["end"] > start + 0.25 and segment["text"].strip()
                ),
                window_segments[0],
            )
            clip_start = max(0.0, float(first_segment["start"]) - 0.18)
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
                clip_end = min(total_duration, float(completed_segments[-1]["end"]) + 0.22)
            else:
                clip_end = clip_end_limit

            matching_segments = [
                segment
                for segment in matching_segments
                if segment["start"] < clip_end and segment["end"] <= clip_end + 0.05
            ]
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

            score = (
                0.34 * text_score
                + 0.27 * audio_score
                + 0.17 * opening_score
                + 0.10 * comment_score
                + 0.08 * pacing_score
                + 0.04 * duration_score
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
                rank_signals=text_details,
                transcript_excerpt=text[:260].strip(),
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
            "selected": [clip.__dict__ for clip in clips],
            "top_candidates": [
                clip.__dict__
                for clip in sorted(candidates, key=lambda item: item.score, reverse=True)[:25]
            ],
        }, f, indent=4)

    print(f" -> Viral clip scoring took: {time.time() - start_finding:.2f} seconds")
    print(f" -> Selected {len(clips)} non-overlapping clips\n")

    for index, clip in enumerate(clips, start=1):
        print(
            f"    Clip {index}: {clip.start_time:.1f}s-{clip.end_time:.1f}s "
            f"| score={clip.score:.3f} text={clip.text_score:.3f} "
            f"audio={clip.audio_score:.3f} opening={clip.opening_score:.3f} "
            f"comment={clip.comment_score:.3f} pace={clip.pacing_score:.3f}"
        )

    if clips:
        print("")

    return clips


# =========================
# Process clips
# =========================

def process_clips(video_filename, audio_filename, cleaned_title, lang_code="en"):
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
        return

    print("Loading YOLO model...")
    model = YOLO("yolov9c.pt")

    clip_number = 1

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
            clip_number += 1
            continue

        try:
            # STEP 1: Extract raw subclip using FFmpeg
            start_step1 = time.time()

            cut_result = try_subprocess([
                FFMPEG_EXE,
                "-y",
                "-ss", str(clip.start_time),
                "-i", video_filename,
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                temp_subclip,
            ], "FFmpeg stream-copy cutting")

            if cut_result.returncode != 0:
                run_subprocess([
                    FFMPEG_EXE,
                    "-y",
                    "-ss", str(clip.start_time),
                    "-i", video_filename,
                    "-t", str(duration),
                    "-map", "0:v:0",
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-movflags", "+faststart",
                    temp_subclip,
                ], "FFmpeg cutting")

            assert_file_exists(temp_subclip, "Temporary subclip")

            print(f" -> Step 1 (FFmpeg Cutting) took: {time.time() - start_step1:.2f} seconds")

            # STEP 2: Smart crop / reframe with OpenCV + YOLO
            start_step2 = time.time()

            smart_crop_to_shorts(
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

            print(f" -> Step 3 (FFmpeg Audio Muxing) took: {time.time() - start_step3:.2f} seconds")

        except Exception as clip_err:
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

        clip_number += 1


# =========================
# Process one video
# =========================

def process_video(video_url, executed_data):
    try:
        start_video_total = time.time()

        with yt_dlp.YoutubeDL(YTDL_COMMON_OPTS) as ydl:
            info = ydl.extract_info(video_url, download=False)

            if info is None:
                print(f"Skipping unreadable/throttled video: {video_url}")
                return executed_data

            video_title = info.get("title", "Unknown_Video")

        cleaned_title = clean_title_for_filename(video_title)

        video_filename, audio_filename = download_media(video_url, cleaned_title)

        assert_file_exists(video_filename, "Downloaded video")
        assert_file_exists(audio_filename, "Extracted audio")

        process_clips(
            video_filename=video_filename,
            audio_filename=audio_filename,
            cleaned_title=cleaned_title,
            lang_code="en",
        )

        executed_data.append(video_url)

        print(f"=== Total workflow duration for video: {time.time() - start_video_total:.2f} seconds ===\n")

    except Exception as e:
        print(f"Failed to process video: {video_url}\n{e}\n")

    return executed_data


# =========================
# Main batch runner
# =========================

def run_clip_generation():
    run_start = time.time()

    existing_data = []
    executed_data = []

    if os.path.exists(json_filename) and os.path.getsize(json_filename) > 0:
        with open(json_filename, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)

            for video_info in data.values():
                video_url = video_info.get("video_url")
                if video_url:
                    existing_data.append(video_url)

    if os.path.exists(executed_json_filename) and os.path.getsize(executed_json_filename) > 0:
        with open(executed_json_filename, "r", encoding="utf-8") as executed_json_file:
            executed_data = json.load(executed_json_file)

    videos_to_process = [v for v in existing_data if v not in executed_data]

    print(f"Videos found: {len(existing_data)}")
    print(f"Already executed: {len(executed_data)}")
    print(f"Videos left to process: {len(videos_to_process)}\n")

    for video_url in videos_to_process:
        executed_data = process_video(video_url, executed_data)

    with open(executed_json_filename, "w", encoding="utf-8") as executed_json_file:
        json.dump(executed_data, executed_json_file, indent=4)

    print("Updated executed_id.json")
    print(f"Script completely finished. Total batch run time: {time.time() - run_start:.2f} seconds")


if __name__ == "__main__":
    run_clip_generation()
