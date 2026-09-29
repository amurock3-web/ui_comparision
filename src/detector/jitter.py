"""Detector box wobble (Phase 17): how far YOLO boxes move under image changes
nobody can see.

make_variants(img) makes near-copies of a screenshot (a 1-3 px shift, a
resample, a JPEG re-save); measure_wobble compares the detector's boxes on
each copy with its boxes on the original. A human sees no difference, so any
box movement is detector noise - the floor under which C1/C2 findings mean
nothing. scripts/measure_jitter.py turns it into a per-class table.

Left out on purpose: scaling (moves bottom elements tens of pixels, a real
layout change) and brightness (screencaps are digital; it would test the
colour checks, not the boxes).
"""
import io

import numpy as np
from PIL import Image

from src.comparison.matcher import _iou

# (name, transform, parameter). shift: (dx, dy) px with edges replicated;
# resample: down to that scale (LANCZOS) and back; jpeg: re-save quality.
VARIANTS = [
    ("shift_1_0", "shift", (1, 0)),
    ("shift_0_1", "shift", (0, 1)),
    ("shift_2_2", "shift", (2, 2)),
    ("shift_3_3", "shift", (3, 3)),
    ("resample_85", "resample", 0.85),
    ("resample_95", "resample", 0.95),
    ("jpeg_70", "jpeg", 70),
    ("jpeg_90", "jpeg", 90),
]
IOU_MIN = 0.5
METRICS = ("size", "diag", "rel_dw", "rel_dh", "dcx", "dcy")


def shift(img: Image.Image, dx: int, dy: int) -> Image.Image:
    """Content moved dx right and dy down; the uncovered edge repeats the old edge."""
    a = np.pad(np.asarray(img), ((dy, 0), (dx, 0), (0, 0)), mode="edge")
    return Image.fromarray(a[:img.height, :img.width])


def resample(img: Image.Image, scale: float) -> Image.Image:
    W, H = img.size
    small = img.resize((round(W * scale), round(H * scale)), Image.LANCZOS)
    return small.resize((W, H), Image.LANCZOS)


def jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def make_variants(img: Image.Image, variants=VARIANTS) -> list:
    """[(name, image, (dx, dy))]: (dx, dy) maps a variant's box back to the
    original (subtract it); only a shift has one."""
    img = img.convert("RGB")
    out = []
    for name, kind, p in variants:
        if kind == "shift":
            out.append((name, shift(img, *p), p))
        elif kind == "resample":
            out.append((name, resample(img, p), (0, 0)))
        elif kind == "jpeg":
            out.append((name, jpeg(img, p), (0, 0)))
        else:
            raise ValueError(f"unknown jitter transform {kind!r}")
    return out


def _deviation(o, v, W, H) -> dict:
    """One variant box against the original, in the units the checks use:
    size = C2's max relative w/h change, diag = C1's centre move as a fraction
    of the screen diagonal."""
    rel_dw = abs(v[2] - o[2]) / max(v[2], o[2], 1e-9)
    rel_dh = abs(v[3] - o[3]) / max(v[3], o[3], 1e-9)
    dx = (v[0] + v[2] / 2) - (o[0] + o[2] / 2)
    dy = (v[1] + v[3] / 2) - (o[1] + o[3] / 2)
    return {"size": max(rel_dw, rel_dh), "diag": (dx * dx + dy * dy) ** 0.5 / (W * W + H * H) ** 0.5,
            "rel_dw": rel_dw, "rel_dh": rel_dh, "dcx": abs(dx) / W, "dcy": abs(dy) / H}


def measure_wobble(original, variants, W, H, iou_min=IOU_MIN) -> list:
    """original: [(class, [x, y, w, h])] on the untouched image.
    variants: [(detections like original, (dx, dy))], one per variant image.

    Per original detection: matched_in (variants with a same-class box at
    IoU >= iou_min after mapping back), class_flips (a box there, other class
    only), and per metric the max |deviation| over the matched variants (None
    when never matched). Max, not std: 3-8 samples give a useless std.
    """
    rows = []
    for cls, o in original:
        devs, flips = [], 0
        for dets, (dx, dy) in variants:
            back = [(c, [b[0] - dx, b[1] - dy, b[2], b[3]]) for c, b in dets]
            same = max(((_iou(o, b), b) for c, b in back if c == cls), default=(0.0, None), key=lambda t: t[0])
            if same[0] >= iou_min:
                devs.append(_deviation(o, same[1], W, H))
            elif any(_iou(o, b) >= iou_min for c, b in back if c != cls):
                flips += 1
        row = {"class": cls, "bbox": list(o), "variants": len(variants),
               "matched_in": len(devs), "class_flips": flips}
        row.update({m: max(d[m] for d in devs) if devs else None for m in METRICS})
        rows.append(row)
    return rows
