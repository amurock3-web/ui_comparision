# How to set up UI Comparison

UI Comparison compares a production screenshot of an OTT app screen with the client design and
reports layout differences as PASS / REVIEW / FAIL. It runs fully on one computer.

> **Keep this zip internal.** It contains SunNXT and JioHotstar client screenshots and reports.
> Never share it outside the company, and never upload it (or any screenshot or report from it) to a
> cloud or AI service. Everything stays local ([rules.md](rules.md) section 2).

## 1. What is inside the zip

The zip unpacks to one folder, `ui_comparison/`:

```
ui_comparison/
├── src/                 the program (pipeline, comparison, reports, web app)
├── scripts/             command-line tools (compare, benchmark, setup check, smoke test, ...)
├── config/              settings and thresholds (config.yaml, detector.yaml, screen_rules/)
├── models/              bundled models, so nothing downloads after setup
│   ├── ui16_v1/         YOLO detector weights (best.pt) + model card and class list
│   ├── paddlex/         PaddleOCR text models (PP-OCRv6_medium det + rec, English)
│   └── SHA256SUMS.txt   checksums the setup check verifies
├── input/               screenshots (production/, client/) and benchmark data (benchmark/)
├── output/              past runs, about 2.4 GB of history; output/INDEX.md says which matter
├── baselines/           stored client designs to compare against
├── docs/                all documentation (this file, USER_GUIDE.md, HANDOVER.md, ...)
├── tests/               unit tests (pytest)
├── graphify-out/        a knowledge graph of the code, for developers
├── .git/                the full git history
├── Claude outputs/      extra material made during the project (pipeline explainer video)
├── README.md            front page
├── setup.bat / setup.sh             one-time setup (Windows / Ubuntu)
├── UI Compare.bat / start.sh        start the drag-and-drop app (Windows / Ubuntu)
├── requirements.txt                 Python packages for the main environment (.venv)
├── requirements-detector.txt        Python packages for the detector environment (.venv-detector)
├── MANIFEST.txt         folder sizes and model checksums of this zip
├── CLAUDE.md            working notes for Claude Code (developers can ignore)
└── Dockerfile, docker-compose.yml   Ubuntu GPU plan, not finished (docs/migration_ubuntu_gpu.md)
```

**Not inside the zip, and why:**

| Missing | Why | How you get it |
|---|---|---|
| `.venv/`, `.venv-detector/` | A Python virtual environment only works on the computer that made it: it points at that computer's Python install. | `setup.bat` / `setup.sh` builds both. |
| `__pycache__/`, `.pytest_cache/`, `*.pyc` | Caches, made again on first run. | Automatic. |
| Ollama and its `qwen2.5vl:7b` model | Optional, about 6 GB, only used with `--vlm`. | See the prerequisites below. |

## 2. Prerequisites

