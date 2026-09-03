Project Memory --- UI Comparison
Project identity

Name: UI Comparison

Directory (host): ~/ui_comparison_workspace Directory (container): /workspace (Migrated from the original Windows path C:\Users\pralhadraj.joshi\Documents\ui_comparison)

Purpose: > Local AI-assisted Production UI vs Client UI comparison.

Critical distinction

This is separate from the previous SunNXT GT/audit project.

Old project context: - 103 screens - existing annotations - GT rules - XML investigations - annotation audits

Those can later be used as reference/evaluation/training-data sources. They are not the architecture of this new project.

Core product

Input: Production screenshot + Client screenshot

Output: - matched elements - missing elements - extra elements - text differences - geometry differences - position/size differences - class differences - structural differences - ordering differences - similarity score - visual report

Architecture
text
Production screenshot
 → PaddleOCR
 → local VLM
 → Fusion
 → UI JSON
 → UI Graph

Client screenshot
 → PaddleOCR
 → local VLM
 → Fusion
 → UI JSON
 → UI Graph

Production ↔ Client
 → JSON comparison
 → Graph comparison
 → geometry/text comparison
 → difference report
Data security

User has a strict requirement that data must not go online.

Therefore: - no cloud VLM - no cloud OCR - no screenshot uploads - all inference and artifacts local

Hardware

Migrated to a GPU Linux sandbox (Docker container), replacing the original Windows/Intel Iris Xe laptop setup.

text
Platform : Docker container (nvidia/cuda:12.6.3-base-ubuntu22.04)
Container: ui_compare_v2 (volume-mounted at /workspace,
           backed by ~/ui_comparison_workspace on the host)
GPU      : NVIDIA GeForce GTX 1070 (Pascal, compute capability 6.1)
VRAM     : 8 GB
Driver   : 580.173.02
CUDA (container toolkit): 12.6.3
PaddlePaddle: paddlepaddle-gpu 3.2.0 (cu126 build)

An earlier container (ui_compare) was created without a volume mount and was checked/confirmed empty before being abandoned. Only ui_compare_v2 should be used going forward — anything installed outside /workspace in a container without a volume mount will be lost if that container is removed.

Full environment details: see environment.md.

Environment
text
Python 3.11 (installed via apt inside the container)
Ollama (installed via ollama.com/install.sh; started manually with
        `ollama serve &`, no systemd in container)
qwen3-vl:4b
paddlepaddle-gpu 3.2.0 (cu126)
PaddleOCR
Pillow
NetworkX
Pydantic
python-dotenv
Ollama Python client
VLM

Current local model: qwen2.5vl:7b (switched from qwen3-vl:4b after benchmarking — see VLM benchmark section above for full reasoning).

Status: benchmarked on GPU, working structured JSON extraction with correct taxonomy classification. Next: fix text hallucination by setting text: null unless clearly legible English (defer exact text to OCR), then move to Phase 3 fusion.

Never switch to cloud VLM without explicit permission.

OCR

PaddleOCR / PP-OCRv6 family.

Purpose: - text - coordinates - confidence

OCR is not expected to understand semantic UI meaning alone.

OCR engine refactor (done)

OCR logic has been refactored out of a single script into a reusable module structure, per architecture.md §16:

text
src/ocr/engine.py      → OCREngine class, OCRElement/OCRResult dataclasses
src/ocr/visualize.py   → draw_ocr_result() — visualization kept
                          separate from OCR logic
scripts/run_ocr_test.py → thin entry point

Added fields per design.md §2 (previously the "next immediate technical task"):

center [cx, cy]
normalized_bbox [x/W, y/H, w/W, h/H]
confidence_tier ("high" >= 0.85, "medium" >= 0.60, "low" < 0.60) — implements rules.md §10 (never silently promote uncertain OCR to fact); visualized as green/orange/red boxes.
First screenshot

input/production/ss012.png

Resolution: 1080 × 2400

OCR benchmark

Windows/CPU run (original): 39 detections, ~41.37s CPU inference.

Windows/CPU rerun (after refactor): 39 detections, ~58.9s — same image/engine, likely machine load variance, not a regression.

High-confidence labels included: - Action Crime - Action Drama - Action Comedy - Action Romance - Free - Movies - Live TV - More - Search - Downloads - Home - Languages - Profile

Stylized movie-poster text was weaker (e.g. "Bgaihnili" for தேவரட்டம், "LJTZO" for டகால்சி) — expected and acceptable, since semantic interpretation belongs to the VLM (design.md §2). Note: OCR's own confidence score sometimes lands "medium" even when the recognized text is garbage (e.g. 0.60-0.80 on stylized Tamil titles) — confidence reflects character-shape certainty, not semantic correctness. Closing this gap is Phase 3 fusion's job.

