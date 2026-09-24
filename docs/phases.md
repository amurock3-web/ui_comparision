# Project Phases --- UI Comparison

## Phase 0 --- Foundation

Completed: - new project folder - Python 3.11 virtual environment -
Ollama 0.32.14 - qwen3-vl:4b - PaddlePaddle 3.2.0 - PaddleOCR - Pillow -
NetworkX - Pydantic - Ollama Python client

## Phase 1 --- OCR Foundation

Goal: local text + coordinate extraction.

Pipeline: `Screenshot → PaddleOCR → text + bbox + confidence → OCR JSON`

SS012 benchmark: - resolution: 1080×2400 - detections: 39 - CPU time:
\~41.37 s

Strong text: Action Crime, Action Drama, Action Comedy, Action Romance,
Free, Movies, Live TV, More, Search, Downloads, Home, Languages,
Profile.

Stylized poster text was weaker. This is acceptable because semantic
interpretation belongs to the VLM.

Next OCR improvement: - center coordinates - normalized bbox - reusable
engine - confidence filtering/metadata

## Phase 2 --- Local VLM

Current candidate: `Qwen3-VL 4B via Ollama`

Status: installed; benchmark paused until possible GPU access.

Tasks: - benchmark model - define local VLM interface - create
structured extraction prompt - validate output - measure latency

## Phase 3 --- OCR + VLM Fusion

OCR supplies exact text/coordinates. VLM supplies semantic
class/context. Fusion produces validated UI JSON.

Status (2026-09-21): active blocker is OCR↔box association.
Proposed simplification: detector-first targeted crop OCR
(architecture.md §4a) — text is read per element crop, so association
becomes trivial and poster artwork text is skipped.

## Phase 4 --- UI Graph

Use NetworkX. Nodes = UI elements. Edges = relationships such as
contains, parent/child, spatial relation and ordering.

## Phase 5 --- Production vs Client Matching

Match using class, text, spatial proximity, normalized coordinates,
size, IoU and graph context. Do not match by list index.

## Phase 6 --- Difference Engine

Detect: - missing - extra - class - text - position - size - geometry -
structural - order - uncertainty

Post-MVP additions (parked): `COLOR_DIFFERENCE`,
`ATTRIBUTE_DIFFERENCE` via attribute extractors (design.md §21-22),
ordered by frequency in real QA tickets.

## Phase 7 --- Reporting

Create summary + detailed findings + visual overlay.

**Expected end result** for one Production/Client pair:
- summary counts (matched / missing / extra / text / position /
  size / order / uncertain)
- detailed findings, each with type, both bboxes, confidence (e.g.
  `TEXT_DIFFERENCE: tab_item 'Movies' → 'Films'`,
  `MISSING_IN_CLIENT: overlay_badge 'Free' on 3rd card of 'Action
  Crime' row`, `POSITION_DIFFERENCE: Subscribe button moved 40px down`)
- side-by-side visual overlay with colored boxes on each difference
- UI JSON + graph files per screen (reproducible, machine-readable)

It replaces manual side-by-side eyeballing by QA. It is not a pixel
diff.

## Phase 8 --- 2--3 Day POC

Minimum:
`Production + Client → local OCR → local VLM → UI JSON → UI Graph → comparison → report`

Validation: synthetic test pairs with known edits (design.md §23) —
measure precision/recall of difference detection, not just detector
mAP.

## Phase 9 --- Batch

Scale to many screens, including the old 103-screen set if desired.

Data expansion (parked, after MVP): add screens from other OTT apps —
20-30 screens each from 4-5 apps beats hundreds from one app. Reduce
annotation cost with **model-assisted labeling**: current YOLO as a
Label Studio pre-annotator, humans only correct.

## Phase 10 --- Detector

After verified outputs exist, optionally train a specialized UI
detector. Do not train before proving the pipeline.

Status (started early, separate repo `UI_Detection_model_training`,
trained on Colab): first run `ui16_20260917_071603` (yolov8s, imgsz
1280) — mAP@50 0.877, mAP@50-95 0.703. Strong: navigation_bar,
cast_card, search_bar, logo, celebrity_card, tab_item. Weak: button
(recall 0.58), icon, metadata_text, rank_number (recall 0.0, 4 samples).

2026-09-22: class refiner experiment started ahead of MVP by decision.

Parked follow-ups:
- class refiner (design.md §18) for the confusable group
- rank_number as rule-derived card attribute (design.md §20)
- ontology v3 remap + retrain (prd_section7_update.md, proposed)

## Phase 11 --- Productionization

Possible future: - dashboard - historical comparisons - regression
tracking - client-specific rules - GPU inference - optimized local VLM -
detector + VLM fallback

Also: new-client onboarding (architecture.md §20) — generic ontology,
multi-app data, VLM fallback, optional 20-30 screen fine-tune per
client; check whether client inputs are real screenshots or design
mockups.

## Post-MVP order (decided 2026-09-21)

1. MVP end-to-end on one pair with current 16 classes
2. Synthetic test pairs with known edits
3. Add checks one at a time, most common real-ticket regression first
   (color, text style, selected tab, ...)
4. Class refiner / ontology v3 / multi-app data only if results show
   they are the bottleneck
