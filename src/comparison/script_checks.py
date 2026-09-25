"""
Script (writing-system) check E4: wrong language on screen
(docs/test_cases_pass_fail.md §E).

SunNXT ships Tamil/Telugu/Kannada/Malayalam/Hindi builds, so a production
screen rendered in the wrong build shows chrome labels in the wrong script.
This module only *measures* which Unicode script dominates a piece of OCR
text; the caller decides which texts are chrome (never rail titles or poster
text, CLAUDE.md) and turns the result into a verdict. min_share defaults are
function defaults only; the caller should pass the value from config.

Counting rules:
- letters (unicodedata category L*) count for the script whose range holds
  them, or "other" when no range matches;
- combining marks (M*, e.g. Tamil vowel signs and virama) count for the
  script of the preceding counted letter;
- digits, punctuation, whitespace and symbols (₹, ©, ...) are ignored.

Stdlib only.
"""

import unicodedata

SCRIPTS: dict[str, list[tuple[int, int]]] = {
    "Latin": [(0x41, 0x5A), (0x61, 0x7A), (0xC0, 0x17F)],
    "Devanagari": [(0x900, 0x97F)],
    "Bengali": [(0x980, 0x9FF)],
    "Gurmukhi": [(0xA00, 0xA7F)],
    "Gujarati": [(0xA80, 0xAFF)],
    "Oriya": [(0xB00, 0xB7F)],
    "Tamil": [(0xB80, 0xBFF)],
    "Telugu": [(0xC00, 0xC7F)],
    "Kannada": [(0xC80, 0xCFF)],
    "Malayalam": [(0xD00, 0xD7F)],
    "CJK": [(0x3040, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF),
            (0xAC00, 0xD7AF), (0xF900, 0xFAFF)],
    "Arabic": [(0x600, 0x6FF), (0x750, 0x77F)],
}


def _script_of(ch: str) -> str:
    cp = ord(ch)
    for name, ranges in SCRIPTS.items():
        if any(lo <= cp <= hi for lo, hi in ranges):
            return name
    return "other"


def _script_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    prev: str | None = None
    for ch in text or "":
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            prev = _script_of(ch)
            counts[prev] = counts.get(prev, 0) + 1
        elif cat.startswith("M"):
            if prev is not None:  # mark attaches to the preceding letter's script
                counts[prev] += 1
        else:
            prev = None
    return counts


def _dominant(counts: dict[str, int]) -> tuple[str | None, float]:
    total = sum(counts.values())
    if not total:
        return None, 0.0
    script = max(counts, key=counts.get)
    return script, counts[script] / total


def dominant_script(text: str) -> tuple[str | None, float]:
    """(script, share of counted characters), or (None, 0.0) if nothing counts."""
    return _dominant(_script_counts(text))


def screen_script(texts, min_share: float = 0.6) -> tuple[str | None, float, dict]:
    """Dominant script over many strings, weighted by counted characters.

    Returns (script, share, per-script counts); script is None when nothing
    counts or the top script's share is below min_share.
    """
    counts: dict[str, int] = {}
    for t in texts:
        for k, v in _script_counts(t).items():
            counts[k] = counts.get(k, 0) + v
    script, share = _dominant(counts)
    if share < min_share:
        script = None
    return script, share, counts


def scripts_differ(a: str, b: str, min_share: float = 0.6) -> bool:
    """True only when both texts have a confident dominant script and they differ."""
    sa, pa = dominant_script(a)
    sb, pb = dominant_script(b)
    return sa is not None and sb is not None and pa >= min_share and pb >= min_share and sa != sb
