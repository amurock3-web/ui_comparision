# UI Comparison: Handover

This is the handover summary for the manager. Install: [`HOW_TO_SETUP.md`](HOW_TO_SETUP.md) · Testers: [`USER_GUIDE.md`](USER_GUIDE.md) · Developers: [`CONTINUING_THE_PROJECT.md`](CONTINUING_THE_PROJECT.md)

Original author: Pralhadraj Joshi

Written 2026-11-18, updated 2026-11-20 (Phase 20, handover packaging) for whoever continues this
project. Start here, then use the links.
Anything marked **not verified** was written from reading files, not from running the code.
Anything marked **TODO (ask ...)** needs information the author or the manager has.

---

## 1. What this project is

QA teams at OTT (streaming) companies check every new app build against the client's design: is
every tab, button and title there, in the right place, at the right size, in the right colour,
with the right label? Today that is done by eye, screen by screen.

This tool does that check automatically. You give it two images of one screen:

- **Client design** (the reference): usually a Figma-style mockup from the client.
- **Production** (what is under test): a screenshot of the real app.

It finds the UI elements on both, pairs them up, and reports each difference with a verdict:

- **PASS**: within tolerance.
- **REVIEW**: borderline, or the tool is unsure. A tester looks at it.
- **FAIL**: clearly wrong. Severity Critical / Major / Minor.

It compares **layout and chrome** (position, size, shape, colour, orientation, static labels).
Poster artwork, movie titles in rails and the status bar change every day, so they are never
compared. It is not a pixel diff. Testers review the output; the tool's aim is to make sure no defect
is *silently* missed, not to replace the tester.

The spec it implements is [`test_cases_pass_fail.md`](test_cases_pass_fail.md) (check ids A-G).
Everything runs locally: no cloud OCR, no cloud VLM, no screenshot uploads ([`rules.md`](rules.md) §2).

## 2. Current state (checked against `src/` on 2026-11-18)

### Built and working (per the code and the test/benchmark runs in `memory.md`)

| Area | Where | Notes |
|---|---|---|
| YOLO UI detector (16 classes) | `src/detector/`, `models/ui16_v1/` | runs in its own Python, see §4 |
| OCR | `src/ocr/engine.py` | PaddleOCR, ~45 s per screen on CPU |
| Detector-first fusion | `src/fusion/fuse.py` (`fuse_detections`) | OCR text hung on detector boxes |
| Layout-tree graph | `src/graph/layout.py` | sections, rows, overlays, clipped, hidden cards |
| Matcher + group shift | `src/comparison/matcher.py` | a panel that moved as one is one finding |
| Differ, 25 of the spec's 39 check rows | `src/comparison/differ.py` + pure modules beside it | A1-A3, A5, B1-B5, B8, B9, C1, C2, C4, D1-D3, D5, D7, E1, E3, E4, F1-F3 (spec "Coverage" table; `gap_analysis.pdf` says "24 of 41") |
| Match levels, regions, dynamic-text patterns | `src/comparison/regions.py`, `config/screen_rules/` | STRICT / LAYOUT / IGNORE_COLORS / NONE, FLOATING |
| Accepted differences | `src/comparison/accepted.py` | an accepted finding comes back as PASS (accepted) |
| Report: JSON, HTML, PNG, PDF, issues, coverage, history | `src/reporting/` | PDF via headless Edge |
| Baselines (stored client designs) | `src/baselines.py`, `baselines/` | stale detection by config hash |
| Batch | `scripts/run_batch.py`, app Batch page | resumable |
| Ticket CSV | `src/reporting/export.py`, `config/ticket_export.yaml` | columns are still defaults |
| Web app | `src/app/` | Compare, History, Results, Rules, Baselines, Batch, Help, job queue, health chips |
| Known-defect + real-pair benchmark | `scripts/make_benchmark.py`, `scripts/run_benchmark.py` | scorecard HTML |
| Policy v1 (Phase 18) | `config/config.yaml`, spec v1 | pending manager review |
| Evaluation metrics (Phase 20) | `scripts/evaluate.py` | precision / recall / F1 with Wilson intervals, screen matrix, `evaluation.html` charts, from saved `results.json` (seconds) |
| Handover packaging (2026-11-20) | `setup.bat`, `setup.sh`, `scripts/check_setup.py`, `scripts/smoke_test.py`, `requirements*.txt`, `models/` | one-command setup, doctor, seconds-long smoke test, bundled models with checksums ([`HOW_TO_SETUP.md`](HOW_TO_SETUP.md)) |

### Partial

- **Old CLI** `src/main.py` fuses with `fuse_detections`, like `src/pipeline.py`, but still builds
  the older pairwise graph (`src/graph/build.py`). The app, `run_comparison` and the benchmark use
  `src/pipeline.py`. The legacy `FusionEngine.fuse()` path is called only by `tests/test_fusion.py`.
  The 15 known test failures are in that legacy code (§8).
- **VLM** (`src/vlm/`, Ollama `qwen2.5vl:7b`): only with `src.main --vlm`, only for elements fusion
  left uncertain. `src/pipeline.py` does not use it. Not run since September (not verified with current code).
- **F1 / F2** (logo / icon SSIM) are wired but idle: the detector rarely outputs `logo` or `icon` on
  the screens tested.
- **Dynamic-text patterns** (price, duration, episode, date) are built but matched no label on the
  saved screens, so they are idle.
- **Low-confidence cap** (spec §I, P7) is built and **off by decision** (dry-run record only).
- **Docker / GPU**: `Dockerfile` + `docker-compose.yml` exist, but the move to the Ubuntu GTX 1070
  machine is a plan, not done ([`migration_ubuntu_gpu.md`](migration_ubuntu_gpu.md)). The image has
  no detector Python, publishes no port and has no Edge.
- **Class refiner** (`scripts/*refiner*`, `config/class_refiner.yaml`): an experiment; not adopted.
- **App browser click-through**: `memory.md` records in-process handler tests of the app (2026-09-29)
  but says the browser UI itself was not clicked through. The Cricket trial (2026-11-06) used the
  app's reports. Whether every page has been clicked through since: **not verified**.

