import os

# Forces Python/OpenCV to see the FFmpeg DLLs on Windows, if present
FFMPEG_BIN = r"C:\ffmpeg\bin"
if os.path.isdir(FFMPEG_BIN) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(FFMPEG_BIN)

import json
import subprocess
import time
import yt_dlp
import cv2
import numpy as np
from clipsai import ClipFinder, Transcriber
from ultralytics import YOLO


# =========================
# Base directories and paths
# =========================

base_dir = r"C:\Users\Admin\Desktop\Project-OBR"

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

def smart_crop_to_shorts(temp_subclip, temp_tracked_avi, model):
    """
    Converts a horizontal clip into 1080x1920 vertical format with a restrained
    virtual camera. Person detection only recenters the crop when the subject
    drifts outside a dead zone, which avoids constant distracting reframes.

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

    detection_interval_seconds = 1.0
    skip_frames = max(1, int(round(fps * detection_interval_seconds)))
    detection_max_height = 720
    min_person_confidence = 0.35

    # Tuned for podcasts/interviews: hold framing, then glide if needed.
    recenter_dead_zone_px = int(output_width * 0.18)
    smoothing_factor = 0.035
    max_center_move_per_frame = max(6, int(output_width * 0.01))

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
                        # CRITICAL FIX:
                        # box.cls is tensor-like, not a normal Python int.
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

            if detected_center_x is not None:
                drift = abs(detected_center_x - camera_center_x)

                if drift > recenter_dead_zone_px:
                    target_center_x = detected_center_x

            if target_center_x is None:
                target_center_x = resized_w / 2

            target_center_x = max(
                output_width / 2,
                min(target_center_x, resized_w - output_width / 2),
            )

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
# Process clips
# =========================

def process_clips(video_filename, audio_filename, cleaned_title, lang_code="en"):
    audio_filename = os.path.abspath(audio_filename)
    video_filename = os.path.abspath(video_filename)

    assert_file_exists(audio_filename, "Audio file")
    assert_file_exists(video_filename, "Video file")

    import torch

    if torch.cuda.is_available():
        print("Initializing Transcriber (Model: tiny | GPU Accelerated)...")
        device_type = "cuda"
        compute_prec = "float16"
    else:
        print("Initializing Transcriber (Model: tiny | CPU)...")
        device_type = "cpu"
        compute_prec = "float32"

    transcriber = Transcriber(
        model_size="tiny",
        device=device_type,
        precision=compute_prec,
    )

    print(f"Transcribing audio (Language forced to: {lang_code})...")
    start_transcribe = time.time()

    transcription = transcriber.transcribe(
        audio_file_path=audio_filename,
        iso6391_lang_code=lang_code,
    )

    print(f" -> Transcription took: {time.time() - start_transcribe:.2f} seconds\n")

    transcription_filepath = os.path.join(
        transcriptions_path,
        f"{cleaned_title}.json",
    )

    with open(transcription_filepath, "w", encoding="utf-8") as f:
        json.dump(transcription.__dict__, f, indent=4, default=str)

    print("Finding clips from transcription...")
    start_clipfind = time.time()

    clipfinder = ClipFinder(
        min_clip_duration=30,
        max_clip_duration=60,
    )

    clips = clipfinder.find_clips(transcription=transcription)

    print(f" -> Finding clips took: {time.time() - start_clipfind:.2f} seconds\n")

    if not clips:
        print("No clips found for this video.\n")
        return

    print("Loading YOLO model...")
    model = YOLO("yolov9c.pt")

    clip_number = 1

    for clip in clips:
        duration = clip.end_time - clip.start_time

        if not (30 <= duration <= 60):
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
