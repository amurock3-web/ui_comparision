# Project Memory — UI Comparison

**This is the single source of truth for current project state.** `rules.md` holds durable
constraints, `architecture.md`/`design.md` hold stable technical design, `environment.md` holds
the infra spec, `prd_section7_update.md` holds the locked taxonomy — none of those four track
day-to-day progress anymore. This file does. Update it whenever phase status, environment, or
the next task changes; do not let a second copy of this table grow anywhere else.

*Last verified against the actual code tree: 2026-09-07.*

## Project identity

**Name:** UI Comparison
**Purpose:** Local AI-assisted Production-UI vs Client-UI comparison.

**Critical distinction:** separate from the earlier SunNXT GT/audit project (103 screens,
existing annotations, GT rules, XML investigations). That work is reused only as
reference/evaluation/training-data material — it is not this project's architecture.

**Core product:**
- Input: Production screenshot + Client screenshot
- Output: matched elements, missing elements, extra elements, text differences, geometry
  differences, position/size differences, class differences, structural differences, ordering
  differences, similarity score, visual report

**Architecture pipeline** (see `architecture.md` for full detail):
```
Production screenshot → PaddleOCR → local VLM → Fusion → UI JSON → UI Graph
Client screenshot      → PaddleOCR → local VLM → Fusion → UI JSON → UI Graph
Production ↔ Client    → JSON comparison → Graph comparison → geometry/text comparison → report
```

**Data security:** everything stays local — no cloud VLM, no cloud OCR, no screenshot uploads.
Never switch to a cloud VLM without explicit permission (`rules.md` §2).

## Current environment — read this before assuming which machine is "current"

Two environments have been documented for this project at different points; they are **not**
the same checkout and this file does not assert one has replaced the other:

- **Windows, local** — `C:\Users\pralhadraj.joshi\Documents\ui_comparison`. This is the checkout
  actually being worked in as of 2026-09-04 (confirmed: git commits and the active dev session
  both run here, on CPU, no CUDA).
- **Docker / Linux / GPU (`ui_compare_v2`)** — set up earlier for GPU-accelerated OCR/VLM
  benchmarking (NVIDIA GTX 1070, volume-mounted at `/workspace`). Full spec in `environment.md`.
  Benchmark numbers below that are labeled "GPU" came from that container, not from this
  Windows checkout.

**Before starting GPU-dependent work, confirm which environment you're actually in** — don't
assume the Docker container from the benchmark numbers below is the one currently checked out.

## Phase status (verified against `src/`, not aspirational)

| Phase | Description | Status |
|---|---|---|
| 0 — Foundation | venv, Ollama, PaddleOCR/PaddlePaddle, Pillow, NetworkX, Pydantic | ✅ Done |
| 1 — OCR | `src/ocr/engine.py` + `visualize.py` | ✅ Done |
| 2 — VLM | `src/vlm/engine.py` + `prompts.py` + `visualize.py`; classify + content_card grounding, both working | ✅ Done |
| 3 — Fusion | `src/fusion/fuse.py` + `visualize.py` | ✅ Done, substantially reworked 2026-09-07 — see below |
| 4 — UI Graph | `src/graph/build.py` + `visualize.py` (new 2026-09-07) | ✅ Done |
| 5 — Matching | `src/comparison/matcher.py` | ✅ Built + tested, wired into `main.py` |
| 6 — Difference engine | `src/comparison/differ.py` | ✅ Built + tested, wired into `main.py`; position/size tolerance doesn't yet distinguish `bbox_source="vlm_grounded"` from `"ocr_exact"` — designed 2026-09-07, not implemented (see open findings below) |
| 7 — Reporting | `src/reporting/report.py` + `visualize.py` | ✅ Built 2026-09-07 (was previously just a docstring stub — earlier "built + tested" claim in this file was wrong, corrected here). `ReportGenerator` (counts + similarity % + findings) and `draw_comparison_result` (side-by-side production/client with differences highlighted). No unit tests yet (`tests/test_reporting.py` is still a placeholder). |
| 8 — End-to-end POC | `src/main.py` now takes `--production-image`/`--client-image` (CLI changed from single-image to a real pair) and runs the full chain: OCR → VLM(classify+ground) → Fusion → Graph → Matcher → DifferenceEngine → Report → visualization | ✅ **Ran successfully end-to-end 2026-09-07** against `input/production/ss012.png` and a synthetic client image (WALTER poster card blanked out) — 68.3% similarity, correctly caught the removed card/title as `MISSING_IN_CLIENT`. See "POC first run" below for real findings and open issues it surfaced. |
| 9 — Batch (103 screens) | Not started — out of POC scope, see `rules.md` §12 | Future |
| 10 — Detector | Not started — only after pipeline is proven | Future |
| 11 — Productionization | Not started | Future |

