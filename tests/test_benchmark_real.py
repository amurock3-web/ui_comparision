import json
from pathlib import Path

import pytest

from scripts.run_benchmark import REAL_DIR, rule_matches, score_real


def finding(spec_id, cls=None, text=None, verdict="FAIL"):
    return {"spec_id": spec_id, "class": cls, "text": text, "verdict": verdict}


def test_rule_matching():
    f = finding("D3", "tab_item", "SUN NT Home")
    assert rule_matches({"spec_id": "D3"}, f)
    assert rule_matches({"spec_id": "D3", "class": "tab_item", "text_contains": "home"}, f)
    assert not rule_matches({"spec_id": "D1"}, f)
    assert not rule_matches({"spec_id": "D3", "class": "button"}, f)
    assert not rule_matches({"spec_id": "D3", "text_contains": "Search"}, f)
    assert rule_matches({"spec_id": "D3", "verdict": "FAIL"}, f)
    assert not rule_matches({"spec_id": "D3", "verdict": "REVIEW"}, f)
    assert not rule_matches({"spec_id": "D3", "text_contains": "x"}, finding("D3"))  # text None


def test_score_real_violation_miss_unlisted():
    manifest = {"expected_verdict": "REVIEW",
                "must_not_flag": [{"spec_id": "B1", "class": "overlay_badge"}],
                "may_flag": [{"spec_id": "B9"}],
                "must_flag": [{"spec_id": "D3", "text_contains": "Search"}]}
    report = {"verdict": "FAIL", "findings": [finding("B1", "overlay_badge"),
                                              finding("B9", "content_card", verdict="REVIEW"),
                                              finding("C1", "title", "Top 10")]}
    s = score_real(manifest, report)
    assert not s["verdict_ok"]
    assert [f["spec_id"] for f in s["violations"]] == ["B1"]
    assert s["misses"] == [{"spec_id": "D3", "text_contains": "Search"}]
    assert [f["spec_id"] for f in s["unlisted"]] == ["C1"]


def test_trending_search_manifest_loads():
    path = Path(REAL_DIR) / "trending_search" / "manifest.json"
    if not path.is_file():
        pytest.skip("input/ is gitignored; benchmark pair not present")
    m = json.loads(path.read_text(encoding="utf-8"))
    assert m["type"] == "real" and m["expected_verdict"] in ("PASS", "REVIEW", "FAIL")
    for key in ("must_not_flag", "may_flag", "must_flag"):
        assert all("spec_id" in r for r in m[key])
