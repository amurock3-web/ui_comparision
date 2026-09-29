# Project Memory — UI Comparison

**This is the single source of truth for current project state.** `rules.md` holds durable
constraints, `architecture.md`/`design.md` hold stable technical design, `environment.md` holds
the infra spec, `archive/prd_section7_update.md` holds the locked taxonomy — none of those four track
day-to-day progress anymore. This file does. Update it whenever phase status, environment, or
the next task changes; do not let a second copy of this table grow anywhere else.

**Acceptance spec (added 2026-09-17):** `test_cases_pass_fail.md` defines what the tool must
decide — PASS / REVIEW / FAIL per check, Critical/Major/Minor severity, a screen verdict, and an
ignore list for dynamic content. It treats the **client design as the reference** and production
as the thing under test. Thresholds there are proposed defaults, not confirmed by the manager.

*Last verified against the actual code tree: 2026-09-18 (OCR text calibration, detector Python
fallback, per-script screen ids, graph NEAR edges + alignment epsilon).*

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
Production screenshot → YOLO detector + PaddleOCR → Fusion (--vlm: VLM if uncertain) → UI JSON → UI Graph
Client screenshot      → YOLO detector + PaddleOCR → Fusion (--vlm: VLM if uncertain) → UI JSON → UI Graph
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
| 10 — Detector | `src/detector/` + `models/ui16_v1` (YOLOv8s, val mAP50 0.877) wired into `main.py` as the primary class/bbox source; fusion via `FusionEngine.fuse_detections()` | ✅ Integrated 2026-09-17 — see "Detector integration" below |
| 11 — Productionization | Not started | Future |

**Why Phases 5-7 aren't wired in yet:** `input/client/` has no screenshot. `main.py`'s
`process_screen()` only runs OCR → VLM → Fusion → Graph and explicitly logs "Comparison stage
not run"; the comparison/reporting code and its tests already exist and are ready to be called
the moment a client screenshot is supplied — this is not undone work, it's an unblocked
integration step.

**Commits (2026-09-17):** the earlier backlog is committed on branch `detector-integration`
(verdict layer, detector integration), not yet merged into `main`.

Every module also has a config surface already calibrated with real rationale, not just
design-doc placeholders — see `config/config.yaml` (fusion thresholds, matching weights, VLM
prompt version, JSON-schema-vs-free-form decoding tradeoff, etc.). Treat those values as the
current tuning, not TODOs.

## Detector integration (Phase 10) — 2026-09-17

- **Model:** `models/ui16_v1` — YOLOv8s fine-tuned in the `UI_Detection_model_training` repo
  on the 103 labelled screens (83 train / 20 val). Val mAP50 0.877, mAP50-95 0.703. Weak
  classes: `rank_number` (0.62, 4 instances), `button` (0.72), `icon` (0.70),
  `metadata_text` (0.71); `rank_number`/`text_input`/`logo` are flagged `low_confidence_class`.
- **Runs in its own Python** (`config/detector.yaml`'s `python_path`, overridden by
  `UI_DETECTOR_PYTHON`; see `environment.md` §9) because
  ultralytics/torch must not share an environment with paddle. `config/detector.yaml`
  `engine: yolo` (default) or `gt_stub` (hand labels, labelled screens only).
- **New `main.py` flow per screen:** detector → OCR → `fuse_detections(dets, ocr)`; only with
  `--vlm` and only if any element is `uncertain` → `VLMEngine.analyze()` →
  `fuse_detections(dets, ocr, vlm)`. Without `--vlm`, uncertain elements → REVIEW. The VLM was
  made opt-in because the status-bar clock triggered it on every screen; status-bar text is now
  `metadata.ignored = "status_bar"` (top 4% of the screen, config `fusion.status_bar_height_norm`)
  and always PASS. On ss012 only 2 items stay uncertain: the false 0.32 card and "VILLAN" (text on
  a cut-off top poster the detector missed).
  `ground_content_cards_experimental()` is no longer called; detector boxes replace it.
- **Verified 2026-09-17, without running OCR or VLM** (saved `output/ocr/ss012_*_ocr.json`
  plus the real detector):
  - YOLO ran twice on `input/client/ss012.png` → byte-identical output (the VLM grounding it
    replaces drifted ~4%).
  - It found 33 elements vs 35 hand labels (19 vs 21 content_card; all other classes exact).
    ss012 is one of the training screens, so this is optimistic.
  - Self-comparison: 100% / PASS with both `gt_stub` and `yolo`.
  - production vs client ss012: `gt_stub` PASS 91.9%, `yolo` REVIEW 90.0% (one size REVIEW).
- **Fusion cleanup (2026-09-17, user decision):** poster text is not needed, so OCR text on
  content/cast/celebrity cards is dropped from the fused UI JSON (its ids are kept in the card's
  `metadata.ocr_ids`; the raw OCR JSON keeps the text). The false 0.32 card is now
  `ignored="overlapped_by_higher_confidence"`. On ss012, fusion went from 54 to 36 elements with only 1
  uncertain ("VILLAN"). Production vs client: REVIEW, 97.2%, the only finding is the VILLAN size
  change. Self-comparison is 100% PASS. The blanked WALTER poster is still not caught (needs the
  pixel check).
- **Floating tab bar fix (2026-09-17):** YOLO labels the "Movies / Live TV / Free / More" pill as
  one `tab_item`, the same as the hand labels, plus a false 0.32 `content_card` on top of it. Fusion was
  giving the tab labels to that card and to the real posters under the pill, so they were skipped as
  dynamic card text. Now OCR text prefers a non-container box, low-tier containers never
  hold text, and joined text uses line-aware reading order → tab text "Movies Live TV Free More".
  The VLM was not used: its fallback can't overrule a detector class, and it flip-flopped
  navigation_bar ↔ tab_item on this screen.
- **Unseen-screen check (2026-09-17):** the 28 screenshots in
  `Documents/ss_data/mobile/{home,search}` that are not in the training set (checked by hash and
  by image similarity; 4 near-copies were skipped). Detector only; the box images are in
  `output/detector/unseen/`. 761 detections: 81% high, 14% medium, 5% low confidence.
  - Reliable: content_card, section_title, bottom navigation_bar + its 5 tabs, the floating
    "Movies / Live TV / Free / More" tab_item, standard "Free" badges. It also handled a new
    screen type (language picker) sensibly.
  - Weak, worth retraining: the "SUN NXT / SUN NXT SHORTS" toggle (labelled button,
    section_title, tab_item or content_card on different screens, often low confidence; its
    second half missed); "Free" badges in unusual spots (called icon at 0.34); crown badges
    (missed or icon at 0.28); a "Dolby Vision" tile called overlay_badge; a poster called
    celebrity_card; the X close icon on the language picker missed; the floating tab bar only
    0.51 when it overlaps a poster.
