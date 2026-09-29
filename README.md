# UI Comparison

Compares a **Production** and a **Client** screenshot of an OTT app screen and reports layout differences: missing or extra elements, position, size, order, alignment, colour, text contrast, label text and language, and broken card images. Each finding gets a PASS / REVIEW / FAIL verdict, repeats of one difference are grouped into issues, and every finding carries its test-case id from [`docs/test_cases_pass_fail.md`](docs/test_cases_pass_fail.md). Poster and tile artwork is treated as dynamic content and ignored.

Per screen you can relax the comparison (match levels STRICT / LAYOUT / IGNORE_COLORS, ignore and floating regions in `config/screen_rules/`), accept a known difference once so it stops coming back, store a client design once as a baseline, and run many screenshots in a batch.

Everything runs locally: a fine-tuned YOLO UI detector, PaddleOCR, an optional local VLM (Ollama) and deterministic graph-based matching.

## Pipeline

```
screenshot ─┬─ YOLO detector (ui16_v1) ─┐
            └─ PaddleOCR ───────────────┴─> Fusion ──(--vlm, only if uncertain)──> VLM
                                              │
                                        UI JSON → UI graph
                                              │
               Production graph ──── Matcher + Differ ──── Client graph
                                              │
                                   Report (JSON + visualization)
```

| Stage      | Code                     |
|------------|--------------------------|
| Detector   | `src/detector/`          |
| OCR        | `src/ocr/`               |
| Fusion     | `src/fusion/`            |
| VLM        | `src/vlm/`               |
| Graph      | `src/graph/`             |
| Comparison | `src/comparison/`        |
| Report     | `src/reporting/`         |
| Schema     | `src/schema/ui_element.py` |

For the details, see [`docs/architecture.md`](docs/architecture.md) and [`docs/design.md`](docs/design.md).

## Setup

### Local (Windows / Linux, Python 3.11)

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux: source .venv/bin/activate
pip install -r requirements.txt pytest
```

**Detector weights.** `models/ui16_v1/best.pt` is not in git. Copy it by hand from the `UI_Detection_model_training` repo. YOLO runs in that repo's own Python, because ultralytics/torch must not share an environment with paddle. Point to it like this:

```powershell
$env:UI_DETECTOR_PYTHON = "C:\path\to\UI_Detection_model_training\.venv\Scripts\python.exe"
```

If the variable isn't set, the `python_path` from `config/detector.yaml` is used instead. Setting `engine: gt_stub` in the same file replays the hand labels, so you can run the pipeline without the model.

**VLM (optional, only with `--vlm`).** Needs Ollama running locally with the model named in `config/config.yaml`.

### Docker (GPU)

```bash
cp .env.example .env            # fill in CODE_DIR / DATA_DIR
docker compose up -d --build
docker compose exec app bash
```

The code is bind-mounted and never copied into the image. See [`docs/environment.md`](docs/environment.md).
Moving to the Ubuntu GTX 1070 machine: [`docs/migration_ubuntu_gpu.md`](docs/migration_ubuntu_gpu.md) (plan, not yet done).

## Usage

### Web UI

**Double-click launcher.** On Windows, double-click `UI Compare.bat` in the project folder. It activates `.venv` if there is one, reads `UI_DETECTOR_PYTHON` from a local `.env` if there is one (a line such as `UI_DETECTOR_PYTHON=C:\path\to\UI_Detection_model_training\.venv\Scripts\python.exe`), and starts the app. If the app exits with an error, the window stays open so you can read it. To put a **UI Compare** shortcut on the desktop, run this once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
```

On Linux, `./start.sh` does the same.

**Command line.**

```bash
python -m src.app                          # http://127.0.0.1:8765, or the next free port up to 8775
python -m src.app --port 8800 --no-browser
```

Both open the page in the browser. The top menu has six pages: **Compare** (drag and drop), **History** (every run in `output/app/`, newest first, with a search box and a verdict filter; click a row to open it, or use its HTML / PDF links), **Baselines**, **Batch**, **Rules** (see below) and **Help** (what PASS / REVIEW / FAIL mean, the check families A–G, where runs are kept). Coloured chips at the top show the health checks from `GET /health` (also `python -m src.health`): detector Python, detector weights, PaddleOCR, the config files, a writable `output/`, Microsoft Edge, and Ollama if the VLM is turned on in the config. If a required check fails, the page shows how to fix it and the Compare button stays disabled. A missing Edge only turns its chip amber. Drop the production screenshot and the client design into the two boxes, then press **Compare**. A progress bar steps through the stages (OCR takes about a minute per image on CPU). When it finishes, the app moves to that run's Results page (`#/results/<run>`), which shows the verdict, the issue counts per verdict, the match level and the accepted count; the two screenshots side by side with every finding's box drawn on them (click an issue to highlight its boxes on both sides, hover a box for its class and text, zoom with − / +); and the issue list, sorted FAIL Critical > Major > Minor > REVIEW, with filter chips by verdict and by spec family A–G. An issue expands to its findings, one sentence each. Each issue has three actions, all local files, each reporting which file it changed and listed under "Changes made from this page" with an **Undo** button (the run's `actions.json` keeps what was written): **Accept** (a note, then one entry per finding in the accepted-differences file from `comparison.accepted_differences.path`; findings with no client element are skipped and counted), **Ignore region** (NONE regions, padded by 0.01, around the issue's boxes in `config/screen_rules/<client screen>.yaml`; the previous file is kept as `<screen>.yaml.<timestamp>.bak`) and **Mark as bug** (`review.json` in the run, shown as a tag). **Re-check**, with a match-level dropdown, redoes matching, the differ and the report from the run's saved fused JSONs in a few seconds (the `scripts/rematch.py` chain, no detector or OCR) into `report_2.json` / `.html`, `report_3...`; nothing is overwritten, the page switches to the newest and the Report dropdown lists the older ones. Downloads: PDF (the first report only), HTML, report.json and a tickets CSV (generated on request with `src/reporting/export.py` and the columns in `config/ticket_export.yaml`). The PDF is printed by headless Microsoft Edge; without Edge, open the HTML and use the browser's Save as PDF.

