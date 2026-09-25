"""
One screenshot -> fused UIDocument + layout graph: detector, OCR,
detector-first fusion (no VLM), LayoutGraphBuilder. The path
scripts/run_comparison.py and scripts/run_benchmark.py share.

The detector and OCR engines are built once per process: OCR model load
dominates a single screen, and the benchmark runs dozens of screens.
"""

import json
from dataclasses import asdict
from functools import cache
from pathlib import Path

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.detector.engine import load_detector
from src.fusion.fuse import FusionEngine
from src.graph.layout import LayoutGraphBuilder
from src.ocr.engine import OCREngine
from src.reporting.html_report import write_html_report
from src.reporting.report import ReportGenerator


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


def compare_documents(production_doc, client_doc, production_image, client_image, out_dir: Path,
                      prefix: str, rules=None, match_level=None) -> dict:
    """Two fused UIDocuments -> matcher -> differ -> report, written to out_dir as
    <prefix>_comparison.json, <prefix>_report.json and <prefix>_report.html (+ .png).
    The graph-onwards half of run_comparison, shared by run_batch and --baseline;
    scripts/rematch.py runs the same chain inline. Returns the report plus the
    intermediate results and paths the callers print."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    production_graph = LayoutGraphBuilder().build(production_doc)
    client_graph = LayoutGraphBuilder().build(client_doc)
    match_result = ElementMatcher().match(production_doc, client_doc, production_graph, client_graph)
    differences = DifferenceEngine(rules_path=rules, match_level=match_level).compare(
        production_doc, client_doc, production_graph, client_graph, match_result,
        production_image=production_image, client_image=client_image,
    )
    comparison_path = out_dir / f"{prefix}_comparison.json"
    comparison_path.write_text(json.dumps([asdict(d) for d in differences], indent=2, ensure_ascii=False),
                               encoding="utf-8")
    report = ReportGenerator().generate(production_doc, client_doc, differences)
    report_path = out_dir / f"{prefix}_report.json"
    ReportGenerator.save_json(report, report_path)
    html_path = write_html_report(report, production_image, client_image, production_doc, client_doc,
                                  differences, out_dir / f"{prefix}_report.html",
                                  production_graph, client_graph)
    return {"report": report, "differences": differences, "match_result": match_result,
            "comparison_path": comparison_path, "report_path": report_path, "html_path": html_path}
