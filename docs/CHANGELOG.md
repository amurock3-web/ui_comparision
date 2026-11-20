# Changelog

What was built, newest first. One short entry per phase; details and measurements are in
[`memory.md`](memory.md), the plan in [`phases.md`](phases.md). Dates come from those files and the
git history. There is no Phase 19.

## Handover packaging (2026-11-20)

Pinned requirements (`requirements.txt`, `requirements-detector.txt`), setup scripts (`setup.bat`,
`setup.sh`), the doctor (`scripts.check_setup`), the smoke test (`scripts.smoke_test`), models bundled
in `models/` with `SHA256SUMS.txt`, and the handover docs. Branch `handover-package`, not committed yet.

## Phase 20 — evaluation metrics and charts (2026-11-19)

`scripts/evaluate.py` scores saved benchmark results: precision, recall, F1 with Wilson intervals,
screen-level confusion matrix, `--pool`, and an `evaluation.html` with charts. Scoring only; checks
and verdicts unchanged (`a817330`).

## Handover docs (2026-11-18)

`docs/HANDOVER.md`, `AUTHORS.md`, README and `phases.md` fixes; client-derived baseline JSONs taken
out of git (`ac0ada6`).

## Report side-by-side at one scale (2026-11-18)

Both screenshots drawn at the same height in the report, with a note when the aspect ratios differ.
Display only (worked on 2026-11-06, committed `960eef3`).

## Gap analysis and explainer video (2026-11-02)

Gap analysis PDF and the pipeline explainer video added (`d33db20`).

## Phase 18 — policy v1 (2026-11-02)

Spec v1; a Minor FAIL makes the screen REVIEW; C1 element-size rule; low-confidence cap (built, left
off); scorecard headline and tester budget (`71f9423` to `84656b5`). Manager review pending.

## Phase 17 — benchmark re-scoring and detector wobble (2026-09-28 to 2026-10-07)

Cached benchmark re-scoring (`run_benchmark --cached`), detector box-wobble measurement, false-alarm
fixes, C2 pixel floor, `flagged_at_edit` score (`c326fa8`, `0d9ffee`). Pipeline demo video (`35580e6`).

## Phases 14-16 — match levels, baselines, web app (2026-09-25)

New checks (contrast, text colour, language, logo / icon / broken image), match levels and regions,
accepted differences, baselines, batch, run history, ticket CSV; the app with its pages, health checks
and job queue; Phase 14b false-alarm fixes from a real pair, 29 -> 16 findings (`ae58696`).

## Phase 13 — noise reduction and new checks (2026-09-24 to 2026-09-25)

Screen (A1-A5), colour (D1, D2, D5) and layout (B3, B4, B5, B8) checks; stop on a Critical screen
failure; 13.1 benchmark-driven noise cuts (`45b19eb`).

## Phase 12 — matching fix (2026-09-24)

Rematch script, element-count similarity and per-group shift matching (`220e57b`). Class refiner
experiment alongside (`e2d8393`, 2026-09-22 to 2026-09-24).

## Layout graph, HTML report, benchmark, web UI (2026-09-21)

Layout-tree graph, HTML report, the known-defect benchmark (`fddf6b3`) and the first drag-and-drop web
UI with progress bar and PDF report (`cbcf9c4`).

## Phase 10 — detector (2026-09-17 to 2026-09-18)

The ui16_v1 YOLO detector wired in as the primary element source; VLM made opt-in; PASS / REVIEW /
FAIL verdict layer from the spec; OCR text accuracy measured against the APK view hierarchy
(`efe0492` to `d8989ba`).

## Docker / CUDA sandbox (2026-09-08)

Container image and compose sandbox for the Linux GPU machine (`438eead`). Migration not done yet.

## Phases 3-8 — end-to-end POC (2026-09-07 to 2026-09-08)

Fusion, UI graph, matcher, difference engine and reporting, run end to end on one pair
(`d4397a9`, `6a69efd`).

## Phases 0-2 — foundation, OCR, local VLM (2026-08-20 to 2026-09-04)

Python 3.11 environment, PaddleOCR stage (`5eb34d0`), local VLM benchmarking (qwen2.5vl:7b kept,
qwen3-vl:4b rejected), repo recovered and module structure scaffolded (`34759cb`).
