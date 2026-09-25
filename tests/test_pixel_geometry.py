# Tests for src/comparison/pixel_geometry.py — tight pixel box and the C2
# size ratios. Crops are synthetic numpy arrays: no screenshots.

import numpy as np
import pytest

from src.comparison.pixel_geometry import TightBox, size_diff, tight_box

BG = (18, 18, 24)       # dark OTT page
FG = (230, 230, 230)    # light icon / label


def _canvas(h=200, w=200):
    img = np.empty((h, w, 3), dtype=np.uint8)
    img[:] = BG
    return img


def _rect(img, x, y, w, h, color=FG):
    img[y:y + h, x:x + w] = color
    return img


def test_solid_rectangle_on_flat_background():
    crop = _rect(_canvas(60, 80), 12, 9, 40, 20)
    tb = tight_box(crop)
    assert tb.reliable, tb.note
    assert abs(tb.x - 12) <= 1 and abs(tb.y - 9) <= 1
    assert abs(tb.w - 40) <= 1 and abs(tb.h - 20) <= 1


def test_detector_margin_wobble_does_not_change_size():
    screen = _rect(_canvas(), 80, 90, 40, 20)
    tight_crop = screen[85:115, 75:125]      # 5 px margin all round
    loose_crop = screen[78:122, 72:128]      # 7 px taller box, uneven margins
    a, b = tight_box(tight_crop), tight_box(loose_crop)
    assert a.reliable and b.reliable, (a.note, b.note)
    assert abs(a.w - b.w) <= 1 and abs(a.h - b.h) <= 1
    wd, hd = size_diff(a, b)
    assert wd < 0.03 and hd < 0.05


def test_genuinely_bigger_rectangle_is_reported():
    prod = tight_box(_rect(_canvas(80, 80), 10, 10, 40, 40))
    client = tight_box(_rect(_canvas(80, 80), 10, 10, 40, 50))
    wd, hd = size_diff(prod, client)
    # differ.py formula: |40-50| / max(40, 50) = 0.2
    assert wd == pytest.approx(0.0, abs=0.03)
    assert hd == pytest.approx(0.2, abs=0.03)


def test_size_diff_normalises_by_screen_size():
    # Same element at 2x resolution on a 2x screenshot -> no size change.
    a = TightBox(0, 0, 40, 20, True)
    b = TightBox(0, 0, 80, 40, True)
    assert size_diff(a, b, (1080, 1920), (2160, 3840)) == pytest.approx((0.0, 0.0))


def test_random_noise_background_is_unreliable():
    rng = np.random.default_rng(0)
    crop = rng.integers(0, 256, size=(60, 80, 3), dtype=np.uint8)
    _rect(crop, 20, 20, 30, 15)
    assert not tight_box(crop).reliable


def test_artwork_through_is_unreliable():
    crop = _rect(_canvas(60, 80), 12, 9, 40, 20)
    tb = tight_box(crop, artwork_through=True)
    assert not tb.reliable
    assert "artwork" in tb.note


def test_flat_crop_without_element_is_unreliable():
    tb = tight_box(_canvas(40, 40))
    assert not tb.reliable
    assert (tb.w, tb.h) == (40, 40)
