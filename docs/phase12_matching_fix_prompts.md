# Claude Code prompts: fix the score, group shifts and box wobble

**Status 2026-09-24:** 12.0, 12.1 and 12.2 implemented (uncommitted on `detector-integration`); 12.3 not started. See memory.md "Phase 12".

How to use:
- Paste one prompt at a time, in order: **12.0 → 12.1 → 12.2 → 12.3**.
- After each one, read Claude Code's plan, say "go", run the commands it gives you, and check the result before you paste the next prompt.
- 12.3 needs 2–3 new screenshot pairs from you: the **same screen on the same build**, taken a few seconds apart. Capture them before you reach 12.3.

Why this order: 12.0 makes testing fast (seconds instead of 90 s per run). 12.1 makes the number honest. 12.2 removes most of the noise. 12.3 calibrates what is left.

---

## Prompt 12.0: save fused docs + a fast re-match script

```
Context: we are fixing three problems in the comparison stage, found by reading
output/app/20260922_121255/report.json (sunnxt_prod_lang vs sunnxt_live_lang)
and output/app/20260921_165919/report.json (sunnxt_prod vs sunnxt_live):
  1. similarity_percent shows 0.0% even though the matcher paired 7 (lang) and
     ~11 (home) elements correctly;
  2. size/position bands flag normal detector box wobble (7-11 px) as findings;
  3. when a whole panel moves (the lang bottom sheet moved up ~136 px), every
     element in it is reported separately, and elements whose IoU drops to ~0
     stop matching and become MISSING + EXTRA pairs.
This first task only makes testing fast. Do not touch matching or reporting logic yet.

Read first: CLAUDE.md, README.md, src/pipeline.py, src/app.py,
scripts/run_comparison.py, scripts/build_graph_from_fusion.py,
src/schema/ui_element.py. Use graphify query where it helps.

1. Wherever a pair is compared (src/app.py run folders and
   scripts/run_comparison.py), also save each side's fused UIDocument as JSON:
   production_fused.json and client_fused.json in the app run folder, and
   testN_<screen>_production_fused.json / testN_<screen>_client_fused.json in
   output/comparison/. Reuse whatever JSON serialisation fusion already uses.

2. New script scripts/rematch.py:
     python -m scripts.rematch <production_fused.json> <client_fused.json>
   It loads both docs, builds the layout graphs with LayoutGraphBuilder (same as
   src/pipeline.py), then runs ElementMatcher + DifferenceEngine +
   ReportGenerator + write_html_report exactly like run_comparison.py. No detector,
   no OCR. Images for the HTML report: take them from the doc's image path if it
   is stored, else accept --production-image / --client-image.
   Output: numbered testN_* files under output/rematch/, never overwrite.
   Print the same summary lines as run_comparison.py, plus one line per matched
   pair: prod id, client id, class, text, score.

3. Keep the edit narrow. No other refactors.

Plan first, wait for my OK, then build. Do not run the pipeline. At the end give me:
- the commands to re-run both real pairs once (so their fused JSONs exist):
    python -m scripts.run_comparison input/production/sunnxt_prod_lang.jpeg input/client/sunnxt_live_lang.jpeg
    python -m scripts.run_comparison input/production/sunnxt_prod.jpeg input/client/sunnxt_live.jpeg
  (confirm these input paths exist; the images are also in the output/app run folders)
- the rematch command for each pair
- a self-compare rematch command (same fused JSON on both sides)
Then run `graphify update .`, list the files you changed, and stop.
```

---

## Prompt 12.1: honest similarity score (problem 1)

