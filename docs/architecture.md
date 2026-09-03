System Architecture --- UI Comparison
1. Goal

Compare Production and Client OTT screenshots locally using OCR, VLM, structured JSON, graphs and deterministic comparison.

2. High-level flow
text
Production screenshot
        ↓
PaddleOCR
        ↓
text + coordinates
        ↓
Local VLM
        ↓
visual semantics
        ↓
Fusion
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

4. OCR engine

Technology: - PaddleOCR - PaddlePaddle 3.2.0 - PP-OCRv6 family - Pillow for image handling/visualization

Responsibilities: - text detection - text recognition - bbox/polygon - confidence - normalized coordinates

5. VLM engine

Runtime: Ollama 0.32.14 Current model: qwen3-vl:4b

Responsibilities: - UI semantic classification - visual component recognition - contextual interpretation - relationships - difficult visual content

The rest of the application should call an abstraction such as:

python
vlm.analyze(image, ocr_result)

rather than calling Ollama everywhere.

6. Fusion

Combines OCR and VLM using bbox overlap, center distance, text similarity and spatial proximity.

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

All processing stays local: Screenshot → OCR → VLM → JSON → Graph → Comparison → Report

No cloud inference is required.

15. Stack
Python 3.11
PaddlePaddle 3.2.0
PaddleOCR
Pillow
Ollama 0.32.14
Qwen3-VL 4B
NetworkX
Pydantic
python-dotenv
standard Python libraries
16. Target source layout
text
src/
├── ocr/
├── vlm/
├── fusion/
├── schema/
├── graph/
├── comparison/
├── reporting/
└── main.py

Create modules incrementally; do not overbuild before the end-to-end POC works.