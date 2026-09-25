"""The job queue and the comparison runner behind the web UI (phase 16.3).

Every heavy job (a comparison, adding a baseline, each batch item) goes through
one FIFO queue served by one worker thread: detector + OCR are CPU-bound and the
models are loaded once, so two at a time would only be slower. `state` is the
progress of the comparison that is running (GET /status); `jobs` is every job
this process queued, each with its status and queue position.
"""

import base64
import itertools
import json
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from src.app.runs import headline
from src.health import find_edge

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "output" / "app"
BASELINE_ROOT = ROOT / "baselines"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
STAGES = [f"{step} ({side})" for side in ("production", "client")
          for step in ("Detector", "OCR", "Fusion", "Graph")] + ["Matching", "Report", "PDF"]

state = {"run": None, "stage": None, "step": 0, "total": len(STAGES), "done": False,
         "error": None, "summary": None, "pdf": False}
lock = threading.Lock()  # held by the worker while a job runs
jobs: list[dict] = []
_queue = queue.Queue()
_ids = itertools.count(1)
_jobs_lock = threading.Lock()
_worker = None


# ---- queue

def enqueue(kind: str, label: str, fn, **info) -> dict:
    """Queue fn() behind every job already waiting; returns the job dict (updated in place)."""
    global _worker
    job = {"id": next(_ids), "kind": kind, "label": label, "status": "queued", "error": None, **info}
    with _jobs_lock:
        jobs.append(job)
        if _worker is None:
            _worker = threading.Thread(target=_work, daemon=True)
            _worker.start()
    _queue.put((job, fn))
    return job


def _work():
    while True:
        job, fn = _queue.get()
        with lock:
            job["status"] = "running"
            try:
                fn()
                job["status"] = "done"
            except Exception as e:
                traceback.print_exc()
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
        _queue.task_done()


def position(job: dict) -> int | None:
    """1 for the next job to run, None unless queued."""
    if job["status"] != "queued":
        return None
    waiting = [j for j in jobs if j["status"] == "queued"]
    return waiting.index(job) + 1 if job in waiting else None


def view(job: dict) -> dict:
    return {**job, "position": position(job)}


def jobs_view(limit: int = 100) -> list[dict]:
    # ponytail: jobs is never trimmed (one dict per job); the view shows the newest `limit`.
    with _jobs_lock:
        return [view(j) for j in jobs[-limit:]]


def find_job(job_id) -> dict | None:
    return next((j for j in jobs if j["id"] == job_id), None)


# ---- comparison runner

def screen_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem) or "screen"


def to_pdf(html_path: Path) -> bool:
    edge = find_edge()
    if not edge:
        return False
    pdf = html_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as profile:  # own profile, so a running Edge doesn't interfere
        subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}", f"--print-to-pdf={pdf}", html_path.as_uri()],
                       capture_output=True, timeout=120)
    return pdf.is_file()


