"""
Drag-and-drop comparison UI: drop a production and a client screenshot,
press Compare, watch the stages, read the report, download it as PDF.

    python -m src.app            # opens http://127.0.0.1:8765

Standard library only. Listens on 127.0.0.1 so screenshots never leave the
machine (rules.md §2). Runs the same chain as scripts/run_comparison.py;
each run is kept in output/app/<run>/ (inputs, report.json/.html/.png/.pdf).
The PDF is the HTML report printed by headless Microsoft Edge, which ships
with Windows 11; without Edge the page falls back to the browser's print.
"""

import base64
import json
import re
import shutil
import subprocess
import tempfile
import threading
import traceback
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.pipeline import build_document
from src.reporting.html_report import write_html_report
from src.reporting.report import ReportGenerator

HOST, PORT = "127.0.0.1", 8765
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "output" / "app"
STAGES = [f"{step} ({side})" for side in ("production", "client")
          for step in ("Detector", "OCR", "Fusion", "Graph")] + ["Matching", "Report", "PDF"]
EDGE_PATHS = [shutil.which("msedge"),
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

# ponytail: one comparison at a time (models are loaded once and OCR is CPU-bound anyway);
# a queue only if several people share one machine.
state = {"run": None, "stage": None, "step": 0, "total": len(STAGES), "done": False,
         "error": None, "summary": None, "pdf": False}
lock = threading.Lock()


def screen_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", Path(name).stem) or "screen"


def to_pdf(html_path: Path) -> bool:
    edge = next((p for p in EDGE_PATHS if p and Path(p).is_file()), None)
    if not edge:
        return False
    pdf = html_path.with_suffix(".pdf")
    with tempfile.TemporaryDirectory() as profile:  # own profile, so a running Edge doesn't interfere
        subprocess.run([edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}", f"--print-to-pdf={pdf}", html_path.as_uri()],
                       capture_output=True, timeout=120)
    return pdf.is_file()


def headline(report: dict) -> str:
    """The one line above the report: how many of the comparable elements paired
    up, and where the rest went. Counts live in report["summary"]; .get keeps an
    older report.json (or a field that moves back to the top level) from
    crashing the page."""
    s = report.get("summary", {})

    def n(key):
        return s.get(key, report.get(key, 0))

    matched, missing, extra = n("matched_pairs"), n("missing"), n("extra")
    return (f"Matched {matched} of {matched + missing + extra} elements "
            f"({n('similarity_percent')}%) · clean {n('clean_pairs')} · "
            f"missing {missing} · extra {extra} · ignored {n('ignored')}")


def run_comparison(run_dir: Path, prod_path: Path, client_path: Path):
    def stage(name):
        state.update(stage=name, step=STAGES.index(name) + 1)

    try:
        prod_doc, prod_graph = build_document(prod_path, screen_id(prod_path.name), "production", stage)
        client_doc, client_graph = build_document(client_path, screen_id(client_path.name), "client", stage)
        # Saved before matching: scripts.rematch reloads these to redo matching,
        # differ and report without paying the ~90s detector + OCR pass again.
        prod_doc.save_json(run_dir / "production_fused.json")
        client_doc.save_json(run_dir / "client_fused.json")
        stage("Matching")
        match = ElementMatcher().match(prod_doc, client_doc, prod_graph, client_graph)
        differences = DifferenceEngine().compare(prod_doc, client_doc, prod_graph, client_graph, match)
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
        traceback.print_exc()
        state["error"] = f"{type(e).__name__}: {e}"
    finally:
        state["done"] = True
        lock.release()


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
        if self.path == "/":
            return self._send(PAGE, "text/html; charset=utf-8")
        if self.path == "/status":
            return self._send(state)
        m = re.fullmatch(r"/run/(\d{8}_\d{6})/(report\.(?:html|pdf|png))", self.path)
        if m and (RUNS_DIR / m[1] / m[2]).is_file():
            ctype = {"html": "text/html; charset=utf-8", "pdf": "application/pdf",
                     "png": "image/png"}[m[2].rsplit(".", 1)[1]]
            return self._send((RUNS_DIR / m[1] / m[2]).read_bytes(), ctype)
        self._send({"error": "not found"}, code=404)

    def do_POST(self):
        if self.path != "/compare":
            return self._send({"error": "not found"}, code=404)
        body = self.rfile.read(int(self.headers["Content-Length"]))  # read first: an unread body aborts the reply
        if not lock.acquire(blocking=False):
            return self._send({"error": "A comparison is already running."}, code=409)
        try:
            data = json.loads(body)
            run = datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir = RUNS_DIR / run
            run_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for side in ("production", "client"):
                name = data[side]["name"]
                ext = Path(name).suffix.lower()
                if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
                    raise ValueError(f"{side}: {name} is not an image")
                path = run_dir / f"{side}_{screen_id(name)}{ext}"
                path.write_bytes(base64.b64decode(data[side]["data"].split(",", 1)[1]))
                paths.append(path)
        except Exception as e:
            lock.release()
            return self._send({"error": f"Bad upload: {e}"}, code=400)
        state.update(run=run, stage=STAGES[0], step=0, done=False, error=None, summary=None, pdf=False)
        threading.Thread(target=run_comparison, args=(run_dir, *paths), daemon=True).start()
        self._send({"run": run})

    def log_message(self, *args):  # keep the console for pipeline output
        pass


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>UI Comparison</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--muted:#667085;--line:#d0d5dd;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--card:#1b2029;--fg:#e6e8ec;--muted:#98a2b3;--line:#344054;--accent:#7c95ff}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}.muted{color:var(--muted)}
.drops{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:20px 0}
.drop{border:2px dashed var(--line);border-radius:12px;background:var(--card);min-height:260px;display:flex;
 flex-direction:column;align-items:center;justify-content:center;cursor:pointer;padding:12px;text-align:center}
.drop.over{border-color:var(--accent)}.drop img{max-height:320px;max-width:100%;border-radius:6px;margin-top:8px}
.drop b{font-size:17px}
button,a.btn{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 22px;font-size:15px;
 cursor:pointer;text-decoration:none;display:inline-block}
button:disabled{opacity:.4;cursor:default}
.bar{height:14px;background:var(--line);border-radius:7px;overflow:hidden;margin:10px 0}
.bar div{height:100%;width:0;background:var(--accent);transition:width .4s}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px}
.stat b{display:block;font-size:22px}
.verdict{color:#fff;border-radius:6px;padding:4px 12px;font-weight:700}
.error{color:#dc2626;white-space:pre-wrap}
iframe{width:100%;height:80vh;border:1px solid var(--line);border-radius:10px;background:#fff;margin-top:12px}
@media (max-width:640px){.drops{grid-template-columns:1fr}}
</style></head><body><main>
<h1>UI Comparison</h1>
<div class="muted">Drop the production screenshot and the client design, then press Compare. Everything stays on this machine.</div>
<div class="drops">
 <label class="drop" id="drop-production"><b>Production</b><span class="muted">drop image or click to browse</span>
  <input type="file" accept="image/*" hidden></label>
 <label class="drop" id="drop-client"><b>Client design</b><span class="muted">drop image or click to browse</span>
  <input type="file" accept="image/*" hidden></label>
</div>
<button id="go" disabled>Compare</button>
<section id="progress" hidden><div class="bar"><div id="fill"></div></div><div id="stage" class="muted"></div></section>
<section id="result" hidden></section>
<script>
const files = {};
const VERDICT = {PASS:"#1f9d55", REVIEW:"#d97706", FAIL:"#dc2626"};
for (const side of ["production", "client"]) {
  const zone = document.getElementById("drop-" + side), input = zone.querySelector("input");
  const take = f => {
    if (!f || !f.type.startsWith("image/")) return;
    const r = new FileReader();
    r.onload = () => {
      files[side] = {name: f.name, data: r.result};
      zone.querySelectorAll("img,.muted").forEach(e => e.remove());
      const img = document.createElement("img"); img.src = r.result; zone.append(img);
      const n = document.createElement("span"); n.className = "muted"; n.textContent = f.name; zone.append(n);
      document.getElementById("go").disabled = !(files.production && files.client);
    };
    r.readAsDataURL(f);
  };
  input.onchange = () => take(input.files[0]);
  zone.ondragover = e => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = e => { e.preventDefault(); zone.classList.remove("over"); take(e.dataTransfer.files[0]); };
}
document.getElementById("go").onclick = async () => {
  const go = document.getElementById("go"); go.disabled = true;
  document.getElementById("result").hidden = true;
  document.getElementById("progress").hidden = false;
  const r = await fetch("/compare", {method: "POST", body: JSON.stringify(files)});
  const j = await r.json();
  if (!r.ok) { showError(j.error); go.disabled = false; return; }
  poll();
};
function showError(msg) {
  const res = document.getElementById("result"); res.hidden = false;
  res.innerHTML = ""; const p = document.createElement("p"); p.className = "error"; p.textContent = msg; res.append(p);
}
async function poll() {
  const s = await (await fetch("/status")).json();
  document.getElementById("fill").style.width = (100 * s.step / s.total) + "%";
  document.getElementById("stage").textContent = s.done ? "Done" : `Step ${s.step} of ${s.total}: ${s.stage}...`;
  if (!s.done) return setTimeout(poll, 1000);
  document.getElementById("go").disabled = false;
  if (s.error) return showError(s.error);
  const m = s.summary;
  const base = "/run/" + s.run + "/report";
  const res = document.getElementById("result"); res.hidden = false;
  res.innerHTML = `<h2><span class="verdict" style="background:${VERDICT[m.verdict]}">${m.verdict}</span></h2>
   <div>${m.headline}</div>
   <div class="stats"><div class="stat"><b>${m.findings}</b>findings</div></div>
   ${s.pdf ? `<a class="btn" href="${base}.pdf" download="report_${s.run}.pdf">Download PDF</a>`
           : `<button onclick="document.querySelector('iframe').contentWindow.print()">Save as PDF</button>`}
   <iframe src="${base}.html"></iframe>`;
}
</script></main></body></html>"""


def main():
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"UI Comparison running at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
