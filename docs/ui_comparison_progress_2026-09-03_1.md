# UI Comparison Project — Progress Summary (as of 2026-09-03)

## 1. Project Overview

**Name:** UI Comparison (local AI-assisted Production UI vs Client UI comparison)

**Directory (host):** `~/ui_comparison_workspace`
**Directory (container):** `/workspace`
(Migrated from the original Windows path `C:\Users\pralhadraj.joshi\Documents\ui_comparison`)

This project is **separate** from the earlier SunNXT GT/audit project (103 screens, existing annotations, GT rules, XML investigations, annotation audits). That older work is being reused only as reference/evaluation/training-data material — it is not the architecture of this new project.

**Core product:**
- Input: Production screenshot + Client screenshot
- Output: matched elements, missing elements, extra elements, text differences, geometry differences, position/size differences, class differences, structural differences, ordering differences, similarity score, visual report

**Architecture pipeline:**
```
Production screenshot → PaddleOCR → local VLM → Fusion → UI JSON → UI Graph
Client screenshot      → PaddleOCR → local VLM → Fusion → UI JSON → UI Graph
Production ↔ Client → JSON comparison → Graph comparison → geometry/text comparison → difference report
```

**Data security requirement:** Everything must stay local — no cloud VLM, no cloud OCR, no screenshot uploads, all inference and artifacts stay on-machine. Never switch to cloud VLM without explicit permission.

---

## 2. Hardware / Environment

Migrated from a Windows/Intel Iris Xe laptop to a GPU Linux sandbox (Docker container):

```
Platform : Docker container (nvidia/cuda:12.6.3-base-ubuntu22.04)
Container: ui_compare_v2 (volume-mounted at /workspace, backed by ~/ui_comparison_workspace on host)
GPU      : NVIDIA GeForce GTX 1070 (Pascal, compute capability 6.1)
VRAM     : 8 GB
Driver   : 580.173.02
CUDA (container toolkit): 12.6.3
PaddlePaddle: paddlepaddle-gpu 3.2.0 (cu126 build)
```

⚠️ An earlier container (`ui_compare`) was created **without** a volume mount and was confirmed empty before being abandoned. **Only `ui_compare_v2` should be used going forward** — anything installed outside `/workspace` in a non-mounted container is lost if that container is removed.

Software stack: Python 3.11, Ollama (manual `ollama serve &`, no systemd in container), qwen3-vl:4b, paddlepaddle-gpu 3.2.0, PaddleOCR, Pillow, NetworkX, Pydantic, python-dotenv, Ollama Python client.

---

## 3. Phase Progress

| Phase | Description | Status |
|---|---|---|
| 0 — Foundation | Project folder, Python venv, Ollama, qwen3-vl:4b, PaddlePaddle, PaddleOCR, Pillow, NetworkX, Pydantic, Ollama client | ✅ Complete |
| 1 — OCR Foundation | PaddleOCR text + bbox + confidence extraction, reusable engine | ✅ Complete (refactored) |
| 2 — Local VLM | Benchmark candidate models, structured extraction prompt | 🔄 In progress (qwen2.5vl:7b working baseline) |
| 3 — OCR + VLM Fusion | Combine OCR exact text/coords with VLM semantic class | ⏭ Next up |
| 4 — UI Graph | NetworkX graph of elements + relationships | Not started |
| 5 — Production vs Client Matching | Match by class/text/spatial/IoU/graph context | Not started |
| 6 — Difference Engine | Missing/extra/class/text/position/size/geometry/structural/order/uncertainty | Not started |
| 7 — Reporting | Summary + detailed findings + visual overlay | Not started |
| 8 — 2–3 Day POC | End-to-end minimum pipeline | In progress overall |
| 9 — Batch | Scale to many screens (incl. old 103-screen set) | Future |
| 10 — Detector | Train specialized UI detector (only after pipeline proven) | Future |
| 11 — Productionization | Dashboard, regression tracking, GPU inference, etc. | Future |

---

## 4. OCR Work (Phase 1) — Details

**Engine refactor (done):** OCR logic pulled out of a single script into a reusable module structure (architecture.md §16):
```
src/ocr/engine.py       → OCREngine class, OCRElement/OCRResult dataclasses
src/ocr/visualize.py    → draw_ocr_result() — visualization kept separate from OCR logic
scripts/run_ocr_test.py → thin entry point
```

