Technical Design --- UI Comparison
1. Design principles
local-first
modular
explainable
model-agnostic
deterministic comparison where possible
benchmark-driven
minimal infrastructure for POC
1a. Detector design

A YOLOv8s model fine-tuned on the 16-class taxonomy (`models/ui16_v1`, 83 train / 20 val
images, val mAP50 0.877, mAP50-95 0.703) is the primary source of class + geometry. It is
deterministic, which the VLM grounding was not. Inference settings (imgsz 1280, conf 0.25,
iou 0.45) come from the bundle's `model_card.json`; `config/detector.yaml` only maps detector
confidence to tiers (high ≥ 0.70, medium ≥ 0.40). Weak classes (`rank_number`, `text_input`,
`logo`, 4-6 training instances each) are tagged `low_confidence_class` and treated as
uncertain until the VLM confirms them.

2. OCR design

Input: PNG/JPG. PaddleOCR returns text, polygon/bbox and confidence.

Store:

text
bbox = [x, y, width, height]
normalized_bbox = [x/W, y/H, width/W, height/H]
center = [x+width/2, y+height/2]

Keep low-confidence OCR observations as evidence rather than deleting them immediately.

3. VLM design

The VLM is now an opt-in fallback: `main.py --vlm` calls it only when detector+OCR fusion
leaves an `uncertain` element. Status-bar text (clock, battery) is ignored, not uncertain, so it
does not trigger the VLM.

