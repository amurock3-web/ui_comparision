# Move UI Comparison: Windows laptop → Ubuntu GPU machine, in a sandbox

## What already exists (good news)

The repo already has a sandboxed Docker setup (`Dockerfile` + `docker-compose.yml`):

| Sandbox rule | Where |
|---|---|
| Runs as your normal user, not root (`user: UID:GID`) | compose `app` |
| Whole container filesystem read-only (`read_only: true`), `/tmp` is a small RAM disk | compose `app` |
| All Linux capabilities dropped, no privilege escalation | `cap_drop: [ALL]`, `no-new-privileges` |
| Only three things mounted: code, `input/` (**read-only**), `output/`, plus a model cache volume | `volumes:` |
| Code is never baked into the image, so deleting the container loses nothing | `.dockerignore` = only `requirements.txt` |
| GPU via NVIDIA runtime; CUDA 12.6 + cuDNN; `paddlepaddle-gpu` cu126 | `Dockerfile` |
| Ollama in its own container, models in a named volume | compose `ollama` |

## What is missing for this move (why it won't work as-is)

1. **No detector Python in the image.** YOLO (ultralytics + torch) must live in a *second* venv,
   never next to paddle. The Dockerfile only builds the paddle venv, and `config/detector.yaml`
   points at a Windows path.
2. **GTX 1070 = Pascal (sm_61).** Newer PyTorch CUDA 12.8+ wheels have dropped Pascal
   support, so torch must come from the **cu126** wheel index and be checked with
   `torch.cuda.get_arch_list()` (it must list `sm_61`).
3. **The web app can't be reached.** It binds `127.0.0.1` *inside* the container and compose
   publishes no port. It needs to bind `0.0.0.0` inside, with the port published **only to the
   Ubuntu machine's own loopback** (`127.0.0.1:8765:8765`). Nobody else on the network can reach it.
4. **PDF uses Microsoft Edge**, which isn't in a Linux container. Either add headless Chrome/Chromium
   to the image, or print from the host browser.
5. **`make_benchmark` writes into `input/`**, which is mounted read-only. Its output needs another
   folder.
6. **Windows leftovers:** CRLF line endings would break `start.sh`, the Windows `python_path`,
   Edge paths.
