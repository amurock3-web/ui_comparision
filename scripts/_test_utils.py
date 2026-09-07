import re
from pathlib import Path


def next_test_number(output_dir: Path) -> int:
    """Highest existing "testN_..." file's N in output_dir, plus 1. Starts at 1.
    Lets every run_*_test.py script number its own runs without clobbering
    previous trial-and-error output in the same folder."""
    existing = [int(m.group(1)) for f in output_dir.glob("test*_*") if (m := re.match(r"test(\d+)_", f.name))]
    return max(existing, default=0) + 1
