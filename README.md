# UI Comparison

Original author: Pralhadraj Joshi

UI Comparison compares a production screenshot of an OTT app screen with the client design for that
screen and reports the layout differences: missing or extra elements, position, size, order,
alignment, colour, text contrast, label text and language, and broken card images. Each finding gets
a PASS / REVIEW / FAIL verdict and the test-case id from
[`docs/test_cases_pass_fail.md`](docs/test_cases_pass_fail.md). It compares geometry and chrome, not
content: poster and tile artwork, movie titles in rails and the status bar are ignored. Everything
runs locally on your computer (a YOLO UI detector, PaddleOCR and graph matching); no screenshot is
ever uploaded.

![Sample report](docs/images/sample_report.png)

## Quick start

1. **Unzip** the handover zip. It unzips to one folder, `ui_comparison/`.
2. **Set up** (once). Needs internet and takes about 10-20 minutes the first time; after that
   everything runs offline.

   ```bat
   setup.bat
   ```

   ```bash
   bash setup.sh
   ```

3. **Launch.** Double-click `UI Compare.bat` (Ubuntu: `bash start.sh`). The app opens in the browser
   at http://127.0.0.1:8765 (or the next free port). Drop the production screenshot and the client
   design into the two boxes and press **Compare**.

To check the install, run the doctor (one PASS / FIX / INFO line per check) and the smoke test
(seconds, no OCR; it must end with `SMOKE TEST: PASS`):

```bat
.venv\Scripts\python.exe -m scripts.check_setup
.venv\Scripts\python.exe -m scripts.smoke_test
```

```bash
.venv/bin/python -m scripts.check_setup
.venv/bin/python -m scripts.smoke_test
```

Setup problems: [`docs/HOW_TO_SETUP.md`](docs/HOW_TO_SETUP.md).

## Docs

| Doc | For whom | What's in it |
|---|---|---|
| [`docs/HANDOVER.md`](docs/HANDOVER.md) | Manager | **The handover summary: start here.** Current state, benchmark numbers, known issues, roadmap, decisions, repository ownership and data |
| [`docs/HOW_TO_SETUP.md`](docs/HOW_TO_SETUP.md) | IT / whoever installs | Install on Windows or Ubuntu, the doctor, the smoke test, fixing setup problems |
| [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) | Testers | Running a comparison in the app, reading a report, accept / ignore region / mark as bug, baselines, batch, rules |
| [`docs/CONTINUING_THE_PROJECT.md`](docs/CONTINUING_THE_PROJECT.md) | Developers | How the code is laid out, how to change a check, tests, benchmark and evaluation |
| [`docs/test_cases_pass_fail.md`](docs/test_cases_pass_fail.md) | Everyone | Every check and what PASS / REVIEW / FAIL mean |
| [`output/INDEX.md`](output/INDEX.md) | Everyone | Which past runs matter and what they show |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Everyone | What was built in each phase, newest first |
| [`docs/memory.md`](docs/memory.md) | Developers | Full project history and every benchmark result (dated sections are current) |
| [`docs/architecture.md`](docs/architecture.md), [`docs/design.md`](docs/design.md) | Developers | Technical design |
| [`docs/rules.md`](docs/rules.md) | Developers | Project constraints that do not change (everything stays local) |
| [`AUTHORS.md`](AUTHORS.md) | Everyone | Who built what |

Also in `docs/`: `phases.md` (phase plan), `environment.md` and `migration_ubuntu_gpu.md` (Docker /
GPU, migration not done yet), `demo/ui_comparison_pipeline.mp4` (pipeline walkthrough video),
`gap_analysis.pdf`, `archive/` (old snapshots).

## Internal only

The zip contains SunNXT and JioHotstar client screenshots and reports (in `input/`, `output/` and
`baselines/`). Do not share them outside the company and do not upload them anywhere
([`docs/rules.md`](docs/rules.md) section 2).

## More

### Pipeline

```
screenshot ─┬─ YOLO detector (ui16_v1) ─┐
            └─ PaddleOCR ───────────────┴─> Fusion ──(--vlm, only if uncertain)──> VLM
                                              │
                                        UI JSON → layout graph
                                              │
               Production graph ──── Matcher + Differ ──── Client graph
                                              │
                                   Report (JSON + HTML + PNG)
```

| Stage | Code |
|---|---|
| Detector | `src/detector/` (runs in its own Python, `.venv-detector`) |
| OCR | `src/ocr/` (bundled models in `models/paddlex/`) |
| Fusion | `src/fusion/` |
| VLM (optional) | `src/vlm/` |
| Graph | `src/graph/` (`layout.py` is the current layout tree) |
| Comparison | `src/comparison/` (`differ.py` wires every check) |
| Report | `src/reporting/` |
| Web app | `src/app/` |
| Schema | `src/schema/ui_element.py` |

