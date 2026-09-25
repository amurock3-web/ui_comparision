"""
Issue grouping (Applitools-style): many findings are one issue repeated.

Presentation only. Verdicts, similarity and report["findings"] are never
changed; each issue just points back at the findings it covers by index.
Thresholds come from the caller (config/config.yaml), not from here.
"""

from src.comparison.color_checks import delta_e2000, to_lab

VERDICT_RANK = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
SEVERITY_RANK = {None: 0, "Minor": 1, "Major": 2, "Critical": 3}
COLOR_TYPES = ("COLOR_DIFFERENCE", "BADGE_COLOR_DIFFERENCE")


def _sign(x) -> int:
    return (x > 0) - (x < 0)


def _bucket(f: dict, size_pass: float, position_step: float):
    """Hashable bucket for exact-key types; None = never grouped."""
    t, d = f["type"], f.get("details") or {}
    if t == "SIZE_DIFFERENCE":
        (pw, ph), (cw, ch) = d["production_size"], d["client_size"]
        return (_sign(pw - cw), _sign(ph - ch),
                round(d["width_ratio_diff"] / size_pass), round(d["height_ratio_diff"] / size_pass))
    if t == "POSITION_DIFFERENCE":
        (px, py), (cx, cy) = d["production_center"], d["client_center"]
        sx, sy = d.get("group_shift") or (0.0, 0.0)
        return (round((px - cx - sx) / position_step), round((py - cy - sy) / position_step))
    if t in ("TEXT_DIFFERENCE", "TEXT_STYLE_DIFFERENCE"):
        return (str(d.get("production_text", "")).strip().casefold(),
                str(d.get("client_text", "")).strip().casefold())
    if t in ("MISSING_IN_PRODUCTION", "EXTRA_IN_PRODUCTION"):
        return f.get("verdict")
    return None


def _summary(f: dict, count: int) -> str:
    try:
        return _typed_summary(f, count)
    except (KeyError, TypeError, ValueError):
        return _plain_summary(f, count)


def _plain_summary(f: dict, count: int) -> str:
    t, cls = f["type"], f.get("class")
    text = f" '{f['text']}'" if f.get("text") else ""
    return f"{t} {cls}{text}" if count == 1 else f"{count} × {cls} {t}{text}"


def _typed_summary(f: dict, count: int) -> str:
    t, cls, d = f["type"], f.get("class"), f.get("details") or {}
    head = f"{count} × {cls}"
    if t in COLOR_TYPES:
        p, c = d["production_rgb"], d["client_rgb"]
        return (f"{head} colour: production rgb({','.join(map(str, p))}) vs design "
                f"rgb({','.join(map(str, c))}), dE {round(d.get('delta_e', 0))}")
    if t == "SIZE_DIFFERENCE":
        (pw, ph), (cw, ch) = d["production_size"], d["client_size"]
        words = [w for w in ({1: "wider", -1: "narrower"}.get(_sign(pw - cw)),
                             {1: "taller", -1: "shorter"}.get(_sign(ph - ch))) if w]
        return f"{head} size: {' and '.join(words) or 'different'} in production"
    if t == "MISSING_IN_PRODUCTION":
        return f"{head} missing in production"
    if t == "EXTRA_IN_PRODUCTION":
        return f"{head} extra in production"
    if t in ("TEXT_DIFFERENCE", "TEXT_STYLE_DIFFERENCE"):
        return f"{head} text: '{d.get('production_text')}' vs design '{d.get('client_text')}'"
    if t == "POSITION_DIFFERENCE":
        return f"{head} position shifted"
    return _plain_summary(f, count)


def group_findings(findings: list[dict], color_pass_de: float = 3.0, size_pass: float = 0.05,
                   position_step: float = 0.01) -> list[dict]:
    """Collapse REVIEW/FAIL findings into issues, in order of first appearance."""
    groups = []   # [{"key": ..., "first": finding, "labs": (p, c) or None, "idx": [...]}]
    by_key = {}   # exact-key types -> group
    for i, f in enumerate(findings):
        if f.get("type") == "MATCH" or f.get("verdict") == "PASS":
            continue
        t, cls = f["type"], f.get("class")
        group = None
        d = f.get("details") or {}
        bucket = None
        if t in COLOR_TYPES and "production_rgb" in d and "client_rgb" in d:
            labs = (to_lab(d["production_rgb"]), to_lab(d["client_rgb"]))
            # Greedy, in input order: compare against each group's FIRST member only,
            # so a slow drift of shades cannot chain into one group.
            # ponytail: O(n * groups) scan; fine for tens of findings per screen.
            for g in groups:
                if (g["labs"] and g["type"] == t and g["class"] == cls
                        and delta_e2000(labs[0], g["labs"][0]) <= color_pass_de
                        and delta_e2000(labs[1], g["labs"][1]) <= color_pass_de):
                    group = g
                    break
        else:
            labs = None
            # A finding without the usual details (a hand-built or older one) is
            # simply not grouped: grouping is presentation and must never
            # break a report.
            try:
                bucket = _bucket(f, size_pass, position_step)
            except (KeyError, TypeError, ValueError):
                bucket = None
            if bucket is not None:
                group = by_key.get((t, cls, bucket))
        if group is None:
            group = {"type": t, "class": cls, "labs": labs, "first": f, "idx": []}
            groups.append(group)
            if labs is None and bucket is not None:
                by_key[(t, cls, bucket)] = group
        group["idx"].append(i)

    issues = []
    for n, g in enumerate(groups, 1):
        members = [findings[i] for i in g["idx"]]
        issues.append({
            "issue_id": f"issue_{n:03d}",
            "type": g["type"],
            "spec_id": g["first"].get("spec_id"),
            "class": g["class"],
            "count": len(members),
            "verdict": max((m.get("verdict") for m in members), key=lambda v: VERDICT_RANK.get(v, 0)),
            "severity": max((m.get("severity") for m in members), key=lambda s: SEVERITY_RANK.get(s, 0)),
            "finding_indices": list(g["idx"]),
            "summary": _summary(g["first"], len(members)),
        })
    return issues
