# Phase 14: Applitools ideas applied to our open problems (plan + Claude Code prompts)

## The plan in one page

Applitools Eyes doesn't use one magic trick. It combines configurable tolerance, pixel-verified
regions, root-cause reporting and "decide once, reuse everywhere". Five of those ideas
map onto the problems still open in `docs/memory.md` (Phase 13, 2026-09-24):

| # | Open problem (memory.md) | Applitools idea | Our local version | Expected effect |
|---|---|---|---|---|
| 14.0 | Same panel move reported twice (`screen` -136 px and `grp_0004` -139 px) | Root cause: report the cause, not its echoes | Merge a nested GROUP_SHIFT into its ancestor when both carry the same shift | Lang pair: 3 GROUP_SHIFT → 2 |
| 14.1 | Status-bar text leaking in as a `section_title` | Ignore region | `ignore_regions` in config, applied to detections **and** OCR, and again at compare time so `rematch` benefits | The leaked title disappears |
| 14.2 | SIZE noise from detector box wobble (10 home, 5 lang) | Compare regions found from pixels, not from a model | Tight box from the pixels inside each matched crop. It confirms or downgrades a C2 finding and never adds one | Most wobble findings gone. Measured first. |
| 14.3 | 12 D1 findings on the home pair that are one thing | Group identical differences | Report-level grouping of findings into "issues" (verdict unchanged) | 12 findings → 1–2 issues |
| 14.4 | Nothing remembers a human decision | Accept once, auto-maintain | Local `baselines/accepted_differences.yaml` plus a CLI to accept a finding | A known, accepted difference comes back as PASS (accepted) |
| 14.5 (optional) | D1 on see-through chrome can't be decided from pixels | (not Applitools: our own heuristic) | Measure how flat the fill is. A textured fill means "possibly see-through" → REVIEW, never FAIL | Only if the measurement separates cleanly |

**Order and why.** 14.0 and 14.1 are small and remove clearly wrong findings. 14.2 removes
the biggest noise source without waiting for the jitter screenshots. 14.3 and 14.4 change how
findings are *presented and remembered*, so they come after the findings themselves are cleaner.
14.5 is measure-first and may end with "no change".

**One change from what I said in chat.** I suggested SSIM to confirm size changes. That doesn't
work: both crops get resized to the same size before SSIM, which hides exactly the size change
we want to test. A tight box from the pixels is the right check, so 14.2 uses that.

**What this does not fix.** OCR misreads ("ONLV ON", "SLAILD"), detector class errors, the
uncalibrated A2/A3 thresholds, and the unbuilt spec rows. 12.3's pixel floor is still worth doing
once jitter pairs exist. After 14.2 it becomes a safety net, not the main fix.

**How to use.** Paste one prompt at a time into Claude Code, in order. Read its plan, say "go",
run the commands it gives you, and check the result before the next prompt. Every step runs on
saved fused JSONs through `scripts.rematch` (seconds, no OCR), except 14.1 if it decides fusion
must change.

**Done looks like:**
- Self-compare is still 100% PASS after every step.
- Lang pair: one sheet move, one header move, no status-bar title, fewer SIZE findings.
- Home pair: SIZE findings mostly gone, the colour findings shown as 1–2 issues.
- A finding a human accepts stays accepted on the next run.

---

## Prompt 14.0: merge nested GROUP_SHIFTs (root cause, report once)

