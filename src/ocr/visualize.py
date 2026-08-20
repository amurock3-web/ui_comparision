from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Colour-code by confidence tier so weak/stylized detections
# (like your Tamil poster titles) are visually obvious at a glance.
TIER_COLORS = {
    "high": "lime",
    "medium": "orange",
    "low": "red",
}


def draw_ocr_result(image_path: Path, ocr_result, output_path: Path):
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    for el in ocr_result.elements:
        x, y, w, h = el.bbox
        x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)
        color = TIER_COLORS[el.confidence_tier]

        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        label = f'{el.text} ({el.confidence:.2f})'
        text_y = max(0, y1 - 22)
        draw.text((x1, text_y), label, fill=color, font=font)

    image.save(output_path)