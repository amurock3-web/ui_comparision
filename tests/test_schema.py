# Tests for src/schema/ui_element.py — schema validation (rules.md §14).

import pytest
from pydantic import ValidationError

from src.schema.ui_element import ALLOWED_CLASSES, UIDocument, UIElement


def _base_kwargs(**overrides):
    kwargs = dict(
        id="el_0001",
        text="Free",
        bbox=[10.0, 20.0, 30.0, 40.0],
        normalized_bbox=[0.01, 0.02, 0.03, 0.04],
        center=[25.0, 40.0],
        confidence=0.9,
        confidence_tier="high",
        source="fused",
    )
    kwargs.update(overrides)
    return kwargs


def test_class_optional():
    el = UIElement(**_base_kwargs())
    assert el.class_ is None
    assert el.text == "Free"


def test_class_alias_accepted():
    el = UIElement(**_base_kwargs(**{"class": "overlay_badge"}))
    assert el.class_ == "overlay_badge"


def test_class_must_be_in_taxonomy():
    with pytest.raises(ValidationError):
        UIElement(**_base_kwargs(**{"class": "not_a_real_class"}))


def test_bbox_must_have_four_values():
    with pytest.raises(ValidationError):
        UIElement(**_base_kwargs(bbox=[1.0, 2.0, 3.0]))


def test_bbox_normalized_bbox_center_optional():
    # fusion's classify-only VLM design (fuse.py) produces elements with
    # no geometry at all when there's no OCR text match and no grid rule
    # (e.g. an "icon" classification) — these must be valid, not dropped.
    el = UIElement(**_base_kwargs(bbox=None, normalized_bbox=None, center=None))
    assert el.bbox is None
    assert el.normalized_bbox is None
    assert el.center is None


def test_center_must_have_two_values():
    with pytest.raises(ValidationError):
        UIElement(**_base_kwargs(center=[1.0]))


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        UIElement(**_base_kwargs(confidence=1.5))


def test_all_taxonomy_classes_valid():
    for cls in ALLOWED_CLASSES:
        el = UIElement(**_base_kwargs(**{"class": cls}))
        assert el.class_ == cls


def test_ui_document_to_dict_uses_class_alias():
    el = UIElement(**_base_kwargs(**{"class": "button"}))
    doc = UIDocument(screen_id="ss012", source="production", image_width=1080, image_height=2400, elements=[el])
    data = doc.to_dict()
    assert data["elements"][0]["class"] == "button"
    assert "class_" not in data["elements"][0]


def test_ui_document_save_json(tmp_path):
    el = UIElement(**_base_kwargs())
    doc = UIDocument(screen_id="ss012", source="production", image_width=1080, image_height=2400, elements=[el])
    out = tmp_path / "doc.json"
    doc.save_json(out)
    assert out.exists()
    assert "ss012" in out.read_text(encoding="utf-8")
