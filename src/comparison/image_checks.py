"""
Image checks F1/F2/F3 (docs/test_cases_pass_fail.md §F).

Like color_checks.py, every function here returns a *measurement* (a float,
an int hash, a Flatness), never a verdict string: the PASS/REVIEW/FAIL bands
live in config/config.yaml and are applied by the caller, so nothing in this
module reads config.

    F1/F2 icon / logo identity -> ssim() (plus dhash()/hamming() as a second
                                  opinion for tiny icons, where SSIM's 11x11
                                  window covers most of the crop)
    F3    broken / placeholder  -> flatness()

SCOPE WARNING (CLAUDE.md, rules.md §2, test_cases_pass_fail.md §H):
poster and tile artwork is dynamic content and is NEVER compared. ssim() and
dhash() are for chrome only (icons, logos, badges); the caller must never
pass the inside of a content_card / cast_card / celebrity_card to them.
flatness() is the one exception, and only because it compares nothing: it
looks at a single card and asks whether *any* picture is there (§H allows a
presence check on the container), never what the poster shows.

Crops are RGB (numpy HxWx3 uint8 or a PIL Image), as everywhere else in the
pipeline. Degenerate or empty crops never raise: ssim() returns 0.0,
dhash() returns 0 and flatness() returns a Flatness with pixels=0.

Dependencies: numpy and cv2 only (no scikit-image).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Wang, Bovik, Sheikh & Simoncelli 2004 constants for 8-bit images.
_C1 = (0.01 * 255) ** 2
_C2 = (0.03 * 255) ** 2


@dataclass
class Flatness:
    """F3 measurement of one card area. pixels=0 means the crop was empty."""
    luminance_std: float              # grey-level std, 0-255 scale
    edge_density: float               # fraction of Canny edge pixels, 0-1
    pixels: int                       # pixels measured after insetting


def _gray(crop) -> np.ndarray | None:
    """RGB/RGBA/grey crop -> 2-D uint8 grey, or None when empty/unusable."""
    try:
        arr = np.asarray(crop)
    except Exception:
        return None
    if arr.ndim == 3 and arr.shape[2] >= 3:
        arr = arr[:, :, :3]
    elif arr.ndim != 2:
        return None
    if arr.size == 0:
        return None
    if arr.dtype != np.uint8:
        arr = arr.astype(np.float32)
        if arr.max() <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    return cv2.cvtColor(np.ascontiguousarray(arr), cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr


def ssim(crop_a, crop_b) -> float:
    """Mean SSIM of two crops (F1/F2), in [-1, 1], 1.0 = identical.

    crop_a is resized to crop_b's size (INTER_AREA) before comparing.
    Resize-then-SSIM is right here because F1/F2 test the *identity* of the
    picture (is it the same icon/logo?); a size difference is C2's job and
    must not be double-counted as a picture difference.

    Standard Gaussian-window SSIM: 11x11 Gaussian, sigma 1.5,
    C1=(0.01*255)^2, C2=(0.03*255)^2, averaged over the map.
    """
    a, b = _gray(crop_a), _gray(crop_b)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        a = cv2.resize(a, (b.shape[1], b.shape[0]), interpolation=cv2.INTER_AREA)
    a, b = a.astype(np.float64), b.astype(np.float64)

    def blur(x):
        return cv2.GaussianBlur(x, (11, 11), 1.5)

    mu_a, mu_b = blur(a), blur(b)
    var_a = blur(a * a) - mu_a ** 2
    var_b = blur(b * b) - mu_b ** 2
    cov = blur(a * b) - mu_a * mu_b
    num = (2 * mu_a * mu_b + _C1) * (2 * cov + _C2)
    den = (mu_a ** 2 + mu_b ** 2 + _C1) * (var_a + var_b + _C2)
    return float(np.mean(num / den))


def dhash(crop, size: int = 8) -> int:
    """Difference hash: size*size bits, 1 where a pixel is brighter than its
    right neighbour on a (size+1)x size grey thumbnail. 0 for an empty crop."""
    g = _gray(crop)
    if g is None:
        return 0
    small = cv2.resize(g, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(sum(1 << i for i, bit in enumerate(bits) if bit))


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes."""
    return bin(a ^ b).count("1")


def flatness(crop, inset_fraction: float = 0.05) -> Flatness:
    """F3 broken / placeholder image: how flat is this card area?

    A card whose image failed to load is a flat fill (or a flat fill plus
    one small placeholder glyph): low luminance std and almost no edges.
    Any real poster, whatever it shows, has texture on both measures.

    This is a PRESENCE check on the container (allowed by
    docs/test_cases_pass_fail.md §H): it measures one crop on its own and
    never compares what the poster shows against the other screen.

    `inset_fraction` trims that fraction off each side first so the card's
    border and rounded corners do not register as edges. Canny thresholds
    are 50/150.
    """
    g = _gray(crop)
    if g is None:
        return Flatness(0.0, 0.0, 0)
    h, w = g.shape
    dy, dx = int(h * inset_fraction), int(w * inset_fraction)
    if h - 2 * dy > 0 and w - 2 * dx > 0:
        g = g[dy:h - dy, dx:w - dx]
    edges = cv2.Canny(np.ascontiguousarray(g), 50, 150)
    return Flatness(
        luminance_std=float(g.std()),
        edge_density=float(np.count_nonzero(edges)) / g.size,
        pixels=int(g.size),
    )