### Not started

- Spec checks A4, B6, B7, C3, D4, D6, E2, E5-E7, F4, G1-G3 (spec "Coverage" table).
- Spec §I "<50% matched means cannot compare": no "inconclusive" verdict exists in `src/`.
- Ignoring a live video area, comparing dynamic text values by position only (Cricket trial).
- A VLM judge for REVIEW findings; grouping one difference across many screens.
- Retraining the detector on other apps.

### Benchmark numbers (from `memory.md`, Phase 18.4, 2026-11-02)

These are the current baselines. They were re-scored from cached fused JSONs (`--cached`), so no
detector or OCR ran for them.

Known-defect benchmark (synthetic: one known edit per case):

| run | screens | flagged at edit | exact spec id | false alarms | identity clean |
|---|---|---|---|---|---|
| test22 (`--cached test16_benchmark ss012 ss031 jiohotstar_test_ss`) | ss012, ss031, jiohotstar_test_ss | 19/19 | 17/19 (89%) | 3 | 3/3 |
| test23 (`--cached test17_benchmark sunnxt_live_movie_detail`) | sunnxt_live_movie_detail | 7/7 | 4/7 (57%) | 1 | 1/1 |

Real pair (production screenshot vs real design mockup):

| run | pair | verdict | false alarms | unlisted | misses | tester load (issues) | findings | over budget (5) |
|---|---|---|---|---|---|---|---|---|
| test24 (`--real-only`) | trending_search | FAIL, expected REVIEW | 2 (D1 Home, C2 Search FAIL) | 3 | 0 | 15 | 16 | yes |

History, for comparison: test3 (2026-09-24, older differ) caught 13, 15 false alarms; test7
(2026-09-29) 17/19 caught, 3 false alarms. Phase 18 made no change to detection.

Cricket App trial (2026-11-06, not a benchmark): two pairs, both FAIL with 26-29% matched and
34-43 findings, mostly noise (see §9).

### Evaluation numbers (from `memory.md`, Phase 20, 2026-11-19)

`python -m scripts.evaluate output/benchmark/test22_benchmark output/benchmark/test23_benchmark
output/benchmark/test24_benchmark --pool`, scored from the same saved results as above. Pooled
output with charts: `output/evaluation/test3_evaluation/` (`evaluation.html`). Wilson 95% intervals.

| metric (pooled, 30 cases) | value |
|---|---|
| lenient recall (finding on the edited element) | 1.000 [0.871, 1.000] 26/26 |
| lenient precision (case TP vs finding FP) | 0.867 [0.703, 0.947] 26/30 |
| lenient F1 | 0.929 |
| exact-id recall / precision / F1 | 0.808 (21/26) / 0.840 (21/25) / 0.824 |
| false alarms per screen, mean / max | 0.13 / 1 |
| screen accuracy | 1.000 [0.886, 1.000] |
| screen specificity (identity PASS) | 1.000 [0.510, 1.000] 4/4 |
| real pair verdict exact | 0/1 (REVIEW expected, FAIL given) |

Weak spots: only 4 identity cases (specificity lower bound 0.51), exact-id recall on the detail page
4/7, and the thresholds were tuned on these screens, so all numbers are optimistic.

## 3. Architecture in one page

```
                     config/detector.yaml        config/config.yaml
                            │                           │
screenshot ──┬── YOLO detector (src/detector/, separate Python) ──┐
             └── PaddleOCR (src/ocr/) ────────────────────────────┤
                                                                  ▼
                       Fusion: fuse_detections (src/fusion/fuse.py)
                       OCR text onto detector boxes; poster text dropped;
                       status bar ignored; uncertain → REVIEW (or VLM with src.main --vlm)
                                                                  │
                                         fused UIDocument JSON (src/schema/ui_element.py)
                                         saved as <side>_fused.json  ◄── rematch / baselines reuse this
                                                                  │
                       Layout graph (src/graph/layout.py): sections, rows, overlays, clipped
                                                                  │
         client graph ──────── Matcher (src/comparison/matcher.py) ──────── production graph
                               class + text + position + size + context, group shifts
                                                                  │
                       Differ (src/comparison/differ.py): every check in order,
                       maths in screen_checks, layout_checks, color_checks, contrast_checks,
                       pixel_geometry, image_checks, script_checks; regions.py (match levels),
                       accepted.py (accepted differences)
                                                                  │
                       Report (src/reporting/): verdict + spec ids + coverage (report.py),
                       issues (grouping.py), new/fixed (history.py), HTML/PDF (html_report.py),
                       side-by-side PNG (visualize.py), tickets CSV (export.py)
```

- `src/pipeline.py` is the shared path: `build_document` (screenshot → fused doc) and
  `compare_documents` (two docs → report). Used by `scripts/run_comparison.py`,
  `scripts/run_benchmark.py`, `scripts/rematch.py` (from saved JSON) and the web app.
- The client design is the reference; production is the thing under test. An unmatched client
  element is MISSING_IN_PRODUCTION (B1), an unmatched production element EXTRA_IN_PRODUCTION (B2).
- Positions and sizes are normalised (fraction of screen width / height / diagonal), so different
  devices compare. A few pixel floors are not normalised (§9).
- Detail: [`architecture.md`](architecture.md), [`design.md`](design.md). Some sections there are
  marked "proposed" or "parked" and are still accurate about that.

## 4. Setup from zero

### 4a. Windows (the path that is in daily use)

The handover medium is the zip (`ui_comparison_handover_<YYYYMMDD>.zip`, one top folder
`ui_comparison/`): code, full git history, models, `input/`, `output/` and `baselines/`. Unzip it,
then run setup once. Full steps, Ubuntu included, and the troubleshooting table:
[`HOW_TO_SETUP.md`](HOW_TO_SETUP.md).

```powershell
setup.bat                                   # Windows; Ubuntu: bash setup.sh
.venv\Scripts\python.exe -m scripts.check_setup   # doctor; Ubuntu: .venv/bin/python -m scripts.check_setup
```