**Rules** (`#/rules`) edits one client screen's `config/screen_rules/<screen>.yaml`. Pick a screen (client screens of runs with saved OCR); its client screenshot from the latest run shows the existing regions coloured by type. Drag on the image to draw a region, drag a region to move it, drag its corner to resize it; set its name and type (NONE, FLOATING with a max-offset slider 0–0.1, LAYOUT, IGNORE_COLORS, STRICT) or delete it. Set the screen's match level, and add dynamic-text patterns as name + regex rows; **Test** lists which OCR texts of the latest run fully match (case-insensitive). **Save rules** validates on the server too (boxes inside [0, 1], regexes compile) and keeps the previous file as a timestamped `.bak`. **Try on last run** saves, re-checks the latest run with the new rules and shows the FAIL / REVIEW / PASS finding counts before and after. The server only listens on localhost. Each run is kept in `output/app/<timestamp>/`: the inputs, `production_fused.json` / `client_fused.json`, plus `report.json`, `.html`, `.png` and `.pdf`. The app lives in `src/app/`: `server.py` (routes), `jobs.py` (the job queue and the comparison runner), `library.py` (Baselines, Batch and the history strip), `runs.py` (reads run folders), `actions.py` (Results and Rules page API: actions and undo, re-check, rules), `static/` (the page, vanilla JS, no CDN). JSON routes: `GET /status`, `GET /health`, `GET /api/runs`, `GET /api/runs/<run>`, `GET /api/runs/<run>/detail[?report=report_N.json]`, `GET /api/screens`, `GET /api/rules/<screen>`, `POST /compare` (`{production, client}` or `{production, baseline: key}`), `GET /api/jobs`, `GET /api/baselines`, `POST /api/baselines` (`{name, data, screen, device, language}`), `POST /api/baselines/delete` (`{key}`), `POST /api/batch/pair` (`{by, items}`), `POST /api/batch` (`{items: [{name, data, baseline}]}`), `GET /api/batch/<id>`, `GET /api/batch/<id>/summary`, `POST /api/runs/<run>/actions` (`{action: accept|ignore_region|bug, issue_id, report, note}`), `POST /api/runs/<run>/actions/undo` (`{id}`), `POST /api/runs/<run>/recheck` (`{match_level}`), `POST /api/rules/<screen>`, `POST /api/rules/<screen>/test` (`{regex}`), `POST /api/rules/<screen>/try`; files, by whitelisted name only: `GET /run/<run>/report[_N].html|pdf|png`, `GET /api/runs/<run>/image/production|client`, `GET /api/baselines/<screen>/<device>/<language>/image` (listed keys only), `GET /api/runs/<run>/json/report[_N].json`, `GET /api/runs/<run>/tickets/report[_N].json` (CSV).

**Job queue.** Heavy jobs (a comparison, adding a baseline, each batch item) run one at a time, since OCR is CPU-bound; a job started while another runs waits in a first-in-first-out queue and its page shows "queued (#n)". `GET /status` keeps reporting the running comparison's progress and adds `jobs`, every job with its status (queued / running / done / failed) and queue position.

**Baselines** (`#/baselines`) lists the stored client baselines from `baselines/<screen>/<device>/<language>/` (see `scripts/add_baseline.py`) with a thumbnail, screen, device, language, created time and a **stale** flag (built under other detector/OCR settings: re-add it). **Add baseline**: drop a client design, give a screen id, a device (default: inferred from the aspect ratio) and a language (default `default`), and a queued job runs detector + OCR on it once (about a minute). **Delete** asks first, removes the image and moves `meta.json` and `client_fused.json` to `baselines/_archive/<key>_<timestamp>/`. On **Compare**, "Client: use a saved baseline" swaps the client drop box for a searchable baseline list (stale ones are disabled): only the production screenshot runs detector + OCR, about half the time. The run lands in `output/app/<run>/` like any other, with the baseline's image and `client_fused.json` copied in and its key in `baseline.json`, so History, Results and Re-check work unchanged.

