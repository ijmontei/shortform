import argparse
import html
import os
import time

from editorial_gates import evaluate_editorial_gates
from theme_config import BASE_DIR, discover_themes, ensure_theme, load_json_file
REPORT_DIR = os.path.join(BASE_DIR, "logs", "review_dashboard")


def esc(value):
    return html.escape(str(value or ""), quote=True)


def compact(value, max_length=140):
    value = str(value or "").strip()

    if len(value) <= max_length:
        return value

    return value[: max(0, max_length - 1)].rstrip(" ,.;:-") + "..."


def fmt_time(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""

    minutes, seconds = divmod(int(value), 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"

    return f"{minutes}:{seconds:02d}"


def review_commands(theme, index):
    return {
        "approve": f".\\venv_313\\Scripts\\python.exe .\\review_queue.py approve --theme {theme} --index {index} --notes \"approved\"",
        "reject": f".\\venv_313\\Scripts\\python.exe .\\review_queue.py reject --theme {theme} --index {index} --reason \"weak hook\"",
        "regen_title": f".\\venv_313\\Scripts\\python.exe .\\review_queue.py request --theme {theme} --index {index} --action regenerate_title --notes \"needs stronger topic-specific title\"",
        "alternate_framing": f".\\venv_313\\Scripts\\python.exe .\\review_queue.py request --theme {theme} --index {index} --action try_alternate_framing",
    }


def clip_rows(theme):
    paths = ensure_theme(theme)
    metadata = load_json_file(paths["final_metadata_file"], {"content": []})
    rows = []

    for index, package in enumerate(metadata.get("content", []), start=1):
        review = package.get("review") or {}
        render_qc = package.get("render_qc") or {}
        rank_signals = package.get("rank_signals") or {}
        editorial_gates = package.get("editorial_gates") or evaluate_editorial_gates(theme, package)
        posting_status = (package.get("posting_status") or {}).get("youtube_shorts", "")

        if review.get("rejected") or posting_status == "rejected":
            approval_status = "rejected"
        elif review.get("approved"):
            approval_status = "approved"
        else:
            approval_status = "needs review"

        rows.append({
            "index": index,
            "theme": theme,
            "video_file": package.get("video_file", ""),
            "source_channel": package.get("source_channel", ""),
            "source_title": package.get("source_title", ""),
            "source_video_url": package.get("source_video_url", ""),
            "clip_start": fmt_time(package.get("clip_start_time")),
            "clip_end": fmt_time(package.get("clip_end_time")),
            "archetype": rank_signals.get("theme_archetype", ""),
            "intro_mode": rank_signals.get("recommended_intro_mode", ""),
            "caption_style": package.get("caption_style", ""),
            "content_format": package.get("content_format", ""),
            "title": package.get("title", ""),
            "description": package.get("description", ""),
            "hashtags": " ".join(package.get("hashtags") or []),
            "readiness_score": package.get("readiness_score") or package.get("score") or "",
            "theme_signal_score": rank_signals.get("theme_signal_score", ""),
            "visual_quality_score": render_qc.get("visual_quality_score", ""),
            "first_second_qc": rank_signals.get("first_second_qc", {}),
            "transformation_score": rank_signals.get("transformation_score", ""),
            "reused_content_risk": rank_signals.get("reused_content_risk", ""),
            "editorial_gate_status": "passed" if editorial_gates.get("passed", True) else "failed",
            "editorial_gate_flags": ", ".join(editorial_gates.get("flags") or []),
            "risk_flags": ", ".join((render_qc.get("flags") or []) + (rank_signals.get("theme_signal_concerns") or [])),
            "analytics_prediction": compact(package.get("hook_reason", "") or rank_signals.get("readiness_tier", "")),
            "approval_status": approval_status,
            "review_notes": review.get("notes", ""),
            "commands": review_commands(theme, index),
        })

    return rows


def build_dashboard(theme=None):
    themes = [theme] if theme else discover_themes()
    all_rows = []

    for theme_name in themes:
        all_rows.extend(clip_rows(theme_name))

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(REPORT_DIR, exist_ok=True)
    output_path = os.path.join(REPORT_DIR, "review_dashboard_latest.html")
    cards = []

    for row in all_rows:
        video = row["video_file"]
        video_tag = (
            f'<video src="file:///{esc(video).replace(os.sep, "/")}" controls preload="metadata"></video>'
            if video and os.path.exists(video)
            else "<div class='missing'>Missing video preview</div>"
        )
        cards.append(f"""
        <article class=\"card\">
            {video_tag}
            <section>
                <div class=\"theme\">{esc(row['theme'])}</div>
                <h2>{esc(row['title'])}</h2>
                <p>{esc(row['description'])}</p>
                <p class=\"meta\">{esc(row['hashtags'])}</p>
                <dl>
                    <dt>Source</dt><dd><a href=\"{esc(row['source_video_url'])}\">{esc(row['source_title'])}</a></dd>
                    <dt>Source Time</dt><dd>{esc(row['clip_start'])} - {esc(row['clip_end'])}</dd>
                    <dt>Format</dt><dd>{esc(row['content_format'])}</dd>
                    <dt>Archetype</dt><dd>{esc(row['archetype'])}</dd>
                    <dt>Intro</dt><dd>{esc(row['intro_mode'])}</dd>
                    <dt>Captions</dt><dd>{esc(row['caption_style'])}</dd>
                    <dt>Readiness</dt><dd>{esc(row['readiness_score'])}</dd>
                    <dt>Theme Signal</dt><dd>{esc(row['theme_signal_score'])}</dd>
                    <dt>Visual Quality</dt><dd>{esc(row['visual_quality_score'])}</dd>
                    <dt>First Second</dt><dd>{esc(row['first_second_qc'])}</dd>
                    <dt>Transformation</dt><dd>{esc(row['transformation_score'])}</dd>
                    <dt>Reused Risk</dt><dd>{esc(row['reused_content_risk'])}</dd>
                    <dt>Editorial Gate</dt><dd>{esc(row['editorial_gate_status'])}</dd>
                    <dt>Gate Flags</dt><dd>{esc(row['editorial_gate_flags'])}</dd>
                    <dt>Flags</dt><dd>{esc(row['risk_flags'])}</dd>
                    <dt>Prediction</dt><dd>{esc(row['analytics_prediction'])}</dd>
                    <dt>Status</dt><dd>{esc(row['approval_status'])}</dd>
                </dl>
                <div class=\"commands\">
                    <code>{esc(row['commands']['approve'])}</code>
                    <code>{esc(row['commands']['reject'])}</code>
                    <code>{esc(row['commands']['regen_title'])}</code>
                    <code>{esc(row['commands']['alternate_framing'])}</code>
                </div>
            </section>
        </article>
        """)

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Shortform Review Dashboard</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; background: #111820; color: #f7f2df; }}
header {{ position: sticky; top: 0; z-index: 2; padding: 18px 28px; background: #2e3440; border-bottom: 3px solid #ffe08a; }}
h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
.sub {{ color: #b7d7c2; margin-top: 4px; }}
main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 18px; padding: 20px; }}
.card {{ display: grid; grid-template-columns: 180px 1fr; gap: 16px; padding: 14px; background: #1b2430; border: 1px solid rgba(255,224,138,.35); border-radius: 6px; }}
video, .missing {{ width: 180px; aspect-ratio: 9 / 16; background: #05070a; border-radius: 4px; object-fit: cover; }}
.missing {{ display: grid; place-items: center; color: #ffb4b8; font-size: 13px; text-align: center; }}
.theme {{ color: #ffe08a; font-size: 12px; font-weight: 700; text-transform: uppercase; }}
h2 {{ margin: 6px 0 8px; font-size: 19px; line-height: 1.18; }}
p {{ margin: 0 0 8px; color: #d8dee9; line-height: 1.35; }}
.meta {{ color: #b7d7c2; }}
dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 5px 10px; margin: 10px 0 0; font-size: 13px; }}
dt {{ color: #ffe08a; }}
dd {{ margin: 0; color: #f7f2df; }}
a {{ color: #6f8faf; }}
.commands {{ margin-top: 12px; display: grid; gap: 6px; }}
code {{ display: block; white-space: normal; word-break: break-word; padding: 7px 8px; background: #0c1118; border: 1px solid rgba(183,215,194,.22); border-radius: 4px; color: #b7d7c2; font-size: 11px; line-height: 1.35; }}
</style>
</head>
<body>
<header>
<h1>Shortform Review Dashboard</h1>
<div class=\"sub\">Generated {esc(generated_at)}. Manual approval remains required before public publishing.</div>
</header>
<main>
{''.join(cards) if cards else '<p>No upload-ready clips found.</p>'}
</main>
</body>
</html>"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    print(f"Review dashboard: {output_path}")
    return output_path


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a local HTML review dashboard for upload-ready clips.")
    parser.add_argument("--theme", help="Optional theme to include. Omit for every theme.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    build_dashboard(theme=args.theme)
