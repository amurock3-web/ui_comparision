"""Class refiner experiment, step 1 (design.md §18): one feature row per ground-truth box.

    python -m scripts.build_refiner_dataset

Reads the 22-class Label Studio export (config/class_refiner.yaml), remaps to the
16-class taxonomy, OCRs every non-card box crop with the existing OCREngine, and
writes output/class_refiner/features.csv. OCR results are cached in
output/class_refiner/ocr_cache.json, so a rerun only OCRs new crops.

The helpers here (remap, crop, features, OCR cache) are reused by
train_class_refiner.py and compare_yolo_vs_refiner.py, so a YOLO box gets
exactly the same features as a ground-truth box.
"""
import contextlib
import csv
import io
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image

import scripts._test_utils  # noqa: F401  forces UTF-8 stdout (OCR returns Tamil)

CONFIG_PATH = Path("config/class_refiner.yaml")
META_COLUMNS = ["image_id", "box_idx", "label", "x1", "y1", "x2", "y2", "text"]


def load_config(path=CONFIG_PATH):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- labels

def load_corrections(path):
    """image stem -> {1-based label line: 16-class name}. Same file and semantics as the
    detector repo's scripts/remap_labels.py."""
    return {stem: {int(k): v for k, v in (fixes or {}).items()}
            for stem, fixes in (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).items()}


def remap_labels(lines, classes_22, remap, fixes=None):
    """YOLO label lines (22-class ids) -> [(class16, cx, cy, w, h)] normalized.

    Mapped by name, never by index. An unknown class name is a hard error: a
    silent skip would drop boxes. `fixes` = {line number: class16} is applied
    after the remap."""
    unknown = [c for c in classes_22 if c not in remap]
    if unknown:
        raise KeyError(f"classes {unknown} are not in the remap table (config/class_refiner.yaml)")
    fixes = fixes or {}
    out = []
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        cid, *coords = line.split()
        name = fixes.get(lineno, remap[classes_22[int(cid)]])
        out.append((name, *map(float, coords)))
    missing = set(fixes) - {i for i, l in enumerate(lines, 1) if l.strip()}
    if missing:
        raise ValueError(f"corrections point at label lines {sorted(missing)} that do not exist")
    return out


def load_gt(cfg):
    """{image_id: (image_path, [(class16, x1, y1, x2, y2) pixels])} for every labelled image."""
    p = cfg["paths"]
    root = Path(p["export_dir"])
    if not root.is_dir():
        raise SystemExit(f"Label Studio export not found: {root} - fix paths.export_dir in {CONFIG_PATH}")
    classes_22 = [c.strip() for c in (root / p["classes_file"]).read_text().splitlines() if c.strip()]
    corrections = load_corrections(p["corrections_file"]) if p.get("apply_corrections") else {}

    gt = {}
    for label_path in sorted((root / p["labels_subdir"]).glob("*.txt")):
        image_path = root / p["images_subdir"] / f"{label_path.stem}.png"
        W, H = Image.open(image_path).size
        boxes = []
        for name, cx, cy, w, h in remap_labels(label_path.read_text().splitlines(), classes_22,
                                              cfg["remap"], corrections.get(label_path.stem)):
            boxes.append((name, (cx - w / 2) * W, (cy - h / 2) * H, (cx + w / 2) * W, (cy + h / 2) * H))
        gt[label_path.stem] = (image_path, boxes)
    return gt


# ---------------------------------------------------------------- OCR

def crop_for_ocr(image, box, pad, upscale_below, factor):
    """Pad the box, clamp it to the image, upscale if short. Returns (crop, (x1, y1, x2, y2), scale).

    PaddleOCR recognition drops on tiny crops (architecture.md §4a)."""
    W, H = image.size
    x1, y1 = max(0, math.floor(box[0] - pad)), max(0, math.floor(box[1] - pad))
    x2, y2 = min(W, math.ceil(box[2] + pad)), min(H, math.ceil(box[3] + pad))
    crop = image.crop((x1, y1, x2, y2))
    scale = factor if (y2 - y1) < upscale_below else 1
    if scale != 1:
        crop = crop.resize(((x2 - x1) * scale, (y2 - y1) * scale), Image.BICUBIC)
    return crop, (x1, y1, x2, y2), scale


