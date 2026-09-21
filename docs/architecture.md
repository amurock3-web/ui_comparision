System Architecture --- UI Comparison
1. Goal

Compare Production and Client OTT screenshots locally using a fine-tuned UI detector, OCR, a VLM fallback, structured JSON, graphs and deterministic comparison.

2. High-level flow
text
Production screenshot
        ↓
YOLO detector (ui16_v1)  +  PaddleOCR
        ↓                       ↓
class + bbox            text + coordinates
        └───────┬───────────────┘
                ↓
Fusion ──(--vlm, only if something is uncertain)──→ Local VLM (classify-only)
        ↓
UI JSON
        ↓
UI Graph
        │
        ├──────────────┐
        │              │
        ↓              ↓
Production side    Client side
        │              │
        └────── Comparison ──────┘
                       ↓
             JSON + Graph + Geometry
                       ↓
                  Report
3. Input layer

Loads local screenshots, validates image dimensions and creates Production/Client pairs.

3a. Detector

`src/detector/engine.py`, configured in `config/detector.yaml`. A YOLOv8s model fine-tuned on
the 16-class taxonomy (bundle `models/ui16_v1/`: `best.pt`, `model_card.json`,
`classes_16.txt`, `gt_detections.json`; weights are not in git). It gives class, bbox and
confidence for every element and is deterministic (same image → identical boxes).

Two engines behind `load_detector().detect(image) -> list[UIElement]`:
- `yolo` (default): runs `best.pt` via `src/detector/yolo_worker.py` in a separate Python —
  `config/detector.yaml`'s `python_path`, overridden by `UI_DETECTOR_PYTHON` where it is set —
  because ultralytics/torch must not share an environment with paddlepaddle-gpu.
- `gt_stub`: replays the hand labels. A perfect detector for the 103 labelled screens, so a
  bug seen with it is a pipeline bug.

The bundle's class order is checked against `config/classes.json` at load time. Classes with
too few training examples (`rank_number`, `text_input`, `logo`) are tagged
`metadata.low_confidence_class`.

4. OCR engine

Technology: - PaddleOCR - PaddlePaddle 3.2.0 - PP-OCRv6 family - Pillow for image handling/visualization

Responsibilities: - text detection - text recognition - bbox/polygon - confidence - normalized coordinates

5. VLM engine

Runtime: Ollama 0.33.3. Current model: qwen2.5vl:7b (qwen3-vl:4b was tried first and rejected —
its thinking mode can't be disabled and exhausts the token budget on screens with many repeated
elements; see `memory.md`'s VLM benchmarking history).

The VLM is an opt-in fallback: with `main.py --vlm`, `VLMEngine.analyze()` (classify-only —
class/text/description/approximate_location, no bbox) runs when detector+OCR fusion left
something `uncertain`. Without `--vlm`, uncertain elements are reported as REVIEW. `VLMEngine.ground_content_cards_experimental()` (native `bbox_2d` grounding for
content_card) is no longer called by `main.py`; the detector replaced it, because VLM boxes
drifted ~4% between sessions.

Responsibilities: - UI semantic classification - visual component recognition - contextual interpretation - relationships - difficult visual content

The rest of the application should call an abstraction such as:

python
vlm.analyze(image, ocr_result)

rather than calling Ollama everywhere.

6. Fusion

Main path — `FusionEngine.fuse_detections(detections, ocr, vlm=None)`:
- every detection is kept with its detector class/bbox/confidence;
- each OCR box goes to the smallest detection containing its center (a non-card box wins over a
  card box). On a poster (content_card, cast_card, celebrity_card) the text is artwork: it is
  dropped from the UI JSON, and only its id is kept in the card's `metadata.ocr_ids` (the raw OCR
  JSON keeps the text). In a navigation_bar it stays a child element with `parent_id`. Otherwise
  its text becomes the detection's text (reading order);
