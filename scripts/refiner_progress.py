"""Live progress of the class refiner runs (read-only).

    python -m scripts.refiner_progress            # dataset build, from ocr_cache.json; every 30 s
    python -m scripts.refiner_progress --once
    python -m scripts.refiner_progress --compare  # compare_yolo_vs_refiner, from its log file

The build saves the cache after every screen, so "screens" = screens finished. The rate is
measured while this tracker runs, so the first ETA appears after the second refresh.
"""
import argparse
import json
import re
import time
from pathlib import Path

import scripts._test_utils  # noqa: F401  forces UTF-8 stdout
from scripts.build_refiner_dataset import load_config


def snapshot(cache_path):
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):  # not started yet, or caught mid-write
        return None
    return len({k.split(":")[0] for k in cache}), len(cache), cache_path.stat().st_mtime


def watch_compare(log_path, every, once):
    """Progress of compare_yolo_vs_refiner from the "[n/N] ..." lines in its log (run with python -u)."""
    while True:
        text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        steps = re.findall(r"^\[(\d+)/(\d+)\] (\w+)", text, re.M)
        now = time.time()
        if "saved to" in text:
            print(f"\nDONE: {re.search(r'saved to (.+)', text).group(1).strip()}")
            return
        if "Traceback" in text:
            print("\nFAILED - see " + str(log_path))
            return
        if steps:
            done, total, last = int(steps[-1][0]), int(steps[-1][1]), steps[-1][2]
            start = log_path.stat().st_ctime  # Windows: creation time = when the run started
            rate = done / ((now - start) / 60)
            eta = time.localtime(now + (total - done) / rate * 60)
            print(f"{time.strftime('%H:%M:%S')}  [{'#' * round(30 * done / total):<30}] {done}/{total} screens "
                  f"({done / total:.0%}), last {last}, {rate:.1f} screens/min, ETA {time.strftime('%H:%M', eta)}",
                  flush=True)
        else:
            print(f"{time.strftime('%H:%M:%S')}  starting (training refiner / loading models)...", flush=True)
        if once:
            return
        time.sleep(every)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=30, help="seconds between refreshes")
    ap.add_argument("--compare", nargs="?", const="output/compare_yolo_vs_refiner.log", metavar="LOG",
                    help="track compare_yolo_vs_refiner from its log instead of the dataset build")
    args = ap.parse_args()
    if args.compare:
        return watch_compare(Path(args.compare), args.every, args.once)

    cfg = load_config()
    total = len(list((Path(cfg["paths"]["export_dir"]) / cfg["paths"]["labels_subdir"]).glob("*.txt")))
    out = Path(cfg["paths"]["output_dir"])
    cache_path, features = out / "ocr_cache.json", out / "features.csv"
    first = None
    while True:
        snap = snapshot(cache_path)
        if features.exists() and features.stat().st_mtime > (snap[2] if snap else 0) - 5:
            print(f"\nDONE: {features} written ({time.strftime('%H:%M', time.localtime(features.stat().st_mtime))})")
            return
        if snap:
            screens, crops, mtime = snap
            first = first or (time.time(), screens)
            bar = "#" * round(30 * screens / total)
            line = (f"{time.strftime('%H:%M:%S')}  [{bar:<30}] {screens}/{total} screens "
                    f"({screens / total:.0%}), {crops} crops, last save {time.time() - mtime:.0f}s ago")
            elapsed, done = time.time() - first[0], screens - first[1]
            if done > 0:
                rate = done / (elapsed / 60)
                eta = time.localtime(time.time() + (total - screens) / rate * 60)
                line += f", {rate:.1f} screens/min, ETA {time.strftime('%H:%M', eta)}"
            print(line, flush=True)
        else:
            print("no ocr_cache.json yet - has the build started?", flush=True)
        if args.once:
            return
        time.sleep(args.every)


if __name__ == "__main__":
    main()