| Item | Needed | Notes |
|---|---|---|
| Operating system | Windows 10 or 11 (64-bit), or Ubuntu 22.04 / 24.04 | Windows is the setup in daily use. |
| Python | **3.11 exactly** (both environments) | Windows: the 3.11 installer from [python.org](https://www.python.org/downloads/windows/); tick **"Add python.exe to PATH"**. Check with `py -3.11 --version`. Ubuntu: see section 4. |
| Disk | about 2.8 GB for the unpacked folder (the zip itself is about 2.2 GB) + about 3-4 GB for the two environments | Keep about 8 GB free; pip also caches downloads during setup. |
| RAM | 8 GB minimum, 16 GB recommended | OCR is the heavy part. |
| Internet | only during setup | After setup everything runs offline (section 8). |
| NVIDIA GPU | not needed | Everything runs on the CPU. GPU torch for the detector: see the comment in `requirements-detector.txt`. |
| Ollama + `qwen2.5vl:7b` | optional, only for `--vlm` | Install Ollama, then `ollama pull qwen2.5vl:7b` (about 6 GB). |
| Microsoft Edge | optional (Windows) | Makes the PDF download of a report. Without it the HTML report still works. Ships with Windows 11. |

## 3. Setup on Windows

1. **Unzip** to a short path with no special characters, for example `C:\work\ui_comparison`.
   Spaces in the path are OK. Do not run it from inside the zip.
2. **Run `setup.bat`**: double-click it, or run it in a terminal:

   ```powershell
   cd C:\work\ui_comparison
   .\setup.bat
   ```

   It needs internet and takes about 10-20 minutes the first time. It:
   - finds Python 3.11 (`py -3.11`, else `python` if that is 3.11),
   - creates `.venv` (main: PaddleOCR) and `.venv-detector` (YOLO: ultralytics + torch),
   - installs `requirements.txt` into `.venv` and `requirements-detector.txt` into `.venv-detector`,
   - runs the setup check (the "doctor", section 5).
3. **Success looks like** a list of `PASS` lines (and some `INFO` lines) ending with:

   ```
   All required checks pass.
   Setup complete. Start the app with "UI Compare.bat".
   ```

   `INFO` lines (Ollama, GPU, sometimes Edge) are optional extras, not errors. A `FIX` line names
   what to fix; fix it and run `setup.bat` again.

Re-running `setup.bat` is safe: healthy environments are kept and pip skips what is installed. An
environment that does not work on this computer (for example one copied from elsewhere) is deleted
and rebuilt.

## 4. Setup on Ubuntu

```bash
unzip ui_comparison_handover_<YYYYMMDD>.zip -d ~/work
cd ~/work/ui_comparison

# Python 3.11 (Ubuntu 22.04 / 24.04 do not ship it)
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt install python3.11 python3.11-venv

# OpenCV needs these libraries (minimal / server installs lack them)
sudo apt install libgl1 libglib2.0-0

bash setup.sh       # needs internet, about 10-20 minutes the first time; safe to re-run
bash start.sh       # starts the app
```

`setup.sh` does the same as `setup.bat` and installs the CPU build of torch for the detector. It
ends with the doctor; `All required checks pass.` means it is ready.

## 5. Verify the install

**Setup check (doctor)**, about 10-30 s, changes nothing:

```powershell
.venv\Scripts\python.exe -m scripts.check_setup
```
```bash
.venv/bin/python -m scripts.check_setup
```

One line per check: `PASS`, `FIX` (must fix) or `INFO` (optional). It checks Python 3.11, the main
imports, that torch/ultralytics are **not** in `.venv`, the detector Python, the model checksums,
the configs, that OCR uses the bundled models, the app port, Ollama, GPU, Edge, the real benchmark
pair and that `output/` is writable. Exit code 0 means ready. Shortened example:

```
PASS  Python  3.11.x in .venv
PASS  no torch in .venv  not installed
PASS  Detector Python  ...\.venv-detector\Scripts\python.exe (from .venv-detector) py3.11 ultralytics 8.4.146 torch 2.14.0 ...
PASS  Model files  10 files match models/SHA256SUMS.txt
PASS  OCR models  PaddleX uses the bundled ...\models\paddlex
PASS  App port  127.0.0.1:8765 free
INFO  Ollama  not reachable at http://127.0.0.1:11434 (...); only needed for the opt-in VLM

All required checks pass.
```

**Smoke test**, a few seconds, no OCR or detector. It re-runs the comparison on the saved real pair
in `input/benchmark/real/trending_search/`:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_test
```
```bash
.venv/bin/python -m scripts.smoke_test
```

Expected (the last lines; a `Pair: ... output: ...` line and the run time are also printed):

```
[PASS] A real pair: verdict FAIL, 16 findings (INFO: manifest expects REVIEW)
[PASS] B self-compare: verdict PASS, 0 findings
SMOKE TEST: PASS
```

The FAIL in line A is expected: it is a known gap on this pair (production differs from an older
design), recorded in [output/INDEX.md](../output/INDEX.md). What matters is `SMOKE TEST: PASS`.
Results go to `output/smoke/testN_smoke/`.

**Unit tests (optional)**, for developers:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```
```bash
.venv/bin/python -m pytest tests -q
```

The last full run gave 343 passed, 15 failed, 1 skipped. The 15 failures are known legacy tests
(14 in `tests/test_fusion.py`, 1 in `tests/test_graph.py`) for old code paths. They are not a
problem with your install.

## 6. First real comparison

### 6a. The drag-and-drop app (for testers)

1. Double-click **`UI Compare.bat`** (Ubuntu: `bash start.sh`).
2. Your browser opens at http://127.0.0.1:8765 (or the next free port if 8765 is taken).
   The app only listens on this computer.

   ![The drag-and-drop page](images/app_home.png)

3. Drop a **production** screenshot and the **client** design (for example
   `input/production/ss012.png` and `input/client/ss012.png`), then press **Compare**.
4. Wait about 2 min on a CPU (OCR takes about 45 s per screen). The page shows each stage.
5. Open the report. Each run is kept in `output/app/<date_time>/` (inputs, `report.html`,
   `report.json`, `report.png`, `report.pdf` when Edge is present).

Stop the app with Ctrl+C in its window.

### 6b. The command line

```powershell
.venv\Scripts\python.exe -m scripts.run_comparison input\production\ss012.png input\client\ss012.png
```
```bash
.venv/bin/python -m scripts.run_comparison input/production/ss012.png input/client/ss012.png
```

The report is written to `output/comparison/testN_<name>_report.html` (plus `.json` and `.png`).

Everything else (baselines, batches, accepting a finding, tickets, reading the verdicts) is in
[USER_GUIDE.md](USER_GUIDE.md).

## 7. Where inputs and outputs live

| Folder | What |
|---|---|
| `input/production/`, `input/client/` | screenshots to compare (you can put new ones here or anywhere) |
| `input/benchmark/` | the known-defect benchmark cases and the real pair used by the smoke test |
| `output/<stage>/testN_*` | results of each script, in a new numbered `testN_` folder or file per run |
| `output/app/<YYYYMMDD_HHMMSS>/` | one folder per web-app run |
| `baselines/` | stored client designs (`python -m scripts.add_baseline`) |

Rule: scripts never overwrite an earlier run; they pick the next free `N`. Do not delete or rename
old `testN_` folders. [output/INDEX.md](../output/INDEX.md) lists the runs that matter.

## 8. Offline use

After setup nothing downloads. The OCR models are in `models/paddlex/` and the program points
PaddleOCR there automatically; the detector weights are in `models/ui16_v1/best.pt`. To confirm,
run the doctor and look for:

```
PASS  OCR models  PaddleX uses the bundled ...models\paddlex
PASS  Model files  10 files match models/SHA256SUMS.txt
```

The only part that needs a network service is the optional VLM (`--vlm`), and that talks to a local
Ollama server on this computer.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: Python 3.11 was not found` / wrong Python version | Python 3.11 not installed or not on PATH | Install 3.11 from python.org with "Add python.exe to PATH" ticked; check `py -3.11 --version`; run setup again. Ubuntu: the deadsnakes commands in section 4. |
| Garbled text or `UnicodeEncodeError` in the Windows console | The console uses cp1252; OCR returns Tamil / CJK text | The scripts already force UTF-8. If it still happens, use Windows Terminal or run `chcp 65001` first. |
| Crashes / `ImportError` after someone installed ultralytics or torch; doctor `FIX no torch in .venv` | ultralytics / torch must never share a venv with PaddlePaddle | `.venv\Scripts\python.exe -m pip uninstall torch` (same for `ultralytics`). They belong only in `.venv-detector`. Never `pip install` them into `.venv`. |
| App opens on 8766 or later | Port 8765 is taken | Normal: the app tries the next 10 ports (up to 8775) and prints the address in its console. Or pick one: `"UI Compare.bat" --port 8800`. |
| A comparison takes about 2 min | OCR on CPU, about 45 s per screen | Normal. A GPU is not required. |
| Doctor `FIX Model file ... missing` or `checksum mismatch` | A model file was damaged or not copied | Re-copy `models/` from the zip, then run the doctor again. |
| Doctor `FIX OCR models` | `models/paddlex/official_models` missing, so OCR would try to download | Re-copy `models/` from the zip. |
| Doctor `FIX Detector Python` | `.venv-detector` missing or broken | Run setup again. To use another detector Python, set `UI_DETECTOR_PYTHON` (or put `UI_DETECTOR_PYTHON=...` in a `.env` file in the project root for the launchers). |
| `--vlm` fails, doctor `INFO Ollama not reachable` | Ollama not running or model not pulled | Only needed for `--vlm`: `ollama serve`, then `ollama pull qwen2.5vl:7b`. |
| Launcher says "Setup has not been run on this computer" | `.venv` or `.venv-detector` is missing | Run `setup.bat` (Ubuntu: `bash setup.sh`). |
| Launcher says "the .venv was made on another computer" | The venv was copied or the folder moved | Run setup again; it rebuilds the venv. |
| `setup.sh: line 2: $'\r': command not found` | The `.sh` files got Windows (CRLF) line endings | `sed -i 's/\r$//' setup.sh start.sh`, then `bash setup.sh`. |
| `pip install` fails with connection / SSL errors behind a company proxy | pip cannot reach the internet | Ask IT for the proxy, then set it for the session (`set HTTPS_PROXY=http://proxy:port` on Windows, `export HTTPS_PROXY=...` on Ubuntu) and re-run setup; or run the failing pip command by hand with `--proxy http://proxy:port`. |
| Ubuntu: `ImportError: libGL.so.1` | OpenCV system libraries missing | `sudo apt install libgl1 libglib2.0-0`. |
| No PDF download | Microsoft Edge not found | Open the HTML report and use the browser's Save as PDF. |

More (stale baselines, disabled Compare button, old runs): [HANDOVER.md section 12](HANDOVER.md#12-troubleshooting).

## 10. Updating or moving the folder later

- **Moving or copying the folder** to another place or computer breaks `.venv` and `.venv-detector`
  (they point at the old location and the old Python). Run setup again; it detects this and rebuilds
  them (internet needed again).
- **Updating the code** (new zip or `git pull`): run setup again, so new package versions in
  `requirements*.txt` are installed, then run the doctor and the smoke test.
- Keep `output/` and `baselines/` when you update: they are your history and stored designs.

Setup background and the planned Ubuntu GPU / Docker setup (not finished):
[HANDOVER.md section 4](HANDOVER.md#4-setup-from-zero) and [migration_ubuntu_gpu.md](migration_ubuntu_gpu.md).
