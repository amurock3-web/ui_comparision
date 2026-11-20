from scripts.check_setup import parse_sums


def test_parse_sums_binary_and_text_mode():
    text = "AB12 *paddlex/a/inference.json\ncd34  ui16_v1/best.pt\n\n"
    assert parse_sums(text) == {"paddlex/a/inference.json": "ab12", "ui16_v1/best.pt": "cd34"}