- Python 3.11 is required. Setup needs internet the first time (~10-20 min); after that everything
  runs offline (except the optional Ollama VLM). It is safe to re-run.
- Setup creates two venvs at the project root: `.venv` (`requirements.txt`, paddle + app) and
  `.venv-detector` (`requirements-detector.txt`, ultralytics + torch). They must never be merged:
  ultralytics / torch next to paddlepaddle breaks it.
- The detector Python is found automatically: `UI_DETECTOR_PYTHON` if set, else
  `.venv-detector`, else `python_path` in `config/detector.yaml` (blank). No `.env` or manual path
  is needed.
- The YOLO weights (`models/ui16_v1/best.pt`) and the PaddleOCR models
  (`models/paddlex/official_models/PP-OCRv6_medium_{det,rec}`) are in the zip. `src/ocr/engine.py`
  points PaddleX at `models/paddlex`, so OCR never downloads. The doctor checks them against
  `models/SHA256SUMS.txt`.
- The `UI_Detection_model_training` repo is not needed to run the tool. It is only needed to retrain
  the detector or to run the class-refiner scripts (`config/class_refiner.yaml` expects it at
  `../UI_Detection_model_training`).

No model? Set `engine: gt_stub` in `config/detector.yaml` to replay the hand labels. It only knows
the 103 labelled SunNXT screenshots, by file name.

**Microsoft Edge** (optional) prints the PDF report. Without it, open the HTML and use the
browser's Save as PDF.

**Ollama + VLM** (optional, only `python -m src.main ... --vlm`):

```powershell
ollama pull qwen2.5vl:7b     # the model named in config/config.yaml vlm.model
ollama serve
```

### 4b. Docker / GPU (Linux; partial, not verified end to end)

```bash
cp .env.example .env          # fill CODE_DIR, DATA_DIR, UID (id -u), GID (id -g)
docker compose up -d --build
docker compose exec app bash
```

The code is bind-mounted, `input/` is mounted read-only, `output/` read-write, `HOME` caches live in
the `app_cache` volume (OCR uses the bundled `models/paddlex` from the mounted code; not verified in
the container), Ollama runs in its own container. What does not work yet (from
[`migration_ubuntu_gpu.md`](migration_ubuntu_gpu.md)): no detector Python in the image; the app
binds 127.0.0.1 inside the container and no port is published (`src.app` has no `--host` flag yet);
no Edge for the PDF; `make_benchmark` writes into the read-only `input/`; GTX 1070 needs torch from
the cu126 index; 8 GB VRAM must be shared by PaddleOCR, YOLO and Ollama. Background:
[`environment.md`](environment.md) (parts of it are older, see its §6).

### 4c. What is not in git, and where to get it

| Item | Needed for | Where it is | Owner |
|---|---|---|---|
| `models/ui16_v1/best.pt` | real detector | in the zip; produced by `UI_Detection_model_training` | company (trained by the author) |
| `models/paddlex/` (PP-OCRv6 det + rec) | OCR | in the zip | PaddlePaddle (public models) |
| `.venv`, `.venv-detector` | running anything | not in the zip; built by setup (a copied venv does not work on another computer) | you |
| `UI_Detection_model_training` repo | retraining, refiner scripts only (not needed to run) | separate repo, expected at `../UI_Detection_model_training` | **TODO (ask Pralhadraj / manager): where it lives and who owns it** |
| `input/` screenshots (`production/`, `client/`) | running real pairs | in the zip (gitignored) | client data, internal only |
| `input/benchmark/` (defect cases, `real/trending_search/` with manifest and cached fused JSONs) | benchmark, smoke test | in the zip (gitignored) | client data, internal only |
| `output/` (benchmark runs incl. `test16_benchmark`, `test17_benchmark`; `output/app/` runs) | `--cached` re-scoring, History, Re-check | in the zip (gitignored); [`../output/INDEX.md`](../output/INDEX.md) says which runs matter | client data, internal only |
| `baselines/**/client.*` images and `client_fused.json` | stored client designs | in the zip (gitignored; `meta.json` is in git) | client data, internal only |
| Ollama + `qwen2.5vl:7b` (~6 GB) | `--vlm` only | not in the zip; `ollama pull qwen2.5vl:7b` | Ollama library (public) |
| `.env` | Docker only | create from `.env.example` | you |

The zip holds SunNXT / JioHotstar client screenshots and reports: internal only, never share it
outside the company or upload it anywhere (rules.md §2).

## 5. First 30 minutes: smoke test (to run by the new owner)

Run these two first (seconds each, no detector or OCR). Both passed on the author's laptop on
2026-11-20 (`memory.md`).

```powershell
.venv\Scripts\python.exe -m scripts.check_setup   # doctor: one PASS / FIX / INFO line per check, exit 0 = ready
.venv\Scripts\python.exe -m scripts.smoke_test    # prints SMOKE TEST: PASS; output in output/smoke/testN_smoke/
```

Ubuntu: `.venv/bin/python` instead of `.venv\Scripts\python.exe`. Fix every FIX line the doctor
prints before going on. The smoke test runs the real pair `trending_search` from cached fused JSONs
(expected FAIL with 16 findings; the manifest expects REVIEW, a known gap, shown as INFO) and a
client self-compare (expected PASS, 0 findings).

The longer manual steps below were not run while writing this document; expected results come from
`memory.md`. Commands assume the `.venv` Python.

