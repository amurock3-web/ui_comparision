import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from scripts._test_utils import next_test_number
from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.pipeline import build_document
from src.reporting.html_report import write_html_report
from src.reporting.report import ReportGenerator

# The pair to diff, as two command-line arguments or the defaults below.
# Screen ids follow the file names, so only the paths need changing.
# Same detector-first fusion as main.py (no VLM), graphed with the
# layout-tree builder (src/graph/layout.py) - see src/pipeline.py.
#   python -m scripts.run_comparison [production.png] [client.png]
#
# Output, per run, in output/comparison/:
#   testN_<screen>_comparison.json   every difference (MATCH included)
#   testN_<screen>_report.json       verdict, findings, coverage, confidence
#   testN_<screen>_report.html       the page to read (self-contained)
#   testN_<screen>_report.png        side-by-side image used in the page
#   testN_<screen>_{production,client}_fused.json   the fused UIDocuments, so
#       scripts.rematch can redo matching/differ/report without the ~90s pass
PRODUCTION_IMAGE = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
CLIENT_IMAGE = Path(sys.argv[2] if len(sys.argv) > 2 else "input/client/ss012.png")
PRODUCTION_SCREEN_ID = PRODUCTION_IMAGE.stem
CLIENT_SCREEN_ID = CLIENT_IMAGE.stem

OUTPUT_DIR = Path("output/comparison")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

N = next_test_number(OUTPUT_DIR)
PREFIX = f"test{N}_{PRODUCTION_SCREEN_ID}_comparison"
REPORT_PREFIX = f"test{N}_{PRODUCTION_SCREEN_ID}_report"

production_doc, production_graph = build_document(PRODUCTION_IMAGE, PRODUCTION_SCREEN_ID, "production")
client_doc, client_graph = build_document(CLIENT_IMAGE, CLIENT_SCREEN_ID, "client")

production_doc.save_json(OUTPUT_DIR / f"test{N}_{PRODUCTION_SCREEN_ID}_production_fused.json")
client_doc.save_json(OUTPUT_DIR / f"test{N}_{PRODUCTION_SCREEN_ID}_client_fused.json")

match_result = ElementMatcher().match(production_doc, client_doc, production_graph, client_graph)
differences = DifferenceEngine().compare(
    production_doc, client_doc, production_graph, client_graph, match_result,
    production_image=PRODUCTION_IMAGE, client_image=CLIENT_IMAGE,
)

(OUTPUT_DIR / f"{PREFIX}.json").write_text(
    json.dumps([asdict(d) for d in differences], indent=2, ensure_ascii=False),
    encoding="utf-8",
)
report = ReportGenerator().generate(production_doc, client_doc, differences)
ReportGenerator.save_json(report, OUTPUT_DIR / f"{REPORT_PREFIX}.json")
html_path = write_html_report(report, PRODUCTION_IMAGE, CLIENT_IMAGE, production_doc, client_doc,
                              differences, OUTPUT_DIR / f"{REPORT_PREFIX}.html",
                              production_graph, client_graph)

type_counts = Counter(d.type for d in differences)

print(f"Production elements: {len(production_doc.elements)}")
print(f"Client elements: {len(client_doc.elements)}")
print(f"Matches: {len(match_result.matches)}")
print(f"Unmatched production: {len(match_result.unmatched_production)}")
print(f"Unmatched client: {len(match_result.unmatched_client)}")
print(f"Difference breakdown: {dict(type_counts)}")
print(f"Verdict: {report['verdict']}  similarity {report['similarity_percent']}%")

print(f"\nDifferences JSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Report JSON saved to:      {OUTPUT_DIR / f'{REPORT_PREFIX}.json'}")
print(f"HTML report saved to:      {html_path}")
print("Fused documents (feed these to scripts.rematch):")
print(f"  {OUTPUT_DIR / f'test{N}_{PRODUCTION_SCREEN_ID}_production_fused.json'}")
print(f"  {OUTPUT_DIR / f'test{N}_{PRODUCTION_SCREEN_ID}_client_fused.json'}")