- a low-tier detection ≥80% inside a more confident detection of another class is a duplicate
  guess: `metadata.ignored = "overlapped_by_higher_confidence"`, always PASS;
- OCR text inside no detection, and detections that are low-tier or of a
  low_confidence_class, get `metadata.match_status = "uncertain"` (→ REVIEW);
- OCR text in no detection inside the top `fusion.status_bar_height_norm` (0.04) of the screen
  is the phone status bar: tagged `metadata.ignored = "status_bar"`, always PASS (spec §H);
- with a VLM result, a VLM class tied to OCR by `ocr_ref_id` or text similarity (never
  zone-only) classifies an orphan OCR box or confirms an uncertain detection of the same class.

Legacy path — `FusionEngine.fuse(ocr, vlm, grounded_cards)`, OCR + VLM only. For most classes: SoM-style id match (VLM's own `ocr_ref_id`) first, then
text similarity, then a position-zone-only fallback — applied uniformly to every VLM
classification, not a restricted subset. content_card geometry comes exclusively from the VLM
grounding call (no fallback); overlay_badge from deterministic OCR keyword+containment. Unmatched
OCR text whose center falls inside a content_card gets `parent_id` set to that card instead of
staying a floating top-level element. Anything still unmatched after all of the above is tagged
`metadata.match_status = "uncertain"` rather than left ambiguous.

Keep raw OCR/VLM evidence; do not destroy it.

7. UI JSON

Suggested fields:

text
screen_id
source
image.width
image.height
elements[]

Element:

text
id
class
text
bbox
normalized_bbox
center
confidence
source
parent_id
metadata
8. UI Graph

NetworkX for POC.

Node attributes: id, class, text, bbox, normalized_bbox, confidence

Edges: relationship, confidence

Initial relationships: CONTAINS, CHILD_OF, BELONGS_TO, ABOVE, BELOW, LEFT_OF, RIGHT_OF, ALIGNED_WITH, OVERLAPS, ORDERED_BEFORE

9. Matching

Candidate signals: - class similarity - text similarity - center distance - bbox overlap/IoU - size - graph context - parent - ordering

10. Geometry

Compare x/y/width/height/center/aspect ratio/IoU/normalized position.

11. Graph comparison

Compare nodes and edges: - missing node - extra node - class mismatch - text mismatch - wrong parent - missing relationship - extra relationship - ordering change

12. Difference engine

Combines: - JSON comparison - OCR/text comparison - geometry - graph comparison

The final decision should be as deterministic/explainable as possible.

13. Reporting

Output:

text
output/
├── ocr/
├── json/
├── graphs/
├── comparisons/
└── reports/

Report includes summary, counts, detailed findings, confidence and visual evidence.

14. Security

All processing stays local: Screenshot → Detector + OCR → (VLM) → JSON → Graph → Comparison → Report

No cloud inference is required.

15. Stack
Python 3.11
PaddlePaddle 3.2.0
PaddleOCR
Pillow
Ultralytics YOLOv8 + PyTorch (separate venv, `UI_DETECTOR_PYTHON`)
Ollama 0.33.3
Qwen2.5-VL 7B
NetworkX
Pydantic
python-dotenv
standard Python libraries
16. Target source layout
text
src/
├── detector/
│   ├── engine.py
│   └── yolo_worker.py
├── ocr/
│   ├── engine.py
│   └── visualize.py
├── vlm/
│   ├── engine.py
│   ├── prompts.py
│   └── visualize.py
├── fusion/
│   ├── fuse.py
│   └── visualize.py
├── schema/
├── graph/
│   ├── build.py
│   └── visualize.py
├── comparison/
│   ├── matcher.py
│   └── differ.py
├── reporting/
└── main.py

Each pipeline stage that has real geometry to draw also has a `visualize.py`, following the same
convention: colour-code by confidence tier, thick outline + labeled box for classified/grounded
elements, thin unlabeled box for unclassified evidence kept per rules.md §10.

Create modules incrementally; do not overbuild before the end-to-end POC works.