"""Phase 16.3: job queue, baselines page, batch page, compare with a baseline, history strip.
No detector / OCR: the heavy calls are stubbed."""
import base64
import json
import threading
import time
from pathlib import Path

import pytest

from src import baselines as bl
from src.app import actions, jobs, library

ROOT = Path(__file__).resolve().parents[1]
DOC = {"screen_id": "home", "source": "client", "image_width": 100, "image_height": 200, "elements": []}
PNG = "data:image/png;base64," + base64.b64encode(b"png").decode()


def _baseline(root, key, stale=False):
    folder = root / key
    folder.mkdir(parents=True)
    screen, device, language = key.split("/")
    (folder / "meta.json").write_text(json.dumps({
        "screen_id": screen, "device": device, "language": language, "created": "2026-09-25T10:00:00",
        "config_hash": "old" if stale else bl.config_hash()}))
    (folder / "client_fused.json").write_text(json.dumps({**DOC, "screen_id": screen}))
    (folder / "client.png").write_bytes(b"img")
    return folder


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)  # config_hash reads config/*.yaml relative to the cwd
    monkeypatch.setattr(jobs, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(jobs, "BASELINE_ROOT", tmp_path / "baselines")
    _baseline(tmp_path / "baselines", "home/phone/default")
    _baseline(tmp_path / "baselines", "detail/tv/default", stale=True)
    return tmp_path


def _wait(pred, timeout=5):
    end = time.time() + timeout
    while not pred():
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def test_queue_runs_one_at_a_time_in_fifo_order():
    order, gate, busy = [], threading.Event(), []

    def work(n):
        def fn():
            busy.append(n)
            assert len(busy) == 1  # never two at once
            if n == 1:
                gate.wait(5)
            order.append(n)
            busy.remove(n)
        return fn

    a, b, c = (jobs.enqueue("test", f"job {n}", work(n)) for n in (1, 2, 3))
    _wait(lambda: a["status"] == "running")
    assert [jobs.position(j) for j in (a, b, c)] == [None, 1, 2]
    assert {j["id"]: j["position"] for j in jobs.jobs_view()}[c["id"]] == 2
    gate.set()
    jobs._queue.join()
    assert order == [1, 2, 3] and all(j["status"] == "done" for j in (a, b, c))


def test_failed_job_does_not_stop_the_queue():
    def boom():
        raise RuntimeError("bad")
    a, b = jobs.enqueue("test", "boom", boom), jobs.enqueue("test", "ok", lambda: None)
    jobs._queue.join()
    assert a["status"] == "failed" and "bad" in a["error"] and b["status"] == "done"


def test_baseline_list_shows_stale(env):
    rows = {r["key"]: r for r in library.baselines()}
    assert rows["home/phone/default"]["stale"] is False and rows["home/phone/default"]["has_image"]
    assert rows["detail/tv/default"]["stale"] is True
    code, body, ctype = library.handle_get("/api/baselines/home/phone/default/image")
    assert code == 200 and body == b"img" and ctype == "image/png"
    for bad in ("/api/baselines/../x/y/image", "/api/baselines/home/phone/../image", "/api/baselines/_archive/x/image"):
        assert library.handle_get(bad)[0] == 404, bad


def test_delete_archives_meta_and_fused_and_removes_image(env):
    code, out, _ = library.handle_post("/api/baselines/delete", {"key": "home/phone/default"})
    assert code == 200, out
    assert not (env / "baselines" / "home").exists()
    (archive,) = (env / "baselines" / "_archive").iterdir()
    assert archive.name.startswith("home_phone_default_")
    assert sorted(p.name for p in archive.iterdir()) == ["client_fused.json", "meta.json"]
    assert [r["key"] for r in library.baselines()] == ["detail/tv/default"]
    assert library.handle_post("/api/baselines/delete", {"key": "../x"})[0] == 404


def test_batch_pairs_and_flags_rows_without_a_baseline(env, monkeypatch):
    pairs = library.pair({"by": "filename", "items": [{"name": "home.png", "width": 100, "height": 200},
                                                      {"name": "nothing.png"},
                                                      {"name": "detail.png", "width": 200, "height": 100}]})
    assert [p["baseline"] for p in pairs] == ["home/phone/default", None, None]
    assert "stale" in pairs[2]["error"]
    assert library.pair({"by": "screen-id", "items": [{"name": "home_2026.png"}]})[0]["baseline"] == "home/phone/default"

    started = []
    monkeypatch.setattr(jobs, "start_compare", lambda data, batch=None: started.append(data) or {"id": -1})
    b = library.start_batch({"items": [{"name": "home.png", "data": PNG, "baseline": "home/phone/default"},
                                       {"name": "nothing.png", "data": PNG, "baseline": None}]})
    assert [d["baseline"] for d in started] == ["home/phone/default"]  # the flagged row is not queued
    flagged = b["rows"][1]
    assert flagged["status"] == "not run" and "no baseline" in flagged["error"]


def test_compare_with_baseline_copies_client_fused(env, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_comparison", lambda *a: calls.append(a))  # production side stubbed
    job = jobs.start_compare({"production": {"name": "home prod.png", "data": PNG}, "baseline": "home/phone/default"})
    jobs._queue.join()
    assert job["status"] == "done" and job["baseline"] == "home/phone/default"
    rd = jobs.RUNS_DIR / job["run"]
    assert (rd / "client_fused.json").read_text() == (env / "baselines/home/phone/default/client_fused.json").read_text()
    assert (rd / "production_home_prod.png").read_bytes() == b"png"
    assert (rd / "client_home.png").read_bytes() == b"img"
    assert json.loads((rd / "baseline.json").read_text()) == {"key": "home/phone/default"}
    run_dir, prod, client, fused = calls[0]
    assert run_dir == rd and fused == rd / "client_fused.json" and client == rd / "client_home.png"
    with pytest.raises(bl.StaleBaselineError):
        jobs.start_compare({"production": {"name": "d.png", "data": PNG}, "baseline": "detail/tv/default"})


def test_new_run_dirs_never_collide(env):
    names = {jobs.new_run_dir().name for _ in range(3)}
    assert len(names) == 3


def test_history_strip_against_previous_run_of_same_baseline(tmp_path):
    f1 = {"type": "MISSING_IN_PRODUCTION", "client_id": "c1", "details": {}}
    f2 = {"type": "EXTRA_IN_PRODUCTION", "client_id": None, "details": {}}
    f3 = {"type": "MISSING_IN_PRODUCTION", "client_id": "c3", "details": {}}
    for run, findings in (("20260925_100000", [f1, f2]), ("20260925_110000", [f1, f3])):
        rd = tmp_path / run
        rd.mkdir()
        (rd / "baseline.json").write_text(json.dumps({"key": "home/phone/default"}))
        (rd / "report.json").write_text(json.dumps({"findings": findings}))
    other = tmp_path / "20260925_105000"  # another screen in between: skipped
    other.mkdir()
    (other / "client_fused.json").write_text(json.dumps({"screen_id": "detail"}))
    (other / "report.json").write_text(json.dumps({"findings": []}))
    _, cur = actions.load_report(tmp_path / "20260925_110000")
    h = library.history(tmp_path / "20260925_110000", cur)
    assert h == {"previous": "20260925_100000", "new": 1, "fixed": 1, "still_open": 1}
    assert library.history(tmp_path / "20260925_100000", {"findings": [f1]}) is None