| # | Command | Expected | Needs |
|---|---|---|---|
| 1 | `python -m src.health` | every required check OK; Edge may be "not found" (amber, optional) | §4a done |
| 2 | `"UI Compare.bat"` (or `python -m src.app`) | browser opens http://127.0.0.1:8765 (next free port up to 8775); health chips green; Compare button enabled | §4a done |
| 3 | `python -m scripts.rematch input/benchmark/real/trending_search/client_fused.json input/benchmark/real/trending_search/client_fused.json` | self-compare: PASS, 100% matched, 0 findings; output in `output/rematch/testN_*` | `input/benchmark/` |
| 4 | `python -m scripts.run_benchmark --real-only` | ~10 s; trending_search FAIL vs expected REVIEW, 2 false alarms, 0 misses, 3 unlisted, tester load 15 (as test24) | `input/benchmark/real/` |
| 5 | `python -m pytest tests -q` | the 15 known failures only (14 in `tests/test_fusion.py`, 1 in `tests/test_graph.py`); the real-YOLO test in `test_detector.py` is skipped unless `UI_DETECTOR_PYTHON` is set and `best.pt` exists | venv + pytest |
| 6 (optional) | `python -m scripts.run_benchmark --cached test16_benchmark ss012 ss031 jiohotstar_test_ss` | 19/19 flagged, 17/19 exact id, 3 false alarms, identity 3/3 (as test22) | `output/benchmark/test16_benchmark` |
| 7 (optional, ~90 s) | `python -m scripts.run_comparison input/production/ss012.png input/client/ss012.png` | finishes and writes a numbered `output/comparison/testN_*` report; exact verdict not recorded in memory.md | detector + OCR |

If 1 fails, fix what it names first (§12). If 3 is not PASS 100%, something in the compare stage
changed: stop and check `git diff`.

## 6. How to use it

### The web app (`"UI Compare.bat"`, `./start.sh` or `python -m src.app [--port N] [--no-browser]`)

Listens on localhost only. Each run is kept in `output/app/<timestamp>/`.

- **Compare** (`#/compare`): drop the production screenshot and the client design, press Compare.
  A progress bar steps through the stages (about a minute per image on CPU). Or tick "Client: use
  a saved baseline" so only the production side runs detector + OCR.
- **Results** (`#/results/<run>`, opens after a run): verdict, counts, side-by-side with every
  finding's boxes, issues sorted FAIL Critical > Major > Minor > REVIEW, filters by verdict and family
  A-G. Downloads: PDF (first report only), HTML, report.json, tickets CSV.
- **History** (`#/history`): every run, newest first, search and verdict filter.
- **Rules** (`#/rules`): per client screen, draw regions on the client image (NONE, FLOATING,
  LAYOUT, IGNORE_COLORS, STRICT), set the match level, add dynamic-text regexes and test them, Save
  (keeps a `.bak`), "Try on last run" shows before/after counts.
- **Baselines** (`#/baselines`): add a client design once (detector + OCR, ~1 min, queued), list,
  stale flag, delete (archives to `baselines/_archive/`).
- **Batch** (`#/batch`): many production screenshots, each paired to a baseline by file name; live
  table; summary download. The table lives in memory until the app restarts.
- **Help** (`#/help`): PASS / REVIEW / FAIL, families A-G, where runs are kept.

Tester workflow on one issue (all actions are local files, listed with an **Undo**):

1. **Accept**: a deliberate difference. Writes to `baselines/accepted_differences.yaml`; comes back
   as PASS (accepted) on later runs until the element changes.
2. **Ignore region**: adds NONE regions around the issue's boxes to
   `config/screen_rules/<client screen>.yaml` (old file kept as `.bak`).
3. **Mark as bug**: tags it in the run's `review.json`.
4. **Re-check** (with a match-level dropdown): redoes match + differ + report from the run's saved
   fused JSONs in seconds into `report_2.json`, `report_3...`; nothing is overwritten.
5. Download the **tickets CSV**: one row per issue.

### CLI equivalents

```powershell
python -m scripts.run_comparison <production.png> <client.png>              # full pair, ~90 s
python -m scripts.rematch <production_fused.json> <client_fused.json>      # seconds, no detector/OCR
python -m scripts.rematch <p.json> <c.json> --match-level LAYOUT --rules my_rules.yaml
python -m scripts.add_baseline <client_image> --screen <id>                 # ~1 min
python -m scripts.add_baseline --list
python -m scripts.run_comparison <production.png> --baseline <id>          # ~45 s
python -m scripts.run_batch <folder>                                       # ~45 s per screenshot
python -m scripts.accept_finding <report.json> --finding N --note "..."
python -m scripts.export_tickets <report.json>
python -m scripts.run_detector|run_ocr|run_fusion <image>                  # one stage, numbered output
python -m scripts.build_graph_from_fusion <fused.json> --layout
python -m src.main --production-image ... --production-screen-id ... --client-image ... --client-screen-id ... [--vlm]
```

Script output is numbered `testN_*` under `output/<stage>/`; earlier runs are never overwritten.

## 7. Configuration guide

Rule: **thresholds live in config, not in code.** Change a value, then rematch saved JSONs to see
the effect in seconds (`scripts.rematch`, `run_benchmark --real-only`, `run_benchmark --cached`).

| File | What it holds |
|---|---|
| `config/config.yaml` | every threshold and on/off switch: `ocr`, `matching`, `comparison` (all checks), `vlm`, `fusion`, `graph`, `reporting`, `benchmark` |
| `config/detector.yaml` | engine (`yolo` / `gt_stub`), bundle, detector Python (`python_env_var`, then `.venv-detector`, then `python_path`, blank), confidence tiers (high 0.70, medium 0.40) |
| `config/classes.json` | the 16-class taxonomy (`v2-16class-2026-09-02`) |
| `config/screen_rules/<client screen id>.yaml` | per-screen match level, regions, dynamic-text patterns. Empty today and not in git (git does not track empty folders). Missing folder or file is fine: `regions.load_rules` and `actions.get_rules` check `is_file()` and fall back to defaults, and writes create the folder (verified by reading `src/comparison/regions.py` and `src/app/actions.py`) |
| `config/ticket_export.yaml` | ticket CSV columns; still defaults, needs the team's real sheet |
| `config/class_refiner.yaml` | the refiner experiment only; expects the training repo at `../UI_Detection_model_training` |

Thresholds that matter most (`config/config.yaml`):

