"""Build a benchmark of known defects (docs/test_cases_pass_fail.md, "How to
get fail cases without client data"): each screenshot is the client design,
and edited copies of it are "production" builds with one known defect each.

    python -m scripts.make_benchmark                           # every input/production/* screen
    python -m scripts.make_benchmark input/production/ss031.png

Elements to edit are taken from the screen's newest fusion JSON
(output/fusion/*_<screen>_fusion.json), so run scripts.run_fusion on a screen
first. Output, per screen, in input/benchmark/<screen>/:
  client.png            the untouched screenshot (the design)
  <case>.png            one production build per defect
  manifest.json         per case: the test-case id it should trigger, the
                        edited region (pixels) and what was done

Then score the pipeline on it with scripts.run_benchmark.

Defects (one element each, the first suitable one top-to-bottom that is not
cut off or ignored; a case is skipped when the screen has no such element):
  identity        no change                    -> expect PASS, no findings
  blank_poster    card filled flat dark grey   -> F3 broken image
  remove_element  tab/button/title painted out -> B1 missing element
  shift_title     section title moved 8% right -> C1 position shift
  resize_card     card squashed to 80% width   -> C2 size change
  relabel_title   title text cut to half       -> E1 wrong label text
  swap_tabs       two neighbouring tabs swapped-> B4 tab order
  rotate          whole screen rotated 90      -> A1 orientation
"""
import json
import statistics
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts._test_utils import next_test_number  # noqa: F401  (utf-8 stdout)
from src.schema.ui_element import UIDocument

FUSION_DIR = Path("output/fusion")
BENCH_DIR = Path("input/benchmark")
STATUS_BAR_NORM = 0.04
EDGE_PX = 6


def newest_fusion(screen: str) -> Path:
    candidates = list(FUSION_DIR.glob(f"test*_{screen}_fusion.json"))
    if not candidates:
        raise SystemExit(f"no fusion JSON for {screen!r} in {FUSION_DIR} - "
                         f"run: python -m scripts.run_fusion input/production/<{screen} image>")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def usable(doc, classes, W, H):
    """Elements of these classes, fully on screen, not ignored, top-to-bottom."""
    out = []
    for e in doc.elements:
        if e.class_ not in classes or e.bbox is None or e.metadata.get("ignored"):
            continue
        x, y, w, h = e.bbox
        if x <= EDGE_PX or y <= STATUS_BAR_NORM * H + EDGE_PX or x + w >= W - EDGE_PX or y + h >= H - EDGE_PX:
            continue
        out.append(e)
    return sorted(out, key=lambda e: (e.bbox[1], e.bbox[0]))


def box(e):
    x, y, w, h = e.bbox
    return int(x), int(y), int(x + w), int(y + h)


def ring_color(img, b, width=4):
    """Median colour of a thin ring just outside the box: the background to
    paint over an element with."""
    x1, y1, x2, y2 = b
    px = []
    for x in range(max(0, x1 - width), min(img.width, x2 + width)):
        for y in (max(0, y1 - width), min(img.height - 1, y2 + width)):
            px.append(img.getpixel((x, y)))
    for y in range(max(0, y1), min(img.height, y2)):
        for x in (max(0, x1 - width), min(img.width - 1, x2 + width)):
            px.append(img.getpixel((x, y)))
    return tuple(int(statistics.median(p[i] for p in px)) for i in range(3))


def paint_out(img, b):
    ImageDraw.Draw(img).rectangle(b, fill=ring_color(img, b))


def as_bbox(b):
    return [b[0], b[1], b[2] - b[0], b[3] - b[1]]


# --- defects: (img copy, doc, W, H) -> (img, case dict) or None ----------

def identity(img, doc, W, H):
    return img, {"spec_id": None, "bbox": None, "note": "unchanged copy"}


def blank_poster(img, doc, W, H):
    cards = usable(doc, {"content_card"}, W, H)
    if not cards:
        return None
    b = box(cards[0])
    ImageDraw.Draw(img).rectangle(b, fill=(26, 26, 26))
    return img, {"spec_id": "F3", "bbox": as_bbox(b), "note": f"{cards[0].id} filled flat grey"}