- **Detector + OCR fusion ran end to end on 2026-09-18** (`python -m scripts.run_fusion`,
  `input/production/ss031.png`, exit 0, `output/fusion/test13_ss031_fusion.*`). 34 detections +
  56 OCR observations → **36 elements, 0 uncertain**, 3 ignored (status bar `3:55`/`A`, plus a
  0.34 `4K` badge dropped as `overlapped_by_higher_confidence`). Classes: content_card 12,
  overlay_badge 13, tab_item 7, navigation_bar 1, icon 1. Only the four complete poster rows
  became cards; the partially cut-off bottom row got none. ss031 is one of the 103 labelled
  screens, so this is not an unseen-screen result.
  Text noise worth knowing before text comparison is trusted: `'-inSUN NXT SHORTS'`,
  `'SUN NT Home'` (logo glyph merged into the tab label), a badge read as `'W'`, and a 0.45
  `icon` whose text is the CJK glyph `个`. None were flagged `uncertain`, and `tab_item` *is* in
  `static_text_classes`, so `'SUN NT Home'` would raise a real TEXT_DIFFERENCE against a clean
  client render.
- **Not yet done:** a full `main.py` run (fusion alone is now proven; the comparison half still
  needs a client screenshot); retraining with the weak cases above.
  `differ.py` still has the `vlm_grounded` bands, used only by the legacy `fuse()` path.

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

## OCR text accuracy vs APK ground truth — 2026-09-18

`scripts/calibrate_text_tolerance.py` measures PaddleOCR's text accuracy against the literal
strings the app rendered, using the six `uiautomator dump` XML files in
`SunNXT-UI-Metadata/apk_analysis/window_xml/` as the oracle (they carry exact `bounds` plus the
real `text`). OCR output is cached in `output/ocr/calibration/`, so re-runs are instant.

**Result — static chrome (the only text E1 compares): 28 exact, 0 slips.** PaddleOCR made no
character errors at all on tabs, section titles and buttons. Dynamic content: 36 exact, 4 slips,
and all four are *truncations* of long strings (`'Prabhu Deva'` → `'Prabhu D'`), not misreads.

**Consequence: `differ.py`'s `_within_one_edit` REVIEW band was left unchanged.** The measurement
says it almost never fires, and when it does it downgrades FAIL → REVIEW (a human still sees the
finding), so it is not masking defects. 28 samples from one app on one OCR engine is too thin to
justify retuning a verdict threshold. Revisit if a real production-vs-client run produces false
text FAILs.

**Important limitation of these XML dumps — read before using them as training labels.** They
were taken without a visibility flag (attributes are `bounds`, `class`, `text`, `resource-id`,
`clickable`, … — there is no `visible-to-user`), and `uiautomator dump` reports views that are
laid out but not drawn. The app keeps its floating "Movies / Live TV / Free / More" tab bar in the
hierarchy at fixed bounds on *every* screen, so on ss017 (the Profile screen) the hidden "Live TV"
node sits exactly over the visible "Version : 4.1.110". 4 of 47 static strings and 17 of 92
dynamic ones are such ghosts; `classify()` in the script filters them by rejecting a match further
than half the longer string. ss005 additionally shows a consistent one-row vertical offset —
its XML was captured at a different scroll position than the screenshot.

Net: **the constant nav-bar geometry across screens is partly an artifact, not a feature** — the
same view objects persist whether or not they are drawn. Any future capture should record
visibility (`uiautomator dump --compressed`, or a dump tool that emits `visible-to-user`) and be
taken at the same scroll position as the screenshot, or XML-derived boxes will teach the detector
to predict elements that are not on screen.

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
   updated to call the grounding function first: `main.py`, `run_comparison.py`,
   `run_fusion.py`, `run_graph.py` were fixed; **`tests/test_fusion.py`'s 14 call sites
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
`relationships=(...)` for more. Wired into `scripts/run_graph.py`.

**Useful pattern discovered while testing this:** graph building and visualization need only a
fused `UIDocument` — no OCR/VLM calls. For iterating on `build.py`/`visualize.py` against a screen
already processed once, reconstruct `OCRResult`/`VLMResult`/`VLMGroundedResult` from the saved
JSON in `output/{ocr,vlm}/` instead of re-running the full (15-20 minute) pipeline. Runs in well
under a second. Since 2026-09-18 this is a real script, `scripts/build_graph_from_fusion.py`
(newest `output/fusion/*.json`, or a given one, plus optional relationship names) →
`output/graph/testN_<screen>_graph.json`, `_graph_diagram.png` (new `draw_graph_diagram`, no
screenshot) and `_graph_overlay.png` (when the screenshot can be found).

**Graph changes 2026-09-18** (`src/graph/build.py`, `config/config.yaml` `graph:`):
- `alignment_epsilon_norm` 0.01 → 0.02. 0.01 (10.8px at 1080 wide) was inside detector jitter:
  ss031's left card column spans x=9.1..21.6, so one column split into two ALIGNED_WITH groups.
- Elements fusion marked `ignored` (status bar, swallowed low-confidence boxes) stay as nodes
  but get no edges, same as `bbox=None` elements.
