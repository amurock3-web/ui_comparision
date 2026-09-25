import cv2
import numpy as np
from PIL import Image

from src.comparison.image_checks import Flatness, dhash, flatness, hamming, ssim


def _icon(shape: str, size: int = 48) -> np.ndarray:
    img = np.full((size, size, 3), 20, np.uint8)
    c, r = size // 2, size // 3
    if shape == "circle":
        cv2.circle(img, (c, c), r, (230, 230, 230), -1)
    else:
        cv2.rectangle(img, (c - r, c - r), (c + r, c + r), (230, 230, 230), -1)
    return img


def _poster(h=180, w=120, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (h // 6, w // 6, 3), dtype=np.uint8)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def test_identical_ssim_is_one():
    icon = _icon("circle")
    assert abs(ssim(icon, icon.copy()) - 1.0) < 1e-6


def test_same_icon_at_double_size_is_similar():
    icon = _icon("circle", 48)
    big = _icon("circle", 96)
    assert ssim(big, icon) > 0.9
    assert ssim(Image.fromarray(big), Image.fromarray(icon)) > 0.9  # PIL input


def test_circle_vs_square_differs():
    circle, square = _icon("circle"), _icon("square")
    assert ssim(circle, square) < 0.9
    assert hamming(dhash(circle), dhash(square)) >= 6  # measured 8 of 64 bits
    assert hamming(dhash(circle), dhash(circle.copy())) == 0


def test_flat_card_is_flat():
    f = flatness(np.full((180, 120, 3), 60, np.uint8))
    assert f.luminance_std < 2 and f.edge_density < 0.01 and f.pixels > 0


def test_textured_poster_is_not_flat():
    f = flatness(_poster())
    assert f.luminance_std > 20 and f.edge_density > 0.05


def test_empty_crop_never_raises():
    empty = np.zeros((0, 0, 3), np.uint8)
    assert ssim(empty, _icon("circle")) == 0.0
    assert dhash(empty) == 0
    assert flatness(empty) == Flatness(0.0, 0.0, 0)
