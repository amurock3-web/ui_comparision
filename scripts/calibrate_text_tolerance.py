"""Measure how far PaddleOCR drifts from the app's real on-screen strings.

`differ.py`'s E1 check calls a text mismatch REVIEW when the two sides are
within one edit and FAIL otherwise. That "one" was a design-doc guess
(config.yaml's header says the thresholds are not experimentally calibrated).
This script replaces the guess with a measurement.

The oracle is `uiautomator dump` XML from the SunNXT APK analysis: a live view
hierarchy whose TextView nodes carry the literal string the app rendered, plus
exact pixel bounds. Running OCR over the same screenshots and pairing detections
to those nodes by geometry gives the real OCR edit-distance distribution.

Static chrome (tabs, section titles, buttons) is reported separately from
dynamic content (poster titles over artwork), because only the static classes
are text-compared at all under E1/§H — and stylised text on posters is expected
to OCR far worse without that mattering.

Run:  python -m scripts.calibrate_text_tolerance
"""
import collections
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from src.comparison.matcher import _normalize_text
from src.ocr.engine import OCRElement, OCREngine

METADATA = Path(r"C:\Users\pralhadraj.joshi\Documents\SunNXT-UI-Metadata")
XML_DIR = METADATA / "apk_analysis" / "window_xml"
IMAGE_DIR = METADATA / "dataset" / "renamed" / "images"
CACHE_DIR = Path("output/ocr/calibration")

# resource-ids whose text is fixed app chrome, i.e. the E1 static classes.
# Everything else (poster titles, metadata rows) is dynamic content under §H.
STATIC_ID = re.compile(r"tabContent|tabs_more|textview_genre_title|btn_|fab_|search", re.I)


def xml_text_nodes(path: Path):
    """(text, [x1,y1,x2,y2], resource_id) for every node carrying a string."""
    out = []
    for node in ET.parse(path).getroot().iter("node"):
        text = (node.get("text") or "").strip()
        if not text:
            continue
        nums = [int(n) for n in re.findall(r"-?\d+", node.get("bounds", ""))]
        if len(nums) == 4:
            out.append((text, nums, node.get("resource-id", "")))
    return out


