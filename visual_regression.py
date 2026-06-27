import argparse
import os
import subprocess
import time

from PIL import Image, ImageDraw, ImageStat

from daily_editorial import (
    FFMPEG_EXE,
    clean_filename,
    compact_text,
    countdown_intro_timing,
    render_countdown_intro_video,
    visual_style,
)
from theme_config import BASE_DIR, PHASE_ONE_ACTIVE_THEMES, clean_theme_name, discover_themes, load_theme_config, write_json_file
from theme_profile import load_theme_profile


LOG_DIR = os.path.join(BASE_DIR, "logs", "visual_regression")
LATEST_REPORT = os.path.join(BASE_DIR, "logs", "visual_regression_latest.json")
PLACEHOLDER_LANE_REVIEW_THRESHOLD = float(os.getenv("SHORTFORM_VISUAL_PLACEHOLDER_LANE_THRESHOLD", "0.72"))
FRAME_TIMES = [
    ("spin", 0.30),
    ("handoff_a", 0.03),
    ("handoff_b", 0.22),
    ("handoff_c", 0.47),
    ("lock", -0.04),
    ("final", 0.42),
]


def hex_rgb(value):
    text = str(value or "").replace("0x", "").replace("#", "").strip()

    if len(text) != 6:
        return (255, 255, 255)

    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))


def channel_label_from_url(url):
    value = str(url or "").strip().rstrip("/")
    label = value.rsplit("/", 1)[-1].replace("@", "").replace("videos", "").strip("/")
    label = label.replace("-", " ").replace("_", " ").strip()
    return label or "Podcast Channel"


def make_preview_thumbnail(path, label, fill, accent):
    image = Image.new("RGB", (320, 180), fill)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 319, 179), outline=(8, 10, 14), width=8)
    draw.rectangle((12, 12, 308, 168), outline=accent, width=4)
    draw.text((24, 62), compact_text(label.upper(), 22), fill=(0, 0, 0))
    image.save(path)
    return path


def build_preview_data(theme, theme_dir):
    config = load_theme_config(theme)
    profile = load_theme_profile(theme)
    style = visual_style(4, theme)
    accent = hex_rgb(style.get("accent"))
    accent2 = hex_rgb(style.get("accent2"))
    palette = [
        hex_rgb(style.get("cream")),
        hex_rgb(style.get("mint")),
        hex_rgb(style.get("blue")),
        accent,
        accent2,
        (232, 232, 238),
        (188, 201, 214),
        (245, 214, 172),
    ]
    channels = list(config.get("priority_channels") or []) + list(config.get("secondary_channels") or [])

    if not channels:
        channels = [theme.replace("_", " ")] * 10

    thumbnails = []
    for index in range(10):
        channel_label = channel_label_from_url(channels[index % len(channels)])
        thumbnails.append(
            make_preview_thumbnail(
                os.path.join(theme_dir, f"thumb_{index + 1:02d}.png"),
                channel_label[:18],
                palette[index % len(palette)],
                accent,
            )
        )

    total = 5
    top_entries = []
    for slot in range(1, total + 1):
        channel = channel_label_from_url(channels[(slot - 1) % len(channels)])
        key = f"{theme}|visual-regression|top-{slot}"
        top_entries.append({
            "slot": slot,
            "rank_index": total - slot + 1,
            "topic": f"{profile.get('brand', {}).get('voice', theme).replace('_', ' ')} moment {slot}",
            "title": f"{channel} source episode {slot}",
            "summary": f"A ranked {theme.replace('_', ' ')} moment for transition QA",
            "source_title": f"{channel} source episode {slot}",
            "source_state_key": key,
            "channel_label": channel,
            "thumbnail_file": thumbnails[slot - 1],
            "clip_file": "",
        })

    source_banners = []
    top_slots_by_index = {1: 5, 3: 4, 5: 3, 7: 2, 9: 1}
    for index in range(10):
        top_slot = top_slots_by_index.get(index)
        channel = channel_label_from_url(channels[index % len(channels)])

        if top_slot:
            key = f"{theme}|visual-regression|top-{top_slot}"
            title = f"{channel} finalist episode {top_slot}"
        else:
            key = f"{theme}|visual-regression|scan-{index + 1}"
            title = f"{channel} source scan {index + 1}"

        source_banners.append({
            "title": compact_text(title, 74),
            "summary": f"{channel} signal",
            "channel_label": channel,
            "letter": channel[:1].upper() or "S",
            "source_state_key": key,
            "is_top": bool(top_slot),
            "slot": top_slot,
            "clip_file": "",
            "thumbnail_file": thumbnails[index],
        })

    return top_entries, source_banners


