# UI Comparison

Compares a **Production** and a **Client** screenshot of an OTT app screen and reports layout differences: missing or extra elements, position, size, colour and text. Each finding gets a PASS / REVIEW / FAIL verdict. Poster and tile artwork is treated as dynamic content and ignored.

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

## Usage

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

## Tests

```bash
pytest
```

## Configuration

- `config/config.yaml`: tolerances, severities, VLM settings
- `config/detector.yaml`: detector engine, model bundle, confidence tiers
- `config/classes.json`: the 16-class UI taxonomy

## Docs

- `docs/memory.md`: current project state (the source of truth)
- `docs/rules.md`: project constraints that don't change
- `docs/test_cases_pass_fail.md`: the PASS / REVIEW / FAIL spec
- `docs/archive/`: old snapshots, kept for history