| Key | Value | What changing it does |
|---|---|---|
| `matching.minimum_match_score` | 0.70 | lower: more pairs, fewer B1/B2, more wrong pairs |
| `comparison.position_bands` | pass 0.01, fail 0.03, major 0.06 (of diagonal) | C1 bands |
| `comparison.position_element_rule` | enabled, factor 1.0 | C1 REVIEW → FAIL Minor when a move exceeds the element's own size |
| `comparison.size_bands` | pass 0.05, fail 0.15 | C2 bands; the biggest noise source with box wobble |
| `comparison.size_min_px` | 4 | C2 pixel floor, in client pixels (resolution-dependent, §9) |
| `comparison.static_text_classes` | tab_item, button, section_title, search_bar | only these get E1 text checks |
| `comparison.critical_classes` | button, tab_item, navigation_bar, logo | a missing one is B1 Critical |
| `comparison.dynamic_on_card_classes` | [overlay_badge] | what on a poster card counts as dynamic |
| `comparison.cap_clipped_to_review` | true | cut-off elements are REVIEW at most |
| `comparison.low_confidence_cap` | enabled false | P7 cap; dry-run record only |
| `comparison.stop_on_critical_screen_failure` | true | A1/A2 Critical stops element checks |
| `comparison.color` / `contrast` / `image` / `screen` / `layout` | see file | D, F, A and B bands |
| `fusion.status_bar_height_norm` | 0.04 | top band ignored as status bar |
| `reporting.minor_fail_verdict` | REVIEW | P1; PASS restores the old rule |
| `reporting.side_by_side_aspect_warning` | 0.05 | display-only note in the HTML |
| `benchmark.review_budget_per_screen` | 5 | P4 tester budget (issues per real pair) |

Baselines are marked stale when `config/detector.yaml` or the `ocr` / `fusion` / `vlm` sections
change (comparison thresholds do not make them stale).

## 8. Tests and benchmarks

```powershell
python -m scripts.check_setup                   # doctor: setup, models, configs (seconds)
python -m scripts.smoke_test                    # real pair + self-compare from cached JSONs (seconds)
python -m pytest tests -q                       # unit tests
python -m scripts.make_benchmark                # writes defect copies into input/benchmark/<screen>/
python -m scripts.run_benchmark                 # ~20 min, OCR on every case (ask before running)
python -m scripts.run_benchmark --real-only     # ~10 s, real pairs from cached fused JSONs
python -m scripts.run_benchmark --cached <testN_benchmark> [screens...]   # seconds, re-score a saved run
python -m scripts.run_benchmark --real-only --compare-to <testN_benchmark>
python -m scripts.evaluate output/benchmark/<testN_benchmark> [more run dirs] [--pool]   # P/R/F1, Wilson CIs, screen matrix + evaluation.html charts (Phase 20)
```

### Known failing tests

These 15 tests failed before the handover packaging and still fail the same way. The names were diffed against
commit `a817330` (Phase 20), so the packaging did not break them. Full run on 2026-11-20: 343 passed,
15 failed, 1 skipped.

| Test | Why it fails |
|---|---|
| `tests/test_fusion.py::test_text_matchable_class_grounded_by_ocr_bbox` | Legacy `FusionEngine.fuse()`: the test does not pass the required `grounded_cards` argument (TypeError). |
| `tests/test_fusion.py::test_ungrounded_vlm_classification_kept_with_no_bbox` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_unmatched_ocr_kept_as_orphan_evidence` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_content_card_grid_inference` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_badge_promoted_via_keyword_and_card_containment` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_badge_keyword_outside_low_confidence_not_promoted` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_duplicate_text_disambiguated_by_approximate_location` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_som_id_match_resolves_collision_text_similarity_gets_wrong` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_som_id_unknown_falls_back_to_text_similarity` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_zone_only_fallback_grounds_element_with_no_text` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_zone_only_fallback_discounts_confidence_vs_text_match` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_section_titles_with_no_text_still_split_cards_into_rows` | Same: legacy `fuse()` called without `grounded_cards`. |
| `tests/test_fusion.py::test_detections_take_ocr_text_and_cards_keep_children` | `fuse_detections()`: the test expects the tab to get the text "TV Shows", but the tab now has no text. The expectation is older than later fusion changes; not triaged yet. |
| `tests/test_fusion.py::test_low_tier_card_does_not_swallow_tab_text` | `fuse_detections()`: the test expects the tab text "Movies Live TV More Soon", but the tab now has no text. Same cause as the test above; not triaged yet. |
| `tests/test_graph.py::test_relations_not_generated_for_every_possible_pair` | The older `src/graph/build.py` (still used by `src/main.py`) gives one pair 4 relationship types, and the test allows at most 3. |

Gap analysis 7.1 recommends deleting the legacy `fuse()`, `build.py` and `main.py` path instead of fixing
these 13 legacy tests. Look at the 2 `fuse_detections()` tests before touching fusion, because they test the
live path.

### What the scores mean

Scores come from `output/benchmark/testN_benchmark/scorecard.html` and `results.json`.

- *flagged at edit X/Y*: synthetic cases where some finding landed on the edited element
  (caught + caught as other). The headline: no silent miss.
- *exact spec id X/Y*: of those, the finding has the expected spec id (e.g. B1, not C2).
- *identity clean*: the unedited copy gives PASS.
- *false alarms*: findings on elements that were not edited.
- Real pairs (`input/benchmark/real/<name>/manifest.json`): *verdict ok* (screen verdict equals
  `expected_verdict`), *false alarms* (hit `must_not_flag`), *misses* (missed `must_flag`),
  *unlisted* (in neither list), *tester load* (REVIEW + FAIL issues), *over budget* (load above 5).

## 9. Known issues and limits

**Cricket App trial, 2026-11-06** (two real pairs, design = screenshots of a Figma WIP file, no
proper export). Both FAIL at 26-29% matched with 34-43 findings, and no real build defect found:

- The live video area is not ignored: banners, a streaming logo, scoreboard text and the LIVE badge
  made about 23 of 27 EXTRA findings.
- Dynamic text values (teams, dates, toss) are compared as words, giving missing/extra and false
  size/position findings. Static labels (Match, Series, Date) matched fine.
- The design image was cropped and low resolution (screen capture): two false B8 clipping FAILs
  and weaker OCR.
- The "Info" tab was detected as an icon in production, and was missing in the design.
- No "inconclusive" verdict: a very low match rate still gives a headline FAIL with dozens of findings.