7. **VRAM (8 GB):** PaddleOCR-GPU, YOLO and Ollama must not all hold the GPU at once. Make
   Ollama optional (it's only used with `--vlm`) and set `OLLAMA_KEEP_ALIVE: "0"`.

---

## Step 1: on the laptop: let Claude Code prepare the repo (paste this)

```
Task: prepare this repo to run on an Ubuntu 22.04 machine with an NVIDIA GTX 1070 (Pascal,
sm_61, 8 GB, driver 580), inside the existing sandboxed Docker setup. Edit files only; this
Windows laptop does not run Docker, so do not try to build or run containers.

Read first: CLAUDE.md, Dockerfile, docker-compose.yml, .env.example, .gitignore, .dockerignore,
docs/environment.md, config/detector.yaml, src/detector/engine.py, src/detector/yolo_worker.py,
models/ui16_v1/model_card.json, src/app/ (or src/app.py), src/health.py, scripts/make_benchmark.py,
scripts/run_benchmark.py, start.sh, "UI Compare.bat", requirements.txt.

Keep every existing sandbox setting in docker-compose.yml (read_only, cap_drop ALL,
no-new-privileges, non-root user, tmpfs /tmp, input mounted :ro). Do not weaken any of them;
if something seems to need that, stop and ask me.

1. Detector venv in the image (separate from paddle, CLAUDE.md rule):
   - Dockerfile: a second venv /opt/detector-venv with torch + torchvision from the cu126
     wheel index (https://download.pytorch.org/whl/cu126) and ultralytics pinned to the version
     the model was trained with (model_card.json or the UI_Detection_model_training repo; tell
     me what you found, and ask if it isn't recorded).
   - A build-time check that fails the build if torch's arch list lacks sm_61 (import only;
     no GPU is available at build time).
   - ENV UI_DETECTOR_PYTHON=/opt/detector-venv/bin/python, and the same in compose.
   - Ultralytics/torch caches must go under HOME=/cache (read-only rootfs); set YOLO_CONFIG_DIR
     if needed.
2. Web app reachable from the host browser only:
   - app gets --host (default 127.0.0.1, env APP_HOST); inside the container it runs with
     0.0.0.0; --no-browser when there is no display.
   - compose app: ports: ["127.0.0.1:8765:8765"] (loopback of the Ubuntu host only).
   - Explain in environment.md why 0.0.0.0 inside + 127.0.0.1 publish is still local-only, and
     that --lan stays refused as before.
3. PDF on Linux: extend to_pdf to also try Chrome/Chromium paths. Propose the lightest way to get
   a headless Chromium into the image (not the snap package, which doesn't work in Docker),
   and tell me the image-size cost; if I say no, keep the browser-print fallback.
4. make_benchmark: write generated cases somewhere writable (e.g. output/benchmark_inputs/ or a
   config path) instead of input/benchmark; run_benchmark reads from there, with the old
   location still accepted so existing Windows cases keep working.
5. Ollama optional: put it under a compose profile "vlm" so `docker compose up` starts only the
   app; OLLAMA_KEEP_ALIVE "0". The app/health check must treat Ollama as optional when the VLM
   is off.
6. Line endings: add .gitattributes (*.sh, Dockerfile, *.yml, *.py -> eol=lf; *.bat -> eol=crlf)
   and renormalise.
7. Windows-only assumptions: grep for hard-coded C:\ paths, msedge-only logic, cp1252, os.startfile,
   backslash path joins, and list them with a fix for each (the Windows checkout must keep working).
8. Optional hardening, describe only: after the first run has cached the PaddleOCR/YOLO models
   in the cache volume, block internet egress for the app container (e.g. an internal network
   for app<->ollama) while keeping the loopback port working. Check that published ports still
   work with the network layout you propose.
9. Docs: rewrite docs/environment.md for this compose setup (host prerequisites, first run,
   verification list below, VRAM notes), and add a dated line to docs/memory.md.

Verification list to put in environment.md (I will run these on Ubuntu):
  nvidia-smi
  python -c "import paddle; paddle.utils.run_check()"
  $UI_DETECTOR_PYTHON -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"
  python -m src.health
  python -m pytest tests -q
  a self-compare scripts.rematch, one scripts.run_comparison, then python -m src.app

Plan first, wait for my OK. You may run pytest on this laptop. At the end: list the files changed,
the exact commit + push commands for a branch named ubuntu-gpu, run `graphify update .`, and stop.
```

Then commit and push to the `ubuntu-gpu` branch. `input/`, `output/`, `.env` and `*.pt` stay out
of git, which is correct: screenshots never go to GitHub (rules.md §2).

## Step 2: copy what git doesn't carry (USB drive)

From the laptop's `Documents\ui_comparison`, copy to a USB drive:

- `models\ui16_v1\` (includes `best.pt`, 22 MB)
- `input\` (screenshots + `input\benchmark\`)
- `output\app\` and `output\benchmark\` (saved fused JSONs let you `rematch` without OCR, and
  test3 is your baseline score)

## Step 3: on Ubuntu (host)

```bash
# 3a. host prerequisites
nvidia-smi
docker --version && docker compose version
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi   # GPU works in Docker

# 3b. code
mkdir -p ~/projects && cd ~/projects
git clone -b ubuntu-gpu https://github.com/amurock3-web/ui_comparision.git ui_comparison
cd ui_comparison

# 3c. data + weights from the USB drive (adjust the USB path)
USB=/media/$USER/<usb-name>/ui_comparison
mkdir -p ~/data/ui_comparison/{input,output} models/ui16_v1
cp -r $USB/input/.  ~/data/ui_comparison/input/
cp -r $USB/output/. ~/data/ui_comparison/output/
cp -r $USB/models/ui16_v1/. models/ui16_v1/

# 3d. settings
cp .env.example .env
nano .env    # CODE_DIR=/home/<you>/projects/ui_comparison  DATA_DIR=/home/<you>/data/ui_comparison
             # UID and GID = output of: id -u   and   id -g

# 3e. build and start the sandbox
docker compose build
docker compose up -d
docker compose exec app bash
```

## Step 4: verify inside the container

```bash
nvidia-smi
python -c "import paddle; paddle.utils.run_check()"
$UI_DETECTOR_PYTHON -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"   # True, includes sm_61
python -m src.health
python -m pytest tests -q          # same pass/fail count as on Windows (known: 15 legacy failures)
python -m scripts.rematch output/app/20260925_145307/production_fused.json output/app/20260925_145307/production_fused.json   # self-compare -> 100% PASS
python -m scripts.run_comparison input/production/sunnxt_prod_lang.jpeg input/client/sunnxt_live_lang.jpeg   # first GPU run; downloads OCR models once
python -m src.app --host 0.0.0.0 --no-browser   # then open http://127.0.0.1:8765 in the Ubuntu browser
```

## Step 5: prove it gives the same answers

GPU OCR can read slightly differently from CPU OCR, so check for parity. Don't just assume it:

1. Compare the `run_comparison` result on the lang pair with the Windows one: same matched count,
   same findings (small OCR confidence changes are fine).
2. Re-run the benchmark on Ubuntu and compare it with **test3** (13 caught / 4 as other / 2 missed
   / 3 identity clean / 15 false alarms). That becomes the new baseline score for the GPU machine.
3. Note the time per screen (Windows CPU: ~45 s OCR). Record both in `docs/memory.md`.

Once Ubuntu matches, keep the old `ui_compare_v2` container only until you're sure, then remove it.
Everything lives in the bind-mounted folders and volumes, not in containers.