```
Task: make the similarity number count matched ELEMENTS, not difference records.
Only src/reporting/ (and the HTML header text) changes. Matching and differ logic
stay the same.

The bug (src/reporting/report.py, ReportGenerator.generate):
  similarity = MATCH records / all Difference records
- One matched pair with text + position + size sub-differences produces 3
  records and zero MATCH records, so it counts as 0 matched and 3 compared.
- A pair with any REVIEW sub-difference never counts as matched.
- Evidence: lang run has 7 matched pairs, 53 records, 0 MATCH -> "0.0%".
design.md §12 already defines the summary as element counts
("Similarity 91.4%, Matched: 27, Missing: 2, Extra: 1 ...").

New definitions (Difference already carries production_id and client_id):
- matched_pairs: distinct (production_id, client_id) where both ids are set
  (MATCH or any sub-difference type).
- clean_pairs: matched pairs whose records are all verdict PASS.
- missing / extra: MISSING_IN_PRODUCTION / EXTRA_IN_PRODUCTION records whose
  verdict is not PASS (PASS here means dynamic content / ignored, which is not
  compared, rule §H).
- ignored: count of records skipped as dynamic/ignored (reported, not in the
  denominator).
- similarity_percent = 100 * matched_pairs / (matched_pairs + missing + extra),
  0.0 if the denominator is 0. Screen with nothing comparable -> 0.0 plus a warning.
- clean_percent = 100 * clean_pairs / (matched_pairs + missing + extra).
Put these in report["summary"] next to the existing per-type counts. Keep the
existing per-type counts. Rename total_compared to difference_records so nobody
reads it as an element count. The screen verdict logic does not change.

HTML report (src/reporting/html_report.py): the header must show
"Matched X of Y elements (Z%) · clean C · missing M · extra E · ignored I"
instead of "0.0% matched · 53 compared".

Also update src/app.py if it shows similarity or total_compared anywhere.

Tests: tests/test_reporting.py is a placeholder. Replace it with real tests built
from hand-made Difference lists (no images):
- a pair with 3 sub-differences counts as 1 matched, 0 clean
- self-compare style input (all MATCH) -> 100% similarity, 100% clean
- dynamic/ignored MISSING/EXTRA records are excluded from the denominator
- the lang case: 7 pairs + 18 non-PASS missing + 14 non-PASS extra -> 17.9%
- empty input -> 0.0, no crash

Plan first, wait for my OK. Do not run the pipeline. Give me:
- the pytest command for the new tests only
- the rematch commands for both real pairs + the self-compare (from 12.0)
- what numbers I should expect to see
Add a dated line to docs/memory.md: the similarity definition changed and why.
Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt 12.2: group shift, i.e. judge items against their group, not the screen (problem 3)

```
Task: when a whole group of elements moves together (a bottom sheet, a rail,
a floating bar), report the move ONCE, judge each member only by how far it moved
relative to its group, and re-match the members that the move made unmatchable.

Read first: docs/rules.md §7, docs/design.md §7-§10, docs/test_cases_pass_fail.md
(C1, B1, B2), src/comparison/matcher.py, src/comparison/differ.py,
src/graph/layout.py (how sections / rows / overlays / NEAR edges are built and
named), config/config.yaml. Use graphify query/explain for the layout graph.

Evidence (lang pair, normalized coords, client is the reference, 1080x2340,
diagonal 2577 px). All of these are real matched pairs in the current report:
  element                       dy (prod - client)
  "Sun NXT Languages" title     -0.0599
  "Sun NXT" tab                 -0.0582
  "Sun NXT Shorts" tab          -0.0608
  "Save" button                 -0.0567
  content_card el_0007/el_0004  -0.0579
  median = -0.0582  -> the sheet moved up ~136 px (5.8% of height)
Today this produces 6 separate POSITION_DIFFERENCE findings, and 7 of the 8
language tiles fail to match. For a tile: class 0.25 + text 0.125 (no text on
either side) + spatial 0.188 + IoU 0.2*0.29 = 0.62 before context, and the
threshold is 0.70. Unclassified text like "HINDI" and the close "X" can never
match after a shift: best case is 0.125 + 0.25 + 0.188 + 0 + 0.1 = 0.66.
The top header tabs, which sit BEHIND the sheet, moved by a different amount
(~ -0.009), and on the home pair the floating bar and the bottom nav moved
differently too. So the shift must be estimated per group, never one global shift.

Design (discuss it with me first; push back if the code suggests a better hook):

A. Anchors. After the current matching pass (pass 1), an anchor is a matched pair
   with: same non-null class on both sides, not dynamic/ignored, and either text
   score >= anchor_min_text_score (both sides have text) or IoU >= anchor_min_iou.

B. Groups. Each element's group = its nearest container in the client layout
   graph (overlay / section / row; use whatever layout.py actually produces).
   For every group with >= min_anchors anchors:
     shift = (median dx, median dy) of its anchors.
   Only accept the shift if the anchors agree: median absolute deviation of
   dx and dy <= max_spread_norm. Otherwise the group did not move as one
   piece, so apply no shift. Elements with no group, or in a group with too few
   anchors: use the median shift of matched NEAR neighbours (k=5, already
   built in layout.py and unused), with the same min_anchors and spread rules.
   Otherwise shift = (0, 0), which is today's behaviour.

C. Pass 2 (matcher). For elements left unmatched after pass 1, recompute
   candidate scores with the production bbox moved back by its group's shift
   (affects the spatial and IoU terms only), same weights, same
   minimum_match_score. Pass-1 matches are never changed. Record on each match:
   match_pass (1|2), group id, applied shift. The greedy conflict resolution
   stays the same.