**Why Phases 5-7 aren't wired in yet:** `input/client/` has no screenshot. `main.py`'s
`process_screen()` only runs OCR → VLM → Fusion → Graph and explicitly logs "Comparison stage
not run"; the comparison/reporting code and its tests already exist and are ready to be called
the moment a client screenshot is supplied — this is not undone work, it's an unblocked
integration step.

**Uncommitted work, still (2026-09-07):** nothing from this session — or the substantial Phase
3-7 build-out that predates it — is committed to git yet. `git status` at session start already
showed 5 staged doc files, 18 modified-unstaged source files, and 10 untracked files; today's
session added more changes on top of the same already-modified files (the fusion rework, 4
script/main.py fixes, 2 new `visualize.py` files under `graph/`) without committing any of it.
Treat committing as overdue, not optional, before this grows further.

Every module also has a config surface already calibrated with real rationale, not just
design-doc placeholders — see `config/config.yaml` (fusion thresholds, matching weights, VLM
prompt version, JSON-schema-vs-free-form decoding tradeoff, etc.). Treat those values as the
current tuning, not TODOs.

## VLM benchmarking (Phase 2) — history

`qwen3-vl:4b` — rejected. Thinking mode is baked into its chat template and cannot be disabled
(`think:false` and `/no_think` both tried). On screens with many repeated elements it
deliberates per-element inside `<think>`, exhausting the token budget before producing JSON.

`qwen2.5vl:7b` — **current model** (`config/config.yaml: vlm.model`). No forced thinking phase.
Prompt evolved through v2 → v3 → the current `v2_qwen2.5vl_classify_only`
(classify-only: class/text/description/approximate_location, no bbox — VLM-provided bboxes for
every class were found non-deterministic across repeated calls, general grounding rejected; see
`src/fusion/fuse.py` docstring). Text-field null-hallucination (VLM returning `text: null` even
for elements OCR read with high confidence) was traced to schema/grammar-constrained decoding
biasing a nullable field toward its null branch (arXiv:2408.02442); fixed by
`use_json_schema: false` (free-form generation + parsing).

**content_card grounding, narrower scope, tested separately (2026-09-07):** a second, narrow
grounding call — `ground_content_cards_experimental()`, prompt `v3_qwen2.5vl_ground_content_cards`,
Qwen2.5-VL's native `bbox_2d` format, content_card only — was determinism-tested with 3 back-to-back
runs on `ss012.png` at `temperature: 0`. Result: near-identical within that tight sequence (~1px
agreement, all 4 poster rows correctly boxed every time), but ~4% normalized position drift showed
up against an earlier same-session sample (row Y-position shifted ~100px, box count varied 12 vs
16 depending on whether a thin partially-cut-off edge column got its own box). Verdict: good enough
to use as the sole content_card geometry source (replaced the old grid-inference fallback
entirely, see Fusion rework below), but the comparison stage must treat it with a looser position
tolerance than OCR-exact geometry — not yet implemented in `differ.py`.

`LocateAnything-3B-GGUF` — rejected. Runs fine on the GTX 1070 but this community GGUF
conversion's chat template appends a literal `"None"` to every response; also NVIDIA
non-commercial licensed. Deleted from Ollama.

