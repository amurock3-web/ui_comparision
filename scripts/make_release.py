"""Build the handover zip: ui_comparison_handover_<YYYYMMDD>.zip with ONE top folder ui_comparison/.

    python -m scripts.make_release [--out <folder>]      (default: the folder above the project)

Ships everything (code, config, docs, tests, .git, models, input, output, baselines, graphify-out)
except what setup rebuilds or what is junk: venvs (a copied venv points at this computer's Python),
caches, the agent worktrees and this laptop's Claude Code settings. Writes MANIFEST.txt (folder sizes,
model SHA256s) into the zip root. Takes a few minutes for ~2.5 GB.
"""
import argparse
import hashlib
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

import scripts._test_utils  # noqa: F401  UTF-8 console

ROOT = Path(__file__).resolve().parents[1]
TOP = "ui_comparison"
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_PATHS = {".claude/worktrees", ".claude/settings.json", ".claude/settings.local.json",
              "models/paddlex/func_ret", "models/paddlex/locks", "models/paddlex/temp",
              # graphify: only graph.json, GRAPH_REPORT.md, graph.html, manifest.json are used;
              # dated snapshots and cache/ are rebuilt by `graphify update .`, .graphify_python is a laptop path
              "graphify-out/cache", "graphify-out/cost.json", "graphify-out/.graphify_python"}
SKIP_SUFFIXES = {".pyc"}
STORED = {".png", ".jpg", ".jpeg", ".mp4", ".pdf", ".pt", ".zip", ".pdiparams"}  # already compressed / big binaries


def skipped(rel: str, path: Path) -> bool:
    parts = rel.split("/")
    return (parts[0].startswith(".venv") or any(p in SKIP_DIRS for p in parts)
            or any(rel == s or rel.startswith(s + "/") for s in SKIP_PATHS)
            or path.suffix in SKIP_SUFFIXES
            or (parts[0] == "graphify-out" and len(parts) > 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]))
            or (len(parts) == 1 and path.name.startswith("ui_comparison_handover_") and path.suffix == ".zip"))


def collect():
    files = []
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if path.is_file() and not path.is_symlink() and not skipped(rel, path):
            files.append((rel, path))
    return files


def manifest(files) -> str:
    sizes = {}
    for rel, path in files:
        top = rel.split("/")[0] if "/" in rel else "(root files)"
        sizes[top] = sizes.get(top, 0) + path.stat().st_size
    total = sum(sizes.values())
    lines = [f"UI Comparison handover - built {date.today().isoformat()}", f"{len(files)} files, {total / 1e6:,.0f} MB unpacked",
             "", "Folder sizes (MB):"]
    lines += [f"  {size / 1e6:>10,.1f}  {name}" for name, size in sorted(sizes.items(), key=lambda kv: -kv[1])]
    lines += ["", "Model SHA256 (also models/SHA256SUMS.txt; check with: python -m scripts.check_setup):"]
    sums = ROOT / "models" / "SHA256SUMS.txt"
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        actual = hashlib.sha256((ROOT / "models" / name).read_bytes()).hexdigest()
        lines.append(f"  {digest}  models/{name}" + ("" if actual == digest else "  <-- MISMATCH on the build machine"))
    lines += ["", "Not included (rebuilt by setup.bat / setup.sh, or junk): .venv, .venv-detector, __pycache__,",
              ".pytest_cache, *.pyc, .claude/worktrees, .claude/settings.json, models/paddlex runtime folders,",
              "graphify-out dated snapshots, cache/, cost.json and .graphify_python (rebuilt by `graphify update .`).",
              "INTERNAL ONLY: contains client screenshots and reports (SunNXT / JioHotstar)."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Build the handover zip.")
    parser.add_argument("--out", type=Path, default=ROOT.parent, help="folder for the zip (default: next to the project)")
    args = parser.parse_args()
    out = args.out.resolve() / f"ui_comparison_handover_{date.today():%Y%m%d}.zip"
    if out.exists():
        sys.exit(f"{out} already exists; move it away first (never overwrite a release)")
    if ROOT in out.parents:
        sys.exit("--out must be outside the project folder")

    files = collect()
    start = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        z.writestr(f"{TOP}/MANIFEST.txt", manifest(files))
        for i, (rel, path) in enumerate(files, 1):
            info = zipfile.ZipInfo.from_file(path, f"{TOP}/{rel}")
            info.compress_type = zipfile.ZIP_STORED if path.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
            if path.suffix == ".sh":
                info.external_attr = 0o100755 << 16  # executable after unzip on Linux
            with open(path, "rb") as src, z.open(info, "w", force_zip64=True) as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            if i % 2000 == 0:
                print(f"  {i}/{len(files)} files ...")
    print(f"{out}  {out.stat().st_size / 1e9:.2f} GB, {len(files)} files + MANIFEST.txt, {time.time() - start:.0f} s")


if __name__ == "__main__":
    main()
