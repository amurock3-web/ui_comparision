"""Run the bundle's YOLO model on one image and print detections as JSON.

Runs in the detector's own Python (ultralytics + torch), never in the
paddle environment — src/detector/engine.py launches it as a subprocess.
Standalone on purpose: imports nothing from src/.

    python src/detector/yolo_worker.py --bundle models/ui16_v1 --image input/client/ss012.png

Output shape is exactly one entry of the bundle's gt_detections.json:
{"image_width", "image_height", "detections": [{cls_id, cls_name, bbox, confidence}]}
with bbox = [x, y, w, h] pixels, top-left origin.
"""
from pathlib import Path
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--image", type=Path, required=True)
    args = ap.parse_args()

    names = (args.bundle / "classes_16.txt").read_text().split()
    card = json.loads((args.bundle / "model_card.json").read_text())

    from ultralytics import YOLO
    model = YOLO(str(args.bundle / "best.pt"))
    model_names = [model.names[i] for i in range(len(model.names))]
    if model_names != names:
        sys.exit(f"taxonomy mismatch: model {model_names} != classes_16.txt {names}")

    res = model.predict(str(args.image), imgsz=card["imgsz"], conf=card["conf_default"],
                        iou=card["iou_default"], verbose=False)[0]
    H, W = res.orig_shape
    dets = []
    for (x1, y1, x2, y2), c, p in zip(res.boxes.xyxy.tolist(),
                                      res.boxes.cls.tolist(), res.boxes.conf.tolist()):
        x1, x2 = max(0.0, min(x1, W)), max(0.0, min(x2, W))
        y1, y2 = max(0.0, min(y1, H)), max(0.0, min(y2, H))
        dets.append({"cls_id": int(c), "cls_name": names[int(c)],
                     "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                     "confidence": round(float(p), 4)})
    print(json.dumps({"image_width": W, "image_height": H, "detections": dets}))


if __name__ == "__main__":
    main()
