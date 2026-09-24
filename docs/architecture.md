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

## 4a. Detector-first targeted OCR (proposed 2026-09-21)

Problem: full-screen OCR also reads text painted inside poster/card
artwork, which is noise for comparison, and it forces a hard OCR↔box
association step (the current fusion blocker).

Proposal: run the detector first, then run OCR **only on crops of
text-bearing classes**: `tab_item`, `section_title`, `button`, `title`,
`metadata_text`, `description`, `overlay_badge`, `search_bar`
(`text_input` if present). Skip OCR inside card artwork.

Why OCR is still required: YOLO cannot read; the VLM hallucinates text
(especially non-Latin scripts); `TEXT_DIFFERENCE` is a core difference
type.

Effects:
- the text already belongs to the crop's element → association is
  trivial, which largely removes the fusion blocker
- artwork text is never read
- fewer OCR calls on small regions

Technical note: pad crops by a few pixels and upscale small crops
(~2×) before PaddleOCR, otherwise recognition accuracy drops. Keep the
OCR confidence and `confidence_tier` per crop.

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

Group shift (Phase 12.2, `matching.group_shift` in config.yaml): pass 1 matches unshifted. Confident
pass-1 pairs (same class, text score ≥ 0.9 or IoU ≥ 0.5, not dynamic) are anchors; each client
layout-graph container with ≥ 3 anchors whose dx/dy MAD ≤ 0.01 gets their median shift. Pass 2 re-scores
only still-unmatched elements with the production box moved back by the shift of the element's own
container (or the nearest shifted one up the CONTAINS chain) — never a global shift, so a header tab
cannot pair with a same-label sheet tab. The differ reports each shift once as `GROUP_SHIFT` (C1 bands)
and judges members' POSITION_DIFFERENCE on the residual only. `enabled: false` restores pre-12.2 output.

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

Proposed additions (post-MVP, see rules.md §20):

``` text
src/
├── fusion/class_refiner.py   # local class refiner (design.md §18)
└── attributes/               # attribute extractors (design.md §21-22)
    ├── color.py
    ├── text_style.py
    └── ...
```

Each pipeline stage that has real geometry to draw also has a `visualize.py`, following the same
convention: colour-code by confidence tier, thick outline + labeled box for classified/grounded
elements, thin unlabeled box for unclassified evidence kept per rules.md §10.

Create modules incrementally; do not overbuild before the end-to-end POC works.

## 17. Proposed target flow v2 (2026-09-21, not yet adopted)

``` text
Screenshot
    ↓
YOLO detector (visual classes, from UI_Detection_model_training bundle)
    ↓
Class refiner (optional, local; only for low-confidence / confusable boxes)
    ↓
Targeted crop OCR (text-bearing classes only, §4a)
    ↓
Rules (rank_number, text role, card style)  +  Attribute extractors
    ↓
Local VLM fallback (only for low-confidence / unseen components)
    ↓
UI JSON  →  UI Graph  →  Comparison  →  Report
```

This is the "fast detector + OCR + local VLM fallback" hybrid from
design.md §17, made concrete. Raw evidence from every stage is kept in
element `metadata` (§6).

## 18. Class refiner (parked)

A small local tabular classifier (logistic regression first, LightGBM
if needed) that gives a second opinion on an element's class from
geometry + OCR + context + YOLO output, returning calibrated class
probabilities. Local replacement for the rejected cloud Jev idea
(rules.md §18).

- Training code: `UI_Detection_model_training` (it owns labels + remap)
- Saved model (`.joblib`): shipped in the same bundle as YOLO weights
- Inference: `ui_comparision/src/fusion/class_refiner.py`

Details: design.md §18.

## 19. Attribute extractors (parked)

Deterministic modules (NumPy/Pillow, no ML) that measure properties of
already-detected elements: color, text color/size, selected tab state,
spacing/alignment, truncation, icon identity. They produce layer-2
attributes (prd_section7_update.md, proposed v3 ontology) that the
comparison engine compares. Details: design.md §21-22.

## 20. Generalization to new clients / other OTT apps

The system compares Production vs Client of the **same app**, so it
does not need to "know" the app — it needs to detect generic components
**consistently on both sides**. Consistent detector errors on both
sides largely cancel out in a relative comparison.

Generalization comes from (in order of impact):
1. A generic, visual-first ontology (proposed v3)
2. Training on a few screens from several OTT apps rather than many
   screens from one (SunNXT only → overfits to one app)
3. Local VLM fallback for low-confidence/unseen components (zero-shot)
4. Per-client onboarding if needed: annotate 20-30 screens
   (model-assisted), fine-tune

Open question: what does "Client" input look like in practice? If
clients provide **design mockups** (e.g. Figma exports) instead of real
app screenshots, there is a domain gap (flat colors, placeholder
images) that a detector trained on real screenshots may not handle.