- New `NEAR` edges (`knn_k: 5`, 0 disables): each element linked both ways to its K nearest
  neighbours by Euclidean distance over both bbox corners (`docs/graph_paper.pdf` §3.2; K=5 is
  the paper's mobile value). Threshold-free, so jitter cannot drop them. **Nothing consumes NEAR
  yet** — it is the substrate for the paper's §3.3 recursive neighbour matching.

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

## Next immediate technical task

(Updated 2026-09-21; the earlier "run OCR on GPU / resume qwen3-vl:4b"
task is done — GPU OCR parity confirmed, qwen2.5vl:7b chosen.)

Finish Phase 3 fusion (current blocker: OCR↔box association). Option
under consideration: detector-first targeted crop OCR
(architecture.md §4a). Then complete the MVP end-to-end on one pair.

## Next immediate task

Re-prioritized 2026-09-17 around `test_cases_pass_fail.md` (its "v0 scope": A1, A3, B1, B2, C1,
D1, D2, E1). In priority order:
1. ~~Commit the outstanding work~~ — done 2026-09-17 on branch `detector-integration`.
2. **Verdict layer in `differ.py`/`report.py`** — *implemented 2026-09-17, tests not run yet*
   (`tests/test_comparison.py` type names updated to `MISSING/EXTRA_IN_PRODUCTION`):
   - Flip the reference side so client = truth, and report "missing/extra in production" (B1/B2).
   - Add PASS/REVIEW/FAIL + severity per finding and the screen-verdict rule.
   - Replace single thresholds (`position_threshold_norm`, `size_ratio_threshold`) with
     PASS/REVIEW/FAIL bands (C1/C2). The looser band for `bbox_source="vlm_grounded"` goes here.
   - Ignore list (§H): no text compare for children of `content_card` or `rank_number` values;
     compare text only for static classes (tab_item, button, section_title, search_bar) — E1.
3. **Screen-level checks A1 (orientation) and A3 (theme)** — plain image math, no OCR/VLM.
4. **Mutation test set** instead of waiting for a real client screenshot: a script that makes
   labeled defect copies of `ss012` (rotate, darken bg, hue-shift Play, paint out a tab, …) plus
   expected verdicts. Cache OCR/VLM JSON per image or run on the GPU box (CPU run ≈ 15-20 min).
   Note: the current synthetic pair (WALTER card removed) is a B9 card-count case — Minor/REVIEW
   under the spec, not a clear FAIL.
5. **VLM class flip-flop** (`navigation_bar` ↔ `tab_item`, see "POC first run") — under C4 a class
   change is a Major FAIL, so treat known-confusable pairs as REVIEW. Plus the REVIEW path (§I):
   use fusion's `match_status="uncertain"`, low confidence, and "<50% matched → cannot compare".
6. **Colour D1/D2** (ΔE2000 on matched element crops; `opencv-contrib-python` already gives Lab
   and SSIM, no new dependency), then ORDER_DIFFERENCE for B3/B4 via existing `ORDERED_BEFORE` edges.
7. Housekeeping: fix `tests/test_fusion.py`'s 12 failing legacy `fuse()` tests (they omit
   `grounded_cards`; still failing 2026-09-17); write `tests/test_reporting.py`.
7a. Detector: ~~run the detector-first pipeline end to end with `engine: yolo`~~ — done
   2026-09-18 for detector + OCR + fusion (see Phase 10 above); `main.py`'s comparison half still
   needs a client screenshot. Measure it on screenshots outside the training set; collect more
   `rank_number`/`text_input`/`logo` examples and retrain.
7b. Graph: element matching via `graph_paper.pdf` §3.3 recursive neighbour matching over the
   `NEAR` edges (added 2026-09-18, unused so far).
8. Later: the rest of the spec (B5-B9, C3, D3-D7, E2-E7, F, G). Zone-tie-break bug only if the
   mutation runs show it causing false B1/E1 fails.

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
11. `main.py` uses `FusionEngine.fuse_detections()` (detector-first). The legacy
    `FusionEngine.fuse()` still requires a `grounded_cards` argument (a `VLMGroundedResult` from
    `VLMEngine.ground_content_cards_experimental()`); there is no grid-inference fallback.
12. For fast iteration on fusion/graph logic against an already-processed screen, reuse the saved
    JSON in `output/{ocr,vlm}/` instead of re-running OCR/VLM — see "Graph (Phase 4)" section
    above for the pattern.
13. Every `scripts/run_*_test.py` takes the image as an optional argument and derives the screen
    id from its file name (`SCREEN_ID = IMAGE_PATH.stem`), so a different screen needs no file
    edit and output can no longer be misnamed:
    `python -m scripts.run_fusion input/production/ss031.png`.
    `run_comparison.py` takes the pair: `<production.png> <client.png>`.
14. `scripts/_test_utils.py` forces UTF-8 on stdout when imported. OCR returns Tamil script, `₹`
    and stray CJK glyphs, and the Windows console is cp1252 — without it a script dies on
    `print` *after* the real work is saved. Keep that import in any new run script.

## Session log 2026-09-21 — decisions and proposals

**Decided**
- TypeSafe Jev (cloud decision model) not adopted — cloud, text-only,
  no reasoning (rules.md §18). Local equivalent = class refiner.
- Everything below is parked until the MVP runs end-to-end
  (rules.md §20), except targeted OCR, which may help the fusion
  blocker now.
- New checks are prioritized by frequency in real QA tickets.

**Proposed (pending approval)**
- Class refiner: local logistic regression / LightGBM on geometry +
  OCR + context (+ YOLO) features (design.md §18)
- Detector-first targeted crop OCR (architecture.md §4a)
- rank_number → rule-derived card attribute, not a class
  (design.md §20)
- Three-layer ontology v3 (prd_section7_update.md); v2 16 classes stay
  locked for now
- `COLOR_DIFFERENCE`, `ATTRIBUTE_DIFFERENCE` (rules.md §8); color via
  CIELAB ΔE (design.md §21); other extractors backlog (design.md §22)
- Synthetic test pairs for end-to-end validation (design.md §23)
- Multi-app data + model-assisted labeling (phases.md Phase 9-10)

**Open questions**
- Do clients provide real app screenshots or design mockups?
- Which regression types are most common in real QA tickets?

## Phase 12 — comparison-stage fixes — 2026-09-24

Prompts in `phase12_matching_fix_prompts.md`. Triggered by the SunNXT app runs
`output/app/20260922_121255` (lang) and `20260921_165919` (home): 0.0% similarity despite correct
pairs, whole-panel moves reported per element, detector box wobble flagged as findings.
- **12.0** `run_comparison` and `src/app.py` save both fused UIDocuments; new
  `scripts/rematch.py` reruns graph → matcher → differ → report from them in seconds
  (`output/rematch/testN_*`). Same JSON twice = self-compare.
- **12.1** Similarity is an element count (design.md §12): matched / (matched + missing + extra),
  §H-ignored content out of the denominator, plus `clean_pairs`/`clean_percent`. The old
  `total_compared` (record count) is gone; `difference_records` keeps it for debugging. HTML
  report and web UI show one headline: "Matched X of Y elements (Z%) · clean · missing · extra · ignored".
  `tests/test_reporting.py` rewritten for this (no longer a placeholder).
- **12.2** Per-container group shift + second matching pass (architecture.md §9); new
  `GROUP_SHIFT` finding (C1); members judged on residual. Config `matching.group_shift`.
  `_is_dynamic` moved to `matcher.py` (shared by matcher and differ).
- **12.3** (box-wobble pixel floor) not started — needs same-build screenshot pairs.

Not yet verified: unit tests and the lang/home rematch were not run as part of this doc update.

## Class refiner experiment (design.md §18) — 2026-09-22

Started ahead of the MVP by decision. Scripts only; outputs in `output/class_refiner/`.
Config: `config/class_refiner.yaml` (22→16 remap + detector-repo `label_corrections.yaml`).
Scripts: `build_refiner_dataset`, `train_class_refiner`, `compare_yolo_vs_refiner`,
`refiner_progress` (live progress bar). Charts + `report.html` per run.

