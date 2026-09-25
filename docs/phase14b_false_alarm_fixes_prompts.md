# Phase 14b: false-alarm fixes from the Trending Search pair (Claude Code prompts)

**Why:** run `output/app/20260925_145307` (production `sunnxt_live_search` vs client
`sunnxt_pre_search`) says **FAIL, 29 findings**, but by eye the layout is the same and only the
posters changed. About 19 findings are false alarms, 6 are borderline, and 1–2 are worth a look.
Target after these fixes: **REVIEW, about 8–9 findings**, with the Search-tab text colour still
reported.

**Order:** F0 (diagnose) → F1 → F2 → F3 → F4 → F5 → F6 → F7. Do these **before Phase 15**:
they fix the verdicts, while Phase 15 adds checks. Paste one prompt at a time, read the plan,
say "go", check the result.

**The rematch command every prompt uses** (seconds, no OCR):

```
python -m scripts.rematch output/app/20260925_145307/production_fused.json output/app/20260925_145307/client_fused.json --production-image output/app/20260925_145307/production_sunnxt_live_search.jpeg --client-image output/app/20260925_145307/client_sunnxt_pre_search.jpeg
```

(If the file names in that folder differ, Claude Code should find the right ones and tell you.)

---

## Prompt F0: diagnose first (no code changes)

```
Context: output/app/20260925_145307 (production sunnxt_live_search vs client sunnxt_pre_search)
reports FAIL with 29 findings. By eye the layout is identical and only the poster content
changed. I believe ~19 findings are false alarms. Before changing code, confirm WHY each happens.

Read first: CLAUDE.md, docs/memory.md (Phase 12-14), that run's report.json and both fused JSONs,
src/comparison/matcher.py (_is_dynamic, match, pass 2), src/comparison/differ.py,
src/comparison/layout_checks.py, src/graph/layout.py (CONTAINS / loose containment),
src/fusion/fuse.py (fuse_detections, how labels are built from OCR tokens), and wherever
TEXT_COLOR_DIFFERENCE is produced. Use graphify query where it helps.

Write a throwaway diagnostic (scripts/diagnose_run.py, reusable: takes a run folder) that prints:
1. For every overlay_badge finding (12): element id, parent_id, the layout-graph container, the
   best-overlapping content_card and the fraction of the badge inside it, and what _is_dynamic
   returns. My hypothesis: parent_id is None for detector badges, so _is_dynamic misses them.
2. For the search_bar MISSING (client el_0001) and EXTRA (production el_0008): both texts, boxes,
   and the full score breakdown (class/text/spatial/iou/context, total) of that pair in pass 1
   and pass 2, and why it stayed below minimum_match_score. Hypothesis: the trailing "0"
   (mic icon) lowers the text score.
3. For the 3 CLIPPING_DIFFERENCE findings: which edge/overlay triggered clipped, and where the
   "may be a false alarm" note is added versus where the verdict is set.
4. For "9 Languages", "Search Movies, TV shows, Live TV... 0" and "SUN NT Home": each OCR token
   with text, confidence, bbox, and its position relative to the element box.
5. For the two TEXT_COLOR_DIFFERENCE findings: which crop was sampled (whole element or OCR line),
   both k-means clusters (colour, pixel share, dE between them).
6. A one-line verdict per finding: false alarm / borderline / possibly real, and why.

Do not change any pipeline code. Run only this script and scripts.rematch (seconds, no OCR).
Show me the output and tell me which hypotheses held and which didn't, then stop.
```

---

## Prompt F1: badges on a card are dynamic content

```
Task: an overlay_badge that sits on a content/cast/celebrity card is part of that card's live
content (test_cases_pass_fail.md §H). It must not produce B1/B2 findings. On the Trending Search
run this is 12 of 29 findings (Free / New Release / Most Viewed / crown badges on posters that
changed). Use F0's findings; if F0 showed a different cause, tell me before building.

Design (discuss first):
- Extend _is_dynamic (matcher.py; shared by matcher and differ) so an element is dynamic when
  ANY of these holds: metadata.ignored; parent_id is a poster card (today's rule); the client/
  production layout graph has a CONTAINS edge from a poster card to it; or, geometrically, at
  least graph.loose_containment_overlap (0.75) of its box lies inside a poster card of the same
  doc. The poster card classes come from one shared constant, not a new list.
- It needs the doc's cards and, where available, the graph; keep the signature change minimal
  and update every caller.
- Unmatched dynamic badge -> MISSING/EXTRA with verdict PASS, details.ignored =
  "badge on dynamic card" (counted as ignored, out of the similarity denominator, as today).
- Matched badge pairs still get D5 colour. A badge NOT on a card (e.g. a header chip) is still
  compared exactly as today.
- Config: comparison.badges_on_cards_are_dynamic: true. false -> identical to today.

Tests (tests/test_dynamic_badges.py, hand-made docs): badge 85% inside a card, no parent_id ->
dynamic; badge outside any card -> B2 FAIL as today; matched on-card badges still get D5; flag
off -> identical; self-compare 100% PASS.

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch (the Trending
Search command plus both older pairs and a self-compare). Do not run the detector, OCR,
run_comparison or the benchmark. Report before/after finding counts for all three pairs. Add a
dated line to docs/memory.md (Phase 14b). Run `graphify update .`, list the files changed, stop.
```

