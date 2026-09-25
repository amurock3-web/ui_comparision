import json
import subprocess
import sys
from pathlib import Path

from src.app import runs

ROOT = Path(__file__).resolve().parents[1]


def _make_runs(tmp_path):
    new = tmp_path / "20260925_120252"
    new.mkdir()
    (new / "production_home.png").write_bytes(b"x")
    (new / "production_fused.json").write_text("{}")
    (new / "client_home_design.jpeg").write_bytes(b"x")
    (new / "report.html").write_text("<html></html>")
    (new / "report.pdf").write_bytes(b"%PDF")
    (new / "report.json").write_text(json.dumps({
        "verdict": "FAIL", "similarity_percent": 20.8, "findings": [{}, {}, {}], "issues": [{}],
        "summary": {"matched_pairs": 10, "missing": 16, "extra": 22, "issues": 29}}))
    old = tmp_path / "20260921_164952"  # old format: no issues, no matched_pairs, no PDF
    old.mkdir()
    (old / "production_prod.jpeg").write_bytes(b"x")
    (old / "report.json").write_text(json.dumps({
        "verdict": "REVIEW", "similarity_percent": 0.0, "findings": [{}], "summary": {"total_compared": 36}}))
    broken = tmp_path / "20260920_090000"  # crashed run: no report.json at all
    broken.mkdir()
    (tmp_path / "not_a_run").mkdir()
    return new, old, broken


def test_list_runs_new_old_and_broken(tmp_path):
    _make_runs(tmp_path)
    got = runs.list_runs(tmp_path)
    assert [r["run"] for r in got] == ["20260925_120252", "20260921_164952", "20260920_090000"]
    new, old, broken = got
    assert new == {**new, "date": "2026-09-25 12:02:52", "production": "home.png",
                   "client": "home_design.jpeg", "verdict": "FAIL", "similarity": 20.8,
                   "findings": 3, "issues": 29, "has_html": True, "has_pdf": True}
    assert new["headline"].startswith("Matched 10 of 48")
    assert old["verdict"] == "REVIEW" and old["findings"] == 1 and old["client"] is None
    assert old["issues"] is None and old["headline"] is None and old["has_pdf"] is False
    assert broken["verdict"] is None and broken["findings"] is None and broken["similarity"] is None


def test_list_runs_missing_dir(tmp_path):
    assert runs.list_runs(tmp_path / "nope") == []


def test_run_file_whitelist_and_traversal(tmp_path):
    new, _, _ = _make_runs(tmp_path)
    assert runs.run_file("/run/20260925_120252/report.pdf", tmp_path) == new / "report.pdf"
    assert runs.run_file("/run/20260921_164952/report.pdf", tmp_path) is None  # missing file
    for bad in ("/run/../../x", "/run/20260925_120252/../../../config/config.yaml",
                "/run/20260925_120252/report.json", "/run/20260925_120252/production_home.png",
                "/run/20260925_120252/report.html/../report.pdf", "/run/..%2F..%2Fx/report.html"):
        assert runs.run_file(bad, tmp_path) is None, bad


def test_cli_help():
    out = subprocess.run([sys.executable, "-m", "src.app", "--help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "--port" in out.stdout and "--no-browser" in out.stdout