**Data:** 2186 GT boxes / 103 images (export in `UI_Detection_model_training/data/renamed`).
rank_number, text_input (4 each) excluded from training. Crop OCR on 1365 non-card boxes
took ~85 min on CPU (~16 crops/min); cached in `ocr_cache.json`.

**test1_logreg** — 5-fold GroupKFold by image, GT boxes, all 103 images: accuracy 0.710,
ECE 0.067. Confusable group recall: button 0.70, tab_item 0.84, overlay_badge 0.80,
icon 0.53, metadata_text 0.83. Cards collapse (content_card recall 0.50, 270 → celebrity_card):
no OCR on cards + geometry-only features cannot separate card types.

**test2_compare_logreg** — the fair test: YOLO ui16_v1 vs refiner on YOLO's 20 val images,
refiner retrained on the other 83, refiner fed YOLO boxes + crop OCR. 375 matched boxes (IoU ≥ 0.5).
- Correct class on matched boxes: YOLO 0.968, refiner 0.675. Confusable group: YOLO 0.953,
  refiner 0.912. button: 0.792 both (24 matched, **7 more buttons YOLO never boxed**).
- Refiner fixes YOLO 2, breaks YOLO 112 (mostly content_card → celebrity_card), both wrong 10.

**Conclusion:** once YOLO boxes an element it almost always has the right class. The 0.58
button recall is mostly *missed boxes*, which a class refiner cannot fix. Refiner not adopted
as-is. Better levers for button: more button training data / check YOLO conf threshold
on buttons. Caveats: 20 images, 24 buttons; YOLO best.pt was selected on these val images
(slightly optimistic for YOLO).
Feature gap found: duration regex misses `01:10:00` style (4 badges → description).

## Phase 12 — matching fix (similarity metric + group shift) — 2026-09-24

Driven by `docs/phase12_matching_fix_prompts.md`. Three separate causes were behind
"FAIL, 0.0% similarity" on every real production-vs-client pair.

**12.0 — fast iteration.** `scripts/rematch.py` re-runs matcher → differ → report from saved
fused JSONs in ~1-2 s, no detector and no OCR (it never imports `src/pipeline.py`).
`scripts/run_comparison.py` and `src/app.py` now save `*_production_fused.json` /
`*_client_fused.json`. `UIDocument` stores no image path, so rematch resolves the screenshot from
`--production-image`/`--client-image`, then a sibling `production_*`/`client_*` file, then
`find_screenshot`. Same JSON twice = self-compare.

**12.1 — the similarity number was arithmetically wrong.** It divided MATCH *records* by *all*
Difference records, so one matched pair with three sub-findings counted as 0 matched and 3
compared. Now: `matched_pairs` (distinct id pairs) over `matched_pairs + missing + extra`, with
`clean_pairs`/`clean_percent` alongside and `total_compared` renamed `difference_records`.
A pair whose every record is `ignored` (§H dynamic content) is excluded from the denominator by
user decision — otherwise poster tiles inflate the similarity of a screen nobody checked.

**12.2 — a whole panel moving was judged per element.** On the language pair the sheet sits
~136 px lower in the client while the header behind it moved ~+21 px. Anchors (matched pairs with
the same class and either text >= 0.9 or IoU >= 0.5) vote per layout-graph container; the shift is
the median of the votes; still-unmatched elements are re-scored in a second pass with the
production box moved back by *their* container's shift. New `GROUP_SHIFT` difference (spec C1)
reports the move once; members are judged on the residual.

Three things were got wrong first and are worth not repeating:
1. Anchors were attributed only to their immediate container. The layout tree splits a panel into
   rows of two, so every container fell below `min_anchors` and the walk-up found nothing. Anchors
   now vote in every container above them. `min_anchors` is 2, not 3, for the same reason.
2. Median absolute deviation was used as the agreement test. MAD tolerates up to half the votes
   disagreeing, so the screen root accepted a sheet-wide shift while two header tabs voted
   against, and those tabs got false position FAILs. Now outlier anchors are trimmed at
   `max_spread_norm` and a quorum of survivors is required — which still lets a single member that
   moved extra keep its own C1 finding.
3. Excluding the screen root outright then killed recall (7 matches again), because the tree hangs
   `Save` and the subtitle directly off the root. The root is allowed, but only as the last
   resort: nearest container wins, so the header keeps its own +21 px.

**Measured, `scripts/rematch` on the saved fused docs (2026-09-24):**

| pair | before | after |
|---|---|---|
| sunnxt_prod_lang vs sunnxt_live_lang | FAIL 0.0%, 7 matches, 22 missing, 16 extra, 47 findings, 6 POSITION | FAIL **62.1%**, 18 matches, 7 missing, 4 extra, 20 findings, **1** POSITION, 3 GROUP_SHIFT |
| sunnxt_prod vs sunnxt_live | FAIL 0.0%, ~11 matches | FAIL **50.0%**, 13 matches, 11 missing, 4 extra, 10 SIZE |
| self-compare (same fused JSON twice) | PASS 100% | PASS 100%, 23 matches, only MATCH records |

The language pair's GROUP_SHIFTs: `grp_0001` +15.8/+20.9 px (header, REVIEW), `screen`
+3.1/-136.2 px (10 members, FAIL), `grp_0004` -6.7/-139.3 px (sheet tabs, FAIL). The `screen` and
`grp_0004` findings describe the same physical move at two levels — redundant but not wrong;
suppressing a group whose shift equals its ancestor's is unfinished polish.

`matching.group_shift.enabled: false` reproduces the pre-12.2 output and is covered by a test.

**Tests:** `tests/test_reporting.py` rewritten (8 tests, real `UIElement`/`UIDocument` — the old
`SimpleNamespace` fakes would have raised in `confidence()`), `tests/test_group_shift.py` new
(8 tests). 39 pass across comparison/reporting/group_shift/schema. The suite still has **15
pre-existing failures** (14 in `test_fusion.py`, 1 in `test_graph.py`) — confirmed present at HEAD
with the Phase 12 changes stashed, so they are untouched by this work. The earlier note in this
file saying 12 was an undercount.

**Still open after this:** tab capitalisation (`SUN NXT` vs `SUNNXT`) needs text normalisation, not
a threshold; `SIZE_DIFFERENCE` on small chrome is detector box wobble awaiting 12.3's pixel floor
(needs `input/jitter/<screen>_a|_b` pairs, same screen same build seconds apart — not captured
yet); OCR noise on the client side ("WORLDWIDE", "ONLV ON", "SLAILD") and a status-bar string
leaking in as a `section_title` because `fusion.status_bar_height_norm` only ignores OCR text that
lands in *no* detection; `STRUCTURAL_DIFFERENCE` fires on most matched pairs and remains a noise
generator.

## Phase 13 — noise reduction + 10 new checks — 2026-09-24