`Molmo` / `Molmo2` (AllenAI) — considered 2026-09-07, deferred, not tested. Specifically strong at
pointing/grounding (its headline strength), which is directly relevant to this project's
persistent grounding pain points (content_card geometry drift, row-detection failures). Not
pursued now because: (1) no GGUF quantization found on Hugging Face from any of the usual
quantizers (bartowski, unsloth, TheBloke) and it isn't in Ollama's library — Molmo's non-standard
vision-token pooling likely isn't supported by llama.cpp, so it can't be pulled/run through Ollama
the way every other model here has been; (2) using it would mean loading it via the `transformers`
library directly — a second, parallel inference backend alongside `VLMEngine`'s Ollama calls, not
a `config/config.yaml: vlm.model` swap; (3) this Windows checkout is CPU-only, and an 8B
multimodal model under `transformers` on CPU would be far slower than even today's slow Ollama CPU
calls — the GPU Docker box (`ui_compare_v2`) would be needed instead. Also: Molmo's grounding
format itself differs from Qwen2.5-VL's `bbox_2d` corners — points normalized to a 0-100 scale
embedded in the prompt, boxes as center+width/height — so adopting it would need a new prompt
template and a new response parser (mirroring `ground_content_cards_experimental()`'s pattern),
not just a different model string. Revisit if: a working GGUF/Ollama-compatible build appears, or
grounding quality becomes enough of a blocker to justify the `transformers` + GPU-box detour.

## OCR benchmarking (Phase 1) — history

Test image: `input/production/ss012.png` (1080 × 2400).
- Windows/CPU: 39 detections, ~41-59s.
- GPU (GTX 1070, `ui_compare_v2` container): 39 elements, 1.59s — ~25-37x speedup, same
  24 high / 7 medium / 8 low confidence-tier breakdown (GPU changed speed only, not accuracy).

## Fusion (Phase 3) rework — 2026-09-07

Starting point was a real bug: the old deterministic grid-inference approach for content_card
geometry (OCR section_title anchors define row bands, each row's card count divides the row width
evenly) silently dropped an entire row of cards on `ss012` — its `approximate_location` bucketing
only distinguishes top/middle/bottom, which can't address a 4th row. Led to a full rework:

1. **content_card geometry made grounding-only, mandatory.** `_infer_card_bboxes`/
   `_find_row_anchors` (the grid-inference code) deleted entirely. `FusionEngine.fuse()` now
   requires a `grounded_cards` argument (a `VLMGroundedResult` from
   `ground_content_cards_experimental()`) — no fallback. Every caller of `fuse()` had to be
   updated to call the grounding function first: `main.py`, `run_comparison_test.py`,
   `run_fusion_test.py`, `run_graph_test.py` were fixed; **`tests/test_fusion.py`'s 14 call sites
   were not** (still broken, explicitly deferred).
2. **Matching generalized to every VLM class.** The `TEXT_MATCHABLE_CLASSES` allowlist (which
   restricted SoM-id/text-similarity/zone-fallback matching to ~10 classes) was removed —
   `icon`/`cast_card`/`celebrity_card`/`navigation_bar` previously got no matching attempt at all
   and stayed ungrounded even when an exact-text OCR match existed (e.g. an "icon" labeled
   "Search" never grabbed OCR's own "Search" box).
3. **`parent_id` hierarchy.** Unmatched OCR text whose center falls inside a content_card's bbox
   (poster titles, subtitle text) now gets `parent_id` set to that card instead of floating as a
   top-level element.
4. **Explicit uncertainty.** Any VLM element with no match after every fallback, or OCR text with
   neither a match nor a parent card, is tagged `metadata.match_status = "uncertain"` — preserves
   the signal instead of leaving it implicit in `bbox=None`/`class=None` (rules.md §10).
5. **Location-string parsing fixed.** `_location_zone_bounds()` used to resolve a malformed
   multi-token `approximate_location` string (e.g. `"bottom-middle-right"`, seen in production —
   not in the prompt's documented 2-token vocabulary) via a fixed-priority substring `if/elif`
   chain, silently picking a zone with no signal the input was ambiguous. Rewritten to
   tokenize + classify per axis; an axis with zero or >1 recognized tokens is now left
   unrestricted instead of guessed.

**Known open bug, found but not fixed (2026-09-07):** a zone-tie-break bug in
`_match_ocr_for_text`/`_location_zone_bounds` — the fixed-thirds zone split (`H/3`, `2H/3`)
doesn't align with real row Y-positions, so a title/tab sitting near a zone boundary can lose its
own correct OCR match to a different, merely-fuzzy-similar candidate that happens to fall inside
the (misaligned) zone. Observed twice: a cascading section_title mislabel ("Action Drama" →
mislabeled "Action Comedy" → real "Action Comedy" mislabeled "Action Romance" → real "Action
Drama" orphaned) and the bottom-nav "Free" tab repeatedly losing its OCR box to a poster badge
with identical text. Root cause is shared with item 5 above in one case (a wrong-not-malformed
location token) but is structurally a `_match_ocr_for_text` tie-break problem, not fixable by
parsing alone. Left for a future session to decide on.

## Graph (Phase 4) — visualization added 2026-09-07

`src/graph/visualize.py` (new) — `draw_graph_result()`, mirroring `fusion/visualize.py`'s
convention (colour-by-confidence-tier boxes, thin gray box for unclassified nodes). Draws only
`CONTAINS` edges by default — every other relationship type is generated for every sibling pair
(design.md §6) and renders as unreadable clutter at typical node counts; pass
`relationships=(...)` for more. Wired into `scripts/run_graph_test.py`.

**Useful pattern discovered while testing this:** graph building and visualization need only a
fused `UIDocument` — no OCR/VLM calls. For iterating on `build.py`/`visualize.py` against a screen
already processed once, reconstruct `OCRResult`/`VLMResult`/`VLMGroundedResult` from the saved
JSON in `output/{ocr,vlm}/` instead of re-running the full (15-20 minute) pipeline. Runs in well
under a second. No permanent script for this exists yet — done ad hoc in a scratchpad script so
far.

## POC first run — 2026-09-07

First real end-to-end run: `python -m src.main --production-image input/production/ss012.png
--production-screen-id ss012 --client-image input/client/ss012.png --client-screen-id ss012`.
Client image is synthetic (`input/client/ss012.png` — a copy of the production screenshot with
the WALTER poster card painted over, to get a known, deliberate difference to test against; not a
real client screenshot yet). Result: 68.3% similarity, 60 elements compared (41 MATCH, 6
MISSING_IN_CLIENT, 5 EXTRA_IN_CLIENT, 4 SIZE_DIFFERENCE, 3 TEXT_DIFFERENCE, 1 CLASS_DIFFERENCE).
The actual planted change (WALTER card removed) was correctly caught as `MISSING_IN_CLIENT`.

**Real noise found, not yet addressed:** several nav-bar items ("Movies", "Live TV", "Free") that
are genuinely unchanged between the two runs still showed up as a false MISSING_IN_CLIENT +
EXTRA_IN_CLIENT pair instead of a MATCH — because the classify-only VLM call labeled them
`navigation_bar` on the production run and `tab_item` on the client run (same screen, same
elements, two separate VLM calls, different classification). `matcher.py`'s class score treats a
class mismatch harshly enough that an otherwise-identical pair doesn't match. This is a real
source of false positives for this comparison tool specifically — two runs of the *same* screen
can already disagree on classification — not something invented for this test; worth deciding how
to handle (e.g. loosen the class score for known-similar classes, or improve prompt consistency).

## Next immediate task

In priority order, all still open as of 2026-09-07:
1. **Commit today's (and the pre-existing) uncommitted work** — see "Uncommitted work" note above.
   Overdue, keeps getting deferred. (Note: `report.py`/`visualize.py`/`main.py` changes from the
   POC-completion push above are also uncommitted.)
2. **Decide how to handle VLM classification inconsistency between separate calls** — see "POC
   first run" above. Real false-positive source, not hypothetical.
3. **Fix `tests/test_fusion.py`'s 14 broken call sites** (`grounded_cards` now required).
4. Get a **real** client screenshot (the current one is synthetic/self-modified) into
   `input/client/`.
5. Decide on the zone-tie-break bug (Fusion rework section above) — fix or leave.
6. Implement the `differ.py` position-tolerance split for `bbox_source="vlm_grounded"` vs
   `"ocr_exact"` (designed 2026-09-07, see VLM benchmarking history above).
7. Write tests for `report.py`/`visualize.py` (`tests/test_reporting.py` is still a placeholder).

## Continuation instructions (for any AI assistant picking this up)

1. Read this file first, then check its "Last verified" date against `git log` — if code has
   moved since, trust `src/` over this table and update it.
2. Keep this project separate from the old SunNXT GT/audit work.
3. Preserve local-only data processing (no cloud OCR/VLM).
4. Preserve JSON + graph dual representation.
5. Preserve OCR/VLM separation (OCR = exact text, VLM = semantic class).
6. Do not assume the GPU/Linux/Docker environment is the one currently checked out — verify.
7. Do not re-implement comparison/reporting — they exist; the blocker is a missing input file.
8. Record new benchmark results here, in the relevant history section above.
9. Do not discard working components without reason.
10. Always give the exact command(s) to run alongside any code.
11. `FusionEngine.fuse()` requires a `grounded_cards` argument (a `VLMGroundedResult` from
    `VLMEngine.ground_content_cards_experimental()`) as of 2026-09-07 — there is no grid-inference
    fallback anymore. Any new caller must call the grounding function first.
12. For fast iteration on fusion/graph logic against an already-processed screen, reuse the saved
    JSON in `output/{ocr,vlm}/` instead of re-running OCR/VLM — see "Graph (Phase 4)" section
    above for the pattern.
