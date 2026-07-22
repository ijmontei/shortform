import argparse
import os
import subprocess
import sys
import time

from run import theme_finished_backlog_count
from theme_config import discover_themes


def campaign_progress(themes, target):
    return {
        theme: {
            "finished": theme_finished_backlog_count(theme),
            "remaining": max(0, target - theme_finished_backlog_count(theme)),
        }
        for theme in themes
    }


def total_finished(progress):
    return sum(item["finished"] for item in progress.values())


def print_progress(progress, target):
    for theme, item in progress.items():
        print(f" -> {theme}: {item['finished']}/{target}; {item['remaining']} remaining")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run resumable generation-only cycles until each theme reaches its local backlog target."
    )
    parser.add_argument("--target", type=int, default=500, help="Finished local videos required per theme.")
    parser.add_argument(
        "--source-videos-per-channel",
        type=int,
        default=50,
        help="Historical source depth for the first cycle.",
    )
    parser.add_argument(
        "--max-source-videos-per-channel",
        type=int,
        default=200,
        help="Maximum historical depth after stalled cycles.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Optional cycle limit; zero continues until complete or repeatedly stalled.",
    )
    parser.add_argument(
        "--max-stalled-cycles",
        type=int,
        default=3,
        help="Stop after this many cycles produce no additional finished videos.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target = max(1, int(args.target))
    source_depth = max(1, int(args.source_videos_per_channel))
    max_source_depth = max(source_depth, int(args.max_source_videos_per_channel))
    themes = discover_themes()
    python_executable = os.path.abspath(sys.executable)
    run_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "run.py"))
    cycle = 0
    stalled_cycles = 0

    if not themes:
        raise SystemExit("No configured themes found.")

    print(f"Backlog campaign target: {target} finished videos for each of {len(themes)} themes.")

    while True:
        before = campaign_progress(themes, target)
        print_progress(before, target)

        if all(item["remaining"] <= 0 for item in before.values()):
            print("Backlog campaign complete.")
            return

        if args.max_cycles > 0 and cycle >= args.max_cycles:
            print(f"Backlog campaign stopped at configured cycle limit: {args.max_cycles}.")
            return

        cycle += 1
        print(f"Starting generation-only backlog cycle {cycle} at source depth {source_depth}.")
        command = [
            python_executable,
            run_script,
            "--travel-safe",
            "--skip-youtube",
            "--backlog-target-per-theme",
            str(target),
            "--source-videos-per-channel",
            str(source_depth),
        ]
        completed = subprocess.run(command, cwd=os.path.dirname(run_script), check=False)
        after = campaign_progress(themes, target)
        gained = total_finished(after) - total_finished(before)
        print(f"Backlog cycle {cycle} exited with code {completed.returncode}; finished-video gain: {gained}.")

        if gained > 0:
            stalled_cycles = 0
            continue

        stalled_cycles += 1

        if source_depth < max_source_depth:
            source_depth = min(max_source_depth, source_depth + 25)
            print(f"No finished-video gain; expanding historical source depth to {source_depth}.")

        if stalled_cycles >= max(1, int(args.max_stalled_cycles)):
            print(
                "Backlog campaign stopped after repeated no-progress cycles. "
                "Existing files and source state remain resumable."
            )
            raise SystemExit(2)

        time.sleep(10)


if __name__ == "__main__":
    main()
