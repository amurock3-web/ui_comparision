# Phase 17: jitter (box wobble), measured and then tolerated (plan + Claude Code prompts)

## The plan in one page

**Problem.** The same element gets slightly different YOLO boxes on two captures of the same
screen. C1/C2 then report position/size differences nobody can see (memory.md Phase 13/14:
Profile height 6.4%, Downloads width 7.5%). 12.3's pixel floor is blocked on real jitter pairs,
and a threshold tuned on SunNXT would not hold for other apps.

**Idea.** Make the jitter ourselves, from any screenshot, with no capture step and no XML:
tiny changes that should never produce a finding. Same mechanics as `make_benchmark.py`,
opposite purpose:

| | Defect cases (today) | Jitter cases (new) |
|---|---|---|
| Change | rotate, blank poster, remove, shift 8%, squash 80%… | 2 px shift, resample, JPEG re-save |
| Expected | caught (FAIL/REVIEW) | PASS, zero findings |
| Measures | recall | noise (false alarms) |

`identity.png` can't do this: it is a byte copy, YOLO is deterministic, so it always gives zero
wobble.

| # | Step | Output | Cost |
|---|---|---|---|
| 17.1 | Jitter cases in the benchmark | The **before** noise number, by spec id | image gen: seconds; benchmark: needs OCR per case |
| 17.2 | `measure_jitter` script (detector only) | Wobble table per class: size, position, missed-detection rate | seconds per screen |
| 17.3 | Per-element tolerance at runtime | C1/C2 bands widen by each element's own measured wobble. Only ever downgrades | ~4–5× YOLO time per screen (OCR unchanged) |

**Transforms, and what was left out on purpose.**
- `shift`: whole screen moved 2 px right and 2 px down, edges replicated, same size.
- `resample`: down to 90% with LANCZOS, then back up to the original size. Changes
  anti-aliasing and edges, moves nothing. Stands in for a different export or render.
- `jpeg`: re-encoded at quality 80, saved back as PNG so the artefacts are fixed.
- `combo`: all three.
- **Not scale ±2%.** It moves bottom elements ~48 px on a 2400 px screen, which is a real
  layout change, not noise.
- **Not brightness.** Screencaps are digital, so a brightness change is unrealistic, and it
  would test the colour checks, not box wobble.

**Order and why.** 17.1 first gives a number to beat. 17.2 says where the wobble is (which
classes, how big) and puts the core code in `src/`, where 17.3 reuses it. 17.3 is the actual
fix and ships `enabled: false` (measure first, like 14.2).

