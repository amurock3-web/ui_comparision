# Tests for src/comparison/screen_checks.py — the screen-level A1/A2/A3/A5
# checks. Images are synthetic (numpy); no screenshot ever goes in git.

import numpy as np

from src.comparison.screen_checks import (check_blank, check_orientation,
                                          check_scaling, check_theme)


def _flat(w, h, rgb=(10, 10, 12)):
    """A uniform frame — the A2 blank case and the base for everything else."""
    return np.full((h, w, 3), rgb, dtype=np.uint8)


def _busy(w, h, bg=(10, 10, 12), fg=(230, 230, 235)):
    """A frame with card-like blocks and text-like stripes: real-screen texture."""
    img = _flat(w, h, bg)
    rng = np.random.default_rng(0)
    for _ in range(40):
        x, y = int(rng.integers(0, w - 40)), int(rng.integers(0, h - 40))
        img[y:y + 30, x:x + 35] = fg
        img[y + 32:y + 35, x:x + 25] = fg  # a caption line under the "card"
    return img


def _light(w, h):
    return _busy(w, h, bg=(245, 245, 245), fg=(20, 20, 25))


# ---- A1 orientation ---------------------------------------------------


def test_portrait_vs_landscape_detected():
    result = check_orientation(_busy(1080, 1920), _busy(1920, 1080))

    assert result["production"]["orientation"] == "portrait"
    assert result["client"]["orientation"] == "landscape"
    assert result["differ"]
    assert (result["production"]["width"], result["production"]["height"]) == (1080, 1920)


def test_same_orientation_not_flagged():
    result = check_orientation(_busy(1080, 1920), _busy(720, 1280))

    assert not result["differ"]


# ---- A2 blank / broken ------------------------------------------------


def test_uniform_frame_is_blank_and_busy_frame_is_not():
    result = check_blank(_flat(400, 800), _busy(400, 800))

    assert result["production"]["blank"]
    assert result["production"]["dominant_colour_fraction"] == 1.0
    assert not result["client"]["blank"]
    assert result["client"]["edge_density"] > 0.005
    assert result["any_blank"]


def test_blank_reports_dominant_colour_and_respects_threshold():
    white = check_blank(_flat(200, 200, (255, 255, 255)), _busy(200, 400))

    assert white["production"]["dominant_colour_rgb"] == [240, 240, 240]  # quantized
    # With the threshold relaxed past 1.0 the colour signal can no longer fire,
    # so only the edge measure is left to call it blank.
    loose = check_blank(_flat(200, 200), _busy(200, 400), dominant_colour_fraction_max=1.1)
    assert not loose["production"]["uniform"]
    assert loose["production"]["no_content"] and loose["production"]["blank"]


# ---- A3 theme ---------------------------------------------------------


def test_dark_vs_light_theme_disagree():
    result = check_theme(_busy(400, 800), _light(400, 800))

    assert result["production"]["theme"] == "dark"
    assert result["client"]["theme"] == "light"
    assert result["differ"]


def test_status_bar_band_is_excluded_from_theme():
    # A dark app under a white status bar must still read as dark.
    img = _busy(400, 800)
    img[: int(800 * 0.04)] = 255
    with_bar = check_theme(img, img)
    full_frame = check_theme(img, img, status_bar_height_norm=0.0)

    assert with_bar["production"]["theme"] == "dark"
    assert with_bar["production"]["mean_luminance"] < full_frame["production"]["mean_luminance"]


# ---- A5 scaling -------------------------------------------------------


def test_different_resolution_same_aspect_is_not_distortion():
    result = check_scaling(_busy(540, 960), _busy(1080, 1920))

    assert not result["same_size"]
    assert not result["aspect_distorted"]
    assert result["aspect_ratio_difference"] < 1e-6
    assert result["scale_x"] == 0.5


def test_stretched_screen_flagged_as_distorted():
    result = check_scaling(_busy(1080, 1400), _busy(1080, 1920))

    assert result["aspect_distorted"]
    assert result["aspect_ratio_difference"] > 0.05


# ---- identical images: nothing anywhere -------------------------------


def test_identical_images_show_no_difference_on_any_check():
    img = _busy(400, 800)

    assert not check_orientation(img, img)["differ"]
    assert not check_blank(img, img)["any_blank"]
    assert not check_theme(img, img)["differ"]
    scaling = check_scaling(img, img)
    assert scaling["same_size"] and not scaling["aspect_distorted"]


def test_accepts_a_path_as_well_as_an_array(tmp_path):
    from PIL import Image

    path = tmp_path / "shot.png"
    Image.fromarray(_busy(200, 400)).save(path)

    assert check_orientation(path, _busy(200, 400))["differ"] is False
    assert check_scaling(str(path), _busy(200, 400))["same_size"]
