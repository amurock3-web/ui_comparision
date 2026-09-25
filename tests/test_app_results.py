import json

import pytest
import yaml

from src.app import actions
from src.comparison import accepted, regions

RUN = "20260925_120252"
SCREEN = "client_home"


@pytest.fixture
def env(tmp_path, monkeypatch):
    runs, rules = tmp_path / "runs", tmp_path / "screen_rules"
    rd = runs / RUN
    rd.mkdir(parents=True)
    monkeypatch.setattr(actions, "RUNS_DIR", runs)
    monkeypatch.setattr(actions, "RULES_DIR", rules)
    monkeypatch.setattr(actions, "ACCEPTED_PATH", tmp_path / "baselines" / "accepted.yaml")
    (rd / "client_home.png").write_bytes(b"x")
    (rd / "production_fused.json").write_text("{}")
    (rd / "client_fused.json").write_text(json.dumps({"screen_id": SCREEN, "elements": [
        {"text": "2h 15m"}, {"text": "Home"}, {"text": " 45 min "}, {"text": None}]}))
    finding = {"type": "COLOR_DIFFERENCE", "spec_id": "D1", "verdict": "FAIL", "severity": "Major",
               "class": "button", "text": "Play", "details": {"production_rgb": [1, 2, 3]},
               "production_bbox_norm": [0.1, 0.1, 0.2, 0.1], "client_bbox_norm": [0.5, 0.5, 0.2, 0.1],
               "client_center_norm": [0.6, 0.55]}
    extra = {"type": "EXTRA_IN_PRODUCTION", "spec_id": "B1", "verdict": "FAIL", "severity": "Major",
             "class": "logo", "text": None, "details": {}, "production_bbox_norm": [0.0, 0.0, 0.1, 0.05],
             "client_bbox_norm": None, "client_center_norm": None}
    report = {"screen": "production_home", "client_screen": SCREEN, "verdict": "FAIL", "summary": {},
              "findings": [finding, extra],
              "issues": [{"issue_id": "issue_001", "spec_id": "D1", "verdict": "FAIL", "severity": "Major",
                          "finding_indices": [0, 1], "summary": "2 x button"}]}
    (rd / "report.json").write_text(json.dumps(report))
    return rd


def post(path, body):
    return actions.handle_post(path, body)


def test_accept_and_undo(env):
    code, out, _ = post(f"/api/runs/{RUN}/actions", {"action": "accept", "issue_id": "issue_001", "note": "ok"})
    assert code == 200 and "skipped 1" in out["message"]
    entries = accepted.load(actions.ACCEPTED_PATH)
    assert len(entries) == 1 and entries[0]["client_screen_id"] == SCREEN and entries[0]["note"] == "ok"
    code, _, _ = post(f"/api/runs/{RUN}/actions/undo", {"id": out["id"]})
    assert code == 200 and accepted.load(actions.ACCEPTED_PATH) == []
    assert post(f"/api/runs/{RUN}/actions/undo", {"id": out["id"]})[0] == 400  # not twice


def test_ignore_region_backup_and_undo(env):
    path = actions.RULES_DIR / f"{SCREEN}.yaml"
    path.parent.mkdir()
    original = "# hand written\nmatch_level: LAYOUT\n"
    path.write_text(original)
    code, out, _ = post(f"/api/runs/{RUN}/actions", {"action": "ignore_region", "issue_id": "issue_001"})
    assert code == 200, out
    data = yaml.safe_load(path.read_text())
    assert data["match_level"] == "LAYOUT"
    assert [r["bbox_norm"] for r in data["regions"]] == [[0.49, 0.49, 0.22, 0.12], [0.0, 0.0, 0.11, 0.06]]
    assert all(r["type"] == "NONE" for r in data["regions"])
    baks = list(path.parent.glob("*.bak"))
    assert len(baks) == 1 and baks[0].read_text() == original
    post(f"/api/runs/{RUN}/actions/undo", {"id": out["id"]})
    assert path.read_text() == original


def test_ignore_region_created_file_is_removed_on_undo(env):
    code, out, _ = post(f"/api/runs/{RUN}/actions", {"action": "ignore_region", "issue_id": "issue_001"})
    path = actions.RULES_DIR / f"{SCREEN}.yaml"
    assert code == 200 and path.is_file()
    post(f"/api/runs/{RUN}/actions/undo", {"id": out["id"]})
    assert not path.exists()


def test_mark_as_bug(env):
    code, out, _ = post(f"/api/runs/{RUN}/actions", {"action": "bug", "issue_id": "issue_001", "note": "JIRA-1"})
    review = json.loads((env / "review.json").read_text())
    assert code == 200 and review[0]["issue_id"] == "issue_001" and review[0]["note"] == "JIRA-1"
    assert actions.detail(env)["review"] == review
    post(f"/api/runs/{RUN}/actions/undo", {"id": out["id"]})
    assert json.loads((env / "review.json").read_text()) == []


