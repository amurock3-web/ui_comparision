import json

from PIL import Image

import scripts.run_batch as run_batch
from src.baselines import add_baseline
from src.schema.ui_element import UIDocument


def _setup(tmp_path):
    root = tmp_path / "baselines"
    design = tmp_path / "design.png"
    Image.new("RGB", (108, 240)).save(design)
    for screen in ("home", "search"):
        add_baseline(design, screen, root=root,
                     fused_doc=UIDocument(screen_id=screen, source="client", image_width=1080,
                                          image_height=2400, elements=[]))
    shots = tmp_path / "shots"
    shots.mkdir()
    for name in ("home", "search", "unknown"):
        Image.new("RGB", (108, 240)).save(shots / f"{name}.png")
    return root, shots


def _fake_compare(fail):
    calls = []

    def compare(image, baseline, run_dir, prefix):
        calls.append(image.name)
        if image.stem in fail:
            raise RuntimeError("OCR crashed")
        report = {"verdict": "PASS", "similarity_percent": 99.0, "summary": {"issues": 0},
                  "findings": [{"type": "MISSING_ELEMENT", "client_id": "c9", "details": {}}]}
        (run_dir / f"{prefix}_report.json").write_text(json.dumps(report), encoding="utf-8")
        return report
    compare.calls = calls
    return compare


def _rows(run_dir):
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return {r["file"]: r for r in summary["rows"]}


def test_failure_does_not_stop_batch_and_resume_skips_done(tmp_path, monkeypatch):
    root, shots = _setup(tmp_path)
    out = tmp_path / "batch"

    monkeypatch.setattr(run_batch, "compare_item", _fake_compare(fail={"home"}))
    run_dir = run_batch.run_batch(shots, out_root=out, baseline_root=root)
    assert run_dir.name == "test1_shots"
    rows = _rows(run_dir)
    assert "OCR crashed" in rows["home.png"]["error"]
    assert rows["search.png"]["verdict"] == "PASS" and rows["search.png"]["baseline"] == "search/phone/default"
    assert "LookupError" in rows["unknown.png"]["error"]  # no baseline: an error row, the batch went on
    assert "OCR crashed" in (run_dir / "summary.html").read_text(encoding="utf-8")

    second = _fake_compare(fail=set())
    monkeypatch.setattr(run_batch, "compare_item", second)
    run_batch.run_batch(shots, out_root=out, baseline_root=root, resume=run_dir)
    assert second.calls == ["home.png"]  # search already had a report
    rows = _rows(run_dir)
    assert rows["home.png"]["verdict"] == "PASS" and rows["search.png"]["resumed"] is True

    # A new run never overwrites the old one and gets history from it.
    run_dir2 = run_batch.run_batch(shots, out_root=out, baseline_root=root)
    assert run_dir2.name == "test2_shots"
    rows = _rows(run_dir2)
    assert rows["home.png"]["new"] == 0 and rows["home.png"]["fixed"] == 0


def test_screen_id_prefix_mode():
    assert run_batch.screen_for("home_2026-09-25", "screen-id", {"home", "home_tab", "search"}) == "home"
    assert run_batch.screen_for("home_tab_v2", "screen-id", {"home", "home_tab"}) == "home_tab"
    assert run_batch.screen_for("home", "filename", set()) == "home"