---

## Prompt F2: rescue pass for MISSING + EXTRA of the same element

```
Task: one element reported twice. The search bar is in both screenshots a few px apart, yet it
appears as MISSING (client el_0001) AND EXTRA (production el_0008), two Major FAILs. Add a
third, conservative matching pass for leftovers. Use F0's score breakdown to confirm why the
pair scored below minimum_match_score.

Design (discuss first):
- After pass 2, take unmatched client and production elements, excluding dynamic ones.
- Candidate pair: same non-null class AND centre distance (after the element's group shift, if
  any) <= comparison.position_bands.fail (0.03 of the diagonal) AND text score >=
  matching.rescue.min_text_score (e.g. 0.5, or both texts empty).
- One-to-one only: a pair is made only when each side has exactly one candidate, or the best is
  clearly better than the second (margin in config). Otherwise keep both unmatched and mark
  them REVIEW with details.ambiguous_rescue (rules.md §I; never guess).
- Rescued pairs record match_pass = 3 and are then judged normally (C1/C2/E1 etc.), so a real
  move or text change is still reported, just once.
- Config: matching.rescue {enabled: true, min_text_score, min_margin}. enabled:false -> today.
- Do NOT change weights or minimum_match_score.

Tests (tests/test_rescue_pass.py): same-class pair 20 px apart with a text slip -> 1 pair, no
B1/B2; two equal candidates -> both stay unmatched, REVIEW; different classes -> not paired;
far apart -> not paired; disabled -> identical; self-compare unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch on the Trending
Search pair and both older pairs (report how many MISSING/EXTRA each loses). No detector, OCR,
run_comparison or benchmark. Add a line to docs/memory.md. Run `graphify update .`, list the
files changed, and stop.
```

---

## Prompt F3: a finding that says "may be a false alarm" can't be FAIL

```
Task: the report adds "Cut off by the screen edge, nav bar or an overlay, so this may be a false
alarm" to findings that stay FAIL · Major (3 CLIPPING_DIFFERENCE, plus B1 search_bar, D1 and D3
on the Home tab in the Trending Search run). The tool contradicts itself. Make the verdict follow
the note.

Design (discuss first; F0 told us where the note is added and where the verdict is set):
- One final step in differ.py (after all checks, before collateral dropping): any Difference
  whose element is flagged clipped / cut-off (the same condition that produces the note) is
  capped at REVIEW (severity kept in details.original_severity so nothing is hidden).
- B8 (layout_checks.py): clipping on a poster card (content/cast/celebrity) is REVIEW at most,
  since a cut-off card is scroll position. B8 on button / tab_item / text / search_bar keeps the
  spec's FAIL Major.
- The note wording stays; the HTML shows "capped to REVIEW: element is cut off".
- Config: comparison.cap_clipped_to_review: true. false -> today.

Tests: clipped element with a D1 FAIL -> REVIEW, original_severity Major; clipped content_card
B8 -> REVIEW; clipped button B8 -> FAIL Major; flag off -> identical; self-compare unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch (Trending Search +
both older pairs). No detector, OCR, run_comparison or benchmark. Report verdict changes per
pair. Add a line to docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt F4: strip icon glyphs from labels

```
Task: OCR reads icons as characters and they end up in labels: "9 Languages" (language icon),
"Search Movies, TV shows, Live TV... 0" (mic icon), "SUN NT Home" (logo). This caused a false E1
FAIL and probably the search-bar mismatch. Use F0's token table.

Design (discuss first):
- Pure function in a small module (e.g. src/comparison/text_cleanup.py) used in two places:
  clean_label(tokens, element_box, cfg) -> (text, dropped). A token is an icon glyph when ALL
  hold: length <= glyph_max_len (2); it is digits/symbols only OR its confidence is below
  glyph_max_conf; and it sits on the icon side of the element: outside the main text line
  (the line with the most characters) or at the far start/end of the box.
- Fusion (fuse_detections): build labels with clean_label; keep dropped tokens in
  metadata.dropped_glyphs (rules.md §10, never delete evidence).
