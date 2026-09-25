"""
Strip OCR-misread icon glyphs from the ends of a UI label.

Why: PaddleOCR reads small UI icons as characters and glues them onto the
neighbouring label — the language icon on a tab becomes "9 Languages", the
mic icon in the search bar becomes "Search Movies, TV shows, Live TV... 0".
Two captures of the same screen then disagree on text purely because of an
icon. Fused JSONs keep only the final label string (no per-token boxes or
confidence), so the rule works on the text alone.

Rule: split on whitespace and repeatedly drop the first or last token while
it is a standalone glyph — at most `max_len` characters, no letters (only
digits and/or symbols), not a protected badge ("4K", "U/A", "13+" ...) —
and at least one other token remains. Middle tokens are never dropped and a
label is never emptied.

CALLERS MUST APPLY THIS TO BOTH SIDES before comparing. The module cannot
tell an icon from a real number: "Season 2" becomes "Season" on both sides,
so identical labels still compare equal. Known limit: "Season 2" vs
"Season 3" also compares equal after cleanup. Pass keep_numeric_suffix=True
where trailing numbers matter; it never drops a trailing all-digit token.

Pure stdlib; thresholds are arguments, nothing here reads config.
"""
from __future__ import annotations

import unicodedata

DEFAULT_PROTECT = ("4K", "HD", "UHD", "U/A", "UA", "A", "U", "S",
                   "18+", "16+", "13+", "7+", "+")


def _has_letter(token: str) -> bool:
    # L* = letters, M* = combining marks (Tamil/Devanagari vowel signs).
    return any(unicodedata.category(ch)[0] in "LM" for ch in token)


def _is_glyph(token: str, max_len: int, protect: set[str]) -> bool:
    return (len(token) <= max_len and not _has_letter(token)
            and token.casefold() not in protect)


def clean_label(text: str | None, max_len: int = 2,
                protect: tuple[str, ...] = DEFAULT_PROTECT,
                keep_numeric_suffix: bool = False) -> tuple[str, list[str]]:
    """Return (cleaned label, dropped tokens in the order they appeared)."""
    tokens = (text or "").split()
    prot = {p.casefold() for p in protect}
    head: list[str] = []
    tail: list[str] = []
    while len(tokens) > 1:
        if _is_glyph(tokens[0], max_len, prot):
            head.append(tokens.pop(0))
        elif (_is_glyph(tokens[-1], max_len, prot)
              and not (keep_numeric_suffix and tokens[-1].isdigit())):
            tail.insert(0, tokens.pop())
        else:
            break
    return " ".join(tokens), head + tail