def edit_distance(a: str, b: str) -> int:
    """Levenshtein. Short UI labels, so the plain O(len(a)*len(b)) DP is fine."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def best_ocr_match(node_box, ocr_elements):
    """OCR element whose center sits inside the node box, largest overlap wins.

    Center-containment rather than IoU because a TextView's bounds include the
    view's padding while OCR boxes hug the glyphs — the two rarely overlap
    enough for an IoU threshold to be meaningful.
    """
    x1, y1, x2, y2 = node_box
    best, best_area = None, 0
    for el in ocr_elements:
        if not el.bbox:
            continue
        ex, ey, ew, eh = el.bbox
        cx, cy = ex + ew / 2, ey + eh / 2
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        overlap = max(0, min(x2, ex + ew) - max(x1, ex)) * max(0, min(y2, ey + eh) - max(y1, ey))
        if overlap > best_area:
            best, best_area = el, overlap
    return best


def main():
    # App strings contain ₹ and Tamil script; the Windows console is cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    engine = OCREngine(lang="en")
    rows = []

    for xml_path in sorted(XML_DIR.glob("*_window.xml")):
        screen = xml_path.name.replace("_window.xml", "")
        image = IMAGE_DIR / f"{screen}.png"
        if not image.exists():
            print(f"  ! {screen}: no screenshot, skipped")
            continue

        cache = CACHE_DIR / f"{screen}_ocr.json"
        if cache.exists():
            # OCRResult is a plain dataclass, so rebuild the elements we need
            # from the saved dict rather than deserialising the whole result.
            saved = json.loads(cache.read_text(encoding="utf-8"))
            elements = [OCRElement(**e) for e in saved["elements"]]
            print(f"  {screen}: OCR from cache ({len(elements)} elements)")
        else:
            print(f"  {screen}: running OCR ...", flush=True)
            result = engine.run(image, screen_id=screen)
            result.save_json(cache)
            elements = result.elements
            print(f"  {screen}: {len(elements)} elements in {result.inference_time_seconds:.1f}s")

        for truth, box, res_id in xml_text_nodes(xml_path):
            match = best_ocr_match(box, elements)
            t, o = _normalize_text(truth), _normalize_text(match.text if match else "")
            distance = None if match is None else edit_distance(t, o)
            rows.append({
                "screen": screen,
                "static": bool(STATIC_ID.search(res_id)),
                "truth": truth,
                "ocr": match.text if match else None,
                "distance": distance,
                "status": classify(t, o, distance),
                "confidence": match.confidence if match else None,
            })

    report(rows)


def classify(truth: str, ocr: str, distance):
    """Split genuine OCR slips from XML nodes that were never on screen.

    `uiautomator dump` has no visibility flag and reports views that are laid
    out but not drawn — the app keeps its floating tab bar in the hierarchy at
    fixed bounds on every screen, so a node's bounds can land on completely
    unrelated pixels. Those must not be counted as OCR errors: on ss017 the
    hidden "Live TV" tab sits exactly over "Version : 4.1.110", which would
    otherwise register as a 15-edit OCR failure.

    A match further apart than half the longer string is unrelated text, not a
    misread of it.
    """
    if distance is None:
        return "absent"       # nothing at those bounds — hidden node, or OCR miss
    if distance == 0:
        return "exact"
    return "slip" if distance <= max(len(truth), len(ocr)) / 2 else "stale"


def report(rows):
    for label, subset in (("STATIC CHROME (E1-compared)", [r for r in rows if r["static"]]),
                          ("DYNAMIC CONTENT (ignored under H)", [r for r in rows if not r["static"]])):
        counts = collections.Counter(r["status"] for r in subset)
        usable = [r for r in subset if r["status"] in ("exact", "slip")]
        print(f"\n{'=' * 70}\n{label}: {len(subset)} XML strings\n{'=' * 70}")
        print(f"  exact={counts['exact']}  slip={counts['slip']}  "
              f"stale={counts['stale']}  absent={counts['absent']}")
        print("  (stale/absent = node not visible on screen; excluded from the rate)")
        if not usable:
            continue

        hist = collections.Counter(r["distance"] for r in usable)
        running = 0
        for d in sorted(hist):
            running += hist[d]
            print(f"  edit distance {d}: {hist[d]:3d}   (<= {d}: {running / len(usable):.1%})")
        for r in sorted((r for r in usable if r["distance"]), key=lambda r: -r["distance"])[:6]:
            print(f"    slip d={r['distance']}  {r['truth']!r} -> {r['ocr']!r}  conf={r['confidence']:.2f}")
        for r in (r for r in subset if r["status"] == "stale"):
            print(f"    stale  [{r['screen']}] {r['truth']!r} sits over {r['ocr']!r}")


def _self_check():
    """Runs without OCR: `python -m scripts.calibrate_text_tolerance --check`."""
    assert edit_distance("free", "free") == 0
    assert edit_distance("free", "fre") == 1          # deletion
    assert edit_distance("free", "frees") == 1        # insertion
    assert edit_distance("free", "frce") == 1         # substitution
    assert edit_distance("live tv", "livetv") == 1    # lost space
    assert edit_distance("", "abc") == 3

    Box = collections.namedtuple("Box", "bbox text confidence")
    node = [100, 100, 200, 140]
    inside = Box([110, 105, 60, 30], "in", 0.9)       # center (140, 120) -> inside
    outside = Box([300, 300, 60, 30], "out", 0.9)     # far away
    bigger = Box([105, 102, 90, 36], "bigger", 0.9)   # inside too, more overlap
    assert best_ocr_match(node, [outside]) is None
    assert best_ocr_match(node, [inside, outside]).text == "in"
    assert best_ocr_match(node, [inside, bigger]).text == "bigger"
    assert best_ocr_match(node, [Box(None, "no bbox", 0.9)]) is None

    assert classify("free", "free", 0) == "exact"
    assert classify("downloads", "downlods", 1) == "slip"      # real OCR miss
    assert classify("live tv", "version : 4.1.110", 15) == "stale"  # hidden tab bar
    assert classify("free", "comedy", 5) == "stale"
    assert classify("free", "", None) == "absent"
    print("self-check OK")


if __name__ == "__main__":
    import sys
    _self_check() if "--check" in sys.argv else main()
