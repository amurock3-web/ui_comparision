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
