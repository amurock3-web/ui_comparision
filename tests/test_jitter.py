"""Phase 17.1: jitter variants and wobble measurement, with fake detections (no YOLO)."""
import numpy as np
from PIL import Image

from src.detector.jitter import VARIANTS, make_variants, measure_wobble

W, H = 200, 400
BOXES = [("tab_item", [20, 300, 40, 30]), ("content_card", [10, 50, 120, 80])]


def _img():
    a = np.random.default_rng(0).integers(0, 255, (H, W, 3), dtype=np.uint8)
    return Image.fromarray(a)


def test_variants_keep_size_and_mode():
    img = _img()
    variants = make_variants(img)
    assert len(variants) == len(VARIANTS)
    for name, v, _ in variants:
        assert v.size == img.size and v.mode == "RGB", name


def test_shift_moves_content_by_its_offset():
    img = _img()
    name, v, (dx, dy) = next(t for t in make_variants(img) if t[0] == "shift_2_2")
    a, b = np.asarray(img), np.asarray(v)
    assert (b[dy:, dx:] == a[:H - dy, :W - dx]).all()
    assert (b[:dy, dx:] == a[0, :W - dx]).all()  # uncovered edge repeats the old one


def _shifted(offset, boxes=BOXES, noise=0):
    dx, dy = offset
    return [(c, [x + dx + noise, y + dy, w + noise, h]) for c, (x, y, w, h) in boxes], offset


def test_boxes_that_follow_the_shift_have_zero_wobble():
    offsets = [(1, 0), (0, 1), (2, 2), (3, 3), (0, 0)]
    rows = measure_wobble(BOXES, [_shifted(o) for o in offsets], W, H)
    for r in rows:
        assert r["matched_in"] == len(offsets) and r["class_flips"] == 0
        assert r["size"] == 0 and r["diag"] == 0


def test_noise_shows_up_at_roughly_its_size():
    rows = measure_wobble(BOXES, [_shifted((0, 0), noise=3), _shifted((0, 0), noise=-3)], W, H)
    tab = rows[0]
    assert tab["matched_in"] == 2
    assert abs(tab["rel_dw"] - 3 / 40) < 1e-9  # worst of 3/43 (w 43) and 3/40 (w 37)
    assert tab["size"] == tab["rel_dw"]
    assert abs(tab["dcx"] - 4.5 / W) < 1e-9    # x +3 and w +3: centre moves 4.5 px


def test_missing_detection_lowers_matched_in():
    variants = [_shifted((0, 0)) for _ in range(6)] + [_shifted((0, 0), boxes=BOXES[1:]) for _ in range(2)]
    tab, card = measure_wobble(BOXES, variants, W, H)
    assert tab["matched_in"] == 6 and card["matched_in"] == 8


def test_same_box_other_class_is_a_flip():
    flipped = [("button", BOXES[0][1]), BOXES[1]]
    tab, card = measure_wobble(BOXES, [_shifted((0, 0)), _shifted((0, 0), boxes=flipped)], W, H)
    assert tab["matched_in"] == 1 and tab["class_flips"] == 1
    assert card["class_flips"] == 0


def test_never_matched_has_no_metrics():
    (tab,) = measure_wobble(BOXES[:1], [([], (0, 0))], W, H)
    assert tab["matched_in"] == 0 and tab["size"] is None
