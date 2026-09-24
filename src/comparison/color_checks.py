"""
Colour checks D1/D2/D4/D5 (docs/test_cases_pass_fail.md §D, design.md §21).

The client design is the reference, production is under test. Every
function here returns a *measurement* (ColorSample / ColorDelta), never a
verdict string: the PASS/REVIEW/FAIL bands live in config/config.yaml and
are applied by differ.py, so nothing in this module reads config.

SCOPE WARNING (CLAUDE.md, rules.md §2, test_cases_pass_fail.md §H):
poster and tile artwork is dynamic content and is NEVER compared. Two
captures of the same screen carry different posters. These functions work
on whatever crop the caller hands them and cannot tell a button from a
poster, so the caller must restrict them to *chrome* — buttons, badges,
tab bars, backgrounds, selected states, logos — and never pass the inside
of a content_card / cast_card / celebrity_card.

Distance is CIEDE2000 in CIELAB (design.md §21.4): RGB distance does not
match the eye. Recommended bands, from §D and the perceptual literature
(ΔE<2 invisible, 2-5 noticeable side by side, >5 obviously different):
    D1 brand/accent  PASS <= 3,  REVIEW 3-6,   FAIL > 6   (Critical)
    D2 background    PASS <= 3,  REVIEW 3-6,   FAIL > 6   (Major)
    D4 selected      PASS <= 5,  REVIEW 5-8,   FAIL > 8   (Major)
    D5 badge         PASS <= 5,  REVIEW 5-10,  FAIL > 10  (Minor/Major)

Dependencies: numpy and opencv (cv2), both already in the runtime env
(pulled by paddleocr; the Dockerfile installs opencv-contrib-python's
system libs). Neither is pinned in requirements.txt — worth adding there
if this module ships, since nothing else in src/ imports cv2 today.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class ColorSample:
    """One region reduced to a single representative colour."""
    rgb: tuple[int, int, int]
    lab: tuple[float, float, float]
    pixels: int                       # pixels that survived insetting / masking
    note: str = ""                    # why a fallback was taken, if one was


@dataclass
class ColorDelta:
    """A D-check measurement. `delta_e` is CIEDE2000; bands are the caller's."""
    check_id: str
    delta_e: float
    production: ColorSample
    client: ColorSample
    notes: list[str] = field(default_factory=list)


# ---- colour space -----------------------------------------------------


def to_lab(rgb) -> tuple[float, float, float]:
    """sRGB (0-255 or 0-1) -> CIELAB D65, L in 0..100, a/b in ~-128..128.

    cv2 does the sRGB gamma decode itself for float32 input in 0..1, so we
    never hand-roll the transfer function.
    """
    arr = np.asarray(rgb, dtype=np.float32).reshape(1, 1, 3)
    if arr.max() > 1.0:
        arr = arr / 255.0
    lab = cv2.cvtColor(arr, cv2.COLOR_RGB2Lab)[0, 0]
    return (float(lab[0]), float(lab[1]), float(lab[2]))


def delta_e2000(lab1, lab2) -> float:
    """CIEDE2000 colour difference (Sharma, Wu & Dalal 2005 formulation).

    Weighting factors kL=kC=kH=1 (graphic-arts default); exposing them
    would be a knob nobody in this pipeline turns.
    """
    l1, a1, b1 = (float(v) for v in lab1)
    l2, a2, b2 = (float(v) for v in lab2)

    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_bar ** 7 / (c_bar ** 7 + 25.0 ** 7))) if c_bar > 0 else 0.5
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)

    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0 if (a1p or b1) else 0.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0 if (a2p or b2) else 0.0

    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        dhp -= 360.0 * (dhp > 180.0)
        dhp += 360.0 * (dhp < -180.0)
    dHp = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2.0)

    lp_bar = (l1 + l2) / 2.0
    cp_bar = (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hp_bar = (h1p + h2p + 360.0) / 2.0
    else:
        hp_bar = (h1p + h2p - 360.0) / 2.0

    t = (1.0
         - 0.17 * np.cos(np.radians(hp_bar - 30.0))
         + 0.24 * np.cos(np.radians(2.0 * hp_bar))
         + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
         - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0)))
    d_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    rc = 2.0 * np.sqrt(cp_bar ** 7 / (cp_bar ** 7 + 25.0 ** 7)) if cp_bar > 0 else 0.0
    sl = 1.0 + (0.015 * (lp_bar - 50.0) ** 2) / np.sqrt(20.0 + (lp_bar - 50.0) ** 2)
    sc = 1.0 + 0.045 * cp_bar
    sh = 1.0 + 0.015 * cp_bar * t
    rt = -np.sin(np.radians(2.0 * d_theta)) * rc

    return float(np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2
                         + rt * (dcp / sc) * (dHp / sh)))