The VLM receives the screenshot and useful OCR observations, plus the allowed taxonomy. Two
separate, versioned prompts, not one: `v2_qwen2.5vl_classify_only` (class/text/description/
approximate_location, no bbox — the default path) and `v3_qwen2.5vl_ground_content_cards`
(content_card-only geometry, via Qwen2.5-VL's native `bbox_2d` grounding format). Free-form
generation (`use_json_schema: false`), not schema-constrained decoding — schema-constrained
decoding was found to bias a nullable `text` field toward its null branch even for elements OCR
read at high confidence (arXiv:2408.02442).

Prompt rules: - do not invent elements - identify repeated elements independently - use approved classes - preserve visible text when reliable - distinguish UI components from artwork - output structured data

The prompt should be versioned.

4. Fusion design

Detector-first (`fuse_detections`, used by `main.py`): detections keep their class/bbox; each
OCR box is assigned to the smallest detection containing its center; text inside a container
class (content_card, cast_card, celebrity_card, navigation_bar) stays a child element, text
inside any other class becomes that element's text. Orphan OCR text, low-tier detections and
low_confidence_class detections are `uncertain`. The VLM result, when present, classifies
orphan OCR boxes and confirms uncertain detections — only via `ocr_ref_id` or text similarity,
never zone-only.

The rest of this section describes the legacy OCR+VLM path (`fuse`), kept for reference.


Real geometry comes from OCR wherever possible — the VLM's own per-element bbox output was found
non-deterministic across repeated calls, disqualifying it for a tool whose job is detecting real
differences between two runs (see `fuse.py` module docstring). Associate OCR and VLM observations
using, in this order: 1. Set-of-Marks id match (VLM's own `ocr_ref_id`, when given) 2. text
similarity 3. position-zone-only fallback (no text comparison) — applied to every VLM
classification uniformly, not restricted to a "text-matchable" subset (that restriction was found
to leave classes like icon/navigation_bar with no matching attempt at all, e.g. an icon labeled
"Search" never grabbing OCR's own "Search" text).

content_card is the one exception: its geometry comes exclusively from a dedicated VLM grounding
call (`ground_content_cards_experimental()`), not OCR association — content_cards have no reliable
OCR-matchable text of their own. That grounding call's own output is near-deterministic within a
tight back-to-back sequence at `temperature: 0`, but showed ~4% normalized position drift across a
longer session-to-session gap — wider than OCR-derived geometry, so grounded elements carry
`metadata.bbox_source = "vlm_grounded"` for the comparison stage to apply a looser position
tolerance than OCR-exact geometry gets.

Example: OCR "Free" + badge keyword match + center inside a content_card's bbox → promoted to
`overlay_badge` using OCR's exact bbox (deterministic keyword+containment, no VLM involved).

Unmatched OCR text whose center falls inside a content_card's bbox gets `parent_id` set to that
card instead of staying a floating top-level element (e.g. a poster's title/subtitle text).
Anything still unmatched after every fallback is tagged `metadata.match_status = "uncertain"`
rather than left ambiguous or silently dropped.

Preserve raw sources.

5. UI schema

Conceptual element:

text
UIElement
├── id
├── class
├── text
├── bbox
├── normalized_bbox
├── center
├── confidence
├── source
├── parent_id
└── metadata

Pydantic should validate this schema.

6. Graph construction

Each UI element becomes a node. Relationships are inferred from semantics and geometry.

Examples: - badge inside card → card CONTAINS badge - card1 left of card2 → card1 LEFT_OF card2 - section title above card row → section_title ABOVE content_card

Avoid generating every mathematically possible relation.

7. Element matching

Candidate score can combine:

text
class score
text score
spatial score
bbox/IoU score
context score

Weights must be configurable and calibrated experimentally.

8. Text comparison

Support: - exact equality - case normalization - whitespace normalization - punctuation normalization - fuzzy similarity

Low-confidence stylized OCR should not automatically create a hard difference.

9. Geometry comparison

Compare: - x/y - width/height - center - aspect ratio - IoU - normalized position

Use resolution-independent normalized coordinates when appropriate.

10. Structural comparison

Compare: - parent/child - containment - sibling ordering - spatial relationships

Example: Production: Card → CONTAINS → Free badge Client: no badge → structural + missing difference.

11. Severity

Future configurable levels: CRITICAL, HIGH, MEDIUM, LOW, INFO, UNCERTAIN

Do not hard-code severity without project evidence.

12. Reporting

Summary:

Similarity counts elements, not Difference records (Phase 12.1): matched pairs / (matched + missing + extra).
A pair with three sub-differences is one matched element; `clean` = matched pairs with no finding.
Dynamic content ignored under §H (poster tiles, status bar) stays out of the denominator and is only
counted as `ignored`. `report["summary"]` holds matched_pairs, clean_pairs, missing, extra, ignored,
comparable, similarity_percent, clean_percent and difference_records (debug only), plus per-type counts.
No comparable elements → 0% with a `warning`.

text
Screen: SS012
Similarity: 91.4%
Matched: 27
Missing: 2
Extra: 1
Text: 2
Geometry: 3
Structure: 1

Detailed finding:

text
Type: MISSING_IN_CLIENT
Class: badge
Text: Free
Parent: content_card
Confidence: 0.96

Also provide visual evidence.

13. Configuration

Use configuration for thresholds, e.g.:

yaml
ocr:
  confidence_warning: 0.60
  confidence_accept: 0.85

matching:
  minimum_match_score: 0.70

Exact values must be experimentally calibrated.

14. Testing

Unit tests should cover: - OCR bbox conversion - normalization - schema validation - graph construction - matching - missing/extra elements - text differences - geometry differences - structural differences

15. Benchmarking

Record: - model - image - resolution - runtime - element count - confidence - manual correctness notes

16. POC technology set

Python + YOLOv8 (Ultralytics, separate venv) + PaddleOCR + Ollama/Qwen2.5-VL 7B + Pydantic + NetworkX + Pillow is sufficient. No
database or large frontend is required. (Qwen3-VL 4B was the original candidate; rejected —
see `memory.md`'s VLM benchmarking history.)

17. Hybrid system (implemented 2026-09-17)

Detector + OCR + local VLM fallback + graph comparison: the detector handles common UI
components and the VLM handles uncertain/unseen ones. Next: retrain with more examples of the
weak classes, and measure the detector on screenshots outside its 103-image training set.

## 18. Class refiner design (parked, rules.md §20)

Goal: fix YOLO confusions (first run: `button` recall 0.58, confused
with `tab_item`/`overlay_badge`; weak `icon`, `metadata_text`) with a
second, explainable opinion.

**Input features per box:**
- Geometry: normalized x, y, w, h, aspect ratio, area
- OCR: text length, word count, has digits, is empty, regex hits
  (`S\d+ ?E\d+`, durations like `2h 10m` / `45 min`, `Free`), OCR
  confidence
- Context: inside a `content_card`? position inside it (corner /
  bottom); strongest signal for button vs overlay_badge
- YOLO: predicted class (one-hot) + confidence (v2 only, see leakage)

**Training data:** ground-truth boxes (after 22→16 remap) from all
103 images + OCR text whose center lies inside each box → one CSV
(~2186 rows). Using GT boxes avoids YOLO leakage and uses all data.

**Pitfalls:**
- Same-screen leakage → split by image (`GroupKFold`, group = image
  id), never by box
- YOLO leakage → YOLO-output features only from images YOLO did not
  train on (val split or k-fold out-of-fold predictions)
- Class imbalance → `class_weight="balanced"`; results on
  `rank_number`/`text_input` are directional only
- Calibration → logistic regression is usually close; LightGBM needs
  `CalibratedClassifierCV`. Probabilities feed `confidence_tier`

**Model choice:** start with logistic regression (inspectable
weights → explainable). Try LightGBM + calibration only if it
plateaus.

**Runtime decision rule (thresholds to tune on held-out images):**
- YOLO conf ≥ 0.85 and class outside the confusable group → keep YOLO
- else run refiner:
  - agrees with YOLO → high confidence
  - refiner ≥ 0.7 and YOLO not confident → take refiner
  - otherwise → `UNCERTAIN`, keep both candidates (rules.md §10)

**Stored per element (metadata):** raw YOLO class + conf, refiner
probabilities, which rule decided, refiner version + thresholds
(rules.md §15).

**Success metric:** on the confusable group (`button`, `tab_item`,
`overlay_badge`, `icon`, `metadata_text`), `button` recall rises above
0.58 without `tab_item` recall dropping. Compare against YOLO-only on
the same held-out images via confusion matrix.

**Limit:** if two classes look different but share size, position and
text, features cannot separate them → needs more YOLO data or a VLM
check on those boxes only.

## 19. Targeted crop OCR design

See architecture.md §4a. Per element crop of a text-bearing class:
pad a few px, upscale small crops ~2×, run PaddleOCR, attach text +
confidence + `confidence_tier` directly to that element. Artwork text
inside cards is not read.

## 20. rank_number rule (proposed)

Derive rank as a card attribute, not a detector class:

A card gets `metadata.rank = N` when:
- OCR reads an integer 1–10 at the left / bottom-left of a
  `content_card`, AND
- the row's `section_title` matches `top\s*10` (case-insensitive), OR
  the row's cards carry sequential numbers 1, 2, 3, ...

Caveats: stylized outlined rank digits may be misread by OCR;
localized or differently-worded row titles ("Top Picks") → the
sequential-number condition covers these. A rank present in Production
but missing in Client is reported (attribute difference), so the
information is not lost by dropping the class.

## 21. Color detection design (built, Phase 13-15)

Built as `src/comparison/color_checks.py` (D1, D2, D5, CIEDE2000) and
`src/comparison/contrast_checks.py` (D3 text colour, D7 contrast via a k-means
text/background split). Background and fill follow points 1-2 below; the
translucent-chrome question (point 3) stayed open: see memory.md Phase 13/14.

1. **Screen background:** mask out all detected boxes, take the
   mode/median color of the remaining pixels.
2. **Element fill color:** sample a thin ring just inside the
   element border (not the full box) so text/icons don't pollute it.
   For text elements, the OCR box separates text color from fill.
3. **Gradients / translucent overlays:** store a small palette (top
   2-3 colors via k-means or histogram), not one value.
4. **Compare in CIELAB with ΔE (CIEDE2000)**, not RGB distance:
   ΔE < 2 ≈ not visible, 2-5 ≈ noticeable on close look, > 5 ≈ clear
   difference. Exact thresholds to be calibrated.
5. Emits proposed `COLOR_DIFFERENCE` (rules.md §8).

Traps:
- Dynamic content (poster rotation, personalization, new releases)
  → compare UI chrome only (nav bar, buttons, tabs, badges,
  backgrounds), never artwork
- Capture conditions (dark/light mode, device, JPEG) → capture both
  sides with the same device and settings, PNG, keep a tolerance

## 22. Other attribute extractors (backlog, by value vs effort)

1. Text color + font size — text colour built (D3); font size not yet
2. Selected/active tab — color-contrast rule vs sibling tabs; high value (D4, not built)
3. Spacing and alignment — alignment built (B5); spacing (B6) not yet
4. Truncation — text ending in "…" on one side only (not built)
5. Icon identity — built as SSIM + dHash (F2, `image_checks.py`)
6. Static image identity (logos only) — built as SSIM (F1); posters never compared

Build order is decided by frequency in real QA bug tickets
(rules.md §20), not by this list.

## 23. End-to-end validation with synthetic test pairs

Detector mAP does not measure the product. Build test pairs with known
answers: copy a real screenshot (e.g. `ss012.png`) and edit the copy —
delete a badge, change a tab's text, shift a button, recolor a
button. The report must find exactly those edits. Gives
precision/recall of **difference detection** for the whole pipeline.
Every new check/extractor gets its own test pair.