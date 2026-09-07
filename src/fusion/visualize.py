from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.ocr.visualize import TIER_COLORS

# Unmatched OCR evidence (class=None, kept per rules.md §10 rather than
# dropped) is drawn faintly — it's real data, but the point of this
# visualization is to sanity-check fusion's classified/grounded output,
# not to spotlight raw OCR noise.
UNCLASSIFIED_COLOR = "gray"


def draw_fusion_result(image_path: Path, ui_document, output_path: Path):
    """Draw fused UIElement bboxes over the screenshot. Only elements with
    real geometry (bbox is not None) can be drawn — a classify-only VLM
    classification with no OCR match (e.g. "icon") has no bbox at all and
    is skipped here, not an error; see src/fusion/fuse.py's module
    docstring for why. Classified elements are colour-coded by confidence
    tier and labeled class + text; unmatched OCR evidence is drawn as a
    thin gray box with no label so it doesn't drown out the classified
    result."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    skipped_no_bbox = 0

    for el in ui_document.elements:
        if el.bbox is None:
            skipped_no_bbox += 1
            continue

        x, y, w, h = el.bbox
        x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)

        if el.class_ is None:
            draw.rectangle([x1, y1, x2, y2], outline=UNCLASSIFIED_COLOR, width=1)
            continue

        color = TIER_COLORS[el.confidence_tier]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        label = el.class_
        if el.text:
            label += f' "{el.text}"'
        label += f" ({el.confidence:.2f})"
        text_y = max(0, y1 - 20)
        draw.text((x1, text_y), label, fill=color, font=font)

    image.save(output_path)
    return skipped_no_bbox
