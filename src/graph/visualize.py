from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from src.ocr.engine import confidence_tier
from src.ocr.visualize import TIER_COLORS
from src.fusion.visualize import UNCLASSIFIED_COLOR

# Real relationship types beyond CONTAINS (ABOVE/BELOW/LEFT_OF/RIGHT_OF/
# ALIGNED_WITH/OVERLAPS/ORDERED_BEFORE) are generated for every sibling
# pair (design.md §6) — at typical node counts that's dense enough to
# render as an unreadable tangle of lines. CONTAINS (the parent/child
# hierarchy, mirroring fusion's parent_id) is the one most useful to see
# at a glance, so it's the only default; pass relationships=(...) to draw
# more.
DEFAULT_RELATIONSHIPS = ("CONTAINS",)

RELATIONSHIP_COLORS = {
    "CONTAINS": "yellow",
    "ABOVE": "cyan",
    "BELOW": "cyan",
    "LEFT_OF": "magenta",
    "RIGHT_OF": "magenta",
    "ALIGNED_WITH": "orange",
    "OVERLAPS": "red",
    "ORDERED_BEFORE": "white",
}


def draw_graph_result(image_path: Path, graph, output_path: Path, relationships=DEFAULT_RELATIONSHIPS):
    """Draw UI graph nodes and a curated subset of edges over the
    screenshot. Nodes: same bbox/colour-by-confidence-tier/label
    convention as fusion's visualization (src/fusion/visualize.py) — a
    class_=None node (unmatched OCR evidence, kept per rules.md §10) is
    drawn as a thin unlabeled gray box, same reasoning as there. A node
    with bbox=None (classification-only, no geometry) has nothing to
    draw and is skipped, not an error. Edges: only relationship types
    listed in `relationships` are drawn, as a line between the two
    nodes' bbox centers, colour-coded by relationship type — see
    DEFAULT_RELATIONSHIPS for why the default is CONTAINS only."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)

    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()

    skipped_no_bbox = 0
    centers = {}

    for node_id, data in graph.nodes(data=True):
        bbox = data.get("bbox")
        if bbox is None:
            skipped_no_bbox += 1
            continue

        x, y, w, h = bbox
        x1, y1, x2, y2 = int(x), int(y), int(x + w), int(y + h)
        centers[node_id] = ((x1 + x2) // 2, (y1 + y2) // 2)

        class_ = data.get("class_")
        if class_ is None:
            draw.rectangle([x1, y1, x2, y2], outline=UNCLASSIFIED_COLOR, width=2)
            continue

        color = TIER_COLORS[confidence_tier(data.get("confidence", 0.0))]
        draw.rectangle([x1, y1, x2, y2], outline=color, width=4)
        label = class_
        if data.get("text"):
            label += f' "{data["text"]}"'
        text_y = max(0, y1 - 18)
        text_bbox = draw.textbbox((x1, text_y), label, font=font)
        draw.rectangle(text_bbox, fill="black")
        draw.text((x1, text_y), label, fill=color, font=font)

    edges_drawn = 0
    for u, v, edge_data in graph.edges(data=True):
        relationship = edge_data.get("relationship")
        if relationship not in relationships:
            continue
        if u not in centers or v not in centers:
            continue
        draw.line([centers[u], centers[v]], fill=RELATIONSHIP_COLORS.get(relationship, "white"), width=2)
        edges_drawn += 1

    image.save(output_path)
    return skipped_no_bbox, edges_drawn
