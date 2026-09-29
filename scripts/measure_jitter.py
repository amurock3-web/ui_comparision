"""Detector box wobble per class (Phase 17.1): detector only - no OCR, no comparison.

    python -m scripts.measure_jitter                           # defaults below
    python -m scripts.measure_jitter input/production/ss012.png

Default images: every input/production/* screen plus both sides of each
input/benchmark/real/<pair>/ (a real pair's client is a design mockup, reported
as its own source: mockups may wobble differently). Each screenshot and its
jitter variants (src/detector/jitter.py) go through the detector in ONE
process (detect_many), so the model loads once per screen.

Output in output/jitter/testN_measure/:
  per_element.csv   one row per original detection (status bar excluded)
  summary.json      per class and source: n, stability, class flips, p50/p95
and a printed table. A class is flagged when p95 x sqrt(2) crosses the C1 or
C2 pass band: a comparison has two boxes that wobble independently.
"""
import csv
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from scripts._test_utils import next_test_number
from src.comparison.differ import DifferenceEngine
from src.detector.engine import load_detector
from src.detector.jitter import METRICS, VARIANTS, make_variants, measure_wobble
from src.fusion.fuse import FusionEngine

OUTPUT_ROOT = Path("output/jitter")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def default_images() -> list:
    images = sorted(p for p in Path("input/production").iterdir() if p.suffix.lower() in IMAGE_EXTS)
    for pair in sorted(p for p in Path("input/benchmark/real").glob("*") if p.is_dir()):
        images += sorted(p for p in pair.iterdir() if p.stem in ("production", "client")
                         and p.suffix.lower() in IMAGE_EXTS)
    return images


def source_of(path: Path) -> str:
    # ponytail: name-based guess; add a source column to a manifest when a third app arrives.
    if path.parent.parent.name == "real" and path.stem == "client":
        return "mockup"
    return "jiohotstar" if "jiohotstar" in path.name.lower() else "sunnxt"


def measure(detector, path: Path, status_bar_norm: float) -> list:
    img = Image.open(path).convert("RGB")
    W, H = img.size
    variants = make_variants(img)
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, v, _ in variants:
            paths.append(Path(tmp) / f"{name}.png")
            v.save(paths[-1])
        found = detector.detect_many([path, *paths])
    as_dets = lambda els: [(e.class_, e.bbox) for e in els]
    # Same rule as fusion: a box wholly inside the status-bar band is never compared.
    original = [d for d in as_dets(found[0]) if d[1][1] + d[1][3] > status_bar_norm * H]
    rows = measure_wobble(original, [(as_dets(f), off) for f, (_, _, off) in zip(found[1:], variants)], W, H)
    for r in rows:
        r.update(image=str(path), source=source_of(path))
    return rows


def summarise(rows) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["class"], r["source"])].append(r)
        groups[(r["class"], "all")].append(r)
    out = {}
    for (cls, src), rs in sorted(groups.items()):
        seen = [r for r in rs if r["matched_in"]]
        entry = {"n": len(rs),
                 "stability": sum(r["matched_in"] for r in rs) / sum(r["variants"] for r in rs),
                 "class_flip_rate": sum(r["class_flips"] for r in rs) / sum(r["variants"] for r in rs)}
        for m in METRICS:
            vals = [r[m] for r in seen]
            entry[m] = ({"p50": float(np.percentile(vals, 50)), "p95": float(np.percentile(vals, 95))}
                        if vals else None)
        out.setdefault(cls, {})[src] = entry
    return out


def main():
    images = [Path(a) for a in sys.argv[1:]] or default_images()
    detector = load_detector()
    status_bar_norm = FusionEngine().status_bar_height_norm
    differ = DifferenceEngine()
    c1_pass, c2_pass = differ.position_bands["pass"], differ.size_bands["pass"]

    rows = []
    for path in images:
        print(f"{path}: detector on original + {len(VARIANTS)} variants")
        rows += measure(detector, path, status_bar_norm)

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_dir = OUTPUT_ROOT / f"test{next_test_number(OUTPUT_ROOT)}_measure"
    out_dir.mkdir()
    fields = ["image", "source", "class", "bbox", "variants", "matched_in", "class_flips", *METRICS]
    with open(out_dir / "per_element.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    summary = summarise(rows)
    flags = {}
    for cls, by_src in summary.items():
        a = by_src["all"]
        crossed = [check for check, m, band in (("C2", "size", c2_pass), ("C1", "diag", c1_pass))
                   if a[m] and a[m]["p95"] * 2 ** 0.5 > band]
        if crossed:
            flags[cls] = crossed
    (out_dir / "summary.json").write_text(json.dumps(
        {"images": [str(p) for p in images], "variants": [v[0] for v in VARIANTS],
         "bands": {"C1_pass_diag": c1_pass, "C2_pass_size": c2_pass},
         "by_class": summary, "flags": flags}, indent=2), encoding="utf-8")

    pct = lambda e, m, q: f"{e[m][q]:.3f}" if e[m] else "  -  "
    print(f"\n{'class':18s} {'source':10s} {'n':>4s} {'stable':>7s} {'flips':>6s} "
          f"{'size50':>7s} {'size95':>7s} {'diag50':>7s} {'diag95':>7s}")
    for cls, by_src in summary.items():
        for src, e in by_src.items():
            print(f"{cls:18s} {src:10s} {e['n']:4d} {e['stability']:7.0%} {e['class_flip_rate']:6.0%} "
                  f"{pct(e, 'size', 'p50'):>7s} {pct(e, 'size', 'p95'):>7s} "
                  f"{pct(e, 'diag', 'p50'):>7s} {pct(e, 'diag', 'p95'):>7s}")
    print(f"\nPass bands: C2 size {c2_pass}, C1 diag {c1_pass}. Flagged when p95 x sqrt(2) exceeds them.")
    for cls, crossed in flags.items():
        print(f"  {cls}: will produce wobble findings on {', '.join(crossed)}")
    if not flags:
        print("  no class crosses a pass band: wobble alone should not produce C1/C2 findings")
    print(f"\n{out_dir}")


if __name__ == "__main__":
    main()
