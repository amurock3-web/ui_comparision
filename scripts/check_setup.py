"""
Setup doctor: is this checkout ready to run? Read-only, ~10-30 s, never runs
OCR or the detector on an image.

    python -m scripts.check_setup        (main venv, project root)

One line per check: PASS / FIX / INFO. Exit 1 if any FIX.
"""

import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import scripts._test_utils  # noqa: F401  UTF-8 console

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
MAIN_MODULES = ["paddleocr", "paddle", "cv2", "numpy", "shapely", "networkx", "pydantic", "PIL", "yaml"]
FORBIDDEN_IN_MAIN = ["ultralytics", "torch"]
DETECTOR_PROBE = (
    "import sys, importlib.util, ultralytics, torch, cv2; "
    "print(f'{sys.version_info[0]}.{sys.version_info[1]}', ultralytics.__version__, torch.__version__, "
    "cv2.__version__, torch.cuda.is_available(), importlib.util.find_spec('paddle') is not None)"
)

results = []


def report(status, item, detail):
    results.append(status)
    print(f"{status:<5} {item}  {detail}")


def parse_sums(text):
    """sha256sum lines `<hex> *<relpath>` (or two spaces) -> {relpath: hex}."""
    out = {}
    for line in text.splitlines():
        if line.strip():
            digest, rel = line.split(maxsplit=1)
            out[rel.lstrip("*")] = digest.lower()
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_python():
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) != (3, 11):
        return report("FIX", "Python", f"{ver} at {sys.executable}; create .venv with Python 3.11")
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        return report("FIX", "Python", f"{ver} at {sys.executable} is not this project's .venv; "
                                        f"run {ROOT / '.venv'} python (activate .venv)")
    report("PASS", "Python", f"{ver} in .venv")


def check_main_imports():
    try:  # must come first: sets PADDLE_PDX_CACHE_HOME before paddlex reads it at import
        import src.ocr.engine  # noqa: F401
    except Exception:
        pass  # the paddleocr import line below reports the failure
    for name in MAIN_MODULES:
        try:
            mod = importlib.import_module(name)
            report("PASS", f"import {name}", getattr(mod, "__version__", "ok"))
        except Exception as e:
            report("FIX", f"import {name}", f"{type(e).__name__}: {e}; pip install -r requirements.txt in .venv")
    for name in FORBIDDEN_IN_MAIN:
        if importlib.util.find_spec(name):
            report("FIX", f"no {name} in .venv", f"{name} is installed; uninstall from .venv, "
                                                 "they belong in .venv-detector")
        else:
            report("PASS", f"no {name} in .venv", "not installed")


