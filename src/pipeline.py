"""
One screenshot -> fused UIDocument + layout graph: detector, OCR,
detector-first fusion (no VLM), LayoutGraphBuilder. The path
scripts/run_comparison.py and scripts/run_benchmark.py share.

The detector and OCR engines are built once per process: OCR model load
dominates a single screen, and the benchmark runs dozens of screens.
"""

from functools import cache
from pathlib import Path

from src.detector.engine import load_detector
from src.fusion.fuse import FusionEngine
from src.graph.layout import LayoutGraphBuilder
from src.ocr.engine import OCREngine


@cache
def _engines():
    return load_detector(), OCREngine(lang="en")


def build_document(image_path: Path, screen_id: str, source: str, on_stage=lambda name: None):
    """on_stage(name) is called before each step - the UI's progress bar (src/app.py)."""
    on_stage(f"Detector ({source})")
    detector, ocr = _engines()
    detections = detector.detect(image_path)
    on_stage(f"OCR ({source})")
    ocr_result = ocr.run(image_path, screen_id=screen_id)
    on_stage(f"Fusion ({source})")
    ui_doc = FusionEngine().fuse_detections(detections, ocr_result, screen_id=screen_id, source=source)
    on_stage(f"Graph ({source})")
    return ui_doc, LayoutGraphBuilder().build(ui_doc)
