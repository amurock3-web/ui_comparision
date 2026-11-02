# Tests for 18.3: a FAIL on a low-confidence element is REVIEW at most (P7). A 200 px move
# on 1080x2340 is 7.8% of the diagonal, so C1 gives FAIL Major before the cap.

from PIL import Image
import yaml

from src.comparison.differ import DifferenceEngine, Difference
from src.comparison.matcher import DEFAULT_CONFIG_PATH, ElementMatcher
from src.reporting.html_report import write_html_report
from src.reporting.report import ReportGenerator
from src.schema.ui_element import UIDocument, UIElement
from tests.test_group_shift import _graph

W, H = 1080, 2340


def _config(tmp_path, enabled=True, tiers=("low",)):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["comparison"]["low_confidence_cap"] = {"enabled": enabled, "tiers": list(tiers)}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _el(y, tier, confidence):
    x, w, h = 100, 200, 40
    return UIElement(
        id="b", **{"class": "tab_item"}, text="Movies",
        bbox=[x, y, w, h],
        normalized_bbox=[x / W, y / H, w / W, h / H],
        center=[x + w / 2, y + h / 2],
        confidence=confidence, confidence_tier=tier, source="detector",
    )


def _docs(prod_tier="high", client_tier="high"):
    conf = {"high": 0.9, "medium": 0.5, "low": 0.3}
    return (UIDocument(screen_id="ss_test", source="production", image_width=W, image_height=H,
                       elements=[_el(1400, prod_tier, conf[prod_tier])]),
            UIDocument(screen_id="ss_test", source="client", image_width=W, image_height=H,
                       elements=[_el(1200, client_tier, conf[client_tier])]))


def _c1(config_path, prod, client, graph=None):
    graph = graph or _graph({"grp": ["b"]})
    result = ElementMatcher(config_path).match(prod, client, graph, graph)
    differences = DifferenceEngine(config_path).compare(prod, client, graph, graph, result)
    return next(d for d in differences if d.type == "POSITION_DIFFERENCE"), differences


def test_low_tier_on_either_side_caps_fail_to_review_and_keeps_severity(tmp_path):
    config = _config(tmp_path)
    for tiers, side in ((("high", "low"), "client"), (("low", "high"), "production"),
                        (("low", "low"), "both")):
        d, _ = _c1(config, *_docs(*tiers))
        assert (d.verdict, d.severity) == ("REVIEW", "Major")
        assert d.details["capped"] == {"reason": "low_confidence", "side": side, "confidence": 0.3,
                                       "original_verdict": "FAIL", "applied": True}


def test_high_and_medium_tiers_stay_fail(tmp_path):
    for tiers in (("high", "high"), ("medium", "medium")):
        d, _ = _c1(_config(tmp_path), *_docs(*tiers))
        assert (d.verdict, d.severity) == ("FAIL", "Major") and "capped" not in d.details


def test_screen_verdict_follows_the_cap(tmp_path):
    config = _config(tmp_path)
    prod, client = _docs(client_tier="low")
    _, differences = _c1(config, prod, client)
    assert ReportGenerator(config).generate(prod, client, differences)["verdict"] == "REVIEW"


def test_finding_without_an_element_is_never_capped(tmp_path):
    engine = DifferenceEngine(_config(tmp_path))
    for type_, severity in (("ORIENTATION_DIFFERENCE", "Critical"), ("SCALING_DIFFERENCE", "Major")):
        d = Difference(type_, None, None, {}, "FAIL", severity)
        assert engine._cap_low_confidence([d], {}, {}) == [d]
        assert d.verdict == "FAIL" and "capped" not in d.details


def test_dry_run_keeps_the_verdict_and_records_the_cap(tmp_path):
    d, _ = _c1(_config(tmp_path, enabled=False), *_docs(client_tier="low"))
    assert (d.verdict, d.severity) == ("FAIL", "Major")
    assert d.details["capped"]["applied"] is False


def test_no_config_key_adds_nothing(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    del cfg["comparison"]["low_confidence_cap"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    d, _ = _c1(path, *_docs(client_tier="low"))
    assert d.verdict == "FAIL" and "capped" not in d.details


def test_cut_off_cap_is_not_overwritten(tmp_path):
    graph = _graph({"grp": ["b"]})
    graph.nodes["b"]["clipped"] = True
    d, _ = _c1(_config(tmp_path), *_docs(client_tier="low"), graph)
    assert (d.verdict, d.severity) == ("REVIEW", None)
    assert d.details["capped"] == "element is cut off"


def _html(tmp_path, config, prod, client, graph=None):
    graph = graph or _graph({"grp": ["b"]})
    _, differences = _c1(config, prod, client, graph)
    for name in ("p.png", "c.png"):
        Image.new("RGB", (W, H), "white").save(tmp_path / name)
    report = ReportGenerator(config).generate(prod, client, differences)
    path = write_html_report(report, tmp_path / "p.png", tmp_path / "c.png", prod, client,
                             differences, tmp_path / "report.html", graph, graph)
    return path.read_text(encoding="utf-8")


def test_html_labels_an_applied_cap(tmp_path):
    page = _html(tmp_path, _config(tmp_path), *_docs(client_tier="low"))
    assert ">REVIEW</span> (capped: low confidence) &middot; Major" in page
    assert "element is cut off" not in page


def test_html_says_nothing_for_a_dry_run(tmp_path):
    page = _html(tmp_path, _config(tmp_path, enabled=False), *_docs(client_tier="low"))
    assert "capped: low confidence" not in page and "Capped to REVIEW" not in page


def test_html_shows_a_cut_off_element_as_before(tmp_path):
    graph = _graph({"grp": ["b"]})
    graph.nodes["b"]["clipped"] = True
    page = _html(tmp_path, _config(tmp_path), *_docs(), graph)
    assert " Capped to REVIEW (was FAIL Major): element is cut off." in page
    assert "capped: low confidence" not in page
