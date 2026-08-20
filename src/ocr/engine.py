"""
Reusable PaddleOCR engine wrapper.

Other modules (fusion, main.py) should import OCREngine and call
engine.run(image_path) rather than touching PaddleOCR directly —
mirrors the vlm.analyze() abstraction in architecture.md §5.
"""

from pathlib import Path
from dataclasses import dataclass, field
import time
import json

from PIL import Image
from paddleocr import PaddleOCR


# Confidence tiers — thresholds live here so they're config, not magic
# numbers scattered around. Matches design.md §13.
CONFIDENCE_ACCEPT = 0.85
CONFIDENCE_WARNING = 0.60
# below CONFIDENCE_WARNING -> "low" tier: kept as evidence, never
# silently trusted or silently dropped (rules.md §10)


def confidence_tier(score: float) -> str:
    if score >= CONFIDENCE_ACCEPT:
        return "high"
    if score >= CONFIDENCE_WARNING:
        return "medium"
    return "low"


@dataclass
class OCRElement:
    id: str
    text: str
    bbox: list          # [x, y, w, h]
    normalized_bbox: list  # [x/W, y/H, w/W, h/H]
    center: list         # [cx, cy]
    confidence: float
    confidence_tier: str
    source: str = "ocr"

    def to_dict(self):
        return {
            "id": self.id,
            "text": self.text,
            "bbox": self.bbox,
            "normalized_bbox": self.normalized_bbox,
            "center": self.center,
            "confidence": self.confidence,
            "confidence_tier": self.confidence_tier,
            "source": self.source,
        }


@dataclass
class OCRResult:
    screen: str
    image_path: str
    image_width: int
    image_height: int
    inference_time_seconds: float
    elements: list = field(default_factory=list)

    def to_dict(self):
        return {
            "screen": self.screen,
            "image": self.image_path,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "ocr_engine": "PaddleOCR",
            "inference_time_seconds": round(self.inference_time_seconds, 3),
            "element_count": len(self.elements),
            "elements": [e.to_dict() for e in self.elements],
        }

    def save_json(self, path: Path):
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class OCREngine:
    """Thin, reusable wrapper around PaddleOCR."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self._ocr = PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def run(self, image_path: Path, screen_id: str = None) -> OCRResult:
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Screenshot not found:\n{image_path.resolve()}")

        image = Image.open(image_path)
        W, H = image.width, image.height
        screen_id = screen_id or image_path.stem

        start = time.time()
        raw_result = self._ocr.predict(str(image_path))
        elapsed = time.time() - start

        elements = []
        for page_result in raw_result:
            data = page_result.json
            if callable(data):
                data = data()
            if isinstance(data, str):
                data = json.loads(data)
            if "res" in data:
                data = data["res"]

            texts = data.get("rec_texts", [])
            scores = data.get("rec_scores", [])
            boxes = data.get("rec_polys", [])

            for i, text in enumerate(texts):
                text = str(text).strip()
                if not text:
                    continue

                confidence = float(scores[i]) if i < len(scores) else 0.0
                polygon = boxes[i]

                xs = [float(p[0]) for p in polygon]
                ys = [float(p[1]) for p in polygon]
                x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                w, h = x2 - x1, y2 - y1

                bbox = [round(x1, 2), round(y1, 2), round(w, 2), round(h, 2)]
                normalized_bbox = [
                    round(x1 / W, 5),
                    round(y1 / H, 5),
                    round(w / W, 5),
                    round(h / H, 5),
                ]
                center = [round(x1 + w / 2, 2), round(y1 + h / 2, 2)]

                elements.append(
                    OCRElement(
                        id=f"ocr_{len(elements) + 1:04d}",
                        text=text,
                        bbox=bbox,
                        normalized_bbox=normalized_bbox,
                        center=center,
                        confidence=round(confidence, 4),
                        confidence_tier=confidence_tier(confidence),
                    )
                )

        return OCRResult(
            screen=screen_id,
            image_path=str(image_path),
            image_width=W,
            image_height=H,
            inference_time_seconds=elapsed,
            elements=elements,
        )