**What this does not fix.** Real mockup-vs-production differences (fonts, placeholders),
OCR misreads, detector class errors on unseen apps (that's the annotator, next). Synthetic
jitter only approximates real capture noise. Check it once against 3–5 real same-screen pairs
(`input/jitter/<screen>_a|_b`, the convention already in memory.md) when you have them.

**Done looks like:**
- Scorecard shows "jitter cases clean X/Y" and false alarms on jitter cases by spec id.
- A per-class wobble table exists for SunNXT, JioHotstar and the trending_search mockup.
- With 17.3 enabled, jitter-case false alarms drop and **every defect case is still caught**
  (resize_card's 80% squash must stay C2, shift_title's 8% must stay C1).
- Self-compare still 100% PASS. `--real-only` still 0 false alarms.

**How to use.** Paste one prompt at a time into Claude Code, in order. Read its plan, say "go",
run the commands it gives you, and check the result before the next prompt.

---

## Prompt 17.1: jitter cases in the benchmark (the "before" number)

```
Task: add "jitter" cases to the known-defect benchmark: tiny, meaningless image changes that
must produce NO findings. They measure noise the way the defect cases measure recall.
No change to detection, matching or thresholds in this task.

Read first: CLAUDE.md, scripts/make_benchmark.py (DEFECTS, make(), the manifest format),
scripts/run_benchmark.py (score(): spec_id None is scored like identity; the scorecard and
summary), input/benchmark/ss012/manifest.json, docs/memory.md "Phase 13.1" (benchmark table).

1. scripts/make_benchmark.py: four new case functions, same signature as the defects,
   none of them needs the fusion doc:
   - jitter_shift     translate the whole image +2 px x, +2 px y; fill the gap by
                      replicating the edge; output size unchanged
   - jitter_resample  resize to 90% (LANCZOS) then back to the original size
   - jitter_jpeg      encode as JPEG quality 80 in memory, decode, save as PNG
   - jitter_combo     shift, then resample, then jpeg
   Each returns {"spec_id": None, "bbox": None, "kind": "jitter", "note": "..."}.
   Add "kind": "defect" to the existing cases and "kind": "identity" to identity.
   Parameters (px, scale, quality) in one dict at the top of the file, not scattered.

2. A --jitter-only flag: generate only the jitter cases and MERGE them into the existing
   manifest.json (replace old jitter cases, keep every other case and image untouched).
   Reason: regenerating defect cases may pick different elements if the newest fusion JSON
   changed, which would silently change the benchmark. In --jitter-only mode do not require
   a fusion JSON.

3. scripts/run_benchmark.py: scoring for jitter cases is the same as identity (any finding is
   a false alarm), but report them separately:
   - summary: "jitter_clean" / "jitter_cases" and "jitter_false_alarm_types" (by spec_id)
   - identity_clean/identity_cases count only kind == "identity" (treat a missing kind as
     "defect" or "identity" exactly as today, so old manifests still score the same)
   - scorecard.html: one more stat tile "jitter cases clean X/Y" and a small table of
     jitter false alarms by spec id and by jitter case
   - a --jitter-only flag that runs only kind == "jitter" cases (plus nothing else)

Tests (tests/test_make_benchmark_jitter.py, small synthetic PIL images, no detector/OCR):
- every jitter output has the original's size and mode
- jitter_resample and jitter_jpeg change pixels but the mean absolute difference is small
  (pick a bound, say why)
- --jitter-only merge keeps the non-jitter cases byte-identical in the manifest
- score() on a jitter case: no findings -> "pass ok"; one finding -> "false alarm"

Plan first and wait for my OK. After my OK you may run pytest and
`python -m scripts.make_benchmark --jitter-only` (image generation only, seconds).
Do NOT run run_benchmark: it needs detector + OCR per case (about 90 s each on CPU).
Instead give me:
- the exact command to run only the jitter cases on ss012, ss031 and jiohotstar_test_ss
- how many cases that is and the expected run time on CPU and on the GPU box
- what "good" and "bad" look like in the output
Add a dated "Phase 17" section to docs/memory.md (what was added; results: "not yet run").
Run `graphify update .`, list the files you changed, and stop.
```

---

## Prompt 17.2: measure wobble per class (detector only)

```
Task: measure how much YOLO boxes wobble under tiny image changes, per class, on any
screenshot. Detector only, no OCR, no comparison. The core must live in src/ because
Prompt 17.3 will call it inside the pipeline.

Read first: CLAUDE.md, src/pipeline.py (how build_document calls the detector and in what
coordinates boxes come back), the detector wrapper it uses, scripts/make_benchmark.py (the
17.1 jitter transforms and their parameter dict), config/config.yaml (C1 position bands,
C2 size_bands, comparison.pixel_verify), docs/memory.md Phase 14 (14.2 margin table).

1. src/detector/jitter.py (or next to the detector wrapper, your call, say why):
   - make_variants(img, spec) -> list of (variant_img, transform) where transform knows how
     to map a box from variant coordinates back to original coordinates (shift: subtract the
     offset; resample/jpeg: identity). Reuse the 17.1 parameters; default spec = 8 variants:
     shift (1,0) (0,1) (2,2) (3,3), resample 0.85 / 0.95, jpeg 70 / 90.
   - measure_wobble(img, detect_fn, spec) -> per original detection:
       matched_in (how many variants found it: same class, IoU >= 0.5 after mapping back),
       class_flips (matched by IoU >= 0.5 but different class),
       rel_dw, rel_dh = spread of w/h relative to the original box (std and max abs),
       dcx, dcy = spread of the centre, normalised by image W/H (std and max abs).
     Pure function around detect_fn so it is testable without YOLO.

2. scripts/measure_jitter.py:
     python -m scripts.measure_jitter [images...]
   default images: every file in input/production/ plus production.* and client.* of each
   input/benchmark/real/<pair>/ (the trending_search client is a design mockup: report it
   as its own group, mockups may wobble differently). Optional
     --pairs input/jitter
   for REAL same-screen pairs (<screen>_a / <screen>_b): same metrics, a vs b, so synthetic
   and real can be compared once pairs exist.
   Output under output/jitter/testN_measure/ (never overwrite):
     per_element.csv, summary.json, and a printed table per class and per source
     (sunnxt / jiohotstar / mockup): n, detection stability (% of variants found),
     class flip rate, p50 / p95 of |rel_dw|, |rel_dh|, |dcx|, |dcy|.
   Below the table print the current C1/C2 pass bands next to the p95 values, and flag
   classes whose p95 * sqrt(2) exceeds the pass band ("this class will produce wobble
   findings"). sqrt(2) because a comparison has two independent wobbling boxes.

Tests (tests/test_jitter.py, fake detect_fn, no YOLO):
- a fake detector that returns the same boxes shifted by the variant offset -> zero wobble
  after mapping back
- a fake detector that adds +-3 px noise -> wobble > 0 and roughly the noise level
- a detection missing in 2 of 8 variants -> matched_in 6
- same box, different class in one variant -> class_flips 1

Plan first and wait for my OK. After my OK you may run pytest and
`python -m scripts.measure_jitter` (detector only; tell me the expected time first).
Do not run OCR, run_comparison or the benchmark.
Report the table, and your reading of it in plain words: which classes are stable, which
are not, and whether the 0.05 C2 pass band is inside or outside the measured wobble.
Add the table and the reading under "Phase 17" in docs/memory.md.
Run `graphify update .`, list the files you changed, and stop.
```

---

## Prompt 17.3: per-element tolerance at runtime

Only after 17.1 and 17.2 have run and the numbers make sense.

```
Task: during each comparison, measure every element's own wobble (17.2's measure_wobble on
3-4 variants) and widen the C1/C2 pass band for that pair by it. This replaces a guessed,
app-specific pixel floor with a per-element measured one. It may only DOWNGRADE a C1/C2
finding (FAIL -> REVIEW -> PASS). It never creates one.

Read first: CLAUDE.md, src/detector/jitter.py (17.2), src/pipeline.py (build_document),
src/comparison/differ.py (C1 position and C2 size bands, where 14.2 pixel_check is applied),
src/comparison/pixel_geometry.py, config/config.yaml, docs/memory.md Phase 17.

1. Config: comparison.jitter_tolerance:
     enabled: false        # measure first, like 14.2
     n_variants: 4         # shift (1,1), shift (2,2), resample 0.9, jpeg 80
     k: 1.0                # safety factor; raise if real pairs wobble more than synthetic
   enabled: false must give byte-identical findings to today.

2. build_document: when jitter_tolerance is configured (even with enabled: false, so we can
   measure), run measure_wobble after detection and store per element
   metadata.wobble = {"rel_dw", "rel_dh", "dcx", "dcy", "matched_in"} (std values).
   It is saved inside the fused JSON, so rematch sees it without re-running anything.
   Elements that did not come from the detector (OCR-only) get no wobble entry.

3. differ.py, C1 and C2 only, for a matched pair a/b with wobble on both sides:
     tol_w = k * sqrt(a.rel_dw**2 + b.rel_dw**2)   (same for h, cx, cy)
     effective pass band = max(config pass band, tol)
   Apply it only when enabled: true. Always record details.jitter_check =
   {tol values, band used, "would_downgrade": bool} so the effect is visible while disabled.
   If either side has no wobble data, leave the finding exactly as today.
   Order with 14.2 pixel_verify: independent; a finding is downgraded if either says so.
   Record which one did it.

4. Detection stability: an element found in fewer than half the variants gets
   metadata.unstable = true. If an unmatched (B1/B2) element is unstable, cap that finding
   at REVIEW. It is the detector flickering, not a missing element. Behind the same flag.

Tests (hand-made docs, no images):
- enabled: false -> findings identical to today; details.jitter_check present
- wobble 0 on both sides -> identical to today even when enabled
- C2 diff 0.06, pass band 0.05, tol 0.07 -> PASS; diff 0.20 (resize_card-like) -> still FAIL
- one side missing wobble -> unchanged
- unstable unmatched element -> B1 capped at REVIEW
- self-compare -> 100% PASS

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch.
Say clearly that the saved fused JSONs have no wobble data yet, so seeing the effect needs
ONE fresh run per pair (detector + OCR). Ask me before running any of those.
Then give me the commands for: the two real pairs, the trending_search real case,
the 17.1 jitter cases, and all defect cases, plus what I should expect:
- jitter false alarms (C1/C2) go down vs the 17.1 "before" number
- every defect case still caught (resize_card C2, shift_title C1 in particular)
- --real-only still 0 false alarms
Record before/after in docs/memory.md under Phase 17. Keep enabled: false until I have
looked at the numbers and said to switch it on.
Run `graphify update .`, list the files you changed, and stop.
```
