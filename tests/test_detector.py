# Tests for src/detector/engine.py — the model bundle from
# UI_Detection_model_training. The GT stub tests need only the bundle's text
# files (committed); the YOLO test also needs best.pt (not in git) and a
# Python with ultralytics named by UI_DETECTOR_PYTHON, and skips otherwise.

import json
import os
import shutil
from pathlib import Path

import pytest

from src.detector.engine import Bundle, GTStubDetector, YOLODetector, load_detector

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "models" / "ui16_v1"
TIERS = {"confidence_high": 0.7, "confidence_medium": 0.4}


def test_bundle_matches_taxonomy():
    b = Bundle(BUNDLE)
    assert b.version == "ui16_v1"
    assert b.classes[0] == "content_card" and len(b.classes) == 16
    assert {"rank_number", "text_input", "logo"} <= b.low_confidence


def test_swapped_class_order_is_rejected(tmp_path):
    bad = tmp_path / "ui16_v1"
    shutil.copytree(BUNDLE, bad, ignore=shutil.ignore_patterns("*.pt"))
    names = (bad / "classes_16.txt").read_text().split()
    names[5], names[9] = names[9], names[5]
    (bad / "classes_16.txt").write_text("\n".join(names) + "\n")
    with pytest.raises(ValueError, match="taxonomy mismatch"):
        Bundle(bad)


def test_gt_stub_replays_hand_labels():
    det = GTStubDetector(Bundle(BUNDLE), **TIERS)
    raw = json.loads((BUNDLE / "gt_detections.json").read_text())["ss012.png"]
    elements = det.detect(Path("input/client/ss012.png"))  # looked up by file name

    assert len(elements) == len(raw["detections"]) > 0
    first, want = elements[0], raw["detections"][0]
    assert first.class_ == want["cls_name"]
    assert first.bbox == want["bbox"]
    assert first.source == "detector"
    assert first.confidence == 1.0 and first.confidence_tier == "high"
    x, y, w, h = first.bbox
    assert first.center == [x + w / 2, y + h / 2]
    assert first.normalized_bbox[2] == pytest.approx(w / raw["image_width"])
    assert first.metadata["detector_engine"] == "gt_stub"
    assert first.metadata["detector_version"] == "ui16_v1"


def test_gt_stub_unknown_image_is_loud():
    det = GTStubDetector(Bundle(BUNDLE), **TIERS)
    with pytest.raises(KeyError, match="no hand labels"):
        det.detect(Path("never_labelled.png"))


def test_load_detector_default_is_gt_stub():
    assert isinstance(load_detector(), GTStubDetector)


def test_yolo_without_python_env_var_is_loud(tmp_path, monkeypatch):
    cfg = tmp_path / "detector.yaml"
    cfg.write_text("engine: yolo\nbundle: models/ui16_v1\n"
                   "python_env_var: UI_DETECTOR_PYTHON_TEST_UNSET\n"
                   "confidence_high: 0.7\nconfidence_medium: 0.4\n")
    monkeypatch.delenv("UI_DETECTOR_PYTHON_TEST_UNSET", raising=False)
    with pytest.raises(RuntimeError, match="UI_DETECTOR_PYTHON_TEST_UNSET"):
        load_detector(cfg)


@pytest.mark.skipif(not (BUNDLE / "best.pt").exists() or not os.environ.get("UI_DETECTOR_PYTHON"),
                    reason="needs best.pt and UI_DETECTOR_PYTHON")
def test_yolo_matches_gt_shape_on_real_screen():
    image = ROOT / "input" / "client" / "ss012.png"
    det = YOLODetector(Bundle(BUNDLE), os.environ["UI_DETECTOR_PYTHON"], **TIERS)
    elements = det.detect(image)
    assert elements, "real model found nothing on a labelled screen"
    assert all(e.source == "detector" and e.metadata["detector_engine"] == "yolo" for e in elements)
    classes = {e.class_ for e in elements}
    assert "content_card" in classes
