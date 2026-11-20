# UI Comparison

Compares a production screenshot of an OTT app screen with the client design screenshot and reports
layout differences with PASS / REVIEW / FAIL verdicts (docs/test_cases_pass_fail.md is the spec).
Pipeline: YOLO detector + PaddleOCR -> fusion -> layout graph -> matcher/differ -> report.
README.md has the stage map; docs/architecture.md and docs/design.md the details.

## Hard rules
- Everything stays local: no cloud OCR/VLM, no uploading screenshots, no third-party image APIs (docs/rules.md §2).
- Compare geometry and chrome (position, size, shape, colour, orientation, static labels).
  Poster/tile artwork, movie titles in rails and the status bar are dynamic content: never compared.
- OCR gives exact text, the detector/VLM give class. Do not let one stand in for the other.
- Thresholds live in config/config.yaml (and config/detector.yaml), not as constants in code.
- Keep this project separate from the old SunNXT annotation/GT audit work.

## Running
Commands assume the project's `.venv` Python (`.venv\Scripts\python.exe`, Ubuntu `.venv/bin/python`).
- First time (needs internet, ~10-20 min, safe to re-run): `setup.bat` / `bash setup.sh` (creates .venv + .venv-detector, runs the doctor)
- Doctor (PASS / FIX / INFO per check, exit 0 = ready): `python -m scripts.check_setup`
- Smoke test (seconds, no OCR/detector; real pair FAIL 16 findings, self-compare PASS 0): `python -m scripts.smoke_test`
- One screen, stage by stage: `python -m scripts.run_detector|run_ocr|run_fusion <image>`
- Layout graph from a saved fusion JSON (no 90 s rerun): `python -m scripts.build_graph_from_fusion <json> --layout`
- Compare a pair (writes the HTML report): `python -m scripts.run_comparison <production> <client>`
- Redo matching/differ/report from saved fused JSONs (seconds, no detector/OCR): `python -m scripts.rematch <production_fused.json> <client_fused.json>` (same JSON twice = self-compare)
- Known-defect benchmark: `python -m scripts.make_benchmark` then `python -m scripts.run_benchmark` (~20 min)
- Real-pair cases only (input/benchmark/real/, cached fused JSONs, ~10 s, no OCR): `python -m scripts.run_benchmark --real-only`
- Precision / recall / F1 + screen-level matrix from saved results (seconds): `python -m scripts.evaluate output/benchmark/<testN_benchmark> [more] [--pool]`
- Drag-and-drop UI: `UI Compare.bat` or `python -m src.app` (http://127.0.0.1:8765, next free port if taken; runs kept in output/app/)
- Rematch overrides: `--match-level STRICT|LAYOUT|IGNORE_COLORS`, `--rules <yaml>`
- Baselines: `python -m scripts.add_baseline <client_image> --screen <id>` (~1 min), then
  `python -m scripts.run_comparison <production> --baseline <id>`; many at once: `python -m scripts.run_batch <folder>`
- Accept a finding: `python -m scripts.accept_finding <report.json> --finding N --note "..."`
- Ticket CSV: `python -m scripts.export_tickets <report.json>`
- Full pipeline CLI: `python -m src.main --production-image ... --production-screen-id ... --client-image ... --client-screen-id ...`
- Unit tests: `python -m pytest tests -q` (15 known legacy failures: tests/test_fusion.py, tests/test_graph.py)
- Handover zip: `python -m scripts.make_release [--out <folder>]` (default: next to the project)
- Script output is numbered testN_* under output/<stage>/; never overwrite earlier runs.

## Environment traps
- The YOLO detector runs in a separate Python (ultralytics must never share a venv with paddlepaddle).
  Lookup (src/detector/engine.detector_python): env var UI_DETECTOR_PYTHON -> <root>/.venv-detector
  -> python_path in config/detector.yaml (blank by default). Never pip install torch/ultralytics into .venv.
- OCR models are bundled in models/paddlex; src/ocr/engine.py sets PADDLE_PDX_CACHE_HOME to it. Never let OCR download models.
- Changing config/detector.yaml or the ocr / fusion / vlm sections of config/config.yaml changes the baseline
  config hash: baselines go stale -> re-add them with scripts.add_baseline.
- OCR takes ~45 s per screen on CPU; the benchmark ~1 min per case. Ask before starting long runs.
- The Windows console is cp1252; scripts import scripts/_test_utils.py to force UTF-8 (OCR returns Tamil/CJK).
- input/ and output/ are gitignored; screenshots never go in git.

## Where things are
- src/pipeline.py: screenshot -> fused doc + layout graph (used by run_comparison, run_benchmark and the app)
- src/graph/layout.py: the layout-tree graph (sections, rows, overlays, clipped, hidden-card placeholders)
- src/graph/build.py: the older pairwise graph, still used by src/main.py
- src/comparison/differ.py: every check, wired in order; the check maths lives in pure modules beside it
  (screen_checks, layout_checks, color_checks, contrast_checks, pixel_geometry, image_checks, script_checks)
- src/comparison/regions.py: match levels + regions (config/screen_rules/); accepted.py: accepted differences
- src/reporting/: report.py (verdict, spec ids, coverage), grouping.py (issues), export.py (tickets),
  history.py (new/fixed/still open), html_report.py, visualize.py
- src/baselines.py: stored client designs; src/app/: the web app package (server, jobs, actions, library, static/)
- docs/memory.md: project history and benchmark results
- Docs map: docs/HANDOVER.md (manager summary), docs/HOW_TO_SETUP.md (install), docs/USER_GUIDE.md (testers),
  docs/CONTINUING_THE_PROJECT.md (developers), docs/CHANGELOG.md, output/INDEX.md (which runs matter)
- scripts/check_setup.py: the doctor; scripts/smoke_test.py: the seconds-long end-to-end check
- models/: ui16_v1/ (best.pt + model_card.json, classes_16.txt, gt_detections.json), paddlex/official_models/
  PP-OCRv6_medium_{det,rec}; checksums in models/SHA256SUMS.txt (checked by the doctor)
- docs/migration_ubuntu_gpu.md: plan for moving to the Ubuntu GTX 1070 box in the sandboxed Docker setup (not done yet)

## How to work with me
- Discuss the analysis and the plan before changing code; keep edits narrowly scoped to what was asked.
- Do not run tests or the pipeline unless I ask; say what you did not run.
- Always give the exact command(s) to run alongside any code change.
- Record new benchmark results and big changes in docs/memory.md.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
