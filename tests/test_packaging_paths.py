# Handover packaging: the detector Python lookup order and the bundled OCR models.
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.detector.engine import detector_python

ROOT = Path(__file__).resolve().parents[1]
CFG = {"python_env_var": "UI_DETECTOR_PYTHON_TEST", "python_path": "from_config.exe"}


def test_detector_python_order(tmp_path, monkeypatch):
    monkeypatch.delenv("UI_DETECTOR_PYTHON_TEST", raising=False)
    assert detector_python(CFG, tmp_path) == ("from_config.exe", "config")
    assert detector_python({**CFG, "python_path": ""}, tmp_path) == (None, "")
    assert detector_python({**CFG, "python_path": None}, tmp_path) == (None, "")

    venv = tmp_path / ".venv-detector" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv.parent.mkdir(parents=True)
    venv.write_text("")
    assert detector_python(CFG, tmp_path) == (str(venv), ".venv-detector")

    monkeypatch.setenv("UI_DETECTOR_PYTHON_TEST", "from_env.exe")
    assert detector_python(CFG, tmp_path) == ("from_env.exe", "env")
    monkeypatch.setenv("UI_DETECTOR_PYTHON_TEST", "")  # empty counts as unset
    assert detector_python(CFG, tmp_path) == (str(venv), ".venv-detector")


@pytest.mark.skipif(not (ROOT / "models" / "paddlex" / "official_models").is_dir()
                    or importlib.util.find_spec("paddleocr") is None,
                    reason="needs models/paddlex/official_models and paddleocr")
def test_ocr_engine_points_paddlex_at_bundled_models():
    # Fresh process: paddlex reads the cache dir once, at import. Builds no PaddleOCR.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PADDLE_PDX_CACHE_HOME", "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK")}
    code = ("import src.ocr.engine, paddlex.utils.cache as c, paddlex.utils.flags as f; "
            "print(c.CACHE_DIR); print(f.DISABLE_MODEL_SOURCE_CHECK)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    cache_dir, check = r.stdout.strip().splitlines()[-2:]
    assert Path(cache_dir).resolve() == (ROOT / "models" / "paddlex").resolve()
    assert check == "True"
