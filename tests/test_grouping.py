import copy

from src.reporting.grouping import group_findings


def colour(p, c, verdict="FAIL", severity="Major", cls="tab_item"):
    return {"type": "COLOR_DIFFERENCE", "spec_id": "D1", "verdict": verdict, "severity": severity,
            "production_id": "el_1", "client_id": "el_2", "class": cls, "text": "Profile",
            "details": {"delta_e": 28.0, "production_rgb": list(p), "client_rgb": list(c)}}


def size(prod, client):
    return {"type": "SIZE_DIFFERENCE", "spec_id": "C2", "verdict": "REVIEW", "severity": None,
            "class": "tab_item", "text": "Profile",
            "details": {"production_size": prod, "client_size": client,
                        "width_ratio_diff": abs(prod[0] - client[0]) / client[0],
                        "height_ratio_diff": abs(prod[1] - client[1]) / client[1]}}


def test_twelve_near_identical_colours_one_issue():
    findings = [colour((105 + k % 2, 99, 99), (40, 40, 42 - k % 2)) for k in range(12)]
    issues = group_findings(findings)
    assert len(issues) == 1
    assert issues[0]["count"] == 12
    assert issues[0]["finding_indices"] == list(range(12))
    assert issues[0]["issue_id"] == "issue_001"
    assert issues[0]["summary"].startswith("12 × tab_item colour")


def test_different_colours_two_issues():
    issues = group_findings([colour((105, 99, 99), (40, 40, 42)),
                             colour((200, 30, 30), (30, 30, 200))])
    assert [i["count"] for i in issues] == [1, 1]


def test_size_bigger_vs_smaller_two_issues():
    issues = group_findings([size([0.12, 0.05], [0.10, 0.04]),
                             size([0.08, 0.03], [0.10, 0.04])])
    assert len(issues) == 2
    assert "wider and taller" in issues[0]["summary"]
    assert "narrower and shorter" in issues[1]["summary"]


def test_worst_verdict_and_severity():
    findings = [colour((105, 99, 99), (40, 40, 42), "REVIEW", None),
                colour((105, 99, 99), (40, 40, 42), "FAIL", "Minor"),
                colour((105, 99, 99), (40, 40, 42), "FAIL", "Critical")]
    (issue,) = group_findings(findings)
    assert issue["verdict"] == "FAIL"
    assert issue["severity"] == "Critical"


def test_match_and_pass_excluded_and_empty():
    assert group_findings([]) == []
    findings = [{"type": "MATCH", "verdict": "REVIEW", "class": "tab_item"},
                colour((105, 99, 99), (40, 40, 42), "PASS", None),
                colour((105, 99, 99), (40, 40, 42))]
    (issue,) = group_findings(findings)
    assert issue["finding_indices"] == [2]


def test_input_not_mutated():
    findings = [colour((105, 99, 99), (40, 40, 42)), size([0.12, 0.05], [0.10, 0.04])]
    before = copy.deepcopy(findings)
    group_findings(findings)
    assert findings == before


def test_findings_without_the_usual_details_are_not_grouped_and_do_not_crash():
    bare = [{"type": t, "spec_id": "C1", "verdict": "FAIL", "severity": "Major",
             "class": "button", "text": "Play", "details": {}}
            for t in ("POSITION_DIFFERENCE", "SIZE_DIFFERENCE", "COLOR_DIFFERENCE")]
    issues = group_findings(bare + bare)
    assert len(issues) == 6
    assert all(i["count"] == 1 for i in issues)