GPU (GTX 1070) rerun: DONE. 39 elements, 1.59s — ~25-37x speedup over CPU (was 41-59s). Same 24 high / 7 medium / 8 low tier breakdown as CPU run — GPU migration changed speed only, not accuracy.

VLM benchmark (GPU, GTX 1070)

qwen3-vl:4b — rejected as primary candidate for structured extraction. This model has thinking mode baked into its chat template (cannot be disabled via think:false or /no_think — both tried, neither worked). On a screen with many repeated elements (movie cards), it deliberates individually over each one inside <think>, consistently exhausting the token budget (tested up to 6144) before ever producing the actual JSON answer (done_reason: "length", 0 elements parsed, every attempt). Generic-prompt timing (not representative of the real task): ~4.5-8s for a one-word answer, ~23-37s for free-text image description.

qwen2.5vl:7b — current working baseline. No forced thinking phase (thinking_length_chars: 0 every run) — the fix that unblocked structured extraction entirely. Image resized to max 1024-1280px before encoding (full 2400px height was producing ~3661 vision tokens and causing cudaMalloc failed: out of memory on the 8GB GTX 1070 with this larger 7B model).

Prompt version	Image max dim	num_predict	Time	Elements	Notes
v2-qwen2.5vl	1024px	2048	88.83s	18	Valid JSON, but nearly everything misclassified as content_card
v3-qwen2.5vl	1280px	3072	88.72s	21	Correct classification (section_title/category_tab/nav_item/logo all distinct); but non-English (Tamil) poster text was hallucinated — plausible-looking but fabricated text, not real transcription

Key finding: classification accuracy fixed by adding concrete per-class examples to the prompt + explicit "list every repeated element separately" instruction (v2 → v3). Text-hallucination on non-Latin scripts confirms the original design.md §4 split (OCR for exact text, VLM for semantic class) is necessary, not optional — VLM should not be trusted for precise text transcription, especially non-English. Next prompt iteration should set text: null unless clearly legible English, deferring exact text to OCR+fusion.

LocateAnything-3B-GGUF (community conversion) — rejected. Loads and runs fine on the GTX 1070 (no CUDA compatibility issue, ~54 tok/s), but the chat template in this specific GGUF conversion is broken — output includes a literal stray "None" string appended to every response (e.g. "Hello!None"), indicating a bug in the community conversion tooling, not a hardware or prompt issue. Also carries an NVIDIA non-commercial license, which would need review before any use beyond personal prototyping. Not pursued further; deleted from Ollama.

Current OCR artifacts
text
output/ocr/ss012_ocr.json
output/ocr/ss012_ocr_visualization.png
Next immediate technical task

Run the OCR engine on the new GPU/Linux environment to confirm parity with the Windows results, then resume VLM benchmarking on qwen3-vl:4b now that GPU access is available (previously paused).

JSON + Graph rule

Both are required: - JSON = canonical structured representation - Graph = relationships/structure

Use NetworkX for the POC. No Neo4j yet.

Comparison principle

Never use only pixel difference.

Use: - semantic class - text - bbox - position - size - IoU - normalized coordinates - spatial relationships - graph context - parent/child - ordering - confidence

Difference taxonomy

MATCH MISSING_IN_CLIENT EXTRA_IN_CLIENT CLASS_DIFFERENCE TEXT_DIFFERENCE POSITION_DIFFERENCE SIZE_DIFFERENCE GEOMETRY_DIFFERENCE STRUCTURAL_DIFFERENCE ORDER_DIFFERENCE UNCERTAIN

POC target

2--3 days: Production + Client → local OCR → local VLM → JSON → Graph → Comparison → Report

Do not spend the POC period cleaning all old annotations, processing all 103 screens, training a VLM, or building a graph database.

Continuation instructions

When another AI assistant continues: 1. Read this memory first. 2. Keep this project separate from the old GT/audit work. 3. Preserve local-only data processing. 4. Preserve JSON + graph. 5. Preserve OCR/VLM separation. 6. Build incrementally. 7. Record benchmark results. 8. Do not discard working components without reason. 9. Keep VLM implementation replaceable. 10. Optimize only after the end-to-end POC works. 11. Work only inside the ui_compare_v2 container (volume-mounted) — never the original unmounted ui_compare container. 12. Always give the exact command(s) to run alongside any code.