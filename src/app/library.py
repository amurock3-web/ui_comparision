"""Baselines page, batch page and the Results history strip (phase 16.3).

    GET  /api/jobs                               the queue (same list as /status "jobs")
    GET  /api/baselines                          stored baselines (src/baselines.py)
    GET  /api/baselines/<screen>/<device>/<language>/image   the design, only for a listed key
    POST /api/baselines         {name, data, screen, device, language} -> queued add_baseline job
    POST /api/baselines/delete  {key}   image removed, meta.json + client_fused.json to baselines/_archive/
    POST /api/batch/pair        {by, items: [{name, width, height}]} -> suggested baseline per item
    POST /api/batch             {items: [{name, data, baseline}]} -> {batch, rows}; rows without a baseline are flagged, not queued
    GET  /api/batch/<id>        live rows (status, verdict, similarity, issues, run)
    GET  /api/batch/<id>/summary   the same rows as a JSON download

Batch items are ordinary output/app/<run>/ runs made by jobs.start_compare.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from src.app import jobs
from src.app.runs import RUN_RE, read_run

PART_RE = re.compile(r"[A-Za-z0-9_.-]{1,120}")
DEVICES = ("phone", "tablet", "tv")
# ponytail: batches live in memory (their runs are on disk); a restart loses the live table, not the results.
batches: dict[str, dict] = {}


class BadRequest(ValueError):
    pass


def _json(code, body):
    return code, body, "application/json"


# ---- baselines

def baselines() -> list[dict]:
    from src.baselines import list_baselines
    rows = []
    for r in list_baselines(jobs.BASELINE_ROOT):
        m = r["meta"]
        rows.append({"key": r["key"], "screen": m.get("screen_id"), "device": m.get("device"),
                     "language": m.get("language"), "created": m.get("created"), "stale": r["stale"],
                     "image_size": m.get("image_size"),
                     "has_image": any(Path(r["path"]).glob("client.*"))})
    return rows


def _listed(key: str) -> Path:
    """The folder of a key list_baselines returns; anything else (.., slashes, _archive) is refused."""
    if not any(r["key"] == key for r in baselines()):
        raise FileNotFoundError(f"no baseline {key!r}")
    return jobs.BASELINE_ROOT / key


def baseline_image(key: str) -> tuple[bytes, str]:
    img = next((p for p in _listed(key).glob("client.*") if p.suffix.lower() in jobs.IMAGE_EXTS), None)
    if img is None:
        raise FileNotFoundError(f"baseline {key} has no image")
    ext = img.suffix.lower()
    return img.read_bytes(), {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, f"image/{ext[1:]}")


def add(body: dict) -> dict:
    screen = str(body.get("screen") or "").strip()
    device = str(body.get("device") or "").strip() or None
    language = str(body.get("language") or "").strip() or None
    if not PART_RE.fullmatch(screen) or screen.startswith(("_", ".")):
        raise BadRequest("screen id: letters, digits, _ - . only (and not starting with _ or .)")
    if device and device not in DEVICES:
        raise BadRequest(f"device must be one of {', '.join(DEVICES)} (or empty to infer it)")
    if language and not PART_RE.fullmatch(language):
        raise BadRequest("language: letters, digits, _ - . only")
    # Kept: meta.json's source_file points at it.
    uploads = jobs.RUNS_DIR / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    image = jobs.save_upload(body, uploads, f"{datetime.now():%Y%m%d_%H%M%S_%f}_")

    def work():
        from src.baselines import add_baseline
        add_baseline(image, screen, device, language, root=jobs.BASELINE_ROOT)

    return jobs.view(jobs.enqueue("baseline", f"add baseline {screen}", work, screen=screen))


def delete(key: str) -> dict:
    folder = _listed(str(key or ""))
    dest = jobs.BASELINE_ROOT / "_archive" / f"{key.replace('/', '_')}_{datetime.now():%Y%m%d_%H%M%S}"
    dest.mkdir(parents=True)
    for name in ("meta.json", "client_fused.json"):
        if (folder / name).is_file():
            shutil.move(str(folder / name), str(dest / name))
    for img in folder.glob("client.*"):
        img.unlink()
    for d in (folder, folder.parent, folder.parent.parent):  # drop the now-empty key folders
        try:
            d.rmdir()
        except OSError:
            break
    return {"key": key, "archive": dest.relative_to(jobs.ROOT).as_posix() if dest.is_relative_to(jobs.ROOT) else str(dest),
            "message": f"Deleted {key}; meta.json and client_fused.json kept in {dest.name}"}


# ---- batch

def pair(body: dict) -> list[dict]:
    """run_batch's pairing: stem == screen id (by=filename) or the longest stored
    screen id the stem starts with (by=screen-id), narrowed by the screenshot's device."""
    from scripts.run_batch import screen_for
    from src.baselines import StaleBaselineError, infer_device, load_baseline
    by = body.get("by") or "filename"
    screens = {r["key"].split("/")[0] for r in baselines()}
    out = []
    for it in body.get("items") or []:
        name, row = str(it.get("name") or ""), {"name": str(it.get("name") or ""), "baseline": None, "error": None}
        try:
            device = infer_device(int(it["width"]), int(it["height"])) if it.get("width") and it.get("height") else None
            row["baseline"] = load_baseline(screen_for(Path(name).stem, by, screens), jobs.BASELINE_ROOT,
                                            device=device).key
        except StaleBaselineError as e:
            row["error"] = f"stale: {e}"
        except (LookupError, FileNotFoundError, ValueError) as e:
            row["error"] = str(e)
        out.append(row)
    return out