def run_comparison(run_dir: Path, prod_path: Path, client_path: Path, client_fused: Path | None = None):
    """Detector + OCR on both screenshots, or on production only when client_fused
    (a stored baseline's fused JSON, already copied into run_dir) is given."""
    stages = [s for s in STAGES if client_fused is None or "(client)" not in s]
    state.update(run=run_dir.name, stage=stages[0], step=0, total=len(stages), done=False,
                 error=None, summary=None, pdf=False)

    def stage(name):
        state.update(stage=name, step=stages.index(name) + 1)

    try:
        from src.comparison.differ import DifferenceEngine
        from src.comparison.matcher import ElementMatcher
        from src.graph.layout import LayoutGraphBuilder
        from src.pipeline import build_document
        from src.reporting.html_report import write_html_report
        from src.reporting.report import ReportGenerator
        from src.schema.ui_element import UIDocument

        prod_doc, prod_graph = build_document(prod_path, screen_id(prod_path.name), "production", stage)
        if client_fused is None:
            client_doc, client_graph = build_document(client_path, screen_id(client_path.name), "client", stage)
        else:
            client_doc = UIDocument.model_validate_json(Path(client_fused).read_text(encoding="utf-8"))
            client_graph = LayoutGraphBuilder().build(client_doc)
        # Saved before matching: scripts.rematch / Re-check reload these to redo matching,
        # differ and report without paying the ~90s detector + OCR pass again.
        prod_doc.save_json(run_dir / "production_fused.json")
        client_doc.save_json(run_dir / "client_fused.json")
        stage("Matching")
        match = ElementMatcher().match(prod_doc, client_doc, prod_graph, client_graph)
        differences = DifferenceEngine().compare(prod_doc, client_doc, prod_graph, client_graph, match,
                                                 production_image=prod_path, client_image=client_path)
        stage("Report")
        report = ReportGenerator().generate(prod_doc, client_doc, differences)
        ReportGenerator.save_json(report, run_dir / "report.json")
        html_path = write_html_report(report, prod_path, client_path, prod_doc, client_doc, differences,
                                      run_dir / "report.html", prod_graph, client_graph)
        stage("PDF")
        state["pdf"] = to_pdf(html_path)
        state["summary"] = {k: report.get(k) for k in ("verdict", "similarity_percent", "summary", "warnings")}
        state["summary"]["findings"] = len(report["findings"])
        state["summary"]["headline"] = headline(report)
    except Exception as e:
        state["error"] = f"{type(e).__name__}: {e}"
        raise  # the worker marks the job failed
    finally:
        state["done"] = True


# ---- starting a run

def new_run_dir() -> Path:
    """output/app/<YYYYMMDD_HHMMSS>/, one second later while that name is taken
    (a batch creates many runs in the same second)."""
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    t = datetime.now()
    while True:
        d = RUNS_DIR / t.strftime("%Y%m%d_%H%M%S")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            t += timedelta(seconds=1)


def save_upload(upload: dict, folder: Path, prefix: str) -> Path:
    """{name, data: data-URL} -> folder/<prefix><screen id><ext>. ValueError if not an image."""
    name = str(upload["name"])
    ext = Path(name).suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ValueError(f"{name} is not an image")
    path = folder / f"{prefix}{screen_id(name)}{ext}"
    path.write_bytes(base64.b64decode(str(upload["data"]).split(",", 1)[1]))
    return path


def start_compare(data: dict, batch: str | None = None) -> dict:
    """{production: {name, data}, client: {name, data}} or {production, baseline: key}
    -> the queued job (its "run" is the run id). ValueError for a bad upload,
    LookupError / StaleBaselineError / FileNotFoundError for an unusable baseline."""
    baseline = None
    if data.get("baseline"):
        from src.baselines import load_baseline
        baseline = load_baseline(str(data["baseline"]), BASELINE_ROOT)  # stale -> StaleBaselineError
    elif not isinstance(data.get("client"), dict):
        raise ValueError("client: upload an image or pick a baseline")
    if not isinstance(data.get("production"), dict):
        raise ValueError("production: upload an image")
    run_dir = new_run_dir()
    try:
        prod = save_upload(data["production"], run_dir, "production_")
        client_fused = None
        if baseline:
            client = run_dir / f"client_{screen_id(baseline.meta.get('screen_id') or 'baseline')}{baseline.image.suffix.lower()}"
            shutil.copyfile(baseline.image, client)
            client_fused = run_dir / "client_fused.json"
            shutil.copyfile(baseline.path / "client_fused.json", client_fused)
            (run_dir / "baseline.json").write_text(json.dumps({"key": baseline.key}), encoding="utf-8")
        else:
            client = save_upload(data["client"], run_dir, "client_")
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return enqueue("compare", f"{prod.name[len('production_'):]} vs {client.name[len('client_'):]}",
                   lambda: run_comparison(run_dir, prod, client, client_fused),
                   run=run_dir.name, baseline=baseline.key if baseline else None, batch=batch)