class CachedCropOCR:
    """OCREngine on box crops, cached by image id + crop rectangle + scale."""

    def __init__(self, cfg, cache_path):
        self.cfg = cfg["ocr"]
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
        self._engine = None
        self._tmp = Path(tempfile.mkdtemp(prefix="refiner_ocr_")) / "crop.png"
        self.new = 0

    def read(self, image_id, image, box):
        c = self.cfg
        crop, rect, scale = crop_for_ocr(image, box, c["crop_pad_px"], c["upscale_below_height_px"], c["upscale_factor"])
        key = f"{image_id}:{','.join(map(str, rect))}:x{scale}"
        if key not in self.cache:
            if self._engine is None:
                from src.ocr.engine import OCREngine  # paddle import is slow; only when needed
                self._engine = OCREngine(lang=c["lang"])
            crop.convert("RGB").save(self._tmp)
            with contextlib.redirect_stdout(io.StringIO()):  # OCREngine prints two lines per call
                result = self._engine.run(self._tmp, screen_id=image_id)
            els = sorted(result.elements, key=lambda e: (e.bbox[1], e.bbox[0]))  # reading order
            self.cache[key] = {"text": " ".join(e.text for e in els),
                               "confidence": sum(e.confidence for e in els) / len(els) if els else 0.0}
            self.new += 1
        return self.cache[key]

    def save(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- features

def text_features(text, confidence, cfg):
    o = cfg["ocr"]
    letters = [ch for ch in text if ch.isalpha()]
    stripped = text.strip()
    low = stripped.lower()
    return {
        "text_len": len(stripped),
        "word_count": len(stripped.split()),
        "has_digits": int(any(ch.isdigit() for ch in stripped)),
        "is_empty": int(not stripped),
        "is_int_1_10": int(stripped.isdigit() and 1 <= int(stripped) <= 10),
        "upper_ratio": sum(ch.isupper() for ch in letters) / len(letters) if letters else 0.0,
        "ocr_conf": confidence,
        "re_episode": int(bool(re.search(o["regex"]["episode"], stripped, re.I))),
        "re_duration": int(bool(re.search(o["regex"]["duration"], stripped, re.I))),
        "re_badge": int(any(re.search(rf"\b{re.escape(w)}\b", low) for w in o["badge_words"])),
    }


def box_features(boxes, W, H, texts, cfg):
    """One feature dict per box. `boxes` = [(class16, x1, y1, x2, y2)] pixels on one screen;
    the classes are used only for context (which boxes are cards), never as a feature."""
    ctx = cfg["context"]
    band = ctx["card_band"]
    cards = [i for i, b in enumerate(boxes) if b[0] in cfg["card_classes"]]
    diag = math.hypot(W, H)
    rows = []
    for i, (_, x1, y1, x2, y2) in enumerate(boxes):
        w, h = x2 - x1, y2 - y1
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        f = {"x": x1 / W, "y": y1 / H, "w": w / W, "h": h / H, "cx": cx / W, "cy": cy / H,
             "aspect": w / h if h else 0.0, "area": (w / W) * (h / H)}
        f.update(text_features(*texts[i], cfg))

        # smallest other card that contains this box's center
        holders = [j for j in cards if j != i and boxes[j][1] <= cx <= boxes[j][3] and boxes[j][2] <= cy <= boxes[j][4]
                   and (boxes[j][3] - boxes[j][1]) * (boxes[j][4] - boxes[j][2]) > w * h]
        card = min(holders, key=lambda j: (boxes[j][3] - boxes[j][1]) * (boxes[j][4] - boxes[j][2]), default=None)
        rx = ry = 0.5
        if card is not None:
            _, cx1, cy1, cx2, cy2 = boxes[card]
            rx, ry = (cx - cx1) / (cx2 - cx1), (cy - cy1) / (cy2 - cy1)
        inside = card is not None
        f.update({
            "in_card": int(inside),
            "card_top_left": int(inside and rx < band and ry < band),
            "card_top_right": int(inside and rx > 1 - band and ry < band),
            "card_bottom_left": int(inside and rx < band and ry > 1 - band),
            "card_bottom_right": int(inside and rx > 1 - band and ry > 1 - band),
            "card_bottom": int(inside and ry > 1 - band),
        })

        f["row_count"] = sum(
            1 for j, (_, a1, b1, a2, b2) in enumerate(boxes)
            if j != i and b2 > b1 and h > 0
            and abs((b1 + b2) / 2 - cy) <= ctx["row_center_tol"] * min(h, b2 - b1)
            and max(h, b2 - b1) / min(h, b2 - b1) <= ctx["row_height_ratio"])

        # edge-to-edge distance to the nearest other card, / screen diagonal; 1.5 (> any real
        # distance) when the screen has no other card
        dists = [math.hypot(max(0, boxes[j][1] - x2, x1 - boxes[j][3]), max(0, boxes[j][2] - y2, y1 - boxes[j][4])) / diag
                 for j in cards if j != i]
        f["dist_card"] = min(dists, default=1.5)
        rows.append(f)
    return rows


def screen_rows(image_id, image_path, boxes, ocr, cfg):
    """Feature rows for one screen (meta columns + features). Card boxes are not OCR'd."""
    image = Image.open(image_path)
    texts = []
    for b in boxes:
        r = {"text": "", "confidence": 0.0} if b[0] in cfg["card_classes"] else ocr.read(image_id, image, b[1:])
        texts.append((r["text"], r["confidence"]))
    feats = box_features(boxes, image.width, image.height, texts, cfg)
    return [{"image_id": image_id, "box_idx": i, "label": b[0],
             "x1": round(b[1], 1), "y1": round(b[2], 1), "x2": round(b[3], 1), "y2": round(b[4], 1),
             "text": texts[i][0], **feats[i]} for i, b in enumerate(boxes)]


def main():
    cfg = load_config()
    out_dir = Path(cfg["paths"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    gt = load_gt(cfg)
    ocr = CachedCropOCR(cfg, out_dir / "ocr_cache.json")

    rows = []
    for n, (image_id, (image_path, boxes)) in enumerate(gt.items(), 1):
        rows += screen_rows(image_id, image_path, boxes, ocr, cfg)
        ocr.save()  # after every screen, so an interrupted run keeps its OCR
        print(f"[{n}/{len(gt)}] {image_id}: {len(boxes)} boxes ({ocr.new} new OCR crops so far)")

    with open(out_dir / "features.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["label"] for r in rows)
    excluded = {c: counts.get(c, 0) for c in cfg["exclude_from_training"]}
    print(f"\n{len(rows)} boxes from {len(gt)} images -> {out_dir / 'features.csv'}")
    print("per class:", dict(counts.most_common()))
    print("excluded from training (still in the CSV):", excluded)
    print(f"OCR: {ocr.new} new crops, cache {len(ocr.cache)} -> {ocr.cache_path}")


if __name__ == "__main__":
    main()