def extract_frame(video_file, time_seconds, output_file):
    subprocess.run(
        [
            FFMPEG_EXE,
            "-y",
            "-ss",
            f"{max(0.0, float(time_seconds)):.3f}",
            "-i",
            video_file,
            "-frames:v",
            "1",
            output_file,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output_file


def frame_placeholder_metrics(path):
    image = Image.open(path).convert("RGB")
    board = image.crop((36, 420, 1044, 1610)).resize((168, 198))
    gray = board.convert("L")
    pixels = list(gray.getdata())
    dark_ratio = sum(1 for value in pixels if value < 18) / max(1, len(pixels))
    very_dark_ratio = sum(1 for value in pixels if value < 8) / max(1, len(pixels))
    row_scores = []

    for y in range(gray.height):
        row = [gray.getpixel((x, y)) for x in range(gray.width)]
        row_scores.append(sum(1 for value in row if value < 16) / max(1, len(row)))

    full_dark_rows = sum(1 for score in row_scores if score > 0.88)
    stat = ImageStat.Stat(gray)
    contrast = float(stat.stddev[0] or 0.0)
    return {
        "dark_ratio": round(dark_ratio, 4),
        "very_dark_ratio": round(very_dark_ratio, 4),
        "full_dark_row_ratio": round(full_dark_rows / max(1, len(row_scores)), 4),
        "contrast": round(contrast, 4),
    }


def create_contact_sheet(frame_paths, output_file):
    cell_w, cell_h = 216, 384
    label_h = 34
    sheet = Image.new("RGB", (cell_w * len(frame_paths), cell_h + label_h), (8, 9, 12))
    draw = ImageDraw.Draw(sheet)

    for index, (label, path) in enumerate(frame_paths):
        image = Image.open(path).convert("RGB").resize((cell_w, cell_h))
        x = index * cell_w
        sheet.paste(image, (x, label_h))
        draw.rectangle((x, 0, x + cell_w - 1, label_h - 1), fill=(18, 20, 27))
        draw.text((x + 10, 9), label, fill=(255, 244, 184))

    sheet.save(output_file, quality=92)
    return output_file


def render_theme_visual_regression(theme, root_dir):
    theme = clean_theme_name(theme)
    theme_dir = os.path.join(root_dir, theme)
    os.makedirs(theme_dir, exist_ok=True)
    intro_duration = 5.0
    countdown_slot = 4
    profile = load_theme_profile(theme)
    theme_label = (profile.get("brand", {}) or {}).get("channel_name") or theme.replace("_", " ").title()
    top_entries, source_banners = build_preview_data(theme, theme_dir)
    video_file = render_countdown_intro_video(
        theme=theme,
        scratch_dir=theme_dir,
        date_key=time.strftime("%Y-%m-%d"),
        rank=countdown_slot,
        intro_duration=intro_duration,
        ranking_title=f"TOP 5 {theme.replace('_', ' ').upper()} MOMENTS THIS WEEK",
        ranking_subtitle=f"FROM THIS WEEK {theme_label.upper()} INTERVIEWS",
        context={"watched_hours": 8.4, "theme_label": theme_label},
        top_entries=top_entries,
        source_banners=source_banners,
        countdown_slot=countdown_slot,
        style=visual_style(countdown_slot, theme),
    )
    spin_end, _, final_lock = countdown_intro_timing(intro_duration)
    frame_specs = [
        ("spin", 0.35),
        ("handoff_a", spin_end + 0.03),
        ("handoff_b", spin_end + 0.22),
        ("handoff_c", spin_end + 0.47),
        ("lock", final_lock - 0.04),
        ("final", final_lock + 0.42),
    ]
    frame_paths = []
    metrics = {}

    for label, seconds in frame_specs:
        frame_path = os.path.join(theme_dir, f"{label}.png")
        extract_frame(video_file, seconds, frame_path)
        frame_paths.append((label, frame_path))
        metrics[label] = frame_placeholder_metrics(frame_path)

    contact_sheet = create_contact_sheet(
        frame_paths,
        os.path.join(theme_dir, f"{theme}_transition_contact_sheet.jpg"),
    )
    handoff_scores = [
        metrics[label]["full_dark_row_ratio"]
        for label in ["handoff_a", "handoff_b", "handoff_c"]
        if label in metrics
    ]
    max_placeholder_lane_ratio = max(handoff_scores or [0.0])
    needs_review = max_placeholder_lane_ratio > PLACEHOLDER_LANE_REVIEW_THRESHOLD
    return {
        "theme": theme,
        "status": "needs_review" if needs_review else "ok",
        "video_file": video_file,
        "contact_sheet": contact_sheet,
        "frames": {label: path for label, path in frame_paths},
        "metrics": metrics,
        "max_placeholder_lane_ratio": round(max_placeholder_lane_ratio, 4),
        "notes": (
            "Handoff frames contain large full-width dark lanes; inspect contact sheet."
            if needs_review
            else "Handoff frames stayed below the placeholder-lane review threshold."
        ),
    }


def build_visual_regression_pack(theme=None):
    themes = [clean_theme_name(theme)] if theme else discover_themes()
    run_id = time.strftime("%Y%m%d_%H%M%S")
    root_dir = os.path.join(LOG_DIR, run_id)
    os.makedirs(root_dir, exist_ok=True)
    results = []
    errors = []

    for theme_name in themes:
        if theme_name not in PHASE_ONE_ACTIVE_THEMES:
            errors.append(f"{theme_name} is not an active phase-one theme")
            continue

        try:
            results.append(render_theme_visual_regression(theme_name, root_dir))
        except Exception as error:
            errors.append(f"{theme_name}: {error}")
            results.append({
                "theme": theme_name,
                "status": "error",
                "error": str(error),
            })

    status = "error" if errors else ("needs_review" if any(item.get("status") == "needs_review" for item in results) else "ok")
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "root_dir": root_dir,
        "themes": themes,
        "results": results,
        "errors": errors,
    }
    write_json_file(LATEST_REPORT, report)
    write_json_file(os.path.join(root_dir, "visual_regression_report.json"), report)
    return report


def print_visual_regression_report(report):
    print(f"Visual regression pack: {report.get('status')}")
    print(f"Root: {report.get('root_dir')}")

    for item in report.get("results") or []:
        print(
            f" - {item.get('theme')}: {item.get('status')} "
            f"placeholder_lane={item.get('max_placeholder_lane_ratio')}"
        )
        if item.get("contact_sheet"):
            print(f"   contact: {item.get('contact_sheet')}")
        if item.get("video_file"):
            print(f"   video: {item.get('video_file')}")
        if item.get("error"):
            print(f"   error: {item.get('error')}")

    if report.get("errors"):
        print("Errors:")
        for error in report["errors"]:
            print(f" - {error}")

    print(f"Report: {LATEST_REPORT}")


def parse_args():
    parser = argparse.ArgumentParser(description="Render visual regression previews for countdown transitions.")
    parser.add_argument("--theme", help="Optional single active phase-one theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    visual_report = build_visual_regression_pack(theme=args.theme)
    print_visual_regression_report(visual_report)
    raise SystemExit(1 if visual_report["status"] == "error" else 0)
