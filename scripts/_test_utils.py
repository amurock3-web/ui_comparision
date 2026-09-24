import re
import sys
from pathlib import Path

# Every scripts/run_*.py prints OCR text, and OCR on these screenshots returns
# Tamil script, ₹ and the occasional stray CJK glyph. The Windows console is
# cp1252, so an un-encodable character kills the script *after* the real work
# is done and the JSON is already saved. Done on import because all six
# scripts import this module; there is no other shared entry point.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def next_test_number(output_dir: Path) -> int:
    """Highest existing "testN_..." file's N in output_dir, plus 1. Starts at 1.
    Lets every scripts/run_*.py script number its own runs without clobbering
    previous trial-and-error output in the same folder."""
    existing = [int(m.group(1)) for f in output_dir.glob("test*_*") if (m := re.match(r"test(\d+)_", f.name))]
    return max(existing, default=0) + 1