def test_recheck_writes_numbered_report_and_keeps_old(env, monkeypatch):
    seen = []

    def fake(rd, level, html_path):
        seen.append(level)
        html_path.write_text("<html></html>")
        return {"verdict": "PASS", "findings": [], "issues": []}

    monkeypatch.setattr(actions, "_rematch", fake)
    old = (env / "report.json").read_text()
    code, out, _ = post(f"/api/runs/{RUN}/recheck", {"match_level": "layout"})
    assert code == 200 and out["report"] == "report_2.json" and seen == ["LAYOUT"]
    assert post(f"/api/runs/{RUN}/recheck", {})[1]["report"] == "report_3.json"
    assert (env / "report.json").read_text() == old
    assert actions.report_names(env) == ["report.json", "report_2.json", "report_3.json"]
    assert actions.detail(env)["report_name"] == "report_3.json"
    assert post(f"/api/runs/{RUN}/recheck", {"match_level": "NONE"})[0] == 400


def test_rules_save_round_trips(env):
    body = {"match_level": "LAYOUT", "patterns": {"duration": r"\d+h \d+m"}, "regions": [
        {"name": "hero", "type": "STRICT", "bbox_norm": [0, 0.06, 1, 0.3]},
        {"name": "rail", "type": "floating", "bbox_norm": [0, 0.5, 1, 0.2], "max_offset_norm": 0.05}]}
    code, out, _ = post(f"/api/rules/{SCREEN}", body)
    assert code == 200, out
    rules = regions.load_rules(SCREEN, actions.RULES_DIR)
    assert rules["match_level"] == "LAYOUT" and rules["patterns"] == {"duration": r"\d+h \d+m"}
    assert [(r["name"], r["type"], r["bbox_norm"]) for r in rules["regions"]] == [
        ("hero", "STRICT", [0, 0.06, 1, 0.3]), ("rail", "FLOATING", [0, 0.5, 1, 0.2])]
    assert rules["regions"][1]["max_offset_norm"] == 0.05
    assert post(f"/api/rules/{SCREEN}", body)[1]["backup"]  # second save keeps the first
    assert len(list(actions.RULES_DIR.glob("*.bak"))) == 1
    got = actions.handle_get(f"/api/rules/{SCREEN}", {})[1]
    assert got["run"] == RUN and got["rules"]["match_level"] == "LAYOUT"


@pytest.mark.parametrize("body, msg", [
    ({"patterns": {"bad": "(unclosed"}}, "bad"),
    ({"regions": [{"name": "r", "type": "NONE", "bbox_norm": [0.5, 0.5, 0.6, 0.1]}]}, "inside"),
    ({"regions": [{"name": "r", "type": "NONE", "bbox_norm": [-0.1, 0, 0.2, 0.1]}]}, "inside"),
    ({"regions": [{"name": "r", "type": "FLOATING", "bbox_norm": [0, 0, 0.2, 0.1], "max_offset_norm": 0.5}]}, "0.1"),
    ({"regions": [{"name": "r", "type": "BLUR", "bbox_norm": [0, 0, 0.2, 0.1]}]}, "type"),
])
def test_rules_invalid_refused(env, body, msg):
    code, out, _ = post(f"/api/rules/{SCREEN}", body)
    assert code == 400 and msg in out["error"]
    assert not (actions.RULES_DIR / f"{SCREEN}.yaml").exists()


def test_pattern_test_lists_full_matches(env):
    code, out, _ = post(f"/api/rules/{SCREEN}/test", {"regex": r"\d+ MIN"})
    assert code == 200 and out["matches"] == ["45 min"] and out["total"] == 3
    assert post(f"/api/rules/{SCREEN}/test", {"regex": "("})[0] == 400


def test_try_rules_reports_before_and_after(env, monkeypatch):
    monkeypatch.setattr(actions, "_rematch", lambda rd, level, html: {"verdict": "PASS", "findings": []})
    code, out, _ = post(f"/api/rules/{SCREEN}/try", {})
    assert code == 200 and out["before"]["verdict"] == "FAIL" and out["counts"]["verdict"] == "PASS"


def test_traversal_refused(env, tmp_path):
    (tmp_path / "secret.json").write_text("{}")
    for path in ("/api/runs/../secret/detail", f"/api/runs/{RUN}/json/..%2F..%2Fsecret.json",
                 f"/api/runs/{RUN}/json/review.json", f"/api/runs/{RUN}/image/..", "/api/rules/..%2Fx",
                 f"/api/runs/{RUN}/json/report_9.json"):
        hit = actions.handle_get(path, {})
        assert hit is None or hit[0] in (400, 404), path
    assert post("/api/rules/..%2F..%2Fconfig", {})[0] == 400
    assert post("/api/runs/../x/actions", {"action": "bug"}) is None
    assert post("/api/runs/20990101_000000/actions", {"action": "bug"})[0] == 404
    assert not list(tmp_path.rglob("config.yaml"))
