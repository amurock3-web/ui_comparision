"""
Screen-level checks A1/A2/A3/A5 (docs/test_cases_pass_fail.md §A).

These compare the two screenshots as whole images, before and independently
of detection/OCR/matching, so they are cheap and they still work when the
detector finds nothing (which is exactly the A2 "blank / broken" case).

The client design is the reference, production is under test. Every function
returns the *measured numbers* plus the booleans they imply — never a verdict
string: the PASS/REVIEW/FAIL bands live in config/config.yaml and are applied
by the caller, so every threshold here is an argument with a documented
default rather than a constant in the code.
"""

import numpy as np
from PIL import Image

# Rec.709 luma — matches how the eye weights the channels, unlike a flat mean.
_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _as_array(image) -> np.ndarray:
    """Path / PIL image / HxWx3 uint8 array -> HxWx3 uint8 array."""
    if isinstance(image, np.ndarray):
        arr = image
        if arr.ndim == 2:  # grayscale in, treat as RGB so the rest is one code path
            arr = np.stack([arr] * 3, axis=-1)
        return arr[:, :, :3].astype(np.uint8, copy=False)
    if isinstance(image, Image.Image):
        return np.asarray(image.convert("RGB"))
    return np.asarray(Image.open(image).convert("RGB"))


def _luminance(arr: np.ndarray) -> np.ndarray:
    """Per-pixel luminance normalized to 0..1."""
    return (arr.astype(np.float32) @ _LUMA) / 255.0


def check_orientation(production, client) -> dict:
    """A1 — portrait vs landscape per side (Critical when they differ)."""
    sides = {}
    for name, image in (("production", production), ("client", client)):
        h, w = _as_array(image).shape[:2]
        # Spec: w > h = landscape, so a square screenshot counts as portrait.
        sides[name] = {"width": int(w), "height": int(h),
                       "aspect_ratio": w / h,
                       "orientation": "landscape" if w > h else "portrait"}
    sides["differ"] = sides["production"]["orientation"] != sides["client"]["orientation"]
    return sides


def check_blank(production, client, *, dominant_colour_fraction_max: float = 0.90,
                edge_density_min: float = 0.005, edge_magnitude_min: int = 12,
                colour_levels: int = 16) -> dict:
    """
    A2 — is either side effectively empty or broken?

    Two independent measures, either of which can condemn a side:
      dominant_colour_fraction — share of the frame in the single most common
        quantized colour (default >0.90 is blank, straight from the spec).
      edge_density — share of pixels next to a luminance step of at least
        edge_magnitude_min/255. A real OTT screen is full of card borders and
        text and sits well above 0.05; a flat or broken frame is near zero, so
        the default 0.005 only fires on genuinely empty output.

    colour_levels buckets each channel (16 levels = ignore <16/255 gradients),
    so a subtly dithered or gradient background still reads as one colour.
    """
    shift = int(np.log2(256 // colour_levels))
    sides = {}
    for name, image in (("production", production), ("client", client)):
        arr = _as_array(image)
        q = (arr >> shift).astype(np.int32)
        codes = (q[..., 0] * colour_levels + q[..., 1]) * colour_levels + q[..., 2]
        counts = np.bincount(codes.ravel(), minlength=colour_levels ** 3)
        dominant = int(counts.argmax())
        dominant_fraction = float(counts[dominant] / codes.size)

        lum = _luminance(arr) * 255.0
        gx = np.abs(np.diff(lum, axis=1))[:-1, :]
        gy = np.abs(np.diff(lum, axis=0))[:, :-1]
        edge_density = float(np.mean((gx > edge_magnitude_min) | (gy > edge_magnitude_min)))

        # Report the dominant colour so a human can tell "black screen" from
        # "white screen" from "grey placeholder" without opening the file.
        rgb = [(dominant // colour_levels ** 2) << shift,
               ((dominant // colour_levels) % colour_levels) << shift,
               (dominant % colour_levels) << shift]
        sides[name] = {
            "dominant_colour_fraction": dominant_fraction,
            "dominant_colour_rgb": rgb,
            "edge_density": edge_density,
            "uniform": dominant_fraction > dominant_colour_fraction_max,
            "no_content": edge_density < edge_density_min,
        }
        sides[name]["blank"] = sides[name]["uniform"] or sides[name]["no_content"]
    sides["any_blank"] = sides["production"]["blank"] or sides["client"]["blank"]
    # ponytail: the spec's other A2 signal ("0 detected elements") needs the
    # detector, so it stays in the element-level pass, not here.
    return sides


def check_theme(production, client, *, dark_luminance_max: float = 0.45,
                status_bar_height_norm: float = 0.04) -> dict:
    """
    A3 — dark vs light theme per side (Critical when swapped).

    Mean luminance over the frame minus the top status_bar_height_norm, which
    is the phone status bar: its clock/battery are dynamic content (§H) and a
    light status bar on a dark app would drag the mean. The median is reported
    alongside as a background proxy — half the pixels of an OTT screen are
    background, so it is the more stable of the two when the mean lands near
    the threshold and the caller wants to flag REVIEW.
    """
    sides = {}
    for name, image in (("production", production), ("client", client)):
        arr = _as_array(image)
        top = int(round(arr.shape[0] * status_bar_height_norm))
        body = arr[top:] if top < arr.shape[0] else arr
        lum = _luminance(body)
        mean = float(lum.mean())
        sides[name] = {"mean_luminance": mean,
                       "median_luminance": float(np.median(lum)),
                       "theme": "dark" if mean <= dark_luminance_max else "light"}
    sides["differ"] = sides["production"]["theme"] != sides["client"]["theme"]
    sides["luminance_difference"] = abs(
        sides["production"]["mean_luminance"] - sides["client"]["mean_luminance"])
    return sides


def check_scaling(production, client, *, aspect_tolerance: float = 0.05) -> dict:
    """
    A5 — same canvas? Reports the two faults separately, because they are
    different bugs: a pure resolution difference (same aspect ratio) is only a
    device difference and everything downstream normalizes it away, while an
    aspect-ratio difference means the UI is genuinely stretched or squashed.

    aspect_ratio_difference is relative (|p-c|/c), so the default 0.05 is the
    spec's ±5% PASS band; the caller bands anything above it.
    """
    ph, pw = _as_array(production).shape[:2]
    ch, cw = _as_array(client).shape[:2]
    p_aspect, c_aspect = pw / ph, cw / ch
    aspect_difference = abs(p_aspect - c_aspect) / c_aspect
    return {
        "production": {"width": int(pw), "height": int(ph), "aspect_ratio": p_aspect},
        "client": {"width": int(cw), "height": int(ch), "aspect_ratio": c_aspect},
        "same_size": (pw, ph) == (cw, ch),
        "scale_x": pw / cw,
        "scale_y": ph / ch,
        "aspect_ratio_difference": aspect_difference,
        "aspect_distorted": aspect_difference > aspect_tolerance,
    }
