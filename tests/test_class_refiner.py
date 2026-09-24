# Tests for the class refiner experiment's data helpers (scripts/build_refiner_dataset.py):
# the 22->16 remap from config/class_refiner.yaml and the OCR crop padding/clamping/upscale.
# No OCR, no model: these run without paddle or sklearn.

import pytest
from PIL import Image

from scripts.build_refiner_dataset import crop_for_ocr, load_config, remap_labels

CFG = load_config()
CLASSES_22 = ["content_card", "nav_item", "badge", "section_title", "button", "cast_card", "icon",
              "metadata_text", "category_tab", "navigation_bar", "celebrity_card", "detail_tab",
              "duration", "carousel_filter", "movie_title", "description", "search_bar",
              "episode_badge", "logo", "rank_number", "text_input", "series_title"]
CLASSES_16 = {"content_card", "tab_item", "overlay_badge", "section_title", "button", "cast_card",
              "icon", "metadata_text", "navigation_bar", "celebrity_card", "title", "description",
              "search_bar", "rank_number", "text_input", "logo"}


def test_remap_table_covers_22_onto_exactly_16():
    remap = CFG["remap"]
    assert set(remap) == set(CLASSES_22)
    assert set(remap.values()) == CLASSES_16
    assert {k for k, v in remap.items() if v == "tab_item"} == {"nav_item", "category_tab", "detail_tab", "carousel_filter"}
    assert {k for k, v in remap.items() if v == "overlay_badge"} == {"badge", "episode_badge", "duration"}
    assert {k for k, v in remap.items() if v == "title"} == {"movie_title", "series_title"}
    assert remap["cast_card"] == "cast_card" and remap["celebrity_card"] == "celebrity_card"


def test_remap_is_by_name_not_index():
    classes = ["duration", "nav_item", "series_title"]  # Label Studio order, not ours
    lines = ["0 0.5 0.5 0.1 0.1", "1 0.1 0.2 0.3 0.4", "", "2 0.5 0.5 0.2 0.2"]
    out = remap_labels(lines, classes, CFG["remap"])
    assert [o[0] for o in out] == ["overlay_badge", "tab_item", "title"]
    assert out[1][1:] == (0.1, 0.2, 0.3, 0.4)


def test_remap_corrections_use_1_based_line_numbers():
    lines = ["0 0.5 0.5 0.1 0.1", "0 0.5 0.5 0.1 0.1"]
    out = remap_labels(lines, ["button"], CFG["remap"], fixes={2: "tab_item"})
    assert [o[0] for o in out] == ["button", "tab_item"]
    with pytest.raises(ValueError):
        remap_labels(lines, ["button"], CFG["remap"], fixes={3: "tab_item"})


def test_remap_unknown_class_is_an_error():
    with pytest.raises(KeyError):
        remap_labels(["0 0.5 0.5 0.1 0.1"], ["mystery_class"], CFG["remap"])


def test_crop_pads_and_keeps_tall_crops_unscaled():
    img = Image.new("RGB", (200, 300))
    crop, rect, scale = crop_for_ocr(img, (50, 50, 100, 120), pad=8, upscale_below=48, factor=2)
    assert rect == (42, 42, 108, 128) and scale == 1 and crop.size == (66, 86)


def test_crop_clamps_to_image_edges():
    img = Image.new("RGB", (200, 300))
    _, rect, _ = crop_for_ocr(img, (3, 2, 197.5, 296), pad=8, upscale_below=48, factor=2)
    assert rect == (0, 0, 200, 300)


def test_crop_upscales_short_crops():
    img = Image.new("RGB", (200, 300))
    crop, rect, scale = crop_for_ocr(img, (10.4, 100, 60.2, 120), pad=8, upscale_below=48, factor=2)
    assert rect == (2, 92, 69, 128)  # floor/ceil so the crop never cuts into the box
    assert scale == 2 and crop.size == (67 * 2, 36 * 2)