def remove_element(img, doc, W, H):
    for cls in ("tab_item", "button", "section_title"):
        els = usable(doc, {cls}, W, H)
        if els:
            b = box(els[0])
            paint_out(img, b)
            return img, {"spec_id": "B1", "bbox": as_bbox(b),
                         "note": f"{els[0].id} {cls} {els[0].text!r} painted out"}
    return None


def shift_title(img, doc, W, H):
    titles = usable(doc, {"section_title"}, W, H)
    if not titles:
        return None
    b = box(titles[0])
    dx = round(0.08 * W)
    crop = img.crop(b)
    paint_out(img, b)
    img.paste(crop, (b[0] + dx, b[1]))
    return img, {"spec_id": "C1", "bbox": as_bbox(b), "note": f"{titles[0].id} moved {dx}px right"}


def resize_card(img, doc, W, H):
    cards = usable(doc, {"content_card"}, W, H)
    if not cards:
        return None
    b = box(cards[0])
    crop = img.crop(b)
    paint_out(img, b)
    img.paste(crop.resize((round(crop.width * 0.8), crop.height)), (b[0], b[1]))
    return img, {"spec_id": "C2", "bbox": as_bbox(b), "note": f"{cards[0].id} squashed to 80% width"}


def relabel_title(img, doc, W, H):
    titles = [t for t in usable(doc, {"section_title"}, W, H) if t.text and len(t.text) >= 6]
    if not titles:
        return None
    t = titles[0]
    b = box(t)
    crop = img.crop(b).convert("L")
    brightest = max(range(crop.width * crop.height), key=lambda i: crop.getpixel((i % crop.width, i // crop.width)))
    ink = img.getpixel((b[0] + brightest % crop.width, b[1] + brightest // crop.width))
    paint_out(img, b)
    new_text = t.text[: len(t.text) // 2]
    try:
        font = ImageFont.truetype("arialbd.ttf", max(10, int((b[3] - b[1]) * 0.8)))
    except OSError:
        font = ImageFont.load_default()
    ImageDraw.Draw(img).text((b[0], b[1]), new_text, fill=ink, font=font)
    return img, {"spec_id": "E1", "bbox": as_bbox(b), "note": f"{t.id} {t.text!r} -> {new_text!r}"}


def swap_tabs(img, doc, W, H):
    tabs = usable(doc, {"tab_item"}, W, H)
    for a in tabs:
        row = sorted((t for t in tabs if abs(t.bbox[1] - a.bbox[1]) < 12), key=lambda t: t.bbox[0])
        if len(row) >= 2:
            ba, bb = box(row[0]), box(row[1])
            ca, cb = img.crop(ba), img.crop(bb)
            img.paste(cb.resize(ca.size), (ba[0], ba[1]))
            img.paste(ca.resize(cb.size), (bb[0], bb[1]))
            union = [min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3])]
            return img, {"spec_id": "B4", "bbox": as_bbox(union),
                         "note": f"{row[0].id} {row[0].text!r} <-> {row[1].id} {row[1].text!r}"}
    return None


def rotate(img, doc, W, H):
    return img.rotate(90, expand=True), {"spec_id": "A1", "bbox": None, "note": "rotated 90 degrees"}


DEFECTS = [identity, blank_poster, remove_element, shift_title, resize_card,
           relabel_title, swap_tabs, rotate]


def make(image_path: Path):
    screen = image_path.stem
    doc = UIDocument.model_validate_json(newest_fusion(screen).read_text(encoding="utf-8"))
    original = Image.open(image_path).convert("RGB")
    W, H = original.size
    out_dir = BENCH_DIR / screen
    out_dir.mkdir(parents=True, exist_ok=True)
    original.save(out_dir / "client.png")

    cases = []
    for defect in DEFECTS:
        made = defect(original.copy(), doc, W, H)
        if made is None:
            print(f"  {screen}: {defect.__name__} skipped (no suitable element)")
            continue
        img, case = made
        img.save(out_dir / f"{defect.__name__}.png")
        cases.append({"id": defect.__name__, "production": f"{defect.__name__}.png", **case})
        print(f"  {screen}: {defect.__name__:15s} -> {case['spec_id'] or 'PASS'}  {case['note']}")

    manifest = {"screen": screen, "source": str(image_path), "client": "client.png", "cases": cases}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{screen}: {len(cases)} cases -> {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    paths = [Path(a) for a in sys.argv[1:]] or sorted(
        p for p in Path("input/production").iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    for path in paths:
        make(path)
