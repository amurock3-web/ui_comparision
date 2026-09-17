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