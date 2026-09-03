Technical Design --- UI Comparison
1. Design principles
local-first
modular
explainable
model-agnostic
deterministic comparison where possible
benchmark-driven
minimal infrastructure for POC
2. OCR design

Input: PNG/JPG. PaddleOCR returns text, polygon/bbox and confidence.

Store:

text
bbox = [x, y, width, height]
normalized_bbox = [x/W, y/H, width/W, height/H]
center = [x+width/2, y+height/2]

Keep low-confidence OCR observations as evidence rather than deleting them immediately.

3. VLM design

The VLM receives the screenshot and useful OCR observations, plus the allowed taxonomy and strict schema.

Prompt rules: - do not invent elements - identify repeated elements independently - use approved classes - preserve visible text when reliable - distinguish UI components from artwork - output structured data

The prompt should be versioned.

4. Fusion design

Associate OCR and VLM observations using: 1. bbox overlap 2. center distance 3. text similarity 4. spatial proximity

Example: OCR "Free" + VLM class badge + overlapping bbox → fused badge element

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

Python + PaddleOCR + Ollama/Qwen3-VL + Pydantic + NetworkX + Pillow is sufficient. No database or large frontend is required.

17. Future hybrid system

Possible production architecture: fast detector + OCR + local VLM fallback + graph comparison where the detector handles common UI components and the VLM handles uncertain/unseen components