Driven by a demo deadline. Coverage went **9 -> 19 of 41** spec checks, and the language pair's
findings fell from 47 (this morning) to 16. Three agents wrote self-contained modules of pure
functions with their own tests and touched no integration point; `differ.py`, `report.py`,
`html_report.py` and `config.yaml` were wired up afterwards in one pass. That division worked —
the Phase 12 lesson holds: delegate work that is specified in advance, keep measurement-driven
work inline.

**Noise (inline, measured on the saved fused docs):**
- `STRUCTURAL_DIFFERENCE` now off by default (`comparison.report_structural_difference`). It has
  no spec row and fired on 9 of 18 matched pairs; two screens with different element counts can
  never share a graph neighbourhood, so it only restated B1/B2. Still available for debugging.
- Case/spacing-only text differences are now **E3** (`TEXT_STYLE_DIFFERENCE`, REVIEW) instead of a
  Major E1 FAIL. `SUN NXT` vs `SUNNXT` was the motivating case.
- Dynamic-only matched pairs leave the similarity denominator (user decision).

**New checks, all running on the real pairs:**
- `src/comparison/screen_checks.py` — A1 orientation, A2 blank/broken, A3 theme, A5 scaling. Pure
  image math, no detector. A2's `edge_density_min` and A3's `dark_luminance_max` are **not
  calibrated against real screenshots**. A5 is the screen-level half only: "UI zoomed >15%" needs
  matched element sizes, not canvas dimensions.
- `src/comparison/color_checks.py` — D1 brand, D2 background, D5 badge, CIELAB ΔE2000, validated
  against four Sharma/Wu/Dalal (2005) Table 1 reference pairs to 1e-3. D2 masks every detected
  element before sampling, so a poster cannot be read as the background. **D4 is not claimed**:
  which tab *should* be highlighted is structural, not a colour measurement.
- `src/comparison/layout_checks.py` — B3 section order, B4 tab order, B5 alignment, B8 clipping,
  read off the layout graph, which already carried all of it unused. B5 fires on how much an
  alignment *loosened*, because the client's own `ALIGNED_WITH` clusters are built at
  `alignment_epsilon_norm` 0.02, looser than B5's 1.5%.

**Measured after all of it (`scripts/rematch`, no OCR):**

| pair | verdict | similarity | findings |
|---|---|---|---|
| sunnxt_prod_lang vs sunnxt_live_lang | FAIL | 62.1% | 16 (was 47) |
| sunnxt_prod vs sunnxt_live | FAIL | 50.0% | 10 SIZE, 12 COLOR, rest small |
| self-compare | PASS | 100.0% | only MATCH records |

Coverage on the language pair: A1,A2,A3,A5 PASS; B1 REVIEW; B2 FAIL; B3,B4 PASS; B5 FAIL;
B8 PASS; B9 REVIEW; C1,C2 FAIL; C4 PASS; D1 FAIL; D2,D5 PASS; E1 PASS; E3 REVIEW.

**A colour hazard found and left honest.** The home pair reports 12 D1 findings, production chrome
sampling at rgb(99-111) against the client's rgb(37-45). A guard was added
(`_shows_artwork_through`) that skips D1/D5 when the layout graph marks the element
`layer="overlay"` or OVERLAPS a card, since translucent chrome over dynamic artwork samples the
poster, not its own fill. **It did not change these findings** — the bottom nav overlaps the last
card row by ~1 px, far below `float_min_overlap`, so it is not an overlay. Sampling the production
image at the *client's* box still returns rgb(111,105,105), so the boxes are right and the pixels
really do differ at the same location. Whether that is a genuine chrome change between builds or
artwork through a translucent bar cannot be settled from pixels — it needs a human to look. Do not
present those 12 as confirmed defects without checking.

**Tests:** 66 pass across comparison/reporting/group_shift/screen/color/layout; full suite 118
pass with the **same 15 pre-existing failures** (14 `test_fusion.py`, 1 `test_graph.py`).

**Still missing / blocked:**
- The C2 size pixel floor (12.3) is still blocked on `input/jitter/<screen>_a|_b` — same screen,
  same build, seconds apart. Size is the largest remaining noise source: 10 findings on the home
  pair, 5 on the language pair.
- `numpy` and `opencv-contrib-python` are **not in `requirements.txt`** — present only
  transitively via paddleocr. Pin them before this ships.
- Not built: A4, B6, B7, C3, D3, D4, D6, D7, E2, E4-E7, F1-F4, G1-G3.
- ~~`make_benchmark` / `run_benchmark` still never run.~~ Run three times on 2026-09-24; see below.

## Phase 13.1 — benchmark-driven noise cuts — 2026-09-24/25

The known-defect benchmark (22 cases: 19 defect, 3 identity) was run three times during Phase 13
(`output/benchmark/test1..3_benchmark/results.json`):

| run | caught | caught as other | missed | identity clean | false alarms | false alarms by type |
|---|---|---|---|---|---|---|
| test1 | 9 | 8 | 2 | 3/3 | 26 | B5 18, C2 5, B1 2, B4 1 |
| test2 | 12 | 5 | 2 | 3/3 | 27 | B5 18, C2 5, B1 2, B4 1, D1 1 |
| test3 | 13 | 4 | 2 | 3/3 | 15 | B5 6, C2 5, B1 2, B4 1, D1 1 |

The two misses are F3 (check not built). test3 still showed three problems, each fixed in the
differ afterwards (config under `comparison` / `comparison.layout`, all default on):

- **A1 buried in noise.** A rotated screen reported A1 plus every element as moved/resized
  (A5/B1/B2/B9/C1/C2) — all true, all artefacts of the rotation. Screen-level checks now run
  first; a Critical FAIL (A1, A2) stops the comparison and emits one `ELEMENT_COMPARISON_SKIPPED`
  record (spec id `info`, REVIEW) naming why. A3/A5 are Major and never stop it.
  `stop_on_critical_screen_failure`.
- **B5 collateral.** Removing one tab un-aligns its neighbours, so one removal read as B1 + two B5.
  An `ALIGNMENT_DIFFERENCE` is now dropped when any of its elements is already named by a
  MISSING/EXTRA/POSITION/SIZE/GROUP_SHIFT finding (`layout.drop_alignment_collateral`). And since
  `ALIGNED_WITH` is a chain, one broken column gave one B5 per link; same-axis rows sharing an
  element are merged into one finding with the worst offset (`layout.merge_alignment_chains`).
- **B4 swaps caught as E1.** On a tab swap the matcher paired by position on two of three screens,
  so the order looked intact and it read as two label changes. `layout_checks._swapped_labels`
  now finds matched items in one bar whose production and client texts are exchanged and reports
  B4 regardless of pairing; the report says "X and Y have traded places".

