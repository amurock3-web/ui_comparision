"""
Drag-and-drop comparison UI: drop a production and a client screenshot,
press Compare, watch the stages, read the report, download it as PDF.
History lists every earlier run; Help explains the verdicts.

    python -m src.app            # opens http://127.0.0.1:8765 (or the next free port)
    python -m src.app --port 8800 --no-browser

Standard library only. Listens on 127.0.0.1 so screenshots never leave the
machine (rules.md §2). Runs the same chain as scripts/run_comparison.py;
each run is kept in output/app/<run>/ (inputs, report.json/.html/.png/.pdf).
The PDF is the HTML report printed by headless Microsoft Edge, which ships
with Windows 11; without Edge the page falls back to the browser's print.
GET /health runs src/health.py's checks; a failed required check disables Compare.
The pipeline is imported on the first comparison, so the page (and /health)
still comes up when paddleocr or the detector is broken.
"""

import argparse
import webbrowser

from src.app.server import HOST, PORT, PORT_TRIES, RUNS_DIR, bind_server
from src.health import run_checks


def main():
    ap = argparse.ArgumentParser(prog="python -m src.app", description="Drag-and-drop UI comparison on http://127.0.0.1 (localhost only).")
    ap.add_argument("--port", type=int, default=PORT, help=f"first port to try (default {PORT}; "
                    f"if taken, the next {PORT_TRIES - 1} are tried)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = ap.parse_args()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    server = bind_server(args.port)
    url = f"http://{HOST}:{server.server_address[1]}"
    print(f"UI Comparison running at {url}  (Ctrl+C to stop)")
    for c in run_checks():
        if not c["ok"]:
            print(f"  health: {c['name']} FAILED - {c['message']}  (fix: {c['fix']})")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