def start_batch(body: dict) -> dict:
    batch_id = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
    rows = []
    for it in body.get("items") or []:
        row = {"file": str(it.get("name") or ""), "baseline": it.get("baseline") or None, "job": None, "error": None}
        if not row["baseline"]:
            row["error"] = "no baseline: not run"
        else:
            try:
                row["job"] = jobs.start_compare({"production": it, "baseline": row["baseline"]}, batch=batch_id)["id"]
            except Exception as e:  # stale / missing baseline, bad image: flag the row, go on
                row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    batches[batch_id] = {"id": batch_id, "created": datetime.now().isoformat(timespec="seconds"), "rows": rows}
    return batch_status(batch_id)


def batch_status(batch_id: str) -> dict:
    b = batches.get(batch_id)
    if b is None:
        raise FileNotFoundError(f"no batch {batch_id!r} (batches are kept until the app restarts)")
    rows = []
    for r in b["rows"]:
        job = jobs.find_job(r["job"]) if r["job"] else None
        row = {"file": r["file"], "baseline": r["baseline"], "status": "not run" if job is None else job["status"],
               "position": jobs.position(job) if job else None, "run": job and job.get("run"),
               "error": r["error"] or (job and job.get("error")), "verdict": None, "similarity": None, "issues": None}
        if job and job["status"] == "done":
            m = read_run(jobs.RUNS_DIR / job["run"])
            row.update(verdict=m["verdict"], similarity=m["similarity"], issues=m["issues"])
        rows.append(row)
    return {"id": b["id"], "created": b["created"], "rows": rows}


# ---- history strip on the Results page

def _client_key(rd: Path) -> tuple:
    """(baseline key or None, client screen id or None) of a run."""
    def read(name, field):
        try:
            return json.loads((rd / name).read_text(encoding="utf-8"))[field]
        except (OSError, ValueError, KeyError, TypeError):
            return None
    return read("baseline.json", "key"), read("client_fused.json", "screen_id")


def _same_client(a: tuple, b: tuple) -> bool:
    return any(x is not None and x == y for x, y in zip(a, b))


def history(rd: Path, report: dict) -> dict | None:
    """new / fixed / still open against the newest earlier run of the same
    baseline key or the same client screen id."""
    from src.app.actions import load_report
    from src.reporting.history import diff
    key = _client_key(rd)
    if key == (None, None):
        return None
    # ponytail: reads each earlier run's client_fused.json until one matches; index by screen if History gets huge.
    for prev in sorted((d for d in rd.parent.iterdir() if d.is_dir() and RUN_RE.fullmatch(d.name)
                        and d.name < rd.name), key=lambda d: d.name, reverse=True):
        if not _same_client(_client_key(prev), key):
            continue
        try:
            _, prev_report = load_report(prev)
        except FileNotFoundError:
            continue
        d = diff(prev_report, report)
        return {"previous": prev.name, **{k: len(v) for k, v in d.items()}}
    return None


# ---- routing (server.py delegates here)

def handle_get(path: str):
    try:
        if path == "/api/jobs":
            return _json(200, jobs.jobs_view())
        if path == "/api/baselines":
            return _json(200, baselines())
        m = re.fullmatch(r"/api/baselines/(.+)/image", path)
        if m:
            body, ctype = baseline_image(m[1])
            return 200, body, ctype
        m = re.fullmatch(r"/api/batch/([0-9_]+)(/summary)?", path)
        if m:
            s = batch_status(m[1])
            return (200, json.dumps(s, indent=2), "application/json") if m[2] else _json(200, s)
        return None
    except FileNotFoundError as e:
        return _json(404, {"error": str(e)})


def handle_post(path: str, body: dict):
    try:
        if path == "/api/baselines":
            return _json(200, add(body))
        if path == "/api/baselines/delete":
            return _json(200, delete(body.get("key")))
        if path == "/api/batch/pair":
            return _json(200, pair(body))
        if path == "/api/batch":
            return _json(200, start_batch(body))
        return None
    except FileNotFoundError as e:
        return _json(404, {"error": str(e)})
    except (BadRequest, ValueError, KeyError, IndexError) as e:
        return _json(400, {"error": f"{type(e).__name__}: {e}" if not isinstance(e, BadRequest) else str(e)})