**Not yet measured.** The benchmark has not been re-run since these changes; re-score from the
saved per-case fused docs with `scripts/rematch` before paying for a full run. Tests not run either.

## Phase 14 — Applitools-style ideas — 2026-09-25

Plan: `phase14_applitools_ideas_prompts.md` (outside the repo). The two pure modules were written
by subagents in isolated worktrees; wiring into differ/report/config was done inline in one pass
(the Phase 13 split). **Nothing below has been run** — no pytest, no rematch, no benchmark — so
there are no before/after numbers yet.

- **14.1 status bar: diagnosed, no code.** Scanned all 56 saved fused JSONs: every status-bar
  string is already `ignored="status_bar"` (e.g. `section_title "16:01 redBus O"`, 100% inside the
  band). The Phase 12 "leak" does not reproduce on any saved doc, so `ignore_regions` / `regions.py`
  was not built. The one near-top unignored text is "VILLAN" (ss012, 38% in the band), a real title.
- **14.0 nested GROUP_SHIFT merge** (`differ._merged_shift_chains`, `matching.group_shift.merge_nested`).
  A container whose shift matches its nearest shifted ancestor's (within `max_spread_norm`) is one
  move; reported once under the outermost non-root container, with `merged_groups`. Anchors are the
  chain's max, not sum — anchors vote in every container above them. Expected on the lang pair:
  `screen` + `grp_0004` → one sheet shift; header stays separate.
- **14.2 pixel-verified size** (`src/comparison/pixel_geometry.py`, `comparison.pixel_verify`).
  Every SIZE finding now carries `details.pixel_check` (tight-box sizes, ratio diffs, reliable,
  confirmed). **`enabled: false`**: measuring only. Next step is to read the pixel_check values off
  a rematch of both pairs, agree thresholds, then enable (drops a finding when both sides are
  reliable and agree within `size_bands.pass`).
- **14.3 issue grouping** (`src/reporting/grouping.py`, `reporting.group_findings: true`). Report
  gains `issues` + `summary.issues`; HTML shows an Issues table above Findings when grouping
  collapses anything. Findings, verdict and similarity unchanged. The 12 D1 findings may land in
  more than one issue: the key includes class, and colours must be within D1's pass band (dE 3).
- **Not done:** 14.4 accepted differences (deferred until runs are reviewed regularly), 14.5
  see-through chrome (measure-only, optional).
- New tests (not run): `tests/test_group_shift.py` (+5), `tests/test_pixel_geometry.py`,
  `tests/test_grouping.py`.

**14.2 margin measured (2026-09-25, rematch, `enabled: false` throughout).** 15 SIZE findings over
both pairs; "would drop" = both sides reliable and pixel diff <= `size_bands.pass` 0.05.

| margin_frac / min_px | would drop | notes |
|---|---|---|
| 0.15 / 4 (first try) | 2 (X, Free) | pixel diff often *bigger* than box: Search 0.057 -> 0.207 h, TV Shows 0.027 -> 0.156 h; crop pulled in neighbours |
| **0.05 / 2 (kept)** | **4** (Sun NXT, X, Profile, Free) | pixel diff tracks the box on the rest; Search 0.248 -> 0.187 |
| 0.0 / 0 | 2 (X, Free) | tab crops have no background ring: 4 of 5 lang tabs unreliable |

Reading: at 0.05 the pixel check agrees with the box on most remaining findings (SUN NT Home
0.174/0.168, TV Shows 0.265/0.258, Select-the-languages 0.161/0.140), so those look like real size
differences between the mockup and production, not detector wobble. Downloads (0.075/0.077) and
Live TV (0.143/0.151) too. Still `enabled: false`; switching it on would remove 4 of 15.

**Decisions 2026-09-25:** `pixel_verify.enabled: true` (expected: home pair drops Profile and Free,
lang pair drops Sun NXT and X; not yet confirmed by a rematch). **14.5 not adopted:** the verdict on
the home pair is FAIL regardless, the colour is sampled from tab items whose icon and label would
read as "texture" on solid chrome too, and a human glance at the 12 D1 findings settles them more
cheaply than a heuristic.

## Phase 15/16 Wave 1 — new checks + launcher — 2026-09-25

Plan: `phase15_features_and_ui_prompts.md` (outside the repo), built in waves because most prompts
share differ.py / config.yaml / app.py and several depend on each other. Wave 0 ran the suite and a
rematch first and found one real bug: `grouping.py` crashed on findings without the usual details
(now left ungrouped, with a test). Wave 1 = five parallel worktree agents writing only new files,
wired in afterwards in one pass. Full suite: 165 pass, the same 15 pre-existing failures.

- **F3 broken image** (`image_checks.flatness`, `comparison.image`): production card with luminance
  std <= 5 and edge density <= 0.01, unless the matched design card is flat too. Measured: every
  benchmark blank_poster card std 0.0/edges 0.0; flattest real card anywhere std 17.4 (production
  27.2). Rematch: **all 3 blank_poster cases now caught** (the benchmark's two misses + one
  caught-as-other), all 3 identity cases still clean.
- **F1/F2 logo/icon** (SSIM, bands from the spec): wired, but idle — no detection on the SunNXT
  pairs is class `logo` or `icon`.
- **D7 contrast / D3 text colour** (`contrast_checks`, `comparison.contrast`): k-means text split,
  WCAG ratio; passes at 4.5:1 or when production >= design ratio - 0.5. Skipped over artwork and on
  unreliable splits. Measured on matched static text: lang pair "SUNNXT SHORTS" 1.29:1 vs design
  2.63:1, text dE 12.3 (D7 FAIL + D3 FAIL); home pair "Profile" text dE 5.1 (D3 REVIEW). Everything
  else passes. WCAG's large-text rule not applied (box height includes icons).
- **E4 language** (`script_checks`, `comparison.language`): matched label with a different dominant
  script -> Critical, instead of E1. No findings on the real pairs (same-language builds). The
  language picker is 50% Latin, so a screen-level script is None there — no screen-level E4 built.
- **15.6 ticket export**: `python -m scripts.export_tickets <report.json>` -> UTF-8-BOM CSV, one
  row per issue; columns in `config/ticket_export.yaml` still need the team's real sheet columns.
- **16.0 launcher**: `UI Compare.bat`, `start.sh`, `scripts/make_shortcut.ps1`, `src/health.py`
  (`GET /health`, chips in the page), `--port` with fallback, `--no-browser`. Not launched yet.

## Phase 15/16 Wave 2 + 14.4 — rules, levels, app pages, acceptances — 2026-09-25

