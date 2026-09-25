import pytest

from src.comparison.text_cleanup import clean_label

CASES = [
    ("9 Languages", ("Languages", ["9"])),
    ("Search Movies, TV shows, Live TV... 0",
     ("Search Movies, TV shows, Live TV...", ["0"])),
    ("4K", ("4K", [])),
    ("U/A 13+", ("U/A 13+", [])),
    ("Season 2", ("Season", ["2"])),
    ("→ Home", ("Home", ["→"])),
    ("SUN NT Home", ("SUN NT Home", [])),
    ("", ("", [])),
    (None, ("", [])),
    ("0", ("0", [])),
    ("9 Languages 0", ("Languages", ["9", "0"])),
    ("தமிழ் 2", ("தமிழ்", ["2"])),
    ("தமிழ்", ("தமிழ்", [])),
    ("Movies 4K", ("Movies 4K", [])),
    ("hd Movies 18+", ("hd Movies 18+", [])),
    ("Top 10 Shows", ("Top 10 Shows", [])),   # middle tokens survive
    ("0 9", ("9", ["0"])),                      # never empties
    ("Home 123", ("Home 123", [])),             # longer than max_len
]


@pytest.mark.parametrize("text,expected", CASES)
def test_clean_label(text, expected):
    assert clean_label(text) == expected


@pytest.mark.parametrize("text,_", CASES)
def test_idempotent(text, _):
    once = clean_label(text)[0]
    assert clean_label(once)[0] == once


def test_keep_numeric_suffix():
    assert clean_label("Season 2", keep_numeric_suffix=True) == ("Season 2", [])
    assert clean_label("9 Languages", keep_numeric_suffix=True) == ("Languages", ["9"])


def test_both_sides_compare_equal():
    assert clean_label("Season 2")[0] == clean_label("Season 2")[0]
    # Known limit: different numbers collapse together.
    assert clean_label("Season 2")[0] == clean_label("Season 3")[0]


def test_custom_protect_and_max_len():
    assert clean_label("9 Languages", protect=("9",)) == ("9 Languages", [])
    assert clean_label("Home 123", max_len=3) == ("Home", ["123"])