- Comparison: E1 and the matcher's text score also apply the cleanup to element text, using
  metadata.ocr_ids tokens when available, so saved fused JSONs benefit via rematch without new OCR.
  Say clearly which part needs a fresh run_comparison.
- Must NOT drop real short labels: "4K", "HD", "U/A", "A", "+", "18+" when they are the main
  text line. Put a protect-list in config.
- Config: comparison.glyph_cleanup {enabled, glyph_max_len, glyph_max_conf, protect}.

Tests (tests/test_text_cleanup.py): "9 Languages" with "9" above the word -> "Languages";
"... TV... 0" with "0" at the right end -> trailing 0 removed; "4K" alone -> kept; "U/A 13+" ->
kept; disabled -> identical; self-compare unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch (all three pairs).
No detector, OCR, run_comparison or benchmark. Report which E1 findings disappear and whether the
search bar now matches in pass 1. Add a line to docs/memory.md. Run `graphify update .`, list the
files changed, and stop.
```

---

## Prompt F5: D3 text colour from the text line only

```
Task: D3 (TEXT_COLOR_DIFFERENCE) sampled the Home tab, whose label is the SUN NXT logo, and got
dE 32 by taking the dark background as "text". Measure text colour only on real text.
The Search tab finding (rgb(206,59,87) vs rgb(206,50,40), dE 12.5) must still be reported:
it may be a real selected-state colour change.

Design (discuss first; F0 showed which crop was used):
- Crop = the OCR text-line box(es) of the element (from metadata.ocr_ids / fused text boxes),
  slightly padded; never the whole icon+label element.
- Not measured (skip, counted as "not measured" in coverage, never PASS) when: no OCR line;
  the line's OCR confidence is low; the two k-means clusters are closer than a config dE floor;
  the text cluster's share is outside a config range; or the element's label is a logo
  (class logo, or text matched against a config list of brand wordmarks such as "SUN NXT").
- Same bands as today. Respect match levels if 15.0 exists.
- Config under comparison.contrast / text_color (whatever exists): line_padding, min_cluster_de,
  text_share_range, logo_wordmarks.

Tests: synthetic tab with an icon + dark text line -> colour from the line; logo label ->
not measured; low-contrast clusters -> not measured; a real red-vs-orange text change -> FAIL
as today; self-compare unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch (all three pairs).
No detector, OCR, run_comparison or benchmark. Show the D3 findings before/after per pair. Add a
line to docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt F6: PDF layout (page 1 half empty)

```
Task: in the PDF (printed by headless Edge from report.html), the side-by-side image does not fit
on page 1, so page 1 is almost blank and the image starts on page 2. Fix the print layout only.

Read first: src/reporting/html_report.py, src/app.py (to_pdf), one saved report.html.

- Add @media print CSS: the side-by-side figure scales to fit the printable page
  (max-height about 90vh / page height, width auto, object-fit contain); header + verdict +
  stats stay on page 1 above it if they fit, otherwise the figure starts page 2 with no blank
  gap; break-inside: avoid on each finding row and issue row; table headers repeat on each page.
- Screen (non-print) layout unchanged.
- No new dependencies, no external fonts.

Test: build a report from the Trending Search rematch, then print it with the existing to_pdf
path; tell me the page count before/after. You may run scripts.rematch and the PDF step only.
List the files changed, run `graphify update .`, and stop.
```

---

## Prompt F7: lock it in (real-pair benchmark case)

```
Task: add the Trending Search pair to the benchmark as a REAL case (not a synthetic mutation),
with the expected answer, so F1-F5 are measured and can't quietly regress.

Read first: scripts/make_benchmark.py, scripts/run_benchmark.py (score(), manifest.json format),
input/benchmark/*/manifest.json, output/benchmark/test3_benchmark/results.json.

- Support a "real" case type: input/benchmark/real/<name>/production.<ext>, client.<ext>,
  manifest.json with: expected verdict (REVIEW), must_not_flag (e.g. overlay_badge B1/B2,
  search_bar B1/B2, E1 on "Languages", D3 on Home), may_flag (C2 on nav tabs, D1 Home,
  B9), must_flag (D3 on the Search tab, if F0 judged it possibly real; ask me).
  Use the fused JSONs from output/app/20260925_145307 as a cache so this case needs no OCR.
- The scorecard gets a "real pairs" section: verdict right/wrong, must_not_flag violations
  (= false alarms), must_flag misses.
- Also correct the stale line in docs/memory.md that says make_benchmark/run_benchmark were
  never run: they ran on 2026-09-24 (test1-3; test3: 13/19 caught, 4 as other, 2 missed,
  3/3 identity clean, 15 false alarms).

Plan first, wait for my OK. You may run pytest. Before running the full benchmark, tell me how
long it will take (~20 min last time) and wait for my OK. Record the new scorecard next to
test3's numbers in docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```
