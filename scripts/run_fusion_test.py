"""Fusion only, same method as main.py: YOLO detector + OCR -> fuse_detections (no VLM).

    python -m scripts.run_fusion_test

The detector's separate interpreter comes from config/detector.yaml's
python_path; set UI_DETECTOR_PYTHON to override it on another machine.
"""
import sys
from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.detector.engine import load_detector
from src.fusion.fuse import FusionEngine
from src.fusion.visualize import draw_fusion_result
from src.ocr.engine import OCREngine

IMAGE_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss031.png")
SCREEN_ID = IMAGE_PATH.stem
OUTPUT_DIR = Path("output/fusion")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_fusion"

detections = load_detector().detect(IMAGE_PATH)
ocr_result = OCREngine(lang="en").run(IMAGE_PATH, screen_id=SCREEN_ID)
ui_doc = FusionEngine().fuse_detections(detections, ocr_result, screen_id=SCREEN_ID, source="production")

ui_doc.save_json(OUTPUT_DIR / f"{PREFIX}.json")
skipped = draw_fusion_result(IMAGE_PATH, ui_doc, OUTPUT_DIR / f"{PREFIX}_visualization.png")

class_counts = Counter(e.class_ for e in ui_doc.elements)
source_counts = Counter(e.source for e in ui_doc.elements)

print(f"\nMethod: YOLO detector ({len(detections)}) + OCR ({len(ocr_result.elements)}) -> fuse_detections, no VLM")
print(f"Elements: {len(ui_doc.elements)}")
print(f"Class breakdown: {dict(class_counts)}")
print(f"Source breakdown: {dict(source_counts)}")
print(f"Uncertain (-> REVIEW): {sum(e.metadata.get('match_status') == 'uncertain' for e in ui_doc.elements)}  "
      f"Ignored (status bar, duplicates): {sum(bool(e.metadata.get('ignored')) for e in ui_doc.elements)}")

print("\nDetector elements with OCR text:")
for e in ui_doc.elements:
    if e.source == "detector" and e.text:
        print(f"  {e.id} {e.class_:14s} {e.confidence:.2f}  {e.text!r}")
print("\nUncertain / ignored:")
for e in ui_doc.elements:
    m = e.metadata
    if m.get("match_status") or m.get("ignored"):
        print(f"  {e.id} {m.get('match_status') or m.get('ignored'):10s} {e.class_} {e.text!r} conf={e.confidence:.2f}")

print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")