def check_detector():
    import yaml
    from src.detector.engine import detector_python  # the lookup the pipeline itself uses
    cfg = yaml.safe_load((ROOT / "config" / "detector.yaml").read_text(encoding="utf-8")) or {}
    python, source = detector_python(cfg)
    python = Path(python) if python else None
    if python is None:
        return report("FIX", "Detector Python", "not found; create .venv-detector (Python 3.11 + ultralytics/torch) "
                                                "or set UI_DETECTOR_PYTHON")
    if not python.is_file():
        return report("FIX", "Detector Python", f"{python} (from {source}) does not exist")
    try:
        r = subprocess.run([str(python), "-c", DETECTOR_PROBE], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return report("FIX", "Detector Python", f"{python}: importing ultralytics/torch took over 60 s")
    if r.returncode:
        err = (r.stderr.strip().splitlines() or ["no output"])[-1]
        return report("FIX", "Detector Python", f"{python} (from {source}): {err}; "
                                                "pip install -r the detector requirements into it")
    ver, ultra, torch, cv2, cuda, has_paddle = r.stdout.split()
    if ver != "3.11":
        report("FIX", "Detector Python", f"{python} is Python {ver}; use 3.11")
    else:
        report("PASS", "Detector Python", f"{python} (from {source}) py{ver} ultralytics {ultra} "
                                          f"torch {torch} cv2 {cv2} cuda={cuda}")
    if has_paddle == "True":
        report("FIX", "no paddle in detector env", f"uninstall paddlepaddle from {python}; it belongs in .venv")
    else:
        report("PASS", "no paddle in detector env", "not installed")


def check_models():
    sums_file = MODELS / "SHA256SUMS.txt"
    if not sums_file.is_file():
        return report("FIX", "Model checksums", f"{sums_file} missing; re-extract the handover zip")
    sums = parse_sums(sums_file.read_text(encoding="utf-8"))
    bad = 0
    for rel, digest in sums.items():
        path = MODELS / rel
        if not path.is_file():
            bad += 1
            report("FIX", "Model file", f"models/{rel} missing; copy it from the handover zip")
        elif sha256(path) != digest:
            bad += 1
            report("FIX", "Model file", f"models/{rel} checksum mismatch; re-copy it from the handover zip")
    if not bad:
        report("PASS", "Model files", f"{len(sums)} files match models/SHA256SUMS.txt")


def check_configs():
    import yaml
    bad = 0
    files = sorted((ROOT / "config").rglob("*.yaml"))
    for path in files:
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as e:
            bad += 1
            report("FIX", "Config", f"{path.relative_to(ROOT)}: {type(e).__name__}: {e}")
    try:
        json.loads((ROOT / "config" / "classes.json").read_text(encoding="utf-8"))
    except Exception as e:
        bad += 1
        report("FIX", "Config", f"config/classes.json: {type(e).__name__}: {e}")
    if not bad:
        report("PASS", "Configs", f"{len(files)} YAML + classes.json parse")
    det = yaml.safe_load((ROOT / "config" / "detector.yaml").read_text(encoding="utf-8")) or {}
    bundle = Path(det.get("bundle", ""))
    bundle = bundle if bundle.is_absolute() else ROOT / bundle
    if det.get("bundle") and bundle.is_dir():
        report("PASS", "Detector bundle", str(bundle))
    else:
        report("FIX", "Detector bundle", f"{bundle} missing; fix bundle in config/detector.yaml")


def check_ocr_models():
    import src.ocr.engine  # noqa: F401  builds no PaddleOCR
    from paddlex.utils.cache import CACHE_DIR  # where PaddleX will look for / download models
    want = (MODELS / "paddlex").resolve()
    if Path(CACHE_DIR).resolve() == want:
        report("PASS", "OCR models", f"PaddleX uses the bundled {want}")
    else:
        report("FIX", "OCR models", f"PaddleX cache is {CACHE_DIR}, not {want}: OCR would download models; "
                                    "check models/paddlex/official_models exists")


def check_port():
    from src.app.server import HOST, PORT, PORT_TRIES  # same host/range the app binds
    for p in range(PORT, PORT + PORT_TRIES):
        with socket.socket() as s:
            try:
                s.bind((HOST, p))
            except OSError:
                continue
        return report("PASS", "App port", f"{HOST}:{p} free" + ("" if p == PORT else f"; app will use {p}"))
    report("FIX", "App port", f"{HOST}:{PORT}-{PORT + PORT_TRIES - 1} all in use; free one or pass --port")


def check_ollama():
    import yaml
    model = ((yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8")) or {})
             .get("vlm") or {}).get("model", "qwen2.5vl:7b")
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    host = host if "://" in host else "http://" + host
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=2) as r:
            names = {m.get("name") for m in json.load(r).get("models", [])}
    except Exception as e:
        return report("INFO", "Ollama", f"not reachable at {host} ({type(e).__name__}); only needed for the opt-in VLM")
    if model in names:
        report("INFO", "Ollama", f"{host}, {model} pulled")
    else:
        report("INFO", "Ollama", f"{host} up, {model} not pulled: ollama pull {model}")


def check_gpu():
    import paddle
    cuda = paddle.device.is_compiled_with_cuda()
    smi = shutil.which("nvidia-smi")
    report("INFO", "GPU", f"paddle CUDA build={cuda}, nvidia-smi {'at ' + smi if smi else 'not found'}")


def check_edge():
    if os.name != "nt":
        return
    from src.health import find_edge
    edge = find_edge()
    report("PASS" if edge else "INFO", "Microsoft Edge",
           edge or "not found; PDF download falls back to the browser's Save as PDF")


def check_real_pairs():
    real = ROOT / "input" / "benchmark" / "real"
    pairs = [d.name for d in sorted(real.glob("*"))
             if (d / "client_fused.json").is_file() and (d / "production_fused.json").is_file()]
    if pairs:
        report("PASS", "Real benchmark pairs", f"{len(pairs)} with cached fused JSONs ({', '.join(pairs)})")
    else:
        report("FIX", "Real benchmark pairs", f"no folder in {real} has client_fused.json + production_fused.json; "
                                              "copy input/benchmark/real/ from the handover zip")


def check_output():
    from src.health import run_checks  # its output/ check makes the dir and writes a temp file
    c = next(c for c in run_checks() if c["name"] == "output/ writable")
    report("PASS" if c["ok"] else "FIX", "output/ writable", c["message"] if c["ok"] else c["fix"])


CHECKS = [check_python, check_main_imports, check_detector, check_models, check_configs, check_ocr_models,
          check_port, check_ollama, check_gpu, check_edge, check_real_pairs, check_output]
OPTIONAL = {check_ollama, check_gpu, check_edge}


def main():
    os.chdir(ROOT)
    for check in CHECKS:
        try:
            check()
        except Exception as e:  # one broken check must not hide the rest
            report("INFO" if check in OPTIONAL else "FIX", check.__name__[6:], f"{type(e).__name__}: {e}")
    fixes = results.count("FIX")
    print(f"\n{'All required checks pass.' if not fixes else f'{fixes} thing(s) to fix.'}")
    return 1 if fixes else 0


if __name__ == "__main__":
    sys.exit(main())
