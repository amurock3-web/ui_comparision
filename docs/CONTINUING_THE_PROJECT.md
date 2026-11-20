# Continuing the project

For the developer who picks this up next. It says where the code is, what state it is in, and how
to make the usual changes. It links [`HANDOVER.md`](HANDOVER.md) instead of repeating it. Setup is
in [`HOW_TO_SETUP.md`](HOW_TO_SETUP.md), daily use in [`USER_GUIDE.md`](USER_GUIDE.md).

In the commands below, `python` means the main venv's Python: `.venv\Scripts\python.exe` on
Windows, `.venv/bin/python` on Ubuntu. Run everything from the project root.

## 1. What the tool does

You give it two images of one OTT app screen: the client design (the reference, usually a
Figma-style mockup) and a production screenshot (the thing under test). A YOLO detector finds the
UI elements and their class, PaddleOCR reads the text, fusion joins the two, and a layout graph
groups the elements into sections and rows. The matcher pairs client and production elements, the
differ runs every check, and the report gives each finding PASS / REVIEW / FAIL and a screen
verdict. The spec of every check is [`test_cases_pass_fail.md`](test_cases_pass_fail.md) (ids A-G).

Hard rules (break none of them):

- **Local only.** No cloud OCR or VLM, no uploading screenshots, no third-party image APIs
  ([`rules.md`](rules.md) section 2). The `input/` and `output/` folders hold client screenshots: internal only.
- **Compare geometry and chrome**: position, size, shape, colour, orientation, static labels.
  Poster artwork, movie titles in rails and the status bar are dynamic content and are never compared.
- **OCR gives the text, the detector gives the class.** Do not let one stand in for the other.
- **Thresholds live in config** (`config/config.yaml`, `config/detector.yaml`), never as constants in code.
- **Never overwrite or renumber a `testN_*` output.** Every script picks the next free N.

## 2. Stage map and code map

| Stage | What it does | Files |
|---|---|---|
| Detector | YOLO `ui16_v1` boxes + class, run as a subprocess in `.venv-detector` (ultralytics never shares a venv with paddle) | `src/detector/engine.py` (`load_detector`, `detector_python`, `gt_stub`), `src/detector/yolo_worker.py` (runs inside the detector venv, imports nothing from `src/`), `src/detector/jitter.py` (box wobble, Phase 17), `config/detector.yaml`, `models/ui16_v1/` |
| OCR | PaddleOCR text + boxes, ~45 s per screen on CPU; uses the bundled models in `models/paddlex/` | `src/ocr/engine.py` |
| Fusion | OCR text hung on detector boxes, poster text dropped, status bar ignored, uncertain elements tagged | `src/fusion/fuse.py` (`FusionEngine.fuse_detections`), `src/schema/ui_element.py` (UIElement / UIDocument) |
| Layout graph | sections, rows, overlays, clipped flags, hidden-card placeholders | `src/graph/layout.py` (`LayoutGraphBuilder`, current) |
| Matching | pairs client and production elements by class, text, position, size, context; group shifts | `src/comparison/matcher.py` |
| Differ | every check, in a fixed order; maths in pure modules beside it | `src/comparison/differ.py`, `screen_checks.py` (A), `layout_checks.py` (B3-B5, B8, C1 element rule), `color_checks.py` (D), `contrast_checks.py` (D7), `pixel_geometry.py` (C2 pixel verify), `image_checks.py` (F), `script_checks.py` (E4), `text_cleanup.py` |
| Rules and acceptances | match levels, regions, dynamic-text patterns; accepted differences | `src/comparison/regions.py`, `config/screen_rules/`, `src/comparison/accepted.py`, `baselines/accepted_differences.yaml` |
| Report | verdict, spec ids, coverage; issues; history; HTML/PDF; side-by-side PNG; tickets | `src/reporting/report.py`, `grouping.py`, `history.py`, `html_report.py`, `visualize.py`, `export.py` |
| Shared path | screenshot -> fused doc + graph (`build_document`); two docs -> report (`compare_documents`) | `src/pipeline.py` (used by `run_comparison`, `run_benchmark`, `rematch` and the app) |
| Baselines | client designs stored once, with a config hash | `src/baselines.py`, `baselines/` |
| Web app | Compare, Results, History, Rules, Baselines, Batch, Help; one job queue | `src/app/server.py` (routes), `jobs.py` (queue, runner, PDF), `library.py` (baselines, batch), `runs.py`, `actions.py` (Results/Rules API), `static/` |
| Health | cheap start-up checks behind the app's health chips (`python -m src.health`) | `src/health.py` |
| Scripts | one stage at a time, rematch, benchmark, evaluate, baselines, batch, tickets, doctor, smoke test | `scripts/` (all import `scripts/_test_utils.py` for UTF-8 and test numbering) |