```
Context: Phase 14 applies Applitools-style ideas to the open problems in docs/memory.md
(Phase 13). This first task: the same physical move is reported twice.
On the language pair (sunnxt_prod_lang vs sunnxt_live_lang) the report has three GROUP_SHIFTs:
  grp_0001  +15.8 / +20.9 px  (header, REVIEW)
  screen     +3.1 / -136.2 px (10 members, FAIL)
  grp_0004   -6.7 / -139.3 px (sheet tabs, FAIL)
"screen" and "grp_0004" are one move seen at two levels of the layout tree. memory.md
already calls this "unfinished polish".

Read first: CLAUDE.md, docs/memory.md (Phase 12 + 13 sections), src/comparison/matcher.py
(_group_shifts, _shift_for, _container_of, _agreed_shift), src/comparison/differ.py
(_group_shifts), src/graph/layout.py (how the root node is named), src/reporting/report.py,
src/reporting/html_report.py, config/config.yaml (matching.group_shift),
tests/test_group_shift.py. Use graphify query/explain where it helps.

Design (discuss it first; push back if the code suggests a better hook):
1. Reporting only. The matcher's per-container shifts and the per-member residuals stay
   exactly as they are. Only the GROUP_SHIFT findings produced in differ._group_shifts merge.
2. For each group in match_result.group_shifts, find its nearest ANCESTOR that is also in
   group_shifts (walk CONTAINS up with _container_of). If |dx - dx_anc| <= max_spread_norm
   and |dy - dy_anc| <= max_spread_norm, it is the same move. Chains merge transitively.
3. One GROUP_SHIFT per chain:
   - reported group = the outermost container in the chain that is NOT the screen root
     (the root is a last-resort bucket, not a real panel); if the chain is only the root,
     report the root.
   - shift = the reported group's own shift; anchors = the sum over the chain;
     members = union of members; details.merged_groups = the other ids in the chain.
   - label: first section_title text among all merged members (today it only looks at
     the reported group's members).
4. Config: matching.group_shift.merge_nested: true. false must give exactly today's output.

Tests (add to tests/test_group_shift.py, hand-made docs/graphs, no images):
- parent and child with the same shift -> 1 GROUP_SHIFT, merged_groups lists the child
- parent and child with different shifts (header +21 px vs sheet -136 px) -> 2 findings
- chain of three with the same shift -> 1 finding
- chain = root + one panel -> reported group is the panel, not the root
- merge_nested: false -> identical to the current output
- self-compare -> no GROUP_SHIFT

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch (seconds, no
OCR). Do not run the detector, OCR, run_comparison or the benchmark.
Give me:
- the pytest command for tests/test_group_shift.py
- the rematch command for both real pairs + a self-compare (find the latest saved
  *_production_fused.json / *_client_fused.json for each pair in output/app/ or output/comparison/)
- expected: lang pair shows 2 GROUP_SHIFTs (header ~+21 px REVIEW, sheet ~-136 px FAIL)
Record before/after GROUP_SHIFT counts in docs/memory.md under a new "Phase 14" section.
Run `graphify update .`, list the files you changed, and stop.
```

---

## Prompt 14.1: ignore regions (status bar first)

```
Task: an Applitools-style ignore region. First job: stop status-bar text from leaking into
the comparison. memory.md (Phase 12) says a status-bar string leaks in as a section_title
because fusion.status_bar_height_norm only catches (a) detections WHOLLY inside the band and
(b) OCR text that lands in NO detection.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md §H, src/fusion/fuse.py (fuse_detections:
the two status_bar rules), src/comparison/matcher.py (_is_dynamic and how ignored elements are
skipped), src/comparison/differ.py (_unmatched, screen checks use status_bar_height_norm),
src/comparison/screen_checks.py, config/config.yaml (fusion.status_bar_height_norm).

Step 1: diagnose, no code changes. Load the latest saved fused JSONs for both real pairs and
print every element that intersects the status-bar band: id, class, bbox, normalized bbox,
text, ocr_ids, metadata, and how much of its area lies inside the band. Tell me exactly why
the leaking one passes both current rules. Stop and show me.

Step 2 (after I agree the diagnosis), proposed design, adjust it to what step 1 finds:
- config: comparison.ignore_regions: a list of {name, bbox_norm: [x, y, w, h], min_overlap}.
  Default one entry: status_bar, [0, 0, 1, <status_bar_height_norm>], min_overlap 0.5.
  Keep fusion.status_bar_height_norm as the single source for the band height (A3 uses it too).
- One pure function, e.g. src/comparison/regions.py: apply_ignore_regions(doc, regions) ->
  marks metadata.ignored = <region name> on any element with >= min_overlap of its area inside
  a region. Idempotent; never deletes an element (rules.md §10: keep evidence).
- Call it at the start of comparison (matcher/differ entry, or wherever both run_comparison,
  rematch and the app share one path), so saved fused JSONs benefit without re-running OCR.
- If step 1 shows the leak is OCR text merged into a larger detection's label, also fix
  fusion: OCR whose centre is inside an ignore region never becomes a host's label text
  (keep it in ocr_ids with a note). Say clearly that this part needs a fresh
  run_comparison to show up, and that rematch cannot show it.
- Ignored elements must count as "ignored" in the report summary, never as missing/extra.

Tests (tests/test_regions.py, hand-made docs):
- element 60% inside the band -> ignored; 30% inside -> not ignored
- ignored element unmatched on one side -> no B1/B2 finding
- empty ignore_regions -> identical to today
- self-compare unchanged, 100% PASS

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch. Do not run
the detector, OCR, run_comparison or the benchmark. Give me the commands, what I should expect,
and which part (if any) needs a fresh run_comparison. Add a dated line to docs/memory.md
(Phase 14). Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt 14.2: pixel-verified size (the box wobble fix without jitter pairs)

```
Task: stop detector box wobble from producing C2 SIZE findings by measuring each matched
element's size from its PIXELS, not from YOLO's box. This is the idea in the Applitools patent
(US20140189576: binarise + morphology to find element regions, compare those regions).
The measurement may only CONFIRM or DOWNGRADE an existing box-based C2 finding; it never
creates a new one (rules.md §7: never rely only on pixels).

