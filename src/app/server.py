"""Routes and JSON API of the web UI; the job queue and comparison runner are in jobs.py.

GET  /                      static/index.html (the hash router shows Compare/Results/History/Help)
GET  /app.css, /app.js, /results.js, /rules.js, /library.js   the rest of static/
GET  /status                progress of the current (or last) comparison, plus "jobs": the queue
GET  /health                src/health.py's checks
GET  /api/runs              every run in output/app/, newest first
GET  /api/runs/<run>        one run
GET  /run/<run>/report[_N].(html|pdf|png)
POST /compare               {"production": {name, data}, "client": {name, data} | "baseline": key}
                            -> {"run", "job", "position"}; queued FIFO behind any running job (jobs.py)
Results/Rules page routes (/api/runs/<run>/detail|image|json|tickets|actions|recheck,
/api/screens, /api/rules/<screen>) live in actions.py, the Baselines / Batch / queue
routes (/api/baselines*, /api/batch*, /api/jobs) in library.py; both expose handle_get / handle_post.
"""

import json
import os
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from src.app import actions, jobs, library
from src.app.jobs import (ROOT, RUNS_DIR, STAGES, lock, run_comparison, screen_id, state,  # noqa: F401
                          to_pdf)
from src.app.runs import list_runs, read_run, run_file
from src.health import run_checks

HOST, PORT = "127.0.0.1", 8765
PORT_TRIES = 11  # the port asked for, then the next 10
STATIC_DIR = Path(__file__).resolve().parent / "static"
# Only these names are served from static/; nothing else under it is reachable.
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          **{f"/{n}.js": (f"{n}.js", "text/javascript; charset=utf-8")
             for n in ("app", "results", "rules", "library")}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path in STATIC:
            name, ctype = STATIC[path]
            return self._send((STATIC_DIR / name).read_bytes(), ctype)
        if path == "/status":  # the running comparison's progress, plus the queue
            return self._send({**state, "jobs": jobs.jobs_view()})
        if path == "/health":
            return self._send(run_checks())
        if path == "/api/runs":
            return self._send(list_runs(RUNS_DIR))
        m = re.fullmatch(r"/api/runs/(\d{8}_\d{6})", path)
        if m and (RUNS_DIR / m[1]).is_dir():
            return self._send(read_run(RUNS_DIR / m[1]))
        f = run_file(path, RUNS_DIR)
        if f:
            ctype = {".html": "text/html; charset=utf-8", ".pdf": "application/pdf",
                     ".png": "image/png"}[f.suffix]
            return self._send(f.read_bytes(), ctype)
        try:
            hit = (library.handle_get(path)
                   or actions.handle_get(path, {k: v[0] for k, v in parse_qs(qs).items()}))
        except Exception as e:
            traceback.print_exc()
            hit = (500, {"error": f"{type(e).__name__}: {e}"}, "application/json")
        if hit:
            code, body, ctype = hit
            return self._send(body, ctype, code)
        self._send({"error": "not found"}, code=404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))  # read first: an unread body aborts the reply
        if self.path.startswith("/api/"):
            try:
                data = json.loads(body or b"{}")
                assert isinstance(data, dict)
            except (ValueError, AssertionError):
                return self._send({"error": "body must be a JSON object"}, code=400)
            try:
                hit = library.handle_post(self.path, data) or actions.handle_post(self.path, data)
            except Exception as e:  # a crash in the differ must still answer the page
                traceback.print_exc()
                hit = (500, {"error": f"{type(e).__name__}: {e}"}, "application/json")
            code, out, ctype = hit or (404, {"error": "not found"}, "application/json")
            return self._send(out, ctype, code)
        if self.path != "/compare":
            return self._send({"error": "not found"}, code=404)
        try:
            job = jobs.start_compare(json.loads(body))
        except Exception as e:  # bad upload, stale or missing baseline
            return self._send({"error": f"Cannot start: {e}"}, code=400)
        self._send({"run": job["run"], "job": job["id"], "position": jobs.position(job)})

    def log_message(self, *args):  # keep the console for pipeline output
        pass


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind a port that is already
    # in use, which would defeat the fallback below.
    allow_reuse_address = os.name != "nt"


def bind_server(port: int, host: str = HOST) -> Server:
    """A server on `port`, or on the first free one of the next PORT_TRIES - 1."""
    for p in range(port, port + PORT_TRIES):
        try:
            return Server((host, p), Handler)
        except OSError:
            continue
    raise OSError(f"ports {port}-{port + PORT_TRIES - 1} are all in use; pass --port")