Legacy paths (do not build on them):

- `src/main.py`: the old full CLI. It still builds the older pairwise graph and is the **only
  caller of the VLM path** (`--vlm`, `src/vlm/`, Ollama `qwen2.5vl:7b`). It calls
  `fuse_detections` like the pipeline does.
- `src/graph/build.py` (`UIGraphBuilder`): the older pairwise graph. Still imported by
  `src/main.py`, and `src/graph/layout.py` imports `DEFAULT_CONFIG_PATH`, `UIGraphBuilder` and two
  helpers from it, so it cannot simply be deleted. 1 known failing test (`tests/test_graph.py`).
- `FusionEngine.fuse` (OCR + VLM fusion without the detector): only `tests/test_fusion.py` calls it;
  14 known failing tests, because the tests do not pass its `grounded_cards` argument.

## 3. Current status and latest numbers

Built: 25 of the spec's 39 check rows, the web app, baselines, batch, tickets, the known-defect and
real-pair benchmark, and the evaluation scripts. Full list and what is partial:
[HANDOVER section 2](HANDOVER.md#2-current-state-checked-against-src-on-2026-11-18).

Latest numbers (Phase 20, [`memory.md`](memory.md) "Phase 20 - evaluation metrics - 2026-11-19";
pooled evaluation of test22 + test23 + test24, 30 cases, in `output/evaluation/test3_evaluation/`):

| Metric (Wilson 95%) | Pooled |
|---|---|
| lenient recall | 1.000 [0.871, 1.000] 26/26 |
| lenient precision (case TP vs finding FP) | 0.867 [0.703, 0.947] 26/30 |
| lenient F1 | 0.929 |
| exact recall | 0.808 [0.621, 0.915] 21/26 |
| exact precision | 0.840 [0.653, 0.936] 21/25 |
| exact F1 | 0.824 |
| screen accuracy | 1.000 [0.886, 1.000] (30/30) |
| screen specificity | 1.000 [0.510, 1.000] 4/4 |

Real pair (test24, trending_search): verdict exact 0/1, REVIEW expected -> FAIL given, 2 false
alarms (D1 Home, C2 Search FAIL), 0 misses, 3 unlisted, tester load 15 vs budget 5.

The source runs (Phase 18.4 baseline, 2026-11-02): test22 flagged at edit 19/19, exact spec id
17/19 (89%), 3 false alarms, identity 3/3; test23 7/7, 4/7 (57%), 1 false alarm, identity 1/1.
Read these as optimistic: the thresholds were tuned on these same screens, there are only 4
identity cases, and there is only 1 real pair. Which runs matter: [`output/INDEX.md`](../output/INDEX.md).

Unit tests: 343 passed, 15 failed, 1 skipped at the 2026-11-20 run. The 15 failures are the legacy
tests above, not regressions.

## 4. Known limitations

Detail and causes: [HANDOVER section 9](HANDOVER.md#9-known-issues-and-limits).

- No "inconclusive" verdict: a wrong or very different pair gives FAIL with dozens of findings.
- Live video areas and dynamic text values (teams, dates) are compared (Cricket trial noise).
- Known false alarms: D1 on tabs with logo artwork, C2 Major on small icons, C1 on shortened labels.
- A few pixel floors (`comparison.size_min_px` and others) are in client pixels, so the verdict can
  depend on the design's resolution.
- Printed PDF reports are not at one scale (diagnosed, not fixed).
- The detector was trained on 103 SunNXT screenshots only; buttons, icons, logos are weak.
- OCR is ~45 s per screen on CPU; the Ubuntu GPU move is a plan (section 6).
- Policy v1 (Phase 18) is pending manager review.

## 5. Open TODOs and ideas

The prioritised list is [HANDOVER section 10](HANDOVER.md#10-roadmap-prioritised). The top five:

1. Inconclusive / "cannot compare" verdict when under 50% of elements match (spec section I).
2. Ignore live video / player regions (about 23 of 27 EXTRA findings in the Cricket trial).
3. Compare dynamic text values by position only (key/value rows).
4. Fix the PDF scale (`src/reporting/html_report.py` print CSS, `visualize.py`, `_crop`).
5. Input checks: low-resolution or cropped design, open keyboard, system navigation band.

Also open:

- **Phase 20.3-20.5 (parked):** new defect types in `scripts/make_benchmark.py`; a pixel-diff
  baseline to compare the tool against; held-out real pairs that were never used for tuning
  (memory.md: "all of this is optimistic until 20.5").
- **IoU localisation:** the benchmark counts a hit when a finding lands on the edited element; a
  box-overlap (IoU) score would measure how well the finding is localised.
- **Per-stage metrics:** detector, OCR, fusion and matching are not scored on their own today;
  only the end result is.
- **Delete the legacy path** (gap analysis section 7.1, [`gap_analysis.pdf`](gap_analysis.pdf)): remove
  `FusionEngine.fuse` and its 14 tests, move what `layout.py` imports out of `build.py`, then
  retire `build.py`, its test and `src/main.py` (decide first whether the `--vlm` path is wanted).
- **Owner TODOs** (repo ownership, client-derived files, personal paths in git):
  [HANDOVER section 15](HANDOVER.md#15-repository-ownership-and-data).

## 6. Ubuntu GPU migration status

The plan is [`migration_ubuntu_gpu.md`](migration_ubuntu_gpu.md): move to the Ubuntu 22.04 box with
an NVIDIA GTX 1070 (Pascal, sm_61, 8 GB) inside the sandboxed Docker setup. **Not done.**

| Done | Not done |
|---|---|
| `docker-compose.yml` sandbox: non-root user, read-only root filesystem, all capabilities dropped, no-new-privileges, `input/` mounted read-only | No detector venv in the image; the Dockerfile builds only the paddle venv |
| `Dockerfile` on `nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04`, `paddlepaddle-gpu` from the cu126 index | torch for the GTX 1070 must come from the cu126 index and list `sm_61` (see the comment in `requirements-detector.txt`) |
| Ollama in its own container | The app binds 127.0.0.1 inside the container and no port is published; `src.app` has no `--host` flag (only `--port`, `--no-browser`) |
| `.gitattributes` keeps `*.sh` LF and `*.bat` CRLF | No Edge in Linux, so no PDF export there (`src/health.py` looks for `msedge` only) |
| `setup.sh` builds both venvs on a plain Ubuntu host (no Docker) | `make_benchmark` writes into `input/benchmark/`, which is read-only in the container |
| | 8 GB VRAM is shared by PaddleOCR, YOLO and Ollama; Ollama is not under a compose profile and keeps `OLLAMA_KEEP_ALIVE: "10m"` |

Stale bits in the migration doc: its Step 4 runs `python -m src.app --host 0.0.0.0`, but that flag
does not exist yet; Step 5 compares against **test3** as the baseline score, but the current
baselines are test22-test24 (section 3); it says the first GPU run downloads the OCR models, but
they are now bundled in `models/paddlex/`.

## 7. How-tos

### a. Add a new check

Files: a new pure module in `src/comparison/`, `src/comparison/differ.py`, `config/config.yaml`,
`src/reporting/report.py`, `docs/test_cases_pass_fail.md`, a new `tests/test_<module>.py`.

1. **Write the maths as a pure module** beside `differ.py` (for example
   `src/comparison/spacing_checks.py`). Follow `color_checks.py` / `layout_checks.py`: functions
   take numbers, crops or graphs and return measurements or plain dicts. They read no config and
   return no verdict; every threshold is an argument.
2. **Add its config block** under `comparison:` in `config/config.yaml`, with an `enabled` switch
   and the PASS / FAIL bands.
3. **Wire it in `differ.py`.** In `DifferenceEngine.__init__` read the block
   (`self.<name>_cfg = cfg.get("<name>", {})`). Write a method that applies the bands and returns
   a list of `Difference(type, production_id, client_id, details, verdict, severity)`. Call it from
   `compare()` at the right place. The order there is:
   - screen level (`_screen_level`, `_background_color`): whole images, before matching; an A1/A2
     Critical stops element checks;
   - unmatched elements (B1/B2), `_group_shifts`, `_layout_structure` (B3-B5, B8 on both graphs);
   - per matched pair, skipping dynamic content: `_sub_differences` (C4, E1/E3/E4, C1, C2), then,
     when images are loaded, `_element_color`, `_pixel_verify_size`, `_text_contrast`,
     `_image_identity`;
   - whole screen after the loop: `_broken_images`;
   - then the post-passes, in this order: `_cap_clipped`, `_drop_alignment_collateral`,
     `_apply_match_levels`, `_apply_acceptances`, `_cap_low_confidence`. Add new checks before them,
     so match levels, acceptances and caps apply to the new findings too.
4. **Give it a spec id.** In `src/reporting/report.py` add the new type to `SPEC_BY_TYPE` and the
   id to `IMPLEMENTED`. The id's first letter is the family that match levels skip (LAYOUT skips
   D, E, F). Add or update the row in `docs/test_cases_pass_fail.md` (its family table and the
   "Coverage vs current pipeline" table), and the implemented list in `differ.py`'s docstring.
5. **Unit test** the pure module (pattern: `tests/test_layout_checks.py`) and one `compare()` case (pattern: `tests/test_position_element_rule.py`).
6. **Try it on saved data** (seconds, no detector or OCR):

```
python -m pytest tests -q
python -m scripts.rematch input/benchmark/real/trending_search/client_fused.json input/benchmark/real/trending_search/client_fused.json
python -m scripts.rematch input/benchmark/real/trending_search/production_fused.json input/benchmark/real/trending_search/client_fused.json
python -m scripts.run_benchmark --real-only --compare-to test24_benchmark
python -m scripts.run_benchmark --cached test16_benchmark ss012 ss031 jiohotstar_test_ss
python -m scripts.run_benchmark --cached test17_benchmark sunnxt_live_movie_detail
```

   The self-compare must stay PASS with 0 findings. Pixel checks need the images: rematch finds them
   from the fused JSON, or pass `--production-image` / `--client-image`. If the check needs new
   detector or OCR output, the full benchmark (~20 min) is the real test; ask before running it.
7. Record the before/after in `docs/memory.md`.

### b. Screen rules and match levels

Files: `config/screen_rules/<client screen id>.yaml`, `src/comparison/regions.py` (format in its
docstring), `comparison.match_levels` in `config/config.yaml` (default level, `skip` map, default
regions).

- Levels: STRICT (all checks), LAYOUT (no D, E, F), IGNORE_COLORS (no D), NONE (ignore region).
  A FLOATING region lets elements move up to `max_offset_norm` before C1 reports.
- Most specific wins: region covering the element > the screen's rules file > the config default.
- A skipped finding becomes PASS with `details["ignored"]`; it is kept as evidence, never deleted.
- The Rules page in the app draws regions and saves the file (old one kept as `.bak`).
- Try a level or a rules file on a saved pair without editing anything:

```
python -m scripts.rematch <production_fused.json> <client_fused.json> --match-level LAYOUT
python -m scripts.rematch <production_fused.json> <client_fused.json> --rules my_rules.yaml
```

  `--match-level` takes STRICT, LAYOUT or IGNORE_COLORS. Unit tests: `tests/test_match_levels.py`.

### c. Add a baseline

```
python -m scripts.add_baseline <client_image> --screen <id>
python -m scripts.add_baseline --list
python -m scripts.run_comparison <production> --baseline <id>
```

`add_baseline` runs detector + OCR once (~1 min) and also takes `--device phone|tablet|tv` and
`--language`. Files go to `baselines/<screen>/<device>/<language>/`. The baseline's `meta.json`
stores a config hash of `config/detector.yaml` plus the `ocr`, `fusion` and `vlm` sections of
`config/config.yaml`. Change any of those and every baseline goes stale: `load_baseline` refuses it,
and you re-add it with the same command. Comparison thresholds do not make baselines stale.

### d. Retrain or replace the detector

The model is trained in the separate `UI_Detection_model_training` repo (expected next to this
project, `../UI_Detection_model_training`; its `docs/INTERFACE.md` describes the bundle). This
project only consumes a bundle:

```
models/<name>/best.pt  model_card.json  classes_16.txt  gt_detections.json
```

1. Train in the training repo; copy the bundle into `models/<name>/`. For speed, train on a GPU:
   on the GTX 1070 install torch from the cu126 index (comment in `requirements-detector.txt`).
2. Point `bundle:` in `config/detector.yaml` at it. Keep `confidence_high` / `confidence_medium` or
   retune them there.
3. The class order in `classes_16.txt`, `model_card.json` and `config/classes.json` must agree;
   `src/detector/engine.py` refuses a mismatch. The file name `classes_16.txt` is hard-coded in
   `engine.py` and `yolo_worker.py`, so a bundle with another class count needs a code change
   there, plus `config/classes.json` and every config list of class names.
4. Update `models/SHA256SUMS.txt` (the doctor checks it) and keep `ultralytics` / `torch` pins in
   `requirements-detector.txt` matching the training run.
5. Changing `config/detector.yaml` makes every baseline stale: re-add them (7c).
6. Score it: the full benchmark (`--cached` replays old detections, so it does not test a new
   model), then evaluate, and compare with test22-24:

```
python -m scripts.make_benchmark
python -m scripts.run_benchmark
python -m scripts.evaluate output/benchmark/<testN_benchmark> --pool
```

7. Record the model card numbers and the benchmark in `docs/memory.md`.

### e. Accept a finding, export tickets

```
python -m scripts.accept_finding <report.json> --finding N --note "why it is expected"
python -m scripts.export_tickets <report.json>
```

`accept_finding` also takes `--issue issue_003` and `--by <name>`; it writes
`baselines/accepted_differences.yaml`. Ticket columns: `config/ticket_export.yaml`. The same
actions exist in the app's Results page: [`USER_GUIDE.md`](USER_GUIDE.md).

## 8. Testing conventions

- Every script writes a new numbered `testN_*` file or folder under `output/<stage>/`. Never
  overwrite, delete or renumber one. New scripts get N from
  `scripts/_test_utils.next_test_number(output_dir)` (highest existing N plus 1) and import
  `scripts/_test_utils.py` so the Windows console prints Tamil / CJK text.
- `output/` is gitignored and internal only. [`output/INDEX.md`](../output/INDEX.md) lists the runs
  that matter; update it when a new baseline run replaces test22-24.
- Record every new benchmark result and every big change in `docs/memory.md` as a dated section:
  what changed, the exact command, the numbers, and what was not run.

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

## 9. How to run things

| What | Command (Windows; Ubuntu: `.venv/bin/python`) | Time | Expected |
|---|---|---|---|
| Doctor | `.venv\Scripts\python.exe -m scripts.check_setup` | seconds | one PASS / FIX / INFO line per check; exit 0 = ready |
| App health | `python -m src.health` | seconds | required checks OK; Edge optional |
| Smoke test | `.venv\Scripts\python.exe -m scripts.smoke_test` | seconds | `SMOKE TEST: PASS` (real pair FAIL with 16 findings is known; self-compare PASS) |
| Unit tests | `.venv\Scripts\python.exe -m pytest tests -q` | not timed | 343 passed, 15 failed, 1 skipped at the last full run; the 15 are listed under [Known failing tests](#known-failing-tests) |
| Rematch | `python -m scripts.rematch <production_fused.json> <client_fused.json>` | seconds | report in `output/rematch/testN_*` |
| Real pairs only | `python -m scripts.run_benchmark --real-only` | ~10 s | as test24 |
| Re-score a saved run | `python -m scripts.run_benchmark --cached <testN_benchmark> [screens...]` | seconds | as test22 / test23 |
| Full benchmark | `python -m scripts.make_benchmark` then `python -m scripts.run_benchmark` | ~20 min | ask before running |
| Evaluate | `python -m scripts.evaluate output/benchmark/<testN_benchmark> [more] [--pool]` | seconds | `evaluation.json`, `evaluation.md`, `evaluation.html` (charts) next to each run; `--pool` writes `output/evaluation/testN_evaluation/` |

The real-YOLO test in `tests/test_detector.py` is skipped unless the detector Python and `best.pt`
are found. More on reading the scores: [HANDOVER section 8](HANDOVER.md#8-tests-and-benchmarks).

## 10. Working with Claude Code

- `CLAUDE.md` at the project root is loaded automatically. It holds the hard rules, the commands,
  the environment traps and the working agreement (discuss before changing code, ask before long
  runs, give the exact commands). Keep it current when commands or rules change.
- `graphify-out/` is a knowledge graph of the code. Ask it first:
  `graphify query "<question>"`, `graphify path "<A>" "<B>"`, `graphify explain "<concept>"`.
  After code changes, run `graphify update .` (AST only, no API cost).
- Long history and the reasoning behind decisions: `docs/memory.md` and
  [HANDOVER section 11](HANDOVER.md#11-decisions-and-why).
