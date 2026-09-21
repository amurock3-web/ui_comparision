"""Build and draw a UI graph from a saved fusion JSON — no OCR, no detector.

UIGraphBuilder only needs a fused UIDocument, and `save_json` already writes
one, so re-running the ~90s detector + OCR pass to iterate on graph logic is
pure waste. memory.md has noted this pattern since 2026-09-07; this is it as a
real script instead of an ad-hoc scratchpad file. Runs in well under a second.

    python -m scripts.build_graph_from_fusion                     # newest fusion JSON
    python -m scripts.build_graph_from_fusion output/fusion/test13_ss031_fusion.json
    python -m scripts.build_graph_from_fusion <json> CONTAINS ABOVE ALIGNED_WITH
    python -m scripts.build_graph_from_fusion --layout            # layout-tree builder (src/graph/layout.py)

Outputs, per run, into output/graph/:
  testN_<screen>_graph.json           the graph itself (node-link JSON)
  testN_<screen>_graph_diagram.png    nodes + edges, no screenshot
  testN_<screen>_graph_overlay.png    the same graph over the screenshot,
                                      when the screenshot can be located
"""
import sys
from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.graph.build import UIGraphBuilder
from src.graph.layout import LayoutGraphBuilder, describe
from src.graph.visualize import DEFAULT_RELATIONSHIPS, draw_graph_diagram, draw_graph_result
from src.schema.ui_element import UIDocument

FUSION_DIR = Path("output/fusion")
OUTPUT_DIR = Path("output/graph")


def newest_fusion_json() -> Path:
    candidates = [p for p in FUSION_DIR.glob("*_fusion.json")]
    if not candidates:
        raise SystemExit(f"no *_fusion.json in {FUSION_DIR} - run scripts.run_fusion first")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_screenshot(screen_id: str):
    """The fused document records no image path, so the screenshot is looked
    up by screen id. Only used for the optional overlay; the diagram does not
    need it."""
    for folder in ("input/production", "input/client"):
        for ext in (".png", ".jpg", ".jpeg"):
            candidate = Path(folder) / f"{screen_id}{ext}"
            if candidate.is_file():
                return candidate
    return None


def main():
    args = sys.argv[1:]
    json_arg = next((a for a in args if a.endswith(".json")), None)
    json_path = Path(json_arg) if json_arg else newest_fusion_json()
    layout = "--layout" in args
    relationships = (tuple(a for a in args if a.isupper())
                     or (("CONTAINS", "ABOVE", "LEFT_OF") if layout else DEFAULT_RELATIONSHIPS))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ui_doc = UIDocument.model_validate_json(json_path.read_text(encoding="utf-8"))
    prefix = f"test{next_test_number(OUTPUT_DIR)}_{ui_doc.screen_id}_{'layout' if layout else 'graph'}"

    print(f"Source: {json_path}  ({ui_doc.screen_id}, {len(ui_doc.elements)} elements, "
          f"{ui_doc.image_width}x{ui_doc.image_height})")
    print(f"Edges drawn: {', '.join(relationships)}")

    builder = LayoutGraphBuilder() if layout else UIGraphBuilder()
    graph = builder.build(ui_doc)
    builder.save_graph_json(graph, OUTPUT_DIR / f"{prefix}.json")
    if layout:
        print("\n" + describe(graph))

    skipped, drawn = draw_graph_diagram(
        graph, OUTPUT_DIR / f"{prefix}_diagram.png",
        image_size=(ui_doc.image_width, ui_doc.image_height),
        relationships=relationships,
        title=f"{ui_doc.screen_id} ({ui_doc.source})",
    )

    counts = Counter(data["relationship"] for _, _, data in graph.edges(data=True))
    print(f"\nNodes: {graph.number_of_nodes()}   Edges: {graph.number_of_edges()}")
    print("Relationship breakdown:")
    for relationship, n in counts.most_common():
        print(f"  {relationship:16s} {n}")
    if skipped:
        print(f"{skipped} node(s) had no geometry and are not plotted")

    print(f"\nGraph JSON: {OUTPUT_DIR / f'{prefix}.json'}")
    print(f"Diagram:    {OUTPUT_DIR / f'{prefix}_diagram.png'}  ({drawn} edges)")

    screenshot = find_screenshot(ui_doc.screen_id)
    if screenshot:
        draw_graph_result(screenshot, graph, OUTPUT_DIR / f"{prefix}_overlay.png", relationships)
        print(f"Overlay:    {OUTPUT_DIR / f'{prefix}_overlay.png'}  (over {screenshot})")
    else:
        print(f"Overlay:    skipped - no screenshot found for {ui_doc.screen_id!r}")


if __name__ == "__main__":
    main()