**PDF report scale: diagnosed, not fixed.** After printing, images are not at the right scale.
Likely causes, all in code:

- `src/reporting/html_report.py`, the `@media print` block: `img.shot { ... max-height:62vh ... }`
  shrinks the side-by-side to fit 62% of the page height.
- `src/reporting/visualize.py`: label font and box line width are fixed pixels, so after scaling
  the image they print at different sizes per report.
- `src/reporting/html_report.py` `_crop(img, bbox, pad=40, max_h=180)`: fixed 40 px padding, and each
  side is resized on its own to 180 px high, so production and design crops have different zoom.

**Resolution-dependent pixel floors** (counted in client pixels, so the same layout can get a
different verdict at a different design resolution): `comparison.size_min_px: 4` (C2) is ~1% of a
390 px design but ~0.2% of a 1920 px one; also `pixel_verify.margin_min_px: 2`, the 2 px colour-crop
guard, `tight_box` `min_pixels: 16`. Everything else works in normalised units.

**Known false alarms:**

- Real pair trending_search: FAIL where REVIEW is expected (test24).
- D1 on a tab_item that contains logo artwork: the colour of the whole tab box includes
  background/glow, the logo colour itself is the same ("SUN NT Home", dE 7.91).
- C2 above 15% is always Major; a 24% change on a small tab icon was barely visible ("Search").
- relabel_title C1: when a label gets shorter, its box centre moves although the left edge does
  not ("Action Crime" → "Action", 75 px); the 18.2 rule then makes it FAIL Minor. Candidate fix:
  measure left-aligned labels by their left edge.
- ss012 relabel_title B2 on a duplicate `metadata_text` box (the detector boxed one word twice).
- Untraced: D1 on jiohotstar swap_tabs "Sports", B4 on ss012 swap_tabs "More".

**Detector** (`ui16_v1`, YOLOv8s, val mAP@50 0.877): trained on 103 SunNXT screenshots only (83
train / 20 val). Weak: button (recall 0.58, mostly missed boxes, not wrong class), icon, metadata_text,
rank_number (4 samples); logo and text_input have almost no samples. Other apps and design mockups
were never in training; the plan is 20-30 screens from each of 4-5 apps, with model-assisted
labelling. Boxes also wobble in size (tab_item p95 ~0.10), the main source of C2 noise.

**Speed**: OCR ~45 s per screen on CPU, ~90 s per pair, ~20 min for the full benchmark. GPU OCR
was 1.6 s per screen on the GTX 1070 in September, but the Ubuntu GPU migration is still a plan.

**Policy v1** (Phase 18: P1 Minor FAIL → REVIEW, P2 C1 element-size rule, P3/P4/P6 scorecard and
tester budget, P5, P7 cap off, P8) was decided by Pralhadraj with Claude on 2026-11-02 and is
**pending manager review** (Dhanya, name to be confirmed by Pralhadraj).

**Spec vs code**: spec A5 says "key element sizes vs screen width", the code compares the canvas
aspect ratio.

**Docs that are older than the code** (kept as history, read with care): the phase table and "Next
immediate task" sections near the top of `memory.md` (last verified 2026-09-18; the dated
sections further down are current), `environment.md` §1, §5, §8 (base image, `qwen3-vl:4b`),
`migration_ubuntu_gpu.md` (quotes test3 as the baseline score and a `--host` flag that does not exist).

## 10. Roadmap (prioritised)

From `memory.md`, `phases.md`, the Cricket trial notes and [`gap_analysis.pdf`](gap_analysis.pdf)
(2026-09-28; its P0 items 2.1-2.3 are still open). Not yet agreed with the manager.

