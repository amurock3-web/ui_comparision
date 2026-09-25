"""
UI element detector — the model bundle from UI_Detection_model_training.

Two engines behind one `detect(image_path) -> list[UIElement]` call:

- GTStubDetector replays the bundle's gt_detections.json (hand labels,
  confidence 1.0). It is a perfect detector, so a bug seen while using it is
  a pipeline bug, never a detection error. It only knows the labelled
  screenshots, looked up by file name.
- YOLODetector runs best.pt. ultralytics/torch must not share an environment
  with paddlepaddle-gpu, so the model runs in a separate Python
  (yolo_worker.py) and hands back JSON in the same shape as the stub.

Both check the bundle's class order against config/classes.json when they
are created. A silent order mismatch would give plausible but wrong reports,
so it raises instead.

Classes the bundle lists as low_confidence_classes (too few training
examples) are tagged metadata.low_confidence_class=True so callers can defer
them to the VLM.
"""

import json
import os
import subprocess
from pathlib import Path

import yaml

from src.schema.ui_element import ALLOWED_CLASSES, UIElement

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "detector.yaml"
CLASSES_PATH = ROOT / "config" / "classes.json"
WORKER = Path(__file__).resolve().parent / "yolo_worker.py"


class Bundle:
    """A verified model bundle folder (best.pt, model_card.json, classes_16.txt, gt_detections.json)."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            self.path = ROOT / self.path
        self.classes = (self.path / "classes_16.txt").read_text().split()
        self.card = json.loads((self.path / "model_card.json").read_text())

        expected = json.loads(CLASSES_PATH.read_text())["classes"]
        if self.classes != expected:
            raise ValueError(f"taxonomy mismatch: bundle {self.path.name} has "
                             f"{self.classes}, config/classes.json has {expected}")
        if self.card.get("classes") != self.classes:
            raise ValueError(f"{self.path.name}: model_card.json classes differ from classes_16.txt")
        self.version = self.card["version"]
        self.low_confidence = set(self.card.get("low_confidence_classes", []))


class _Detector:
    def __init__(self, bundle: Bundle, confidence_high: float, confidence_medium: float):
        self.bundle = bundle
        self.confidence_high = confidence_high
        self.confidence_medium = confidence_medium

    def _tier(self, score):
        if score >= self.confidence_high:
            return "high"
        if score >= self.confidence_medium:
            return "medium"
        return "low"

    def _to_elements(self, entry, engine_name):
        W, H = entry["image_width"], entry["image_height"]
        elements = []
        for i, d in enumerate(entry["detections"]):
            name = self.bundle.classes[d["cls_id"]]
            if name != d["cls_name"] or name not in ALLOWED_CLASSES:
                raise ValueError(f"detection {i}: cls_id {d['cls_id']} is {name!r}, "
                                 f"but cls_name says {d['cls_name']!r}")
            x, y, w, h = d["bbox"]
            elements.append(UIElement(
                id=f"det_{i:03d}",
                class_=name,
                bbox=[x, y, w, h],
                normalized_bbox=[x / W, y / H, w / W, h / H],
                center=[x + w / 2, y + h / 2],
                confidence=d["confidence"],
                confidence_tier=self._tier(d["confidence"]),
                source="detector",
                metadata={
                    "bbox_source": "detector",
                    "detector_engine": engine_name,
                    "detector_version": self.bundle.version,
                    "low_confidence_class": name in self.bundle.low_confidence,
                },
            ))
        return elements


class GTStubDetector(_Detector):
    def __init__(self, bundle, **tiers):
        super().__init__(bundle, **tiers)
        self.gt = json.loads((bundle.path / "gt_detections.json").read_text())

    def detect(self, image_path) -> list[UIElement]:
        name = Path(image_path).name
        if name not in self.gt:
            raise KeyError(f"{name} has no hand labels in {self.bundle.path.name}/gt_detections.json "
                           f"- the GT stub only knows the labelled screenshots")
        return self._to_elements(self.gt[name], "gt_stub")


class YOLODetector(_Detector):
    def __init__(self, bundle, python, **tiers):
        super().__init__(bundle, **tiers)
        if not (bundle.path / "best.pt").is_file():
            raise FileNotFoundError(f"{bundle.path / 'best.pt'} missing - weights are not in git, "
                                    f"copy them from UI_Detection_model_training/models/")
        self.python = python

    def detect(self, image_path) -> list[UIElement]:
        r = subprocess.run([self.python, str(WORKER), "--bundle", str(self.bundle.path),
                            "--image", str(image_path)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"yolo_worker failed ({r.returncode}):\n{r.stderr or r.stdout}")
        return self._to_elements(json.loads(r.stdout.strip().splitlines()[-1]), "yolo")


def load_detector(config_path=DEFAULT_CONFIG_PATH):
    """The detector named by config/detector.yaml's `engine`."""
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    bundle = Bundle(cfg["bundle"])
    tiers = {"confidence_high": cfg["confidence_high"],
             "confidence_medium": cfg["confidence_medium"]}
    if cfg["engine"] == "gt_stub":
        return GTStubDetector(bundle, **tiers)
    if cfg["engine"] == "yolo":
        # The environment variable wins, so the Linux/GPU box can point at its
        # own interpreter without editing config; python_path is the checked-in
        # fallback that lets the scripts run with no shell setup.
        python = os.environ.get(cfg["python_env_var"]) or cfg.get("python_path")
        if not python:
            raise RuntimeError(f"set {cfg['python_env_var']} to a Python that has ultralytics "
                               f"(not this paddle environment), or give python_path in "
                               f"config/detector.yaml")
        if not Path(python).is_file():
            raise FileNotFoundError(f"detector Python {python!r} does not exist - set "
                                    f"{cfg['python_env_var']} or fix python_path in "
                                    f"config/detector.yaml")
        return YOLODetector(bundle, python, **tiers)
    raise ValueError(f"config/detector.yaml: unknown engine {cfg['engine']!r} (gt_stub or yolo)")
