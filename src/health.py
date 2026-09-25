"""
Cheap start-up checks for the web UI (GET /health): is everything a comparison
needs actually there? No model is loaded and nothing heavy is imported.

    run_checks() -> [{name, ok, message, fix, required}, ...]

`required` False means the app still works without it (Edge: the page falls
back to the browser's print), so it does not block the Compare button.
"""

import importlib.util
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
CACHE_SECONDS = 30
_cache = {}


def find_edge():
    """Headless Edge prints the report to PDF (src/app.py)."""
    return next((p for p in [shutil.which("msedge"), *EDGE_PATHS] if p and Path(p).is_file()), None)


def _check(name, ok, message, fix="", required=True):
    return {"name": name, "ok": bool(ok), "message": message, "fix": "" if ok else fix, "required": required}


def _load(path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _checks(config_dir: Path):
    root = config_dir.parent
    cfg, cfg_err = _load(config_dir / "config.yaml")
    det, det_err = _load(config_dir / "detector.yaml")
    out = []
    for name, err in (("config.yaml", cfg_err), ("detector.yaml", det_err)):
        out.append(_check(f"Config {name}", not err, err or "parses",
                          f"fix the YAML in {config_dir / name}"))

    det = det or {}
    if det.get("engine") == "yolo":
        var = det.get("python_env_var", "UI_DETECTOR_PYTHON")
        # Same order as src/detector/engine.load_detector: env var, then python_path.
        python = os.environ.get(var) or det.get("python_path")
        out.append(_check("Detector Python", python and Path(python).is_file(),
                          f"{python}" if python else "not set",
                          f"set {var} (in .env next to 'UI Compare.bat', or the shell) to the "
                          f"UI_Detection_model_training venv's python, or fix python_path in "
                          f"config/detector.yaml"))
        bundle = Path(det.get("bundle", ""))
        weights = (bundle if bundle.is_absolute() else root / bundle) / "best.pt"
        out.append(_check("Detector weights", weights.is_file(), str(weights),
                          "copy best.pt from UI_Detection_model_training/models/ (not in git)"))
    else:
        out.append(_check("Detector", True, f"engine {det.get('engine')!r}: no YOLO Python needed"))

    out.append(_check("PaddleOCR", importlib.util.find_spec("paddleocr"), "installed",
                      "pip install -r requirements.txt in this project's .venv"))

    try:
        (root / "output").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root / "output"):
            pass
        out.append(_check("output/ writable", True, str(root / "output")))
    except OSError as e:
        out.append(_check("output/ writable", False, str(e), f"make {root / 'output'} writable"))

    edge = find_edge()
    out.append(_check("Microsoft Edge", edge, edge or "not found",
                      "install Edge for the PDF download; the browser's Save as PDF still works",
                      required=False))

    vlm = (cfg or {}).get("vlm") or {}
    if vlm.get("enabled"):  # the app's pipeline has no VLM today; only checked if config turns it on
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        host = host if "://" in host else "http://" + host
        try:
            urllib.request.urlopen(host, timeout=1).close()
            out.append(_check("Ollama", True, host))
        except OSError as e:
            out.append(_check("Ollama", False, f"{host}: {e}", "start Ollama (ollama serve)"))
    return out


def run_checks(config_dir=CONFIG_DIR) -> list[dict]:
    """The checks, cached for CACHE_SECONDS per config dir."""
    key = str(Path(config_dir).resolve())
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    result = _checks(Path(config_dir).resolve())
    _cache[key] = (time.monotonic(), result)
    return result


if __name__ == "__main__":
    for c in run_checks():
        print(("OK  " if c["ok"] else "FAIL") + f"  {c['name']}: {c['message']}" + (f"\n      fix: {c['fix']}" if c["fix"] else ""))
