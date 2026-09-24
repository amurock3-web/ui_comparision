# Tests for src/comparison/color_checks.py — ΔE2000 and the D1/D2/D4/D5
# colour measurements (test_cases_pass_fail.md §D). Crops are synthetic
# numpy arrays: no screenshots, nothing from input/ or output/.

import numpy as np
import pytest

from src.comparison.color_checks import (background_color_delta, badge_color_delta,
                                         brand_color_delta, delta_e2000, dominant_color,
                                         selected_state_color_delta, to_lab)

# Recommended bands from the module docstring / §D, restated here so a
# threshold change shows up as a test edit, not a silent drift.
D1_PASS, D1_FAIL = 3.0, 6.0
D5_PASS, D5_FAIL = 5.0, 10.0

ORANGE = (255, 106, 0)      # a plausible OTT accent
BLUE = (0, 102, 255)
DARK_BG = (18, 18, 18)
DARK_BG_NEAR = (20, 20, 21)  # the same grey after a JPEG round trip


def _solid(color, w=80, h=40):
    return np.full((h, w, 3), color, dtype=np.uint8)


def _rounded_button(fill, background, w=80, h=40, border=4):
    """A fill with a thick anti-aliased rim blended toward the background.

    Stands in for a rounded, anti-aliased button: every edge pixel is a
    50/50 mix, which is exactly what drags a naive mean off the fill.
    """
    img = _solid(background, w, h)
    blend = tuple(int((a + b) / 2) for a, b in zip(fill, background))
    img[border // 2:h - border // 2, border // 2:w - border // 2] = blend
    img[border:h - border, border:w - border] = fill
    return img


# ---- ΔE2000 -----------------------------------------------------------


def test_identical_colors_have_zero_delta():
    assert delta_e2000(to_lab(ORANGE), to_lab(ORANGE)) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize(
    "lab1,lab2,expected",
    [
        # Sharma, Wu & Dalal (2005), "The CIEDE2000 Color-Difference
        # Formula", Table 1 — the reference data everyone validates against.
        ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),      # pair 1
        ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),                  # pair 17
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),  # pair 19
        ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),       # pair 34
    ],
)
def test_matches_published_ciede2000_values(lab1, lab2, expected):
    assert delta_e2000(lab1, lab2) == pytest.approx(expected, abs=1e-3)


def test_delta_is_symmetric():
    a, b = to_lab(ORANGE), to_lab(BLUE)
    assert delta_e2000(a, b) == pytest.approx(delta_e2000(b, a), abs=1e-9)


# ---- D1 brand / accent ------------------------------------------------


def test_two_near_identical_greys_stay_inside_the_pass_band():
    result = brand_color_delta(_solid(DARK_BG), _solid(DARK_BG_NEAR))
    assert result.check_id == "D1"
    assert result.delta_e < D1_PASS


def test_brand_color_swap_lands_well_above_the_fail_band():
    result = brand_color_delta(_solid(BLUE), _solid(ORANGE))
    assert result.delta_e > D1_FAIL * 3
    assert result.production.rgb == pytest.approx(BLUE, abs=2)
    assert result.client.rgb == pytest.approx(ORANGE, abs=2)


def test_antialiased_border_does_not_bleed_into_the_reported_fill():
    # Same fill on both sides, different page behind it: if the rim leaked
    # into the sample the two would disagree.
    prod = _rounded_button(ORANGE, DARK_BG)
    client = _rounded_button(ORANGE, (255, 255, 255))

    assert dominant_color(prod).rgb == pytest.approx(ORANGE, abs=2)
    assert dominant_color(client).rgb == pytest.approx(ORANGE, abs=2)
    assert brand_color_delta(prod, client).delta_e < D1_PASS


def test_label_text_does_not_move_the_fill_color():
    # White "text" over a third of the button: the median ignores a minority.
    crop = _solid(ORANGE)
    crop[16:24, 20:45] = (255, 255, 255)
    assert dominant_color(crop).rgb == pytest.approx(ORANGE, abs=2)


def test_tiny_crop_falls_back_to_the_whole_crop_and_says_so():
    sample = dominant_color(_solid(ORANGE, w=3, h=3))
    assert sample.rgb == pytest.approx(ORANGE, abs=2)
    assert "too small to inset" in sample.note


def test_empty_and_non_rgb_crops_are_rejected():
    with pytest.raises(ValueError):
        dominant_color(np.zeros((0, 10, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        dominant_color(np.zeros((10, 10), dtype=np.uint8))


# ---- D4 selected state / D5 badge -------------------------------------


def test_selected_state_carries_its_spec_id_and_measures_the_highlight():
    result = selected_state_color_delta(_solid(ORANGE), _solid((255, 110, 5)))
    assert result.check_id == "D4"
    assert result.delta_e < D1_PASS


def test_badge_color_change_exceeds_the_badge_fail_band():
    # A "Free" badge turned from green to red: 20x12, the size D5 really sees.
    result = badge_color_delta(_solid((0, 160, 60), w=20, h=12),
                               _solid((200, 30, 30), w=20, h=12))
    assert result.check_id == "D5"
    assert result.delta_e > D5_FAIL


def test_badge_color_unchanged_stays_inside_the_badge_pass_band():
    result = badge_color_delta(_solid((0, 160, 60), w=20, h=12),
                               _solid((2, 158, 62), w=20, h=12))
    assert result.delta_e < D5_PASS


# ---- D2 background ----------------------------------------------------


def _screen(bg, poster, poster_box):
    img = _solid(bg, w=200, h=300)
    x, y, w, h = poster_box
    img[y:y + h, x:x + w] = poster
    return img


def test_background_ignores_masked_poster_artwork():
    # Same page background, different posters — D2 must not see the posters.
    box = [20, 20, 160, 120]
    prod = _screen(DARK_BG, (200, 40, 30), box)
    client = _screen(DARK_BG, (30, 60, 220), box)

    result = background_color_delta(prod, client, [box], [box])

    assert result.check_id == "D2"
    assert result.delta_e < 1.0
    assert result.production.rgb == pytest.approx(DARK_BG, abs=2)


def test_background_change_is_measured_with_boxes_masked():
    box = [20, 20, 160, 120]
    prod = _screen((40, 40, 40), (200, 40, 30), box)
    client = _screen(DARK_BG, (200, 40, 30), box)

    assert background_color_delta(prod, client, [box], [box]).delta_e > D1_FAIL


def test_background_without_boxes_reports_its_ceiling():
    result = background_color_delta(_solid(DARK_BG, 200, 300), _solid(DARK_BG, 200, 300))
    assert result.delta_e < 1.0
    assert any("no element boxes" in n for n in result.notes)