Background: memory.md Phase 13 says SIZE is the largest remaining noise source: 10 findings on
the home pair, 5 on the language pair. Example: bottom-nav "Profile" height 0.0477 vs 0.0447
(7 px, 6.4%), "Downloads" width 11 px (7.5%); identical by eye. 12.3's pixel floor is still
blocked on jitter screenshots; this does not need them.
Note: SSIM is NOT the check here: resizing both crops to one size hides the size change.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md (C2), src/comparison/differ.py
(_sub_differences C2 block, compare(), _shows_artwork_through), src/comparison/color_checks.py
(module style: pure functions returning measurements, bands applied in differ),
config/config.yaml (comparison.size_bands).

Step 1: measure, no verdict changes.
- New module src/comparison/pixel_geometry.py, pure functions, no config reads:
  tight_box(crop, contrast_threshold, min_pixels) -> TightBox(x, y, w, h, reliable, note)
  * background = median colour of the crop's border ring
  * mask = pixels whose luminance (or Lab dE) differs from background by > contrast_threshold
  * morphological close, then the bounding box of the mask
  * reliable=False (with a note) when: mask too small, mask touches all four crop edges
    (element bigger than the crop / no clear background), or the element shows artwork
    through (caller passes that flag in)
- In differ: for each matched non-dynamic pair where the box-based C2 fires, crop each side
  from its own image with a margin (config: comparison.pixel_verify.margin_frac, e.g. 0.15 of
  the box, min a few px), run tight_box on both, and record the result in the finding's
  details (tight sizes, tight width/height ratio diffs, reliable flags). Verdict unchanged.
- scripts/rematch prints one line per SIZE finding: element, class, box ratio diff, tight
  ratio diff, reliable. Show me that table for both pairs and stop.

