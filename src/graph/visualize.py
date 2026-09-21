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
    "NEAR": "#66ff99",
}


# Stable colour per class, taken by index from config/classes.json so the
# same class is the same colour in every diagram — without that, a
# production and a client diagram of the same screen would be coloured
# differently and could not be compared by eye.
CLASS_PALETTE = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff",
    "#9a6324", "#fffac8", "#800000", "#aaffc3",
]


def _class_color(class_, class_order):
    if class_ is None:
        return UNCLASSIFIED_COLOR
    if class_ in class_order:
        return CLASS_PALETTE[class_order.index(class_) % len(CLASS_PALETTE)]
    return "#888888"


def draw_graph_diagram(graph, output_path: Path, image_size, relationships=DEFAULT_RELATIONSHIPS,
                       width: int = 900, title: str = ""):
    """Draw the graph itself — nodes and edges, no screenshot underneath.

    Nodes keep their real screen positions (bbox centre, scaled to the
    canvas) rather than getting a spring/force layout: for a UI graph the
    spatial arrangement *is* the meaning, and a force layout would scramble
    the rows and columns the graph is describing. Radius follows sqrt(area),
    clamped, so a content_card reads as bigger than a badge without a card
    swallowing the badges drawn inside it.

    Edge types are filtered the same way as draw_graph_result — see
    DEFAULT_RELATIONSHIPS for why everything at once is unreadable.
    """
    import json as _json
    classes_path = Path(__file__).resolve().parents[2] / "config" / "classes.json"
    class_order = _json.loads(classes_path.read_text())["classes"]

    img_w, img_h = image_size
    scale = width / img_w
    plot_h = int(img_h * scale)
    legend_w = 240
    canvas = Image.new("RGB", (width + legend_w, plot_h), "#111111")
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("arial.ttf", 13)
        small = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = small = ImageFont.load_default()

    positions, radii, skipped = {}, {}, 0
    for node_id, data in graph.nodes(data=True):
        bbox = data.get("bbox")
        if bbox is None:
            skipped += 1
            continue
        x, y, w, h = bbox
        if data.get("virtual"):
            # Layout-tree groups (src/graph/layout.py): an outline box, anchored
            # at its left-middle so the marker doesn't sit on the middle child.
            # The screen node would just be a box around everything.
            if data.get("class_") == "screen":
                continue
            draw.rectangle([x * scale, y * scale, (x + w) * scale, (y + h) * scale],
                           outline="#555555", width=1)
            positions[node_id] = (x * scale, (y + h / 2) * scale)
            radii[node_id] = 4
            continue
        positions[node_id] = ((x + w / 2) * scale, (y + h / 2) * scale)
        radii[node_id] = max(5, min(18, (w * h) ** 0.5 * scale * 0.06))

    # Edges first so nodes sit on top of them.
    edges_drawn = 0
    for u, v, edge_data in graph.edges(data=True):
        relationship = edge_data.get("relationship")
        if relationship not in relationships or u not in positions or v not in positions:
            continue
        draw.line([positions[u], positions[v]],
                  fill=RELATIONSHIP_COLORS.get(relationship, "white"), width=1)
        edges_drawn += 1

    seen_classes = []
    for node_id, data in graph.nodes(data=True):
        if node_id not in positions:
            continue
        cx, cy = positions[node_id]
        r = radii[node_id]
        class_ = data.get("class_")
        color = _class_color(class_, class_order)
        if class_ not in seen_classes:
            seen_classes.append(class_)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color, outline="#ffffff")
        draw.text((cx + r + 2, cy - 6), node_id.replace("el_", ""), fill="#cccccc", font=small)

    y = 10
    if title:
        draw.text((width + 10, y), title, fill="#ffffff", font=font)
        y += 22
    draw.text((width + 10, y), f"{len(positions)} nodes / {edges_drawn} edges", fill="#aaaaaa", font=small)
    y += 22
    for class_ in seen_classes:
        draw.ellipse([width + 12, y + 3, width + 22, y + 13], fill=_class_color(class_, class_order))
        draw.text((width + 30, y), str(class_), fill="#dddddd", font=small)
        y += 17
    y += 8
    for relationship in relationships:
        draw.line([(width + 12, y + 8), (width + 26, y + 8)],
                  fill=RELATIONSHIP_COLORS.get(relationship, "white"), width=2)
        draw.text((width + 30, y), relationship, fill="#dddddd", font=small)
        y += 17

    canvas.save(output_path)
    return skipped, edges_drawn


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
        class_ = data.get("class_")

        if data.get("virtual"):
            # Same as draw_graph_diagram: thin unlabelled box, left-middle anchor.
            if class_ == "screen":
                continue
            draw.rectangle([x1, y1, x2, y2], outline="#888888", width=1)
            centers[node_id] = (x1, (y1 + y2) // 2)
            continue

        centers[node_id] = ((x1 + x2) // 2, (y1 + y2) // 2)
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
