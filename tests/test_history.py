import json

from src.reporting.history import diff, find_previous


def _f(type_, client_id, **details):
    return {"type": type_, "client_id": client_id, "production_id": "p", "text": None, "details": details}


def test_new_fixed_still_open():
    previous = {"findings": [
        _f("TEXT_DIFFERENCE", "c1", production_text="Home"),
        _f("COLOR_DIFFERENCE", "c2", production_rgb=[201, 10, 10]),
        _f("POSITION_DIFFERENCE", "c3", production_center=[10, 10], client_center=[5, 10]),
        _f("MISSING_ELEMENT", "c4"),
    ]}
    current = {"findings": [
        _f("TEXT_DIFFERENCE", "c1", production_text="Hom"),  # text changed: new + fixed
        _f("COLOR_DIFFERENCE", "c2", production_rgb=[199, 12, 9]),  # same rounded rgb: still open
        _f("POSITION_DIFFERENCE", "c3", production_center=[30, 10], client_center=[5, 10]),  # same side
        _f("MISSING_ELEMENT", "c5"),  # another element: new
    ]}
    result = diff(previous, current)
    ids = lambda key: [(f["type"], f["client_id"]) for f in result[key]]  # noqa: E731
    assert ids("new") == [("TEXT_DIFFERENCE", "c1"), ("MISSING_ELEMENT", "c5")]
    assert ids("fixed") == [("TEXT_DIFFERENCE", "c1"), ("MISSING_ELEMENT", "c4")]
    assert ids("still_open") == [("COLOR_DIFFERENCE", "c2"), ("POSITION_DIFFERENCE", "c3")]


def test_position_flip_and_duplicates():
    previous = {"findings": [_f("GROUP_SHIFT", None, dx_px=5, dy_px=0)] * 2}
    current = {"findings": [_f("GROUP_SHIFT", None, dx_px=9, dy_px=0), _f("GROUP_SHIFT", None, dx_px=-5, dy_px=0)]}
    result = diff(previous, current)
    assert (len(result["still_open"]), len(result["new"]), len(result["fixed"])) == (1, 1, 1)


def test_find_previous(tmp_path):
    def run(n, rows):
        d = tmp_path / f"test{n}_shots"
        d.mkdir()
        (d / "summary.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
        for r in rows:
            (d / r["report"]).write_text("{}", encoding="utf-8")
        return d

    run(1, [{"baseline": "home/phone/default", "report": "home_report.json"}])
    run(2, [{"baseline": "home/phone/default", "report": "home_report.json", "error": "boom"}])
    current = run(3, [{"baseline": "home/phone/default", "report": "home_report.json"}])
    assert find_previous(tmp_path, "home/phone/default", current) == tmp_path / "test1_shots" / "home_report.json"
    assert find_previous(tmp_path, "home/phone/default", 4).parent.name == "test3_shots"
    assert find_previous(tmp_path, "search/phone/default", current) is None
    assert find_previous(tmp_path, "home/phone/default", 1) is None
