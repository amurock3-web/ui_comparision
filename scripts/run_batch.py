"""Compare a folder of production screenshots against stored client baselines
(scripts.add_baseline), one at a time. ~45 s per screenshot (detector + OCR on
the production side only).

    python -m scripts.run_batch <folder> [--baseline-by filename|screen-id]
    python -m scripts.run_batch <folder> --resume output/batch/testN_<name>

--baseline-by filename (default): the file stem is the baseline screen id
    (home.png -> baselines/home/...).
--baseline-by screen-id: the longest stored screen id the stem starts with
    (home_2026-09-25.png -> baselines/home/...).
A screen with several device/language baselines is narrowed by the
screenshot's device (aspect ratio); still ambiguous is an error row.

Output in output/batch/testN_<folder name>/ (never overwrites an earlier run):
  <stem>_report.json/.html/.png, <stem>_comparison.json, <stem>_production_fused.json
  summary.json, summary.html   one row per screenshot, rewritten after every item
Resumable: --resume skips items whose report already exists and reuses a saved
production_fused.json (no OCR). A failing item becomes an error row; the batch goes on.
"""
import argparse
import html
import json
import traceback
from datetime import datetime
from pathlib import Path

from PIL import Image

from scripts._test_utils import next_test_number
from src.baselines import ROOT as BASELINE_ROOT, infer_device, list_baselines, load_baseline
from src.reporting.history import diff, find_previous
from src.schema.ui_element import UIDocument

OUT_ROOT = Path("output/batch")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def compare_item(image: Path, baseline, run_dir: Path, prefix: str) -> dict:
    """Production screenshot vs stored baseline -> report dict (files in run_dir)."""
    from src.pipeline import build_document, compare_documents  # paddleocr import

    fused = run_dir / f"{prefix}_production_fused.json"
    if fused.is_file():
        doc = UIDocument.model_validate_json(fused.read_text(encoding="utf-8"))
    else:
        doc, _ = build_document(image, image.stem, "production")
        doc.save_json(fused)
    return compare_documents(doc, baseline.doc, image, baseline.image, run_dir, prefix)["report"]


def screen_for(stem: str, by: str, screens) -> str:
    if by == "filename":
        return stem
    found = max((s for s in screens if stem.startswith(s)), key=len, default=None)
    if found is None:
        raise LookupError(f"no baseline screen id is a prefix of {stem!r}")
    return found


def write_summary(run_dir: Path, info: dict, rows: list):
    (run_dir / "summary.json").write_text(json.dumps({**info, "rows": rows}, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    cells = []
    for r in rows:
        link = f'<a href="{html.escape(r["html"])}">report</a>' if r.get("html") else ""
        history = f'{r["new"]} / {r["fixed"]}' if "new" in r else ""
        values = [r["file"], r.get("baseline") or "", r.get("verdict") or "ERROR",
                  "" if r.get("similarity") is None else f'{r["similarity"]}%',
                  "" if r.get("issues") is None else r["issues"], history]
        cells.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in values)
                     + f"<td>{link}{html.escape(r.get('error', ''))}</td></tr>")
    (run_dir / "summary.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Batch summary</title>"
        "<style>body{font-family:sans-serif;margin:16px}td,th{border:1px solid #ccc;padding:4px 8px}"
        "table{border-collapse:collapse}</style>"
        f"<h1>{html.escape(run_dir.name)}</h1><p>{html.escape(info['folder'])} - {len(rows)} screenshots</p>"
        "<table><tr><th>File</th><th>Baseline</th><th>Verdict</th><th>Similarity</th><th>Issues</th>"
        "<th>New / fixed</th><th>Report</th></tr>" + "".join(cells) + "</table>",
        encoding="utf-8")


def run_batch(folder, by="filename", resume=None, out_root=OUT_ROOT, baseline_root=BASELINE_ROOT) -> Path:
    folder, out_root = Path(folder), Path(out_root)
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if resume:
        run_dir = Path(resume)
    else:
        out_root.mkdir(parents=True, exist_ok=True)
        run_dir = out_root / f"test{next_test_number(out_root)}_{folder.name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    screens = {row["key"].split("/")[0] for row in list_baselines(baseline_root)}
    info = {"folder": str(folder), "baseline_by": by, "updated": datetime.now().isoformat(timespec="seconds")}

    rows = []
    for i, image in enumerate(images, 1):
        prefix = image.stem
        report_path = run_dir / f"{prefix}_report.json"
        row = {"file": image.name}
        try:
            with Image.open(image) as im:
                device = infer_device(*im.size)
            done = report_path.is_file()
            # A finished item only needs the key, even if its baseline went stale since.
            baseline = load_baseline(screen_for(image.stem, by, screens), baseline_root,
                                     device=device, allow_stale=done)
            row.update(screen=baseline.meta.get("screen_id"), baseline=baseline.key)
            report = (json.loads(report_path.read_text(encoding="utf-8")) if done
                      else compare_item(image, baseline, run_dir, prefix))
            findings = report.get("findings", [])
            row.update(verdict=report.get("verdict"), similarity=report.get("similarity_percent"),
                       issues=(report.get("summary") or {}).get("issues", len(findings)),
                       report=report_path.name, html=f"{prefix}_report.html", resumed=done)
            previous = find_previous(out_root, baseline.key, run_dir)
            if previous:
                changes = diff(json.loads(previous.read_text(encoding="utf-8")), report)
                row.update(previous=str(previous), new=len(changes["new"]), fixed=len(changes["fixed"]))
        except Exception as e:  # one bad item never stops the batch
            row["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        rows.append(row)
        write_summary(run_dir, info, rows)
        print(f"[{i}/{len(images)}] {image.name}: {row.get('error') or row['verdict']}"
              + (" (resumed)" if row.get("resumed") else ""))
    return run_dir


def main():
    parser = argparse.ArgumentParser(description="Compare a folder of production screenshots with baselines.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--baseline-by", choices=["filename", "screen-id"], default="filename")
    parser.add_argument("--resume", type=Path, help="an earlier output/batch/testN_* run to continue")
    args = parser.parse_args()
    run_dir = run_batch(args.folder, args.baseline_by, args.resume)
    print(f"\nSummary: {run_dir / 'summary.html'}")


if __name__ == "__main__":
    main()
