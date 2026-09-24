"""Class refiner experiment, step 3: YOLO class vs refiner class vs truth on YOLO's validation images.

    python -m scripts.compare_yolo_vs_refiner [--model logreg|lightgbm]

Needs features.csv (scripts.build_refiner_dataset) and ultralytics in the detector Python
(UI_DETECTOR_PYTHON or python_path in config/detector.yaml).

- Only YOLO's val split (paths.yolo_val_images_dir): YOLO never trained on these.
- The refiner is retrained here WITHOUT those images.
- The refiner sees what it would see at runtime: features from the YOLO box, its crop OCR,
  and YOLO's own card boxes as context. Not the ground-truth box.
- YOLO boxes are matched to ground truth one-to-one, greedily by IoU >= compare.match_iou.
Writes output/class_refiner/testN_compare_<model>/: yolo_vs_refiner.txt, report.html and its
charts (outcome, accuracy_per_class, confusion_yolo, confusion_refiner .png).
"""
import argparse
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from scripts import _refiner_plots as plots
from scripts._test_utils import next_test_number
from scripts.build_refiner_dataset import CachedCropOCR, box_features, load_config, load_gt
from scripts.train_class_refiner import load_training_data, make_model
from src.detector.engine import YOLODetector, load_detector


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def match(pred_boxes, gt_boxes, threshold):
    """[(pred index, gt index, iou)], one-to-one, highest IoU first."""
    pairs = sorted(((iou(p, g), i, j) for i, p in enumerate(pred_boxes) for j, g in enumerate(gt_boxes)), reverse=True)
    used_p, used_g, out = set(), set(), []
    for v, i, j in pairs:
        if v < threshold:
            break
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append((i, j, v))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=["logreg", "lightgbm"], default="logreg")
    args = ap.parse_args()
    cfg = load_config()

    val_dir = Path(cfg["paths"]["yolo_val_images_dir"])
    val_ids = sorted(p.stem for p in val_dir.glob("*.png")) if val_dir.is_dir() else []
    if not val_ids:
        raise SystemExit(f"YOLO validation split not found at {val_dir} - set paths.yolo_val_images_dir "
                         f"(the images YOLO did not train on) before comparing.")

    detector = load_detector(cfg["paths"]["detector_config"])
    if not isinstance(detector, YOLODetector):
        raise SystemExit(f"{cfg['paths']['detector_config']}: engine must be yolo for this comparison")

    # refiner trained without the val images
    df, features, excluded = load_training_data(cfg, exclude_images=val_ids)
    assert not set(df.image_id) & set(val_ids)
    refiner = make_model(args.model, cfg).fit(df[features].to_numpy(float), df.label.to_numpy())
    print(f"refiner ({args.model}) trained on {df.image_id.nunique()} images, {len(df)} boxes")

    base = Path(cfg["paths"]["output_dir"])
    ocr = CachedCropOCR(cfg, base / "ocr_cache.json")
    gt = load_gt(cfg)
    rows, missed = [], Counter()
    for n, image_id in enumerate(val_ids, 1):
        image_path, gt_boxes = gt[image_id]
        image = Image.open(image_path)
        dets = detector.detect(image_path)
        yolo = [(d.class_, d.bbox[0], d.bbox[1], d.bbox[0] + d.bbox[2], d.bbox[1] + d.bbox[3]) for d in dets]

        texts = []
        for b in yolo:  # OCR skipped on what YOLO calls a card, as it would be at runtime
            r = {"text": "", "confidence": 0.0} if b[0] in cfg["card_classes"] else ocr.read(image_id, image, b[1:])
            texts.append((r["text"], r["confidence"]))
        feats = box_features(yolo, image.width, image.height, texts, cfg)
        X = np.array([[f[k] for k in features] for f in feats], dtype=float)
        proba = refiner.predict_proba(X)

        pairs = match([b[1:] for b in yolo], [b[1:] for b in gt_boxes], cfg["compare"]["match_iou"])
        matched_gt = {j for _, j, _ in pairs}
        missed.update(b[0] for j, b in enumerate(gt_boxes) if j not in matched_gt)
        for i, j, v in pairs:
            k = proba[i].argmax()
            rows.append({"image": image_id, "truth": gt_boxes[j][0], "yolo": yolo[i][0],
                         "yolo_conf": dets[i].confidence, "refiner": refiner.classes_[k],
                         "refiner_p": proba[i][k], "iou": v, "box": [round(c) for c in yolo[i][1:]],
                         "text": texts[i][0]})
        ocr.save()
        print(f"[{n}/{len(val_ids)}] {image_id}: {len(yolo)} YOLO boxes, {len(gt_boxes)} truth, {len(pairs)} matched")

    # --- report
    group = cfg["confusable_group"]
    lines = [
        f"YOLO ({detector.bundle.version}) vs class refiner ({args.model}) on YOLO's {len(val_ids)} validation images",
        f"val images: {', '.join(val_ids)}",
        f"refiner trained on {df.image_id.nunique()} other images ({len(df)} boxes); "
        f"not trained on {sorted(excluded)} (counts in all data: {excluded})",
        f"match: one-to-one, IoU >= {cfg['compare']['match_iou']}; accuracy = share of matched boxes of that "
        f"true class given the right class (= recall on matched boxes)",
        f"truth: 22->16 remap{' + detector-repo label corrections' if cfg['paths'].get('apply_corrections') else ''}",
        "", f"{'class':<16}{'matched':>8}{'YOLO':>8}{'refiner':>9}{'YOLO missed':>13}",
    ]

    def acc_line(sel):
        n = len(sel)
        y = sum(r["yolo"] == r["truth"] for r in sel) / n if n else float("nan")
        f = sum(r["refiner"] == r["truth"] for r in sel) / n if n else float("nan")
        return n, y, f

    for c in sorted({r["truth"] for r in rows} | set(missed)):
        n, y, f = acc_line([r for r in rows if r["truth"] == c])
        mark = " *" if c in group else ("  (refiner not trained)" if c in excluded else "")
        lines.append(f"{c:<16}{n:>8}{y:>8.3f}{f:>9.3f}{missed[c]:>13}{mark}")
    for name, sel in [("confusable *", [r for r in rows if r["truth"] in group]), ("ALL", rows)]:
        n, y, f = acc_line(sel)
        lines.append(f"{name:<16}{n:>8}{y:>8.3f}{f:>9.3f}{'':>13}")

    both_wrong = sum(r["yolo"] != r["truth"] and r["refiner"] != r["truth"] for r in rows)
    fixed = sum(r["yolo"] != r["truth"] and r["refiner"] == r["truth"] for r in rows)
    broke = sum(r["yolo"] == r["truth"] and r["refiner"] != r["truth"] for r in rows)
    lines += ["", f"refiner fixes YOLO: {fixed}   refiner breaks YOLO: {broke}   both wrong: {both_wrong}",
              "", "=== Boxes where YOLO and the refiner disagree ===",
              f"{'image':<7} {'box x1,y1,x2,y2':<22} {'truth':<15} {'YOLO (conf)':<24} {'refiner (p)':<24} text"]
    for r in sorted((r for r in rows if r["yolo"] != r["refiner"]), key=lambda r: (r["image"], r["box"][1])):
        who = "Y" if r["yolo"] == r["truth"] else ("R" if r["refiner"] == r["truth"] else "-")
        lines.append(f"{r['image']:<7} {','.join(map(str, r['box'])):<22} {r['truth']:<15} "
                     f"{'%s (%.2f)' % (r['yolo'], r['yolo_conf']):<24} "
                     f"{'%s (%.2f)' % (r['refiner'], r['refiner_p']):<24} "
                     f"[{who}] {r['text']!r}")
    lines.append("\n[Y] YOLO right, [R] refiner right, [-] both wrong")

    out = base / f"test{next_test_number(base)}_compare_{args.model}"
    out.mkdir(parents=True)
    (out / "yolo_vs_refiner.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- charts + report.html
    classes = sorted({r["truth"] for r in rows})
    stats = {c: acc_line([r for r in rows if r["truth"] == c]) for c in classes}
    order = sorted(classes, key=lambda c: -stats[c][0])
    plots.grouped_bars([f"{c} *" if c in group else c for c in order],
                       {"YOLO": [stats[c][1] for c in order], "refiner": [stats[c][2] for c in order]},
                       f"Correct class on matched boxes, {len(val_ids)} YOLO-val images", out / "accuracy_per_class.png",
                       "accuracy (= recall on matched boxes)", annotate=[f"n={stats[c][0]}" for c in order], group=group)
    preds = sorted(set(classes) | {r["yolo"] for r in rows} | {r["refiner"] for r in rows})
    for who in ("yolo", "refiner"):
        cm = [[sum(r["truth"] == t and r[who] == p for r in rows) for p in preds] for t in classes]
        plots.confusion(cm, classes, preds, f"{'YOLO' if who == 'yolo' else 'Refiner'}: matched boxes",
                        out / f"confusion_{who}.png", group, figsize=(10, 8.5))
    both_right = len(rows) - fixed - broke - both_wrong
    plots.outcome_bar({"both right": both_right, "refiner fixes YOLO": fixed, "refiner breaks YOLO": broke,
                       "both wrong": both_wrong}, "Where the refiner changes the answer", out / "outcome.png")
    _, gy, gr = acc_line([r for r in rows if r["truth"] in group])
    plots.html_report(
        out / "report.html", f"YOLO vs class refiner ({args.model}), {out.name}",
        [("matched boxes", len(rows)), ("YOLO accuracy", f"{acc_line(rows)[1]:.3f}"),
         ("refiner accuracy", f"{acc_line(rows)[2]:.3f}"),
         ("confusable group YOLO / refiner", f"{gy:.3f} / {gr:.3f}"),
         ("button YOLO / refiner", "%.3f / %.3f" % stats["button"][1:] if "button" in stats else "n/a"),
         ("fixes / breaks", f"{fixed} / {broke}")],
        [("outcome.png", "Every matched box: both right, only the refiner right, only YOLO right, both wrong."),
         ("accuracy_per_class.png", "Share of each true class that got the right class; * = confusable group."),
         ("confusion_yolo.png", "YOLO's class vs truth on the same matched boxes."),
         ("confusion_refiner.png", "Refiner's class vs truth on the same matched boxes.")],
        [("Per class", ["class", "matched", "YOLO", "refiner", "YOLO missed (no box)"],
          [[c + (" *" if c in group else ""), stats[c][0], f"{stats[c][1]:.3f}", f"{stats[c][2]:.3f}", missed[c]]
           for c in order]),
         ("Boxes where YOLO and the refiner disagree ([Y] YOLO right, [R] refiner right, [-] both wrong)",
          ["image", "box", "truth", "YOLO (conf)", "refiner (p)", "who", "OCR text"],
          [[r["image"], ",".join(map(str, r["box"])), r["truth"], "%s (%.2f)" % (r["yolo"], r["yolo_conf"]),
            "%s (%.2f)" % (r["refiner"], r["refiner_p"]),
            "Y" if r["yolo"] == r["truth"] else ("R" if r["refiner"] == r["truth"] else "-"), r["text"]]
           for r in sorted((r for r in rows if r["yolo"] != r["refiner"]), key=lambda r: (r["image"], r["box"][1]))])])

    print("\n".join(lines[:lines.index("=== Boxes where YOLO and the refiner disagree ===")]))
    print(f"\nsaved to {out / 'yolo_vs_refiner.txt'}")


if __name__ == "__main__":
    main()