**Batch** (`#/batch`) takes many production screenshots at once. Each row is paired with a baseline by the rules of `scripts/run_batch.py` (file stem = screen id, or the longest stored screen id the stem starts with; narrowed by the screenshot's device) and can be changed per row; rows with no baseline are flagged and not run. **Start** queues the rest, and the table (`#/batch/<id>`) updates live: queued (#n) / running / done / failed, verdict, similarity, issues, and a link to each finished run's Results page. Every item is a normal `output/app/<run>/` run. **Download summary** saves the rows as JSON. The live table is kept in memory until the app restarts; the runs stay in History.

**History strip.** When an earlier run compared the same client screen (same baseline key, or the same client screen id), the Results header shows how many findings are **new**, **fixed** and **still open** since that run (`src/reporting/history.py`), with a link to it.

### Command line

```bash
python -m src.main \
  --production-image input/production/ss012.png --production-screen-id ss012 \
  --client-image     input/client/ss012.png     --client-screen-id     ss012
```

Add `--vlm` to have the VLM resolve elements that the detector and OCR left uncertain. This is slow. Without it, those elements are reported as REVIEW.

Outputs go under `output/`:

| Folder            | Contents                                     |
|-------------------|----------------------------------------------|
| `output/reports/` | `<screen>_report.json` + comparison PNG       |
| `output/json/`    | fused UI document per screen                 |
| `output/graph/`   | UI graph per screen                          |
| `output/ocr/`, `output/vlm/` | raw per-stage results             |

### Running a single stage

`scripts/run_<stage>.py` runs one stage on its own and saves numbered debug output. The stages are `detector`, `ocr`, `fusion`, `vlm`, `graph` and `comparison`:

```bash
python -m scripts.run_fusion input/production/ss031.png
python -m scripts.run_comparison <production.png> <client.png>
```

`run_comparison` and the web UI also save each side's fused document. To iterate on matching, the differ or the report without the ~90 s detector + OCR pass:

```bash
python -m scripts.rematch <production_fused.json> <client_fused.json>   # output/rematch/testN_*
```

Pass the same JSON twice for a self-compare: it should come out 100% matched, 100% clean, PASS. `--match-level STRICT|LAYOUT|IGNORE_COLORS` overrides the screen's match level and `--rules <file.yaml>` uses another rules file; `--production-image` / `--client-image` give the screenshots when they are not found next to the JSONs (colour, contrast, pixel-size and broken-image checks need them).

### Baselines, batch, acceptances, tickets

```bash
python -m scripts.add_baseline input/client/home.png --screen home        # ~1 min: detector + OCR on the design, once
python -m scripts.add_baseline --list                                      # instant; stale ones say "re-add"
python -m scripts.run_comparison input/production/home.png --baseline home # ~45 s: production side only
python -m scripts.run_batch input/production/                              # ~45 s per screenshot; resumable
python -m scripts.accept_finding <report.json> --finding 3 --note "deliberate copy change"
python -m scripts.export_tickets <report.json>                             # CSV, one row per issue
```

- Baselines live in `baselines/<screen>/<device>/<language>/` (the image is gitignored). A baseline built under other detector / OCR / fusion settings is stale and refused until it is re-added.
- `run_batch` pairs each screenshot with a baseline by file name (or `--baseline-by screen-id`), writes `output/batch/testN_<folder>/summary.json` + `summary.html`, and never stops on one failed item.
- Accepted differences go to `baselines/accepted_differences.yaml`; the next run reports a matching finding as PASS (accepted) and lists entries that matched nothing as stale.
- Ticket columns are set in `config/ticket_export.yaml`.

## Benchmark

```bash
python -m scripts.make_benchmark       # labelled defect copies of a few screens (input/benchmark/<screen>/)
python -m scripts.run_benchmark        # ~20 min (OCR on every case): caught / missed / false alarms
python -m scripts.run_benchmark --real-only   # ~10 s: only the real pairs, from cached fused JSONs
```

Synthetic cases are one known edit each (rotate, blank poster, remove element, swap tabs, ...). Real
cases live in `input/benchmark/real/<name>/` with the two screenshots, their cached fused JSONs and a
`manifest.json` naming the expected verdict and what must, may and must not be flagged, so a fixed
false alarm cannot quietly come back. Results go to `output/benchmark/testN_benchmark/`
(`results.json`, `scorecard.html`).

## Tests

```bash
pytest
```

## Configuration

- `config/config.yaml`: tolerances, severities, every check's thresholds and on/off switch, match levels, VLM settings
- `config/detector.yaml`: detector engine, model bundle, confidence tiers
- `config/classes.json`: the 16-class UI taxonomy
- `config/screen_rules/<client screen id>.yaml`: per-screen match level, regions (NONE / FLOATING / LAYOUT / IGNORE_COLORS / STRICT) and dynamic-text patterns; edited by hand or on the app's Rules page
- `config/ticket_export.yaml`: ticket CSV columns

## Docs

- `docs/memory.md`: current project state (the source of truth)
- `docs/rules.md`: project constraints that don't change
- `docs/test_cases_pass_fail.md`: the PASS / REVIEW / FAIL spec
- `docs/archive/`: old snapshots, kept for history
