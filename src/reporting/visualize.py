"""
Visual evidence for a comparison report (design.md §12) — side-by-side
production/client screenshots with differences highlighted.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DIFF_COLORS = {
    "MISSING_IN_PRODUCTION": "red",
    "EXTRA_IN_PRODUCTION": "yellow",
    "CLASS_DIFFERENCE": "magenta",
    "TEXT_DIFFERENCE": "orange",
    "POSITION_DIFFERENCE": "cyan",
    "SIZE_DIFFERENCE": "cyan",
    "STRUCTURAL_DIFFERENCE": "purple",
}


def _draw_box(draw, el, color, label, font):
    if el is None or el.bbox is None:
        return
    x, y, w, h = el.bbox
    x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)
    draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
    text_y = max(0, y1 - 18)
    text_bbox = draw.textbbox((x1, text_y), label, font=font)
    draw.rectangle(text_bbox, fill="black")
    draw.text((x1, text_y), label, fill=color, font=font)


def draw_comparison_result(production_image_path, client_image_path, production_doc, client_doc,
                            differences, output_path: Path):
    """Production | Client side by side. Only non-MATCH differences are
    outlined (colour keyed by DIFF_COLORS) and labeled with the
    difference type — MATCH pairs aren't drawn, the point is to
    spotlight what changed, not repeat the fusion/graph visualizations'
    full-element dump."""
    prod_img = Image.open(production_image_path).convert("RGB")
    client_img = Image.open(client_image_path).convert("RGB")
    prod_draw = ImageDraw.Draw(prod_img)
    client_draw = ImageDraw.Draw(client_img)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    prod_by_id = {el.id: el for el in production_doc.elements}
    client_by_id = {el.id: el for el in client_doc.elements}

    drawn = 0
    for d in differences:
        if d.verdict == "PASS":
            continue
        color = DIFF_COLORS.get(d.type, "white")
        _draw_box(prod_draw, prod_by_id.get(d.production_id), color, d.type, font)
        _draw_box(client_draw, client_by_id.get(d.client_id), color, d.type, font)
        drawn += 1

    gap = 20
    height = max(prod_img.height, client_img.height)
    combined = Image.new("RGB", (prod_img.width + client_img.width + gap, height), "black")
    combined.paste(prod_img, (0, 0))
    combined.paste(client_img, (prod_img.width + gap, 0))

    header_draw = ImageDraw.Draw(combined)
    header_draw.text((10, 10), "PRODUCTION", fill="white", font=font)
    header_draw.text((prod_img.width + gap + 10, 10), "CLIENT", fill="white", font=font)

    combined.save(output_path)
    return drawn