Step 2 (after I've seen the table and agreed the values):
- config comparison.pixel_verify: {enabled: true, margin_frac, contrast_threshold, min_pixels}
- if both sides are reliable and the tight-box size diff is within size_bands.pass -> drop the
  SIZE finding (the pair becomes MATCH with details.size_check = "pixel_verified").
- if the tight diff is also beyond the band -> keep the finding and say "confirmed by pixels"
  in the details and the HTML text.
- if either side is unreliable -> keep today's box-based finding unchanged, note why.
- enabled: false -> identical to today.
- Scope: C2 only. Record the tight-box centre delta in details too, but do NOT change C1 yet.
  I'll decide on position after seeing the numbers.

Tests (tests/test_pixel_geometry.py, synthetic numpy images, no screenshots):
- a solid rectangle on a flat background: tight box within 1 px of truth
- same rectangle, detector box 7 px taller on one side -> finding dropped
- rectangle really 20% bigger -> finding kept, "confirmed by pixels"
- textured/noisy background -> reliable=False, finding kept
- enabled: false -> identical output; self-compare still 100% PASS

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch (with
--production-image / --client-image so crops exist). Do not run the detector, OCR,
run_comparison or the benchmark. Give me the commands and the expected before/after SIZE counts.
Record the measured table and the chosen values in docs/memory.md (Phase 14).
Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt 14.3: group identical findings into issues (report only)

```
Task: Applitools-style grouping. Many findings are one issue repeated: on the home pair
12 D1 COLOR_DIFFERENCE findings all say production chrome ~rgb(99-111) vs client ~rgb(37-45).
Group them in the report so a human reviews issues, not records. The screen verdict,
per-finding verdicts and the similarity numbers do NOT change.

Read first: CLAUDE.md, src/reporting/report.py (generate, findings, summary),
src/reporting/html_report.py, src/app.py (anything that shows findings), the latest rematch
report.json for both real pairs.

Design (discuss first):
- New pure function group_findings(findings, cfg) in src/reporting/grouping.py.
  Group key = type + class + a type-specific bucket:
    COLOR / BADGE_COLOR: production and client colours each within dE2000 <= color
      brand_bands.pass of the group's first member (reuse color_checks.delta_e2000)
    SIZE: same sign of width and height change, ratio rounded to size_bands.pass
    POSITION: residual dx/dy rounded to matching.group_shift.max_spread_norm
    TEXT / TEXT_STYLE: same normalised (production_text, client_text)
    MISSING / EXTRA: same class and same verdict
    everything else: never grouped
- report["issues"]: [{issue_id, type, spec_id, class, count, verdict (worst), severity (worst),
  finding_indices, summary}], e.g. "12 x navigation_bar / tab_item colour: production
  rgb(105,99,99) vs client rgb(40,40,42), dE 28". Singletons are issues of count 1.
- summary gains "issues": n. report["findings"] stays exactly as it is.
- HTML: show issues first ("26 findings in 9 issues"), each expandable to its findings and
  their boxes on the overlay. Keep the existing findings table below.
- Config: reporting.group_findings: true. false -> no "issues" key, HTML as today.

Tests (tests/test_grouping.py, hand-made finding dicts):
- 12 near-identical colour findings -> 1 issue of 12
- two clearly different colours -> 2 issues
- SIZE bigger vs smaller -> 2 issues
- verdict/similarity identical with grouping on and off
- empty findings -> no crash

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch. Do not run
the detector, OCR, run_comparison or the benchmark. Give me the commands and the expected issue
counts for both pairs. Add a line to docs/memory.md (Phase 14). Run `graphify update .`,
list the files changed, and stop.
```

---

## Prompt 14.4: accepted differences (decide once, reuse)

```
Task: a local, Applitools-style "accept this difference" baseline. When a human reviews a
finding and says it is expected (e.g. a deliberate copy change), the next run reports it as
PASS (accepted) instead of re-raising it. Everything stays local and in plain files.

Read first: CLAUDE.md, src/reporting/report.py, src/comparison/differ.py (compare() end),
scripts/rematch.py, scripts/run_comparison.py, src/app.py, src/reporting/grouping.py (14.3).

Design (discuss first):
- File: baselines/accepted_differences.yaml (tracked in git; holds no screenshots). Entry:
    {client_screen_id, type, client_class, client_text, client_center_norm: [x, y],
     details_signature (e.g. production_text for TEXT, rgb pair for COLOR),
     note, accepted_by, date}
- A finding matches an entry when screen, type and class are equal, text is equal
  (normalised), the centre is within accept_center_tolerance_norm (config, e.g. 0.02),
  and the signature matches (colour within the D1 pass band, text equal).
- Apply after differ, in one place all three entry points share. A matched finding becomes
  verdict PASS with details.accepted = {note, date}; it is not a finding any more but is
  listed in report["accepted"] and counted in summary.accepted.
- Entries that matched nothing this run are listed as report["stale_acceptances"] (info only),
  so old decisions don't hide silently.
- CLI: python -m scripts.accept_finding <report.json> --finding N [--issue ID] --note "..."
  appends the entry (or all members of an issue from 14.3). Never edits past reports.
- Config: comparison.accepted_differences_path; missing file = nothing accepted.

Tests (tests/test_acceptance.py):
- accepted TEXT finding -> PASS (accepted) next run; the same text on another screen -> not accepted
- element moved beyond tolerance -> not accepted
- stale entry reported
- no file -> identical to today; self-compare unchanged

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch. Do not run
the detector, OCR, run_comparison or the benchmark. Give me: the command to accept one finding
from the latest lang report, then the rematch command that shows it as accepted.
Add a line to docs/memory.md (Phase 14). Run `graphify update .`, list the files changed, and stop.
```

---

## Prompt 14.5 (optional): is this chrome see-through? (measure first)

```
Task: decide whether a colour check can tell "chrome colour really changed" from "translucent
chrome showing different artwork behind it". memory.md Phase 13: the home pair's 12 D1 findings
(production rgb 99-111 vs client 37-45) cannot be settled from pixels today, and
_shows_artwork_through misses them because the bottom nav overlaps the last card row by ~1 px.
Idea to test: solid chrome has a flat fill, while translucent chrome over a poster shows
texture. This is our own heuristic, not an Applitools feature. It may not separate cleanly;
if it doesn't, we stop.

Read first: src/comparison/color_checks.py (dominant_color, compare_crops),
src/comparison/differ.py (_element_color, _shows_artwork_through).

Step 1: measure only. Add fill_spread(crop, inset_fraction) to color_checks.py: e.g. the share
of inset pixels farther than dE 10 from the dominant colour, plus the Lab L std. Log it for
both sides of every D1/D5 comparison in rematch. Show me a table for: the 12 home-pair findings,
and chrome on the lang pair that clearly did not change (Save button, sheet tabs). Stop.

Step 2 (only if the two sets separate clearly and I agree a threshold):
- config comparison.color.max_fill_spread
- if either side's spread > max_fill_spread -> the colour finding becomes REVIEW (never FAIL)
  with details.note = "fill not flat - possibly translucent over artwork"
- no threshold / feature off -> identical to today

Tests on synthetic crops: flat fill -> low spread; noisy texture -> high spread; the REVIEW
downgrade; off -> unchanged.
Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch. Record the
measured table (and the decision, even if it is "does not separate, not adopted") in
docs/memory.md. Run `graphify update .`, list files changed, and stop.
```
