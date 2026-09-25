from src.comparison.script_checks import dominant_script, screen_script, scripts_differ


def test_latin():
    assert dominant_script("Movies") == ("Latin", 1.0)


def test_tamil_combining_marks_count():
    assert dominant_script("திரைப்படங்கள்") == ("Tamil", 1.0)


def test_devanagari():
    assert dominant_script("हिंदी") == ("Devanagari", 1.0)


def test_symbols_and_digits_ignored():
    assert dominant_script("₹199") == (None, 0.0)
    assert dominant_script("") == (None, 0.0)


def test_mixed_share_below_one():
    script, share = dominant_script("Movies திரை")
    assert script == "Latin" and 0.5 < share < 1.0


def test_scripts_differ():
    assert scripts_differ("Movies", "திரைப்படங்கள்")
    assert not scripts_differ("Movies", "Home")
    # "Movie திரை": Latin 5 vs Tamil 4 -> share 0.56 < 0.6, not confident
    assert not scripts_differ("Movie திரை", "திரைப்படங்கள்")


def test_screen_script_language_picker():
    script, share, counts = screen_script(
        ["Tamil", "தமிழ்", "Hindi", "हिंदी", "Telugu", "తెలుగు"])
    assert set(counts) == {"Latin", "Tamil", "Devanagari", "Telugu"}
    assert len(set(counts) - {"Latin"}) == 3
    assert counts["Latin"] == 16
    # Latin is 16 of 32 counted chars: below min_share, so no dominant script
    assert script is None and share == 0.5
