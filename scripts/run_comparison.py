import argparse
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from scripts._test_utils import next_test_number
from src.baselines import infer_device, load_baseline
from src.pipeline import build_document, compare_documents

# The pair to diff, as two command-line arguments or the defaults below.
# Screen ids follow the file names, so only the paths need changing.
# Same detector-first fusion as main.py (no VLM), graphed with the
# layout-tree builder (src/graph/layout.py) - see src/pipeline.py.
#   python -m scripts.run_comparison [production.png] [client.png]
#   python -m scripts.run_comparison production.png --baseline <screen>[/<device>/<language>]
# --baseline takes the client from baselines/ (scripts.add_baseline), so only
# production goes through detector + OCR (~45 s instead of ~90 s).
#
# Output, per run, in output/comparison/:
#   testN_<screen>_comparison.json   every difference (MATCH included)
#   testN_<screen>_report.json       verdict, findings, coverage, confidence
#   testN_<screen>_report.html       the page to read (self-contained)
#   testN_<screen>_report.png        side-by-side image used in the page
#   testN_<screen>_{production,client}_fused.json   the fused UIDocuments, so
#       scripts.rematch can redo matching/differ/report without the ~90s pass
parser = argparse.ArgumentParser(description="Compare a production screenshot with a client design.")
parser.add_argument("production", type=Path, nargs="?", default=Path("input/production/ss012.png"))
parser.add_argument("client", type=Path, nargs="?", default=Path("input/client/ss012.png"))
parser.add_argument("--baseline", help="stored client baseline key: screen[/device/language]")
args = parser.parse_args()

PRODUCTION_IMAGE = args.production
PRODUCTION_SCREEN_ID = PRODUCTION_IMAGE.stem

if args.baseline:
    try:
        with Image.open(PRODUCTION_IMAGE) as im:  # a screen-only key picks the matching device
            baseline = load_baseline(args.baseline, device=infer_device(*im.size))
    except (LookupError, RuntimeError, FileNotFoundError) as e:
        sys.exit(str(e))
    client_doc, CLIENT_IMAGE = baseline.doc, baseline.image
    print(f"Client baseline: {baseline.key} (created {baseline.meta.get('created')})")
else:
    CLIENT_IMAGE = args.client

OUTPUT_DIR = Path("output/comparison")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

N = next_test_number(OUTPUT_DIR)
PREFIX = f"test{N}_{PRODUCTION_SCREEN_ID}"

production_doc, _ = build_document(PRODUCTION_IMAGE, PRODUCTION_SCREEN_ID, "production")
if not args.baseline:
    client_doc, _ = build_document(CLIENT_IMAGE, CLIENT_IMAGE.stem, "client")

production_doc.save_json(OUTPUT_DIR / f"{PREFIX}_production_fused.json")
client_doc.save_json(OUTPUT_DIR / f"{PREFIX}_client_fused.json")

result = compare_documents(production_doc, client_doc, PRODUCTION_IMAGE, CLIENT_IMAGE, OUTPUT_DIR, PREFIX)
report, match_result = result["report"], result["match_result"]
type_counts = Counter(d.type for d in result["differences"])

print(f"Production elements: {len(production_doc.elements)}")
print(f"Client elements: {len(client_doc.elements)}")
print(f"Matches: {len(match_result.matches)}")
print(f"Unmatched production: {len(match_result.unmatched_production)}")
print(f"Unmatched client: {len(match_result.unmatched_client)}")
print(f"Difference breakdown: {dict(type_counts)}")
print(f"Verdict: {report['verdict']}  similarity {report['similarity_percent']}%")

print(f"\nDifferences JSON saved to: {result['comparison_path']}")
print(f"Report JSON saved to:      {result['report_path']}")
print(f"HTML report saved to:      {result['html_path']}")
print("Fused documents (feed these to scripts.rematch):")
print(f"  {OUTPUT_DIR / f'{PREFIX}_production_fused.json'}")
print(f"  {OUTPUT_DIR / f'{PREFIX}_client_fused.json'}")
