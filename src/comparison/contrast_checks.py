"""
Text checks D3 (text colour) and D7 (text contrast, WCAG) —
docs/test_cases_pass_fail.md §D.

Same contract as color_checks.py: every function returns a *measurement*
(TextSplit / ContrastMeasure), never a verdict. The PASS/REVIEW/FAIL bands
(ΔE for D3, the 4.5:1 / 3:1 WCAG floors and the allowed ratio drop for D7)
belong in config/config.yaml and are applied by the caller; nothing here
reads config.

SCOPE: hand these functions crops of *static chrome text* only — button
labels, tab titles, section headers. Movie titles in rails and anything on
poster artwork are dynamic content and never compared (CLAUDE.md, §H).

Colour maths (to_lab, delta_e2000, ColorSample) is reused from
color_checks.py, not reimplemented.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from src.comparison.color_checks import ColorSample, delta_e2000, to_lab


@dataclass
class TextSplit:
    """A text crop separated into glyph colour and background colour."""
    text: ColorSample
    background: ColorSample
    text_fraction: float              # share of crop pixels in the text cluster
    reliable: bool
    note: str = ""                    # why reliable is False, if it is


@dataclass
class ContrastMeasure:
    """D3 + D7 measurement for one matched text element."""
    production_ratio: float           # WCAG contrast, production text vs its background
    client_ratio: float
    text_delta_e: float               # CIEDE2000 between the two text colours (D3)
    production: TextSplit
    client: TextSplit


# ---- WCAG 2.x ---------------------------------------------------------


def relative_luminance(rgb) -> float:
    """WCAG 2.1 relative luminance of an sRGB colour given as 0-255 ints."""
    c = np.asarray(rgb, dtype=np.float64)[:3] / 255.0
    lin = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2])


def wcag_contrast(rgb_a, rgb_b) -> float:
    """WCAG contrast ratio (L1 + 0.05) / (L2 + 0.05), lighter on top: 1..21."""
    la, lb = relative_luminance(rgb_a), relative_luminance(rgb_b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# ---- splitting a text crop --------------------------------------------


def _sample(pixels: np.ndarray, note: str = "") -> ColorSample:
    """Median colour (in Lab, as dominant_color does) of Nx3 float 0..1 RGB pixels."""
    lab = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_RGB2Lab).reshape(-1, 3)
    med_lab = np.median(lab, axis=0)
    med_rgb = cv2.cvtColor(med_lab.reshape(1, 1, 3).astype(np.float32), cv2.COLOR_Lab2RGB)[0, 0]
    return ColorSample(
        rgb=tuple(int(round(v)) for v in np.clip(med_rgb * 255.0, 0, 255)),
        lab=tuple(float(v) for v in med_lab),
        pixels=int(pixels.shape[0]),
        note=note,
    )


def _degenerate(note: str) -> TextSplit:
    empty = ColorSample(rgb=(0, 0, 0), lab=to_lab((0, 0, 0)), pixels=0, note=note)
    return TextSplit(empty, empty, 0.0, False, note)


def split_text_background(
    crop,
    min_cluster_de: float = 10.0,
    text_fraction_range=(0.03, 0.5),
) -> TextSplit:
    """k-means (k=2) the crop's pixels; the smaller cluster is the text.

    Each cluster is reduced to its median colour. `reliable` is False (with
    a note) when the two colours are within `min_cluster_de` ΔE2000 of each
    other — no real text/background separation — or when the text share
    falls outside `text_fraction_range`. Never raises: a degenerate crop
    comes back unreliable.

    # ponytail: "smaller cluster is text" assumes a tight crop around the
    # label. A loose crop with a thin label on a big fill still works; a
    # crop where text covers more than half the pixels flips the roles and
    # is caught only by text_fraction_range.
    """
    try:
        arr = np.asarray(crop)
        if arr.ndim != 3 or arr.shape[2] < 3 or arr.shape[0] * arr.shape[1] < 2:
            return _degenerate(f"degenerate crop, shape {getattr(arr, 'shape', None)}")
        flat = arr[:, :, :3].reshape(-1, 3).astype(np.float32)
        if flat.max() > 1.0:
            flat /= 255.0

        cv2.setRNGSeed(0)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1e-3)
        _, labels, _ = cv2.kmeans(flat, 2, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
        labels = labels.ravel()
        counts = np.bincount(labels, minlength=2)
        if counts.min() == 0:
            return _degenerate("crop is a single colour; no text cluster")

        text_label = int(counts.argmin())
        text = _sample(flat[labels == text_label])
        background = _sample(flat[labels != text_label])
        fraction = float(counts[text_label] / counts.sum())

        notes = []
        de = delta_e2000(text.lab, background.lab)
        if de < min_cluster_de:
            notes.append(f"text/background clusters only {de:.1f} ΔE apart (< {min_cluster_de})")
        lo, hi = text_fraction_range
        if not lo <= fraction <= hi:
            notes.append(f"text fraction {fraction:.2f} outside [{lo}, {hi}]")
        return TextSplit(text, background, fraction, not notes, "; ".join(notes))
    except Exception as exc:  # never raise on a bad crop
        return _degenerate(f"split failed: {exc}")


def measure_pair(prod_crop, client_crop, **split_kwargs) -> ContrastMeasure:
    """D3/D7 measurement for a matched text element (client is the reference)."""
    prod = split_text_background(prod_crop, **split_kwargs)
    client = split_text_background(client_crop, **split_kwargs)
    return ContrastMeasure(
        production_ratio=wcag_contrast(prod.text.rgb, prod.background.rgb),
        client_ratio=wcag_contrast(client.text.rgb, client.background.rgb),
        text_delta_e=delta_e2000(prod.text.lab, client.text.lab),
        production=prod,
        client=client,
    )
