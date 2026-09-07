from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.ocr.visualize import TIER_COLORS


def draw_vlm_result(image_path: Path, vlm_result, output_path: Path):
    """Draw VLM bounding boxes over the screenshot, colour-coded by
    confidence tier (same palette as draw_ocr_result), labeled by class
    (+ text if the VLM produced any).

    Only usable with VLMEngine.analyze_grounded_experimental()'s output
    (VLMGroundedElement — has bbox/confidence). The DEFAULT classify-only
    VLMEngine.analyze() never reports a bbox at all (see src/vlm/engine.py
    module docstring) — for a picture of THAT output, visualize the fused
    result instead (src/fusion/visualize.py), which is where real
    geometry actually gets attached."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    for el in vlm_result.elements:
        x, y, w, h = el.bbox
        x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)
        color = TIER_COLORS[el.confidence_tier]

        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        label = f"{el.class_} ({el.confidence:.2f})"
        if el.text:
            label += f' "{el.text}"'
        text_y = max(0, y1 - 20)
        draw.text((x1, text_y), label, fill=color, font=font)

    image.save(output_path)