D. Differ.
   - C1 for a member is computed on the RESIDUAL: its displacement minus its
     group's shift. Same position bands as today.
   - New difference type GROUP_SHIFT (spec id C1), one per group whose shift
     exceeds the C1 pass band, with the C1 bands and severities applied to the
     group shift. Details: group id and label (section title text if any),
     dx/dy in px and % of the diagonal, anchor count, member ids.
   - Update SPEC_BY_TYPE / IMPLEMENTED in report.py and the HTML wording, e.g.
     "Language sheet moved up 136 px (5.8% of height)".

E. Config (config/config.yaml, matching.group_shift). No constants in code:
     enabled: true
     min_anchors: 3
     anchor_min_text_score: 0.9
     anchor_min_iou: 0.5
     max_spread_norm: 0.01
   enabled: false must give exactly today's output.

Out of scope, do NOT change: the matching weights, the unclassified-score
ceiling, text normalisation, size bands, fusion, the detector.

Tests (tests/test_group_shift.py, hand-made UIDocuments, no images):
- group of 6 elements shifted by dy=-0.058 -> 1 GROUP_SHIFT, no member C1
  findings, shifted content_cards (no text) are matched in pass 2
- same, but one member moved an extra 0.03 -> that member still gets a C1
  finding (the median ignores it)
- a group with only 2 anchors -> no shift applied, same output as today
- two groups moving differently -> two different shifts
- anchors disagree (spread > max_spread_norm) -> no shift
- self-compare -> shift (0,0) everywhere, 100% PASS, identical to enabled:false
- enabled:false -> identical results to the current code

Plan first, wait for my OK. Do not run the pipeline. Give me:
- the pytest commands
- rematch commands for both real pairs + self-compare
- what I should expect on the lang pair: one GROUP_SHIFT of ~136 px up; title,
  tabs and Save with no position findings; most tiles matched; remaining
  findings mostly the subtitle copy change and uncertain OCR leftovers
Record the before/after finding counts for both pairs in docs/memory.md.
Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt 12.3: measure box wobble, then add a pixel floor (problem 2)

```
Task: stop normal detector box wobble from being reported as size/position
changes. Measure the wobble first; don't guess it.

Background: C2 in docs/test_cases_pass_fail.md is relative (PASS within ±5%).
On small elements that is only a few pixels. On the home pair, bottom-nav
"Profile" (height 0.0477 vs 0.0447 = 7 px, 6.4%) and "Downloads" (width 11 px,
7.5%) look identical by eye but are flagged. design.md §7 says thresholds
must be calibrated experimentally, and CLAUDE.md says thresholds live in config.

Input I will provide: input/jitter/<screen>_a.jpeg and <screen>_b.jpeg, meaning
the SAME screen on the SAME build, captured a few seconds apart (2-3 pairs).
Any difference between a and b is noise by definition.

Step 1 (measure; no threshold changes yet):
- scripts/measure_jitter.py: for each a/b pair, build the fused docs (or load
  saved fused JSON if present), run the matcher (with group shift from 12.2),
  and for every matched, non-dynamic pair record |dx|, |dy|, |dw|, |dh| in px and
  as ratios, plus class and box size.
- Print percentiles (50/90/95/max) overall and per class; write
  output/jitter/testN_jitter.json.
- Tell me how long it will take (OCR ~45 s per image) and wait for my OK before
  running anything.

Step 2 (after I've seen the numbers and agreed the values):
- config/config.yaml comparison: size_min_px and position_min_px (proposed = the
  95th-percentile wobble, rounded up).
- differ.py: a size change counts only if the ratio is beyond the C2 band AND
  the absolute change is more than size_min_px, per dimension. A position change
  (on the residual from 12.2) counts only if beyond the C1 band AND more than
  position_min_px.
- docs/test_cases_pass_fail.md: add a note under C1/C2 that a pixel noise floor
  applies, with the measured values and the date. The % bands stay as they are.

Tests: an element 5 px bigger at 6% -> no finding; 20 px bigger at 20% -> FAIL;
a floor of 0 -> identical to the current behaviour; self-compare still 100% PASS.

Plan first, wait for my OK. Give me the exact commands. Record the jitter numbers
and the chosen floor in docs/memory.md. Run `graphify update .`, list the files
changed, and stop.
```

---

## What "done" looks like

- Self-compare of any screenshot: 100% matched, 100% clean, PASS.
- Lang pair: about 4 findings instead of 47 (the sheet moved up about 136 px, the subtitle wording changed, a few uncertain items), and a similarity number that means something.
- Home pair: the bottom-nav items no longer flagged for size.
- Still open after this: tab capitalisation (text normalisation), dynamic content leaking behind modals, and the unclassified-score ceiling.