**New fields added** (design.md §2):
- `center` [cx, cy]
- `normalized_bbox` [x/W, y/H, w/W, h/H]
- `confidence_tier` ("high" ≥ 0.85, "medium" ≥ 0.60, "low" < 0.60) — implements rules.md §10 (never silently promote uncertain OCR to fact); visualized as green/orange/red boxes.

**Test image:** `input/production/ss012.png` (1080 × 2400)

**Benchmark results:**
- Windows/CPU (original): 39 detections, ~41.37s
- Windows/CPU rerun (post-refactor): 39 detections, ~58.9s (machine load variance, not a regression)
- **GPU (GTX 1070) rerun: 39 elements, 1.59s — ~25–37x speedup over CPU.** Same 24 high / 7 medium / 8 low confidence-tier breakdown — GPU migration changed speed only, not accuracy.

Strong OCR text recognition on: Action Crime, Action Drama, Action Comedy, Action Romance, Free, Movies, Live TV, More, Search, Downloads, Home, Languages, Profile.

Weaker on stylized movie-poster text (e.g. "Bgaihnili" for தேவரட்டம், "LJTZO" for டகால்சி) — expected/acceptable since semantic interpretation belongs to the VLM. Note: OCR confidence sometimes lands "medium" even on garbage text (e.g. stylized Tamil titles) — confidence reflects character-shape certainty, not semantic correctness. Closing that gap is Phase 3 fusion's job.

**Current OCR artifacts:**
```
output/ocr/ss012_ocr.json
output/ocr/ss012_ocr_visualization.png
```

---

## 5. VLM Benchmarking (Phase 2) — Details

Tested on GPU (GTX 1070):

**qwen3-vl:4b — rejected as primary candidate.** Thinking mode is baked into its chat template and cannot be disabled (`think:false` and `/no_think` both tried, neither worked). On screens with many repeated elements (movie cards), it deliberates individually over each one inside `<think>`, consistently exhausting the token budget (tested up to 6144) before producing the JSON answer (`done_reason: "length"`, 0 elements parsed, every attempt).

**qwen2.5vl:7b — current working baseline.** No forced thinking phase (fix that unblocked structured extraction). Images resized to max 1024–1280px before encoding (full 2400px height was producing ~3661 vision tokens and causing `cudaMalloc failed: out of memory` on the 8GB GTX 1070 with this larger 7B model).

| Prompt version | Image max dim | num_predict | Time | Elements | Notes |
|---|---|---|---|---|---|
| v2-qwen2.5vl | 1024px | 2048 | 88.83s | 18 | Valid JSON, but nearly everything misclassified as `content_card` |
| v3-qwen2.5vl | 1280px | 3072 | 88.72s | 21 | Correct classification (section_title/category_tab/nav_item/logo all distinct); but non-English (Tamil) poster text was hallucinated — plausible-looking but fabricated, not real transcription |

**Key finding:** Classification accuracy fixed by adding concrete per-class examples to the prompt + explicit "list every repeated element separately" instruction (v2 → v3). Text hallucination on non-Latin scripts confirms the OCR/VLM split (design.md §4) is necessary, not optional — VLM should not be trusted for precise text transcription, especially non-English.

**Next prompt iteration:** set `text: null` unless clearly legible English, deferring exact text to OCR + fusion.

**LocateAnything-3B-GGUF (community conversion) — rejected.** Runs fine on GTX 1070 (~54 tok/s, no CUDA compatibility issue), but the chat template in this GGUF conversion is broken — every response has a literal stray `"None"` appended (e.g. `"Hello!None"`). Also carries an NVIDIA non-commercial license needing review before use beyond prototyping. Not pursued further; deleted from Ollama.

---

## 6. UI Taxonomy (locked 2026-09-02, in `prd_section7_update.md`)

Reduced from an original 22-class taxonomy to a **16-class taxonomy**, based on visual/functional analysis of the 103-image labeled benchmark set. Rationale: several original classes were visually indistinguishable or functionally redundant, making classification unnecessarily hard for the VLM without adding diagnostic value.

### Final 16-class taxonomy

