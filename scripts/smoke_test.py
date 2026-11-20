"""Install check in seconds: no OCR, no detector, no Edge.

Re-runs matcher -> differ -> report (scripts/rematch.py) on the first real pair
in input/benchmark/real/ that has cached fused JSONs:
  A  production vs client: completes, writes HTML + JSON, verdict PASS/REVIEW/FAIL
     (manifest's expected verdict is printed as INFO only - known to differ, test24)
  B  client vs itself: verdict must be PASS

    python -m scripts.smoke_test

Output: output/smoke/testN_smoke/{real,self}/ (rematch's own files + rematch.log).
"""
import contextlib
import json
import sys
import time
from pathlib import Path

from scripts import _test_utils  # noqa: F401  UTF-8 console
from scripts import rematch
from scripts._test_utils import next_test_number

REAL_DIR = Path("input/benchmark/real")
SMOKE_DIR = Path("output/smoke")


def run_rematch(prod_json, client_json, prod_image, client_image, out_dir: Path) -> dict:
    """scripts.rematch.main into out_dir, its console chatter into rematch.log."""
    out_dir.mkdir(parents=True)
    rematch.OUTPUT_DIR = out_dir
    sys.argv = ["rematch", str(prod_json), str(client_json),
                "--production-image", str(prod_image), "--client-image", str(client_image)]
    with open(out_dir / "rematch.log", "w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
        rematch.main()
    report_json = next(out_dir.glob("*_report.json"))
    if not next(out_dir.glob("*_report.html"), None):
        raise RuntimeError(f"no HTML report in {out_dir}")
    return json.loads(report_json.read_text(encoding="utf-8"))


def main() -> int:
    start = time.time()
    pair = next((d for d in sorted(REAL_DIR.glob("*")) if (d / "client_fused.json").is_file()
                 and (d / "production_fused.json").is_file()), None)
    if pair is None:
        print("SMOKE TEST: FAIL (input/benchmark/real/<pair>/ needs client_fused.json and production_fused.json)")
        return 1
    image = lambda side: next(p for p in pair.glob(f"{side}.*") if p.suffix.lower() in rematch.IMAGE_EXTS)
    prod_json, client_json = pair / "production_fused.json", pair / "client_fused.json"
    out = SMOKE_DIR / f"test{next_test_number(SMOKE_DIR)}_smoke"
    print(f"Pair: {pair}   output: {out}")
    failures = []

    try:
        report = run_rematch(prod_json, client_json, image("production"), image("client"), out / "real")
        expected = json.loads((pair / "manifest.json").read_text(encoding="utf-8")).get("expected_verdict")
        ok = report["verdict"] in ("PASS", "REVIEW", "FAIL")
        print(f"[{'PASS' if ok else 'FAIL'}] A real pair: verdict {report['verdict']}, "
              f"{len(report['findings'])} findings (INFO: manifest expects {expected})")
        if not ok:
            failures.append(f"real pair verdict {report['verdict']!r}")
    except Exception as e:  # any crash in the stack is exactly what this test is for
        print(f"[FAIL] A real pair: {type(e).__name__}: {e}")
        failures.append("real pair crashed")

    try:
        report = run_rematch(client_json, client_json, image("client"), image("client"), out / "self")
        ok = report["verdict"] == "PASS"
        print(f"[{'PASS' if ok else 'FAIL'}] B self-compare: verdict {report['verdict']}, "
              f"{len(report['findings'])} findings")
        for f in report["findings"] if not ok else []:
            print(f"    {f['spec_id']} {f['verdict']} {f['type']} {f['class']} {f['text']!r} {f['details']}")
        if not ok:
            failures.append(f"self-compare gave {report['verdict']}")
    except Exception as e:
        print(f"[FAIL] B self-compare: {type(e).__name__}: {e}")
        failures.append("self-compare crashed")

    print(f"({time.time() - start:.1f} s)")
    print("SMOKE TEST: PASS" if not failures else f"SMOKE TEST: FAIL ({'; '.join(failures)})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