- **15.0 match levels + regions** (`src/comparison/regions.py`, `comparison.match_levels`). STRICT /
  LAYOUT (skip D, E, F) / IGNORE_COLORS (skip D) / NONE. Most specific wins: smallest covering
  region (>= min_overlap of the element) > `config/screen_rules/<client screen id>.yaml` > default.
  The status-bar band is a default NONE region (14.1 folded in; one mechanism). A skipped finding
  becomes PASS with `details.ignored = "match level X"`; coverage says "skipped (X)", never PASS.
  STRICT with no rules file gives byte-identical findings (no MATCH_LEVEL record is added then).
  `scripts.rematch --match-level LAYOUT` on the lang pair: 23 -> 17 findings (D/E/F skipped).
- **15.1 dynamic text + floating regions.** E1 compares a value's FORMAT when the design text fully
  matches a pattern (duration, episode, price, date); production matching none -> E1 FAIL with
  `expected_format`. The prompt's `rating` and `count` patterns were dropped: `count` matches any
  bare number and `rating` matched OCR noise ("A"). Checked against every saved OCR text: no
  static-text label matches any pattern yet, so this is idle on today's screens. FLOATING regions
  widen C1's bands for elements inside to `max_offset_norm` (fraction of the diagonal).
- **Bug found and fixed:** every config reader used `read_text()` without an encoding, i.e. cp1252
  on Windows; the ₹ in the price pattern came out garbled. All seven `config.yaml` readers now read
  UTF-8.
- **16.1 app package** (subagent): `src/app/` (server, runs, static JS/CSS), pages Compare / History
  / Help / Results, `GET /api/runs`, whitelisted file serving.
- **14.4 accepted differences** (`src/comparison/accepted.py`, `scripts/accept_finding.py`,
  `comparison.accepted_differences`). Entry keyed by client screen + type + class + text + centre
  (±0.02) + signature (production text / production colour within D1's pass band). Report gains
  `client_screen`, per-finding `production_bbox_norm` / `client_bbox_norm` / `client_center_norm`,
  `accepted`, `stale_acceptances`, `summary.accepted`. End-to-end check: accepting the lang pair's
  "SUNNXT" E3 finding took it from 23 to 22 findings on the next rematch (temp file removed after).
- Full suite: 191 pass, the same 15 pre-existing failures.
- **15.5 baseline library, batch, history** (subagent): `src/baselines.py` (baselines/<screen>/<device>/
  <language>/ with client image, client_fused.json, meta.json; device from aspect ratio),
  `scripts/add_baseline.py` (~45-90 s, runs detector+OCR on the design once; `--list` instant),
  `scripts/run_comparison.py --baseline <key>` (~45 s: production only), `scripts/run_batch.py`
  (resumable, one failure never stops it, summary.json/html with new/fixed counts),
  `src/reporting/history.py` (new / fixed / still_open by type + client id + signature),
  `src/pipeline.compare_documents` (shared graph->match->differ->report; checked in-process on the
  lang pair: same 23 findings as rematch). Staleness hash narrowed (by me) to detector.yaml + the
  ocr/fusion/vlm sections of config.yaml: comparison thresholds change often and are applied at
  compare time, so hashing the whole file would have marked every baseline stale on any tweak.
  No baseline has been added for real yet.
- **16.2 results page + 16.4 rules editor** (subagent, `src/app/actions.py`, `results.js`,
  `rules.js`): canvas side-by-side with click-to-highlight, issue cards with verdict/family
  filters, Accept / Ignore region / Mark as bug (each logged in `<run>/actions.json` and undoable;
  ignore-region and rules saves keep timestamped `.bak` backups), in-process Re-check with a
  match-level dropdown writing `report_N.json/html` (never overwrites), downloads incl. tickets CSV.
  Rules page: draw/move/resize regions on the client image, match level, dynamic-text patterns with
  a test-against-OCR button, validated save, "Try on last run" before/after counts. Runs made
  before today have no `*_bbox_norm`, so boxes appear only after a Re-check. Not clicked through
  in a browser yet.
- **16.3 baselines + batch pages + job queue** (subagent, `src/app/jobs.py`, `library.py`,
  `library.js`): FIFO queue with visible positions (one job at a time; replaces the 409), Baselines
  page (add via queue, delete archives meta + fused to baselines/_archive/), Compare with a saved
  baseline (production-only detector+OCR), Batch page (auto-pair, per-row override, unpaired rows
  not run, live table), Results history strip (new / fixed / still open vs the previous run of the
  same screen). Batch table lives in memory only (lost on restart; the runs stay in History).
- **Final check 2026-09-25:** full suite 222 pass, the same 15 pre-existing failures (14
  test_fusion, 1 test_graph). Rematch: lang pair FAIL 62.1%, home pair FAIL 50.0%, self-compare
  PASS 100%. Not done: no browser click-through of the app, no real add_baseline / batch / benchmark
  run, ticket columns still defaults.

## Phase 14b — false-alarm fixes from the Trending Search run — 2026-09-25

Run `output/app/20260925_145307` (production `sunnxt_live_search` vs design `sunnxt_pre_search`):
FAIL, 29 findings, about 19 of them false. Split: three subagents on disjoint files (F6 PDF print
CSS, F7 real benchmark case, F4 `text_cleanup.py`), the shared matcher/differ/layout work inline.

| step | Trending Search findings |
|---|---|
| before | 29 (FAIL) |
| F1 badges on a card are dynamic | 17 |
| F2 rescue pass 3 | 20 (search bar matched once, but its own E1/D3 appeared) |
| F3 + F4 + F5 + layout clip fix + unread-text rule | **16 (FAIL)** |

- **F1** `_is_dynamic`: >= `graph.loose_containment_overlap` of the box on a poster card = dynamic,
  since fusion gives detector badges no parent (all 12 badges had `parent_id` None).
- **F2** `matcher._rescue`: same-class leftovers within 0.03 of the diagonal, each other's nearest by
  a margin, AT LEAST ONE SIDE LABELLED (text-less cards in a grid paired with their neighbour at
  0.0297 in the first version — caught by test_group_shift). Near-ties -> REVIEW (`ambiguous`).
- **Clip root cause** (`layout._mark_clipped`): an element whose centre lies inside an occluder is
  part of it, not behind it — the Home tab's icon pokes above the nav bar and was flagged clipped.
- **F3** FAILs on clipped elements -> REVIEW (original kept in details); B8 on poster cards REVIEW.
- **F4** text-only glyph cleanup in E1 and the matcher's text score ("9 Languages" -> "Languages").
- **E1 on an unread label** (one side no OCR text) is REVIEW "no text read on one side", not FAIL.
- **F5** D3/D7 need text on both sides, skip exact logo labels (`contrast.logo_wordmarks`), and on
  a tab_item measure only the bottom `tab_text_band` (0.4). Search-tab D3 kept (now REVIEW).
- **F6** print CSS: the side-by-side image is on page 1 (was pushed to page 2); thead repeats.
- **F7** `input/benchmark/real/trending_search/` + `python -m scripts.run_benchmark --real-only`
  (~10 s, cached fused JSONs): **0 false alarms, 0 misses, 3 unlisted** (search bar C1/C2/E1
  REVIEW); verdict FAIL vs expected REVIEW. The two FAILs left are D1 on the Home logo (production
  rgb(166,67,88) vs design rgb(133,79,89)) and C2 on the Search tab (+24% height: the design has a
  selected-state dot production lacks) — both look like real differences; the manifest's
  expected REVIEW may be what needs changing. Human call.
- Other pairs: lang 23 -> 21, home 41 -> 38 (badges on cards), self-compare PASS 100%.
- Full suite: 272 pass, the same 15 pre-existing failures.

**Committed 2026-09-25** as `ae58696` on branch `phase-13.1-16` (pushed to origin; not merged into
main yet). Open: decide whether the Trending Search case's expected verdict should be FAIL (the
remaining D1 Home-logo and C2 Search-dot findings look real) or those two need more work.
Also open: `docs/migration_ubuntu_gpu.md` (move to the Ubuntu GTX 1070 box inside the sandboxed
Docker setup) is written but not carried out; no browser click-through of the app; no real
add_baseline / run_batch / full benchmark run; ticket columns in `config/ticket_export.yaml` are
still the defaults.