def _notes(prod: "ColorSample", client: "ColorSample") -> list[str]:
    """Surface each side's sampling fallback so the report can show it."""
    out = []
    if prod.note:
        out.append(f"production: {prod.note}")
    if client.note:
        out.append(f"client: {client.note}")
    return out


# ---- sampling a region ------------------------------------------------


def dominant_color(crop, inset_fraction: float = 0.25, min_pixels: int = 16) -> ColorSample:
    """Representative colour of an RGB crop: componentwise median in Lab.

    Median, not mean: a button crop is fill plus a label, a rounded corner
    and an anti-aliased rim. The mean is dragged toward whatever sits on
    top (white text, the page behind the corner); the median ignores any
    minority as long as the fill is over half the sampled pixels. Lab, not
    RGB, so the median is taken along perceptual axes and the result stays
    near a real colour of the crop.

    `inset_fraction` crops that fraction off each side first (0.25 -> the
    centre 50% x 50%), which is what removes the anti-aliased border and
    the rounded corners entirely rather than just out-voting them. It is
    relaxed automatically when the inset would leave fewer than
    `min_pixels`, so tiny badge crops still report something.

    # ponytail: componentwise median, not a k-means dominant cluster
    # (§D suggests k=2). It is one numpy call and is right whenever the
    # fill is the majority after insetting. Upgrade to cv2.kmeans if a
    # real screen shows a chrome element where it is not.
    """
    arr = np.asarray(crop)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError(f"expected an HxWx3 RGB crop, got shape {getattr(arr, 'shape', None)}")
    arr = arr[:, :, :3]
    h, w = arr.shape[:2]
    if h == 0 or w == 0:
        raise ValueError("empty crop")

    note = ""
    dy, dx = int(h * inset_fraction), int(w * inset_fraction)
    region = arr[dy:h - dy, dx:w - dx] if (h - 2 * dy) > 0 and (w - 2 * dx) > 0 else arr[:0]
    if region.size == 0 or region.shape[0] * region.shape[1] < min_pixels:
        region = arr
        note = f"crop {w}x{h} too small to inset by {inset_fraction}; sampled whole crop (edge pixels included)"

    flat = region.reshape(-1, 3).astype(np.float32)
    if flat.max() > 1.0:
        flat /= 255.0
    lab = cv2.cvtColor(flat.reshape(1, -1, 3), cv2.COLOR_RGB2Lab).reshape(-1, 3)
    med_lab = np.median(lab, axis=0)
    med_rgb = cv2.cvtColor(med_lab.reshape(1, 1, 3).astype(np.float32), cv2.COLOR_Lab2RGB)[0, 0]
    return ColorSample(
        rgb=tuple(int(round(v)) for v in np.clip(med_rgb * 255.0, 0, 255)),
        lab=tuple(float(v) for v in med_lab),
        pixels=int(flat.shape[0]),
        note=note,
    )


def compare_crops(
    production_crop,
    client_crop,
    check_id: str = "D1",
    inset_fraction: float = 0.25,
    min_pixels: int = 16,
) -> ColorDelta:
    """ΔE2000 between the dominant colours of two matched crops.

    Crops are RGB (numpy array or PIL Image) — the pipeline loads with
    `Image.open(...).convert("RGB")` throughout, so do NOT hand this a
    cv2.imread BGR array.
    """
    prod = dominant_color(production_crop, inset_fraction, min_pixels)
    client = dominant_color(client_crop, inset_fraction, min_pixels)
    return ColorDelta(check_id, delta_e2000(prod.lab, client.lab), prod, client, _notes(prod, client))


# D1/D4/D5 are the same measurement on different element classes; the
# wrappers exist only to stamp the spec id and carry each check's default
# sampling. The caller picks which elements qualify (chrome only).


def brand_color_delta(production_crop, client_crop, inset_fraction: float = 0.25,
                      min_pixels: int = 16) -> ColorDelta:
    """D1 brand/accent colour of a matched primary button, logo or accent."""
    return compare_crops(production_crop, client_crop, "D1", inset_fraction, min_pixels)


def selected_state_color_delta(production_crop, client_crop, inset_fraction: float = 0.25,
                               min_pixels: int = 16) -> ColorDelta:
    """D4 selected-state colour of the matched active tab / highlight crop.

    Only the colour half of D4. "Wrong tab highlighted, or no highlight"
    is a structural question about *which* element is selected — that is
    the matcher's and differ's job, not a colour measurement.
    """
    return compare_crops(production_crop, client_crop, "D4", inset_fraction, min_pixels)