Details: [`docs/architecture.md`](docs/architecture.md), [`docs/design.md`](docs/design.md),
[`docs/HANDOVER.md#3-architecture-in-one-page`](docs/HANDOVER.md#3-architecture-in-one-page).

### Command line

Run these with the `.venv` Python (`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` on
Ubuntu). Every script writes a new numbered `testN_*` folder under `output/<stage>/` and never
overwrites an earlier run.

```bash
python -m scripts.run_comparison <production.png> <client.png>             # one pair, HTML report
python -m scripts.rematch <production_fused.json> <client_fused.json>      # redo matching + report in seconds
python -m scripts.add_baseline input/client/home.png --screen home         # store a client design (~1 min)
python -m scripts.run_comparison input/production/home.png --baseline home # compare against it
python -m scripts.run_batch input/production/                              # many screenshots; resumable
python -m scripts.accept_finding <report.json> --finding 3 --note "deliberate copy change"
python -m scripts.export_tickets <report.json>                             # ticket CSV, one row per issue
python -m src.main --production-image ... --production-screen-id ... --client-image ... --client-screen-id ...
```

- One stage on its own: `python -m scripts.run_detector|run_ocr|run_fusion <image>`.
- `rematch` with the same JSON twice is a self-compare and must come out PASS.
  `--match-level STRICT|LAYOUT|IGNORE_COLORS` and `--rules <file.yaml>` override the screen rules.
- `--vlm` (on `src.main`) asks a local Ollama VLM (`ollama pull qwen2.5vl:7b`, not in the zip) about
  elements the detector and OCR left uncertain. Slow; without it those are reported as REVIEW.
- App options: `python -m src.app --port 8800 --no-browser`. Desktop shortcut (Windows, once):
  `powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1`.
- PDF export of reports uses Microsoft Edge; without Edge, the HTML report still works.

Full usage: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) and
[`docs/HANDOVER.md#6-how-to-use-it`](docs/HANDOVER.md#6-how-to-use-it). The app's JSON routes are in
`src/app/server.py`.

### Tests, benchmark, evaluation

```bash
python -m pytest tests -q                 # last full run: 343 passed, 15 failed, 1 skipped
python -m scripts.make_benchmark          # labelled defect copies of a few screens
python -m scripts.run_benchmark           # ~20 min (OCR on every case)
python -m scripts.run_benchmark --real-only   # ~10 s: the real pairs, from cached fused JSONs
python -m scripts.evaluate output/benchmark/<testN_benchmark> [more] [--pool]   # precision / recall / F1
```

The 15 failures are known legacy tests, not regressions: 14 in `tests/test_fusion.py` (old
`FusionEngine.fuse` path) and 1 in `tests/test_graph.py` (`src/graph/build.py`). Real benchmark
pairs live in `input/benchmark/real/<name>/` with a `manifest.json` of what must and must not be
flagged. Latest numbers: [`docs/HANDOVER.md#8-tests-and-benchmarks`](docs/HANDOVER.md#8-tests-and-benchmarks)
and [`output/INDEX.md`](output/INDEX.md).

### Configuration

Thresholds live in config files, not in code.

- `config/config.yaml`: tolerances, severities, every check's thresholds and on/off switch, match levels, VLM settings
- `config/detector.yaml`: detector engine, model bundle, confidence tiers (`engine: gt_stub` replays hand labels without the model)
- `config/classes.json`: the 16-class UI taxonomy
- `config/screen_rules/<client screen id>.yaml`: per-screen match level, regions (NONE / FLOATING / LAYOUT / IGNORE_COLORS / STRICT) and dynamic-text patterns; edit by hand or on the app's Rules page
- `config/ticket_export.yaml`: ticket CSV columns

The detector Python is found automatically (`UI_DETECTOR_PYTHON` if set, else `.venv-detector`, else
`python_path` in `config/detector.yaml`). ultralytics/torch and paddle must never share a venv.
Guide: [`docs/HANDOVER.md#7-configuration-guide`](docs/HANDOVER.md#7-configuration-guide).

### Docker (GPU, partial)

`cp .env.example .env` (fill in `CODE_DIR` / `DATA_DIR`), then `docker compose up -d --build` and
`docker compose exec app bash`. Not verified end to end; see [`docs/environment.md`](docs/environment.md)
and [`docs/migration_ubuntu_gpu.md`](docs/migration_ubuntu_gpu.md).
