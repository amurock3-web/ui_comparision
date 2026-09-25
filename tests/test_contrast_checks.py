import numpy as np
import pytest

from src.comparison.contrast_checks import (
    measure_pair,
    split_text_background,
    wcag_contrast,
)


def _text_crop(fg, bg, h=40, w=120):
    """Background fill with a few vertical and horizontal 'glyph' strokes."""
    crop = np.full((h, w, 3), bg, dtype=np.uint8)
    for x in range(10, w - 10, 14):
        crop[8:32, x:x + 3] = fg
    crop[18:21, 10:w - 10] = fg
    return crop


def test_wcag_white_black():
    assert wcag_contrast((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0)
    assert wcag_contrast((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0)


def test_wcag_777_on_white():
    assert wcag_contrast((0x77, 0x77, 0x77), (255, 255, 255)) == pytest.approx(4.48, abs=0.01)


def test_black_text_on_white():
    s = split_text_background(_text_crop((0, 0, 0), (255, 255, 255)))
    assert s.reliable, s.note
    assert sum(s.text.rgb) < 60
    assert sum(s.background.rgb) > 700
    assert wcag_contrast(s.text.rgb, s.background.rgb) > 15


def test_grey_on_near_grey_unreliable():
    s = split_text_background(_text_crop((120, 120, 120), (128, 128, 128)))
    assert not s.reliable
    assert s.note


def test_noise_and_degenerate_do_not_raise():
    rng = np.random.default_rng(0)
    split_text_background(rng.integers(0, 256, (30, 30, 3), dtype=np.uint8))
    assert not split_text_background(np.zeros((0, 0, 3), np.uint8)).reliable
    assert not split_text_background(np.full((10, 10, 3), 50, np.uint8)).reliable


def test_measure_pair_identical():
    crop = _text_crop((230, 230, 230), (20, 20, 40))
    m = measure_pair(crop, crop.copy())
    assert m.text_delta_e == pytest.approx(0.0, abs=1e-6)
    assert m.production_ratio == pytest.approx(m.client_ratio)