def badge_color_delta(production_crop, client_crop, inset_fraction: float = 0.15,
                      min_pixels: int = 16) -> ColorDelta:
    """D5 badge colour (overlay_badge: "Free", "New", "Premium").

    Smaller default inset than D1: badges are a few dozen pixels wide and
    mostly text, so a 25% inset can leave only glyph pixels behind.
    """
    return compare_crops(production_crop, client_crop, "D5", inset_fraction, min_pixels)


# ---- D2 background ----------------------------------------------------


def background_color(
    image,
    boxes=None,
    margin: float = 0.02,
    quantize: int = 16,
    min_pixels: int = 256,
) -> ColorSample:
    """Page background of a full screenshot (design.md §21.1).

    Masks out every detected element box (grown by `margin` of the frame's
    short side, to drop the anti-aliased halo around each widget), then
    takes the *modal* colour of what is left, quantized into `quantize`-wide
    buckets, and reports the median of that bucket's pixels. Mode, not
    median: the leftover pixels are typically flat page background plus a
    hero image and a gradient scrim, and the median of that mixture is a
    colour that appears nowhere on screen, while the mode lands on the flat
    background that dominates it.

    `boxes` are [x, y, w, h] in pixels (UIElement.bbox). Passing them is
    strongly preferred.

    # ponytail: with boxes=None this falls back to the mode of the WHOLE
    # frame. On a dark OTT screen that is usually still the background, but
    # on a screen dominated by one large poster or a light modal it will
    # report the poster instead — dynamic content, exactly what §H says
    # never to compare. The returned note says so; the caller should treat
    # a boxes=None result as REVIEW rather than PASS/FAIL.
    """
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] < 3:
        raise ValueError(f"expected an HxWx3 RGB image, got shape {getattr(arr, 'shape', None)}")
    arr = arr[:, :, :3]
    h, w = arr.shape[:2]

    note = ""
    keep = np.ones((h, w), dtype=bool)
    if boxes:
        pad = int(round(margin * min(h, w)))
        for x, y, bw, bh in ([float(v) for v in b[:4]] for b in boxes):
            x0, y0 = max(0, int(x) - pad), max(0, int(y) - pad)
            x1, y1 = min(w, int(x + bw) + pad), min(h, int(y + bh) + pad)
            keep[y0:y1, x0:x1] = False
        if int(keep.sum()) < min_pixels:
            keep[:] = True
            note = "element boxes covered the whole frame; sampled every pixel"
    else:
        note = "no element boxes given; sampled every pixel — may land on poster artwork, treat as REVIEW"

    pixels = arr[keep].reshape(-1, 3)
    if pixels.max() > 1.0:
        pixels = pixels.astype(np.float32) / 255.0
    else:
        pixels = pixels.astype(np.float32)

    # Mode over quantized sRGB: cheap, and the bucket width is a visible knob.
    step = quantize / 255.0
    buckets = np.floor(pixels / step).astype(np.int32)
    keys = (buckets[:, 0] << 20) | (buckets[:, 1] << 10) | buckets[:, 2]
    values, counts = np.unique(keys, return_counts=True)
    winners = pixels[keys == values[counts.argmax()]]

    lab = cv2.cvtColor(winners.reshape(1, -1, 3), cv2.COLOR_RGB2Lab).reshape(-1, 3)
    med_lab = np.median(lab, axis=0)
    med_rgb = cv2.cvtColor(med_lab.reshape(1, 1, 3).astype(np.float32), cv2.COLOR_Lab2RGB)[0, 0]
    return ColorSample(
        rgb=tuple(int(round(v)) for v in np.clip(med_rgb * 255.0, 0, 255)),
        lab=tuple(float(v) for v in med_lab),
        pixels=int(winners.shape[0]),
        note=note,
    )


def background_color_delta(
    production_image,
    client_image,
    production_boxes=None,
    client_boxes=None,
    margin: float = 0.02,
    quantize: int = 16,
    min_pixels: int = 256,
) -> ColorDelta:
    """D2 background colour: ΔE2000 between the two screens' page backgrounds.

    Images are full RGB screenshots; boxes are each side's detected element
    bboxes ([x, y, w, h] px). See background_color for the sampling ceiling
    when boxes are omitted.
    """
    prod = background_color(production_image, production_boxes, margin, quantize, min_pixels)
    client = background_color(client_image, client_boxes, margin, quantize, min_pixels)
    return ColorDelta("D2", delta_e2000(prod.lab, client.lab), prod, client, _notes(prod, client))