| # | Next step | Why it matters | Files |
|---|---|---|---|
| 1 | Inconclusive / "cannot compare" verdict (spec §I, <50% matched) | wrong pairs today give FAIL + dozens of findings; testers lose trust | `src/comparison/differ.py`, `src/reporting/report.py`, `config/config.yaml` |
| 2 | Ignore live video / player regions | ~23 of 27 EXTRA findings in the Cricket trial | `src/comparison/regions.py`, `config/screen_rules/`, maybe a default region in `config/config.yaml` |
| 3 | Dynamic text values compared by position only (key/value rows) | different matches/dates gave false B1/B2/C1/C2 | `src/comparison/differ.py` (E1), `src/comparison/matcher.py` (text score), `comparison.dynamic_text` |
| 4 | PDF scale fixes (§9) | printed reports are the deliverable for testers | `src/reporting/html_report.py`, `src/reporting/visualize.py` |
| 5 | Input checks: low-resolution / cropped design, open keyboard, system nav band (gap 2.2, 2.3) | bad input produces walls of findings | `src/comparison/screen_checks.py`, `src/pipeline.py` |
| 6 | Collect 15-30 real mockup-vs-production pairs; score precision per spec id from Accept / Mark-as-bug clicks | all tuning rests on 1 real pair | `input/benchmark/real/`, a new `scripts/score_labels.py` (gap 1) |
| 7 | Fix the known false alarms (§9): D1 on logo tabs, C2 on small icons, C1 on shortened labels | real-pair verdict FAIL vs REVIEW | `src/comparison/color_checks.py`, `layout_checks.py`, `config/config.yaml` |
| 8 | VLM judge for REVIEW findings (local Ollama only) | cut tester load without silent misses | `src/vlm/`, `src/comparison/differ.py` |
| 9 | Group the same difference across screens in a batch | one bug, one ticket | `src/reporting/grouping.py`, `scripts/run_batch.py`, `src/reporting/export.py` |
| 10 | New-client onboarding: per-screen rules, baselines, ticket columns | each new app needs its rules files | `config/screen_rules/`, Rules page, `config/ticket_export.yaml`, [`architecture.md`](architecture.md) §20 |
| 11 | Detector data from other apps + mockups, retrain; class refiner only if results show class errors | trained on SunNXT only; button misses are missed boxes | `UI_Detection_model_training` repo, `models/`, `config/class_refiner.yaml` |
| 12 | Normalise the pixel floors (§9) | same layout, different verdict per resolution | `config/config.yaml`, `src/comparison/differ.py`, `pixel_geometry.py` |
| 13 | Ubuntu GPU migration | OCR 45 s → ~2 s per screen makes tuning practical | [`migration_ubuntu_gpu.md`](migration_ubuntu_gpu.md), `Dockerfile`, `docker-compose.yml`, `src/app/__main__.py` |
| 14 | Housekeeping: retire legacy `fuse()` / `build.py` / `main.py` path (the 15 failures), merge the local branches to `main` (§15). (Pinning requirements and removing the author's config paths were done in the handover packaging.) | a clean start for the next owner | `src/fusion/fuse.py`, `src/graph/build.py`, `src/main.py` |
| 15 | Manager review of policy v1 | Phase 18 rules are not confirmed | [`test_cases_pass_fail.md`](test_cases_pass_fail.md), `config/config.yaml` |

## 11. Decisions and why

- **Local only** (no cloud OCR/VLM/APIs): client screenshots are confidential (rules.md §2). A cloud
  decision model (TypeSafe Jev) was rejected for this reason (rules.md §18).
- **Detector first, then OCR**: VLM boxes were non-deterministic (~4% drift); YOLO gave
  byte-identical output on repeated runs. OCR gives exact text, the detector gives class; neither
  stands in for the other.
- **VLM opt-in**: the status-bar clock triggered it on every screen; uncertain elements are REVIEW
  instead.
- **JSON + graph, both kept**: JSON is the reproducible record (rematch, baselines); the graph gives
  context for matching and layout checks.
- **No XML (uiautomator) route**: the dumps have no visibility flag and keep hidden views ("ghost"
  tab bars), and client designs have no XML anyway. Used only as an OCR accuracy oracle.
- **Separate detector repo and Python**: ultralytics/torch and paddlepaddle conflict in one env.
- **VLM model `qwen2.5vl:7b`**: `qwen3-vl:4b` rejected (thinking mode cannot be disabled, runs out of
  tokens); `LocateAnything-3B-GGUF` rejected (appends "None", non-commercial licence); Molmo deferred
  (no Ollama/GGUF build).
- **Client design is the reference**, production is under test (spec §0).
- **Poster artwork and rail titles are dynamic content**: they change daily; check the container, not
  the content.
- **Class refiner not adopted**: YOLO's class is right 97% of the time once it boxes an element.
- **Per-class box-wobble tolerance dropped** (Phase 17): it would turn real defects into REVIEW and
  removed none of the remaining false alarms.
- **Low-confidence cap off** (18.3): on the cached cases it capped 7 true defects and 0 false alarms.
- **Minor FAIL → screen REVIEW** (P1): a Minor FAIL should reach a tester.

## 12. Troubleshooting

Setup and install problems (Python version, venvs, missing models, launcher says "run setup first",
OpenCV libraries on Ubuntu): see the troubleshooting table in [`HOW_TO_SETUP.md`](HOW_TO_SETUP.md).
`python -m scripts.check_setup` names most of them with a FIX line. The rest:

| Symptom | Cause | Fix |
|---|---|---|
| Detector chip red / "detector Python not found" | no `.venv-detector` (setup not run or failed) and `UI_DETECTOR_PYTHON` unset | run `setup.bat` / `bash setup.sh` again, or set `UI_DETECTOR_PYTHON` to a Python that has ultralytics |
| `ImportError` / crashes after installing ultralytics | ultralytics/torch installed in `.venv` next to paddle | uninstall them from `.venv`; they belong only in `.venv-detector` (the doctor flags this) |
| `UnicodeEncodeError` on print (Tamil / CJK / ₹) | Windows console is cp1252 | run scripts that import `scripts/_test_utils.py` (forces UTF-8); keep that import in new scripts |
| App starts on 8766 or later | port 8765 taken | it uses the next free port up to 8775; or `python -m src.app --port 8800` |
| PDF download missing / Edge chip amber | Microsoft Edge not installed | open the HTML report and use the browser's Save as PDF |
| Baseline disabled, "stale" | built under other detector/OCR/fusion settings | `python -m scripts.add_baseline <client_image> --screen <id>` again |
| Compare button disabled | a required health check failed | `python -m src.health` names the failing check and its fix |
| Old run shows no boxes on Results | runs before 2026-09-25 have no `*_bbox_norm` | press Re-check |
| Old run still says PASS after a policy change | saved reports keep their verdict | Re-check (or `rematch`); `run_batch --resume` reuses saved verdicts |
| `run_benchmark --cached testN` errors on a missing JSON | that run lacks a screen | name the screens it has (see §5 step 6) |
| Very slow | OCR on CPU | use `rematch` / `--cached` / `--real-only` while tuning; ask before long runs |

## 13. Where things are

```
config/            config.yaml, detector.yaml, classes.json, ticket_export.yaml, class_refiner.yaml, screen_rules/ (empty)
src/pipeline.py    screenshot -> fused doc + layout graph; compare_documents (shared by scripts and app)
src/detector/      engine.py (load_detector, gt_stub, YOLO subprocess), yolo_worker.py, jitter.py
src/ocr/           engine.py (PaddleOCR), visualize.py
src/fusion/        fuse.py (fuse_detections; legacy fuse), visualize.py
src/graph/         layout.py (layout tree, current), build.py (older pairwise graph, src/main.py only), visualize.py
src/comparison/    matcher.py, differ.py (every check, in order), screen_checks, layout_checks, color_checks,
                   contrast_checks, pixel_geometry, image_checks, script_checks, text_cleanup,
                   regions.py (match levels), accepted.py (accepted differences)
src/reporting/     report.py (verdict, spec ids, coverage), grouping.py (issues), export.py (tickets),
                   history.py (new/fixed/still open), html_report.py, visualize.py
src/vlm/           engine.py, prompts.py, visualize.py (Ollama, opt-in)
src/schema/        ui_element.py (UIElement / UIDocument)
src/baselines.py   stored client designs;  src/health.py  health checks;  src/main.py  old full CLI
src/app/           server.py (routes), jobs.py (queue, runner, PDF), library.py (baselines, batch),
                   runs.py, actions.py (Results/Rules API), static/ (vanilla JS, no CDN)
scripts/           run_* (one stage), rematch, run_comparison, add_baseline, run_batch, accept_finding,
                   export_tickets, make_benchmark, run_benchmark, measure_jitter, refiner scripts,
                   evaluate, check_setup (doctor), smoke_test, make_release (handover zip),
                   _test_utils.py (UTF-8), make_shortcut.ps1
tests/             pytest, one file per module
models/ui16_v1/    model_card.json, classes_16.txt, gt_detections.json (best.pt not in git, in the zip)
models/paddlex/    PaddleOCR PP-OCRv6 det + rec (not in git, in the zip); models/SHA256SUMS.txt checksums
baselines/         <screen>/<device>/<language>/ meta.json (image + client_fused.json local only), _archive/
docs/              HANDOVER.md (this), HOW_TO_SETUP.md, USER_GUIDE.md, CONTINUING_THE_PROJECT.md, CHANGELOG.md,
                   memory.md (history + benchmark results), test_cases_pass_fail.md (spec), rules.md,
                   architecture.md, design.md, phases.md, environment.md, migration_ubuntu_gpu.md,
                   gap_analysis.pdf, graph_paper.pdf, phase*_prompts.md (build prompts), demo/, archive/
input/, output/    gitignored, in the zip (screenshots, runs, benchmark results); output/INDEX.md: which runs matter
setup.bat, setup.sh   one-time setup (.venv + .venv-detector);  requirements.txt, requirements-detector.txt
UI Compare.bat, start.sh   app launchers;  Dockerfile, docker-compose.yml   GPU sandbox
```

## 14. Glossary

- **PASS / REVIEW / FAIL**: per finding: within tolerance / a human should look / clearly outside
  tolerance. **Screen verdict**: any Critical or Major FAIL → FAIL; else any REVIEW or Minor FAIL →
  REVIEW; else PASS.
- **Severity**: Critical (breaks brand or usability), Major (visible to a normal user), Minor (only a
  designer would notice). Only FAILs carry a severity in the verdict rule.
- **Spec ids A-G**: A screen-level, B layout and structure, C position and size, D colour, E text, F
  images/icons/logo, G interaction state. §H ignore list, §I uncertainty → REVIEW.
- **Match level**: how strictly a screen or region is compared: STRICT (all), LAYOUT (no D, E, F),
  IGNORE_COLORS (no D), NONE (ignored). **FLOATING** region: elements may move up to
  `max_offset_norm` before C1 reports.
- **Baseline**: a client design stored once (image + fused JSON + meta) so later runs only process
  production.
- **Fused JSON**: one screen's UIDocument after detector + OCR + fusion (`*_fused.json`). Re-check,
  rematch and baselines start from it, so no detector or OCR is needed.
- **Accepted difference**: a finding a human accepted once; it comes back as PASS (accepted) until
  the element, its text or its colour changes. Entries that match nothing are listed as stale.
- **Issue**: findings of one check grouped (repeats of one difference); a ticket is one issue.
- **Dynamic content**: poster art, rail titles, badges on cards, status bar: never compared.
- **Group shift**: a panel that moved as one piece, reported once.

## 15. Repository ownership and data

- **Remote**: `https://github.com/amurock3-web/ui_comparision.git`. Whether it is public, and whose
  account `amurock3-web` is, has **not been verified**.
  **TODO (manager, Dhanya): move the code to a company-owned private repository and remove or
  archive this one.**
- **Handover medium**: the zip (full git history included), not GitHub.
- **Branches**: `origin/main` stops at Phase 17.3 (`35580e6`, 2026-10-07). Everything after is only
  local, in this order: `phase-18` (Phase 18, side-by-side scale), `handover-docs` (this document),
  `phase-20` (evaluation metrics), `handover-package` (setup, doctor, smoke test, bundled models).
  Nothing has been pushed. Leftover local branches (`worktree-agent-*`, `claude/remote-control-*`,
  `explain_project_structure`, `detector-integration`) are old agent and feature branches; they were not deleted.
- **Client-derived files that need a data-sharing decision** (TODO, manager):
  - `models/ui16_v1/gt_detections.json`: hand labels of the 103 SunNXT screens. **Already on origin.**
  - `docs/demo/ui_comparison_pipeline.mp4`: pipeline walkthrough video, **already on origin**
    (`35580e6`). Not played for this check; it is a pipeline demo, so it likely shows SunNXT
    screenshots (not verified). `Claude outputs/ui_comparison_pipeline.mp4` is a byte-identical
    duplicate of it, in local commit `d33db20` (not pushed); it is kept in the zip at the author's
    request.
  - `baselines/*/meta.json` (in git): settings only (screen id, size, config hash, model card) plus
    the upload's file name (no longer the full local path); no OCR text. The baseline images and `client_fused.json` (OCR
    text of client designs, incl. the Cricket WIP design) are local only and gitignored.
  - `input/` (SunNXT and JioHotstar screenshots) and `output/` (all runs, incl. the Cricket trial
    uploads in `output/app/`): local only, never in git.
  - `docs/gap_analysis.pdf`: internal assessment, no images; names SunNXT and quotes a few OCR
    misreads of client labels. Fine internally; decide before any public sharing.
  - `docs/graph_paper.pdf`: a third-party research paper (Moradi et al., Tricentis AI Research Lab).
    No client data. Its redistribution licence is **not verified**; a citation/link would be safer
    than the PDF in a public repo.
- **Personal paths in git**: fixed in the handover packaging: `config/detector.yaml` `python_path`
  is now blank, `config/class_refiner.yaml` uses the relative `../UI_Detection_model_training`,
  `scripts/calibrate_text_tolerance.py` takes `--metadata <folder>`, `baselines/*/meta.json` stores
  the file name only, the `scripts/run_detector.py` docstring uses a placeholder, and the docs use
  project-relative paths or placeholders. Earlier commits keep the old paths. Not secrets. No passwords, API keys or tokens were found (searched 2026-11-18).
