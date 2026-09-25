"""
Pixel-measured element size, to confirm or downgrade box-based C2 findings.

Detector (YOLO) boxes wobble a few pixels between two screenshots of the
same widget, which is enough to trip C2 SIZE_DIFFERENCE on small chrome
(a bottom-nav "Profile" box at 0.0477 vs 0.0447 of screen height, identical
by eye). This module re-measures the element from its pixels: inside the
detector crop, find the tight bounding box of everything that differs from
the crop's own background.

Returns *measurements* (TightBox, ratio pairs), never verdicts, and reads no
config. The caller (differ.py) may only use them to CONFIRM or DOWNGRADE a
finding the box geometry already raised, never to create one: a tight box is
a heuristic and is wrong whenever the crop has no clean background.

SSIM is deliberately not used: comparing two crops by SSIM means resizing
them to one size first, which hides exactly the size change being measured.

SCOPE WARNING (CLAUDE.md, test_cases_pass_fail.md §H): chrome only. On a
crop over poster artwork the "background" is the artwork and the mask is
meaningless; pass artwork_through=True for such elements and the result is
marked unreliable.

Distance is plain CIELAB Euclidean (ΔE76), not CIEDE2000 as in
color_checks.py: this is a foreground/background threshold over every pixel,
not a perceptual judgement between two colours, and ΔE76 is one vectorised
numpy call.
"""

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class TightBox:
    """Tight foreground box in crop pixels. `reliable=False` -> don't trust it."""
    x: int
    y: int
    w: int
    h: int
    reliable: bool
    note: str = ""


def tight_box(crop, contrast_threshold: float = 12.0, min_pixels: int = 16,
              artwork_through: bool = False) -> TightBox:
    """Bounding box of the pixels that stand out from the crop's background.

    Background = per-channel median of the border ring (max(1, min(h,w)//20)
    px wide). Foreground = pixels more than `contrast_threshold` ΔE76 from it,
    closed with a 3x3 kernel so glyph gaps and anti-aliasing don't split the
    element. Crop is RGB (numpy HxWx3 or PIL Image), not cv2 BGR.

    When unreliable, the best box available is still returned (the mask box
    if there is one, else the whole crop) with a note saying why.
    """
    arr = np.asarray(crop)
    if arr.ndim != 3 or arr.shape[2] < 3 or arr.shape[0] < 3 or arr.shape[1] < 3:
        shape = getattr(arr, "shape", None)
        h, w = (shape[0], shape[1]) if shape is not None and len(shape) >= 2 else (0, 0)
        return TightBox(0, 0, int(w), int(h), False, f"empty or degenerate crop {shape}")
    arr = arr[:, :, :3].astype(np.float32)
    if arr.max() > 1.0:
        arr /= 255.0
    h, w = arr.shape[:2]
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2Lab)

    r = max(1, min(h, w) // 20)
    ring = np.ones((h, w), dtype=bool)
    ring[r:h - r, r:w - r] = False
    ring_lab = lab[ring]
    bg = np.median(ring_lab, axis=0)

    mask = (np.linalg.norm(lab - bg, axis=2) > contrast_threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    count = int(mask.sum())
    if count == 0:
        return TightBox(0, 0, w, h, False, "too few foreground pixels")
    bx, by, bw, bh = (int(v) for v in cv2.boundingRect(mask))

    notes = []
    if artwork_through:
        notes.append("chrome over artwork")
    if float(ring_lab[:, 0].std()) > 2 * contrast_threshold:
        notes.append("busy background")
    if count < min_pixels:
        notes.append("too few foreground pixels")
    if bx == 0 and by == 0 and bx + bw == w and by + bh == h:
        notes.append("no clear background: element fills the crop")
    return TightBox(bx, by, bw, bh, not notes, "; ".join(notes))


def size_diff(prod: TightBox, client: TightBox,
              prod_image_size=(1, 1), client_image_size=(1, 1)) -> tuple[float, float]:
    """(width_ratio_diff, height_ratio_diff), the same numbers C2 thresholds.

    Mirrors differ.py's C2 (ElementDiffer, "# C2" block):
        width_ratio_diff  = abs(p_w - c_w) / max(p_w, c_w, 1e-9)
        height_ratio_diff = abs(p_h - c_h) / max(p_h, c_h, 1e-9)
    where p_w/p_h are normalized_bbox w/h, i.e. pixel size / screenshot W/H.
    Pass each side's full screenshot (W, H) so the tight sizes are
    normalised the same way; the default (1, 1) compares raw pixels, which is
    only right when both screenshots share a resolution.
    """
    p_w, p_h = prod.w / prod_image_size[0], prod.h / prod_image_size[1]
    c_w, c_h = client.w / client_image_size[0], client.h / client_image_size[1]
    return (abs(p_w - c_w) / max(p_w, c_w, 1e-9),
            abs(p_h - c_h) / max(p_h, c_h, 1e-9))