| Class | Source class(es) | Sample count (n=103 imgs) |
|---|---|---|
| content_card | content_card | 657 |
| tab_item | nav_item + category_tab + detail_tab + carousel_filter | 459 |
| overlay_badge | badge + episode_badge + duration | 302 |
| section_title | section_title | 193 |
| button | button | 105 |
| cast_card | cast_card | 95 |
| icon | icon | 94 |
| metadata_text | metadata_text | 88 |
| navigation_bar | navigation_bar | 71 |
| celebrity_card | celebrity_card | 47 |
| title | movie_title + series_title | 28 |
| description | description | 21 |
| search_bar | search_bar | 13 |
| rank_number | rank_number | 4 |
| text_input | text_input | 4 |
| logo | logo | 6 |

### Key merge/keep/drop decisions

- **tab_item** (merged): nav_item, category_tab, detail_tab, carousel_filter differ mainly by screen position (captured separately via bbox/geometry), not visual appearance.
- **overlay_badge** (merged): badge, episode_badge, duration are all small corner tags on a card; differ by text content (preserved via OCR fusion, not class).
- **title** (merged): movie_title and series_title are visually identical (same bold white-on-black caption style); no reliable visual cue distinguishes them in a crop alone.
- **cast_card vs. celebrity_card** (kept separate, NOT merged): visually distinct (cast_card = small circular headshot + name/credits row; celebrity_card = full-width rectangular promo banner) and contextually distinct (cast_card on detail screens; celebrity_card on home/browse). Needed to diagnose "wrong card type shown for this screen" issues.
- **rank_number, text_input** (kept, low-confidence flag): in scope per product decision, but only 4 labeled examples each — treat eval/fine-tuning results on these as directional only, not statistically reliable, until more labeled data exists.

### Superseded — original 22-class taxonomy

content_card, nav_item, badge, section_title, button, cast_card, icon, metadata_text, category_tab, navigation_bar, celebrity_card, detail_tab, duration, carousel_filter, movie_title, description, search_bar, episode_badge, logo, rank_number, text_input, series_title

Kept for historical reference — the original 103-image label set (YOLO format, Label Studio export, `classes.txt`/`notes.json`) uses this 22-class id scheme. The class-remap (old → new) must be applied at UI-JSON conversion time; original label files are not re-annotated in place. The earlier 32 GT rules from the SunNXT project remain reference/evaluation material only (rules.md §1/§11), not part of this taxonomy.

---

## 7. Core Design Principles (carried through the project)

- **JSON + Graph both required:** JSON = canonical structured representation; Graph = relationships/structure. Using NetworkX for the POC (no Neo4j yet).
- **Never use pixel diff alone.** Compare using: semantic class, text, bbox, position, size, IoU, normalized coordinates, spatial relationships, graph context, parent/child, ordering, confidence.
- **Difference taxonomy:** `MATCH`, `MISSING_IN_CLIENT`, `EXTRA_IN_CLIENT`, `CLASS_DIFFERENCE`, `TEXT_DIFFERENCE`, `POSITION_DIFFERENCE`, `SIZE_DIFFERENCE`, `GEOMETRY_DIFFERENCE`, `STRUCTURAL_DIFFERENCE`, `ORDER_DIFFERENCE`, `UNCERTAIN`
- **POC target (2–3 days):** Production + Client → local OCR → local VLM → JSON → Graph → Comparison → Report. Explicitly out of scope for POC: cleaning all old annotations, processing all 103 screens, training a VLM, building a graph database.

---

## 8. Next Immediate Technical Task

Fix VLM text hallucination by setting `text: null` unless clearly legible English (defer exact text to OCR), then move into **Phase 3: OCR + VLM Fusion**.

---

## 9. Continuation Instructions (for any AI assistant picking this up)

1. Read project memory first (`memory.md`).
2. Keep this project separate from the old GT/audit work.
3. Preserve local-only data processing (no cloud OCR/VLM).
4. Preserve JSON + graph dual representation.
5. Preserve OCR/VLM separation (OCR = exact text, VLM = semantic class).
6. Build incrementally.
7. Record benchmark results.
8. Do not discard working components without reason.
9. Keep the VLM implementation replaceable.
10. Optimize only after the end-to-end POC works.
11. Work only inside the `ui_compare_v2` container (volume-mounted) — never the original unmounted `ui_compare` container.
12. Always give the exact command(s) to run alongside any code.

---

*Compiled from project docs (`memory.md`, `phases.md`, `prd_section7_update.md`) as of 2026-09-03.*