## Phase 17 — detector box wobble (jitter), measure first — 2026-09-28

Plan: `phase17_jitter_prompts.md` (outside the repo), revised after review: measure before
building, a batched detector, a static per-class tolerance tried before a runtime per-element one.
Caution carried into the plan: not every small C2 on a mockup-vs-production pair is wobble; the
14.2 margin table showed the pixel tight-box agreeing with the box on Downloads (0.075 / 0.077).

Built (nothing run yet: no pytest, no benchmark, no detector):
- **17.0** `run_benchmark --cached <testN_benchmark>`: re-scores a saved run from its per-case fused
  JSONs, no detector/OCR; a missing JSON is an error, never a silent OCR fall-back. test3's cache
  covers all 22 current cases. Gives the free "before" number: C2/B1 false alarms on untouched
  elements of defect cases are the wobble signal (test3: C2 5, B1 2, under the older differ).
- **17.1** `yolo_worker.py` takes several `--image` paths (model loaded once, one JSON line per
  image); `detect_many(paths)` on every detector, `detect()` now routes through it.
  `src/detector/jitter.py`: 8 variants (shift 1,0 / 0,1 / 2,2 / 3,3; resample 0.85 / 0.95;
  jpeg 70 / 90) and a pure `measure_wobble` giving, per original box, matched_in, class_flips and
  the max |deviation| in the checks' own units (size = C2's max rel w/h, diag = C1's centre move
  over the screen diagonal). `scripts/measure_jitter.py`: per-class/per-source table
  (sunnxt / jiohotstar / mockup), flags classes whose p95 x sqrt(2) crosses the C1/C2 pass band.
  Output `output/jitter/testN_measure/`. Tests: `tests/test_jitter.py` (fake detections).

**Results 2026-09-28.** pytest (jitter, benchmark_real, detector): 17 pass, 1 skip (real-YOLO test).

17.0 `run_benchmark --cached test3_benchmark` -> `test6_benchmark` (seconds): caught 15/19, as other
3, missed 1, identity clean 3/3, **false alarms 5** (C2 3, D1 1, B4 1) vs test3's 15 (B5 6, C2 5,
B1 2, D1 1, B4 1) — the Phase 13.1+ fixes removed the B5/B1 ones. The 3 C2 left:
- ss012 "VILLAN" x2 (blank_poster, shift_title): an OCR-only box (class None), 36 vs 39 px high =
  0.077. Text-box wobble of 3 px, not YOLO; a detector-class table cannot reach it.
- ss012 remove_element "Search" tab: 128 vs 100 px wide (0.217, FAIL). The painted-out row
  (x 187-882, y 2002-2102) does not touch Search (x 46-174, y 2192+); Search grew 17 px left and
  11 px right. So YOLO boxes change with edits elsewhere on the screen - non-local context
  wobble, twice the largest synthetic tab_item p95 (0.096). Synthetic jitter under-measures it.
- The VILLAN box moves with edits elsewhere too: [46,83,122,36] in blank_poster/shift_title,
  [44,81,125,39] in remove_element, client [43,81,126,39]. OCR box wobble, source "ocr".
**Regression found (cause traced 2026-09-29, not fixed):** remove_element on jiohotstar (TV tab)
was B1 in test3, now missed. The matcher does report client el_0020 "TV" as MISSING_IN_PRODUCTION,
but the differ marks it PASS `ignored: dynamic content`: the TV tab [295,2013,54,37] lies wholly
inside content_card el_0010 [32,1964,333,158], and the F1 rule (badge on a poster card = dynamic,
`matcher._is_dynamic` via `on_card_overlap`) treats anything on a card as dynamic. On jiohotstar
the detector boxes the tab row as content cards, so the tabs on it are ignored. ss031
remove_element (B1 -> "caught as other") not traced yet.

17.1 `measure_jitter` -> `output/jitter/test1_measure/` (1 m 29 s, 8 screens x 9 images):
- Position (C1): diag p95 <= 0.007 in every class with n >= 5 except jiohotstar content_card
  (0.011, n 11). C1's 0.01 band is outside detector wobble. Not a C1 problem.
- Detection is stable: 98-100% found in every variant, class flips ~0 (icon/metadata_text n 2).
  The planned "unstable element -> cap B1 at REVIEW" (17.4 item 3) has nothing to act on.
- Size (C2) p50 / p95: content_card 0.007 / 0.055, tab_item 0.025 / 0.096, overlay_badge 0.036 /
  0.082, section_title 0.023 / 0.069. Flagged (p95 x sqrt 2 > 0.05): content_card, tab_item,
  overlay_badge, section_title (+ icon, metadata_text on n = 2). Medians are well inside the band;
  the tail is. Worst rows are malformed boxes, not normal wobble: ss012's merged 695-px tab
  (0.207), cards cut off at the top edge (0.362, 0.113), a jiohotstar card (0.231).
- Sources broadly agree (tab_item mockup 0.078 vs sunnxt 0.105), so no case for 17.4 runtime.

Reading: detector wobble is real only for size, and only in the tail; p95-based per-class
tolerance (tab_item ~0.136) would eat most of C2's REVIEW band and turn real defects like the
Search-tab +24% into REVIEW. And none of the 3 remaining benchmark C2 false alarms is YOLO
wobble. Tolerance as planned in 17.2 would not remove them.
