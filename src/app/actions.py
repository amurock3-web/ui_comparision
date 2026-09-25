"""Results-page actions, in-process re-check and the Rules page (phase 16.2 / 16.4).

Every write is a local file, and every action is logged in <run>/actions.json
with exactly what it wrote, so the page can undo it:

    accept         append entries to the accepted-differences YAML (config path)
    ignore_region  append NONE regions to config/screen_rules/<client screen>.yaml
    bug            append {issue_id, note, time} to <run>/review.json

Re-check redoes matching -> differ -> report from the run's saved fused JSONs
(scripts/rematch.py's path; no detector, no OCR) into report_N.json/.html.

handle_get / handle_post route the new URLs and return (code, body, content
type); server.py only delegates. Run ids, report names and screen ids are
checked against fixed regexes before any path is built, so no traversal.
"""

import json
import re
import shutil
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from src.app.runs import RUN_RE, _input_name, headline, read_run
from src.comparison import accepted, regions

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "output" / "app"
_CFG = (yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8")) or {}).get("comparison", {})
ACCEPTED_PATH = ROOT / (_CFG.get("accepted_differences") or {}).get("path", "baselines/accepted_differences.yaml")
RULES_DIR = ROOT / "config" / (_CFG.get("match_levels") or {}).get("rules_dir", "screen_rules")

REPORT_RE = re.compile(r"report(?:_(\d+))?\.json")
SCREEN_RE = re.compile(r"[A-Za-z0-9_-]{1,120}")
RECHECK_LEVELS = ("STRICT", "LAYOUT", "IGNORE_COLORS")
PAD = 0.01  # ignore-region padding around a finding's box, normalized
# ponytail: one lock for every write the page makes; per-run locks if several people share the app.
write_lock = threading.Lock()


class BadRequest(ValueError):
    pass


def _rel(p: Path) -> str:
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def run_dir(run: str) -> Path:
    if not RUN_RE.fullmatch(run or "") or not (RUNS_DIR / run).is_dir():
        raise FileNotFoundError(f"run {run!r} not found")
    return RUNS_DIR / run


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---- reports

def report_names(rd: Path) -> list[str]:
    """report.json, report_2.json, ... oldest first."""
    names = [p.name for p in rd.glob("report*.json") if REPORT_RE.fullmatch(p.name)]
    return sorted(names, key=lambda n: int(REPORT_RE.fullmatch(n)[1] or 1))


def load_report(rd: Path, name: str | None = None) -> tuple[str, dict]:
    names = report_names(rd)
    if name and name not in names:
        raise FileNotFoundError(f"report {name!r} not found")
    if not names:
        raise FileNotFoundError("this run has no report.json")
    name = name or names[-1]
    report = _read_json(rd / name, {})
    return name, report if isinstance(report, dict) else {}


def issues_of(report: dict) -> list[dict]:
    """The report's issues; an older report without them gets one issue per finding."""
    if isinstance(report.get("issues"), list):
        return report["issues"]
    return [{"issue_id": f"finding_{i + 1:03d}", "type": f.get("type"), "spec_id": f.get("spec_id"),
             "class": f.get("class"), "count": 1, "verdict": f.get("verdict"), "severity": f.get("severity"),
             "finding_indices": [i], "summary": f"{f.get('class') or 'element'} {f.get('type')}"}
            for i, f in enumerate(report.get("findings") or [])]


def _issue(report: dict, issue_id: str) -> tuple[dict, list[dict]]:
    issue = next((i for i in issues_of(report) if i.get("issue_id") == issue_id), None)
    if issue is None:
        raise BadRequest(f"issue {issue_id!r} not in this report")
    findings = report.get("findings") or []
    return issue, [findings[i] for i in issue.get("finding_indices", []) if 0 <= i < len(findings)]


def _reason(f: dict) -> str:
    try:
        from src.reporting.html_report import _reason as reason
        return reason(f)
    except Exception:  # older finding shapes lack the keys a sentence needs
        return f"{f.get('class') or 'element'} {f.get('type')}"


def counts(report: dict) -> dict:
    findings = report.get("findings") or []
    return {"verdict": report.get("verdict"), "findings": dict(Counter(f.get("verdict") for f in findings)),
            "issues": dict(Counter(i.get("verdict") for i in issues_of(report)))}


def detail(rd: Path, name: str | None = None) -> dict:
    name, report = load_report(rd, name)
    for f in report.get("findings") or []:
        f["reason"] = _reason(f)
    report["issues"] = issues_of(report)
    stem = name[:-5]
    return {"meta": read_run(rd), "report_name": name, "headline": headline(report), "reports": report_names(rd), "report": report,
            "counts": counts(report), "has_html": (rd / f"{stem}.html").is_file(),
            "has_pdf": (rd / f"{stem}.pdf").is_file(), "review": _read_json(rd / "review.json", []),
            "actions": _read_json(rd / "actions.json", []), "history": _history(rd, report)}


def _history(rd: Path, report: dict):
    from src.app.library import history
    try:
        return history(rd, report)
    except Exception:  # the strip is extra; a bad older run must not break the page
        return None


# ---- actions + undo

def _log(rd: Path, entry: dict) -> dict:
    log = _read_json(rd / "actions.json", [])
    entry = {"id": f"a{len(log) + 1}", "time": datetime.now().isoformat(timespec="seconds"),
             "undone": False, **entry}
    _write_json(rd / "actions.json", log + [entry])
    return entry


def _backup(path: Path) -> Path | None:
    """Copy `path` to <name>.<timestamp>.bak beside it; None if there was nothing to back up."""
    if not path.is_file():
        return None
    bak = path.with_name(f"{path.name}.{datetime.now():%Y%m%d_%H%M%S_%f}.bak")
    shutil.copy2(path, bak)
    return bak


def _dump_yaml(path: Path, data: dict) -> str:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _accept(rd, report, issue, findings, note):
    entries, skipped = [], 0
    for f in findings:
        if f.get("client_center_norm"):
            entries.append(accepted.entry_for(report, f, note))
        else:
            skipped += 1
    if not entries:
        raise BadRequest("none of this issue's findings has a client element to anchor on "
                         "(production-only findings cannot be accepted)")
    accepted.append(ACCEPTED_PATH, entries)
    msg = f"Accepted {len(entries)} finding(s) in {_rel(ACCEPTED_PATH)}"
    if skipped:
        msg += f"; skipped {skipped} with no client element"
    return {"file": _rel(ACCEPTED_PATH), "entries": entries, "message": msg}


def _padded(box):
    x, y, w, h = box
    x0, y0 = max(0.0, x - PAD), max(0.0, y - PAD)
    x1, y1 = min(1.0, x + w + PAD), min(1.0, y + h + PAD)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _ignore_region(rd, report, issue, findings, note):
    screen = report.get("client_screen") or _client_screen(rd)
    if not screen or not SCREEN_RE.fullmatch(screen):
        raise BadRequest("this run has no client screen id to attach rules to")
    boxes = [f.get("client_bbox_norm") or f.get("production_bbox_norm") for f in findings]
    boxes = [b for b in boxes if b and len(b) == 4]
    if not boxes:
        raise BadRequest("none of this issue's findings has a box to ignore")
    path = RULES_DIR / f"{screen}.yaml"
    previous = path.read_text(encoding="utf-8") if path.is_file() else None
    bak = _backup(path)
    data = yaml.safe_load(previous or "") or {}
    added = [{"name": f"ignore_{issue['issue_id']}_{k + 1}", "type": "NONE", "bbox_norm": _padded(b)}
             for k, b in enumerate(boxes)]
    data["regions"] = (data.get("regions") or []) + added
    written = _dump_yaml(path, data)
    msg = f"Added {len(added)} NONE region(s) to {_rel(path)}"
    if bak:
        msg += f" (previous version in {bak.name})"
    return {"file": _rel(path), "path": str(path), "regions": added, "previous": previous,
            "written": written, "message": msg}


def _bug(rd, report, issue, findings, note):
    bug = {"issue_id": issue["issue_id"], "note": note, "time": datetime.now().isoformat(timespec="seconds")}
    _write_json(rd / "review.json", _read_json(rd / "review.json", []) + [bug])
    return {"file": _rel(rd / "review.json"), "bug": bug, "message": f"Marked as bug in {_rel(rd / 'review.json')}"}


ACTIONS = {"accept": _accept, "ignore_region": _ignore_region, "bug": _bug}


def do_action(rd: Path, body: dict) -> dict:
    kind = body.get("action")
    if kind not in ACTIONS:
        raise BadRequest(f"unknown action {kind!r}")
    with write_lock:
        name, report = load_report(rd, body.get("report"))
        issue, findings = _issue(report, body.get("issue_id"))
        result = ACTIONS[kind](rd, report, issue, findings, str(body.get("note") or ""))
        return _log(rd, {"action": kind, "issue_id": issue["issue_id"], "report": name, **result})


def _remove_each(items: list, gone: list) -> list:
    items = list(items)
    for g in gone:
        if g in items:
            items.remove(g)
    return items


def undo(rd: Path, action_id: str) -> dict:
    with write_lock:
        log = _read_json(rd / "actions.json", [])
        entry = next((a for a in log if a.get("id") == action_id), None)
        if entry is None or entry.get("undone"):
            raise BadRequest(f"no action {action_id!r} to undo")
        kind = entry["action"]
        if kind == "accept":
            left = _remove_each(accepted.load(ACCEPTED_PATH), entry["entries"])
            _dump_yaml(ACCEPTED_PATH, {"accepted": left})
        elif kind == "ignore_region":
            path = Path(entry["path"])
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current == entry["written"]:  # untouched since: put the old file back exactly
                if entry["previous"] is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(entry["previous"], encoding="utf-8")
            elif current is not None:  # edited since: take out only our regions
                data = yaml.safe_load(current) or {}
                data["regions"] = _remove_each(data.get("regions") or [], entry["regions"])
                _dump_yaml(path, data)
        elif kind == "bug":
            _write_json(rd / "review.json", _remove_each(_read_json(rd / "review.json", []), [entry["bug"]]))
        entry["undone"] = True
        _write_json(rd / "actions.json", log)
        return {"id": action_id, "file": entry["file"], "message": f"Undid {kind}; {entry['file']} restored"}


# ---- re-check (no detector, no OCR)

def _rematch(rd: Path, match_level, html_path: Path) -> dict:
    """scripts/rematch.py's chain on this run's fused JSONs; writes the HTML, returns the report."""
    from scripts.rematch import load
    from src.comparison.differ import DifferenceEngine
    from src.comparison.matcher import ElementMatcher
    from src.reporting.html_report import write_html_report
    from src.reporting.report import ReportGenerator

    try:
        p_doc, p_graph, p_img = load(rd / "production_fused.json", None)
        c_doc, c_graph, c_img = load(rd / "client_fused.json", None)
    except SystemExit as e:  # rematch.load exits when a screenshot is missing
        raise BadRequest(str(e))
    match = ElementMatcher().match(p_doc, c_doc, p_graph, c_graph)
    diffs = DifferenceEngine(match_level=match_level).compare(
        p_doc, c_doc, p_graph, c_graph, match, production_image=p_img, client_image=c_img)
    report = ReportGenerator().generate(p_doc, c_doc, diffs)
    write_html_report(report, p_img, c_img, p_doc, c_doc, diffs, html_path, p_graph, c_graph)
    return report


def recheck(rd: Path, match_level=None) -> dict:
    match_level = (match_level or "").upper() or None
    if match_level and match_level not in RECHECK_LEVELS:
        raise BadRequest(f"match level must be one of {', '.join(RECHECK_LEVELS)}")
    for side in ("production", "client"):
        if not (rd / f"{side}_fused.json").is_file():
            raise BadRequest(f"this run has no {side}_fused.json to re-check from")
    with write_lock:
        n = max([int(REPORT_RE.fullmatch(x)[1] or 1) for x in report_names(rd)], default=1) + 1
        report = _rematch(rd, match_level, rd / f"report_{n}.html")
        _write_json(rd / f"report_{n}.json", report)
    return {"report": f"report_{n}.json", "counts": counts(report),
            "message": f"Re-checked ({match_level or 'screen default'} match level) into report_{n}.json"}


def tickets(rd: Path, name: str) -> Path:
    from src.reporting.export import DEFAULT_COLUMNS, to_ticket_rows, write_csv
    name, report = load_report(rd, name)
    cfg = ROOT / "config" / "ticket_export.yaml"
    columns = ((yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("columns")
               if cfg.is_file() else None) or DEFAULT_COLUMNS
    out = rd / f"tickets{name[len('report'):-len('.json')]}.csv"
    write_csv(to_ticket_rows(report, str(rd / name), columns), columns, out)
    return out


# ---- rules page

def _client_screen(rd: Path) -> str | None:
    return (_read_json(rd / "client_fused.json", {}) or {}).get("screen_id")


def screens() -> list[dict]:
    """Client screen ids of runs that can be re-checked, each with its newest run."""
    seen = {}
    if RUNS_DIR.is_dir():
        for rd in sorted(RUNS_DIR.iterdir(), key=lambda d: d.name, reverse=True):
            if rd.is_dir() and RUN_RE.fullmatch(rd.name) and (rd / "production_fused.json").is_file():
                s = _client_screen(rd)
                if s and SCREEN_RE.fullmatch(s) and s not in seen:
                    seen[s] = {"screen": s, "run": rd.name}
    return list(seen.values())


def _latest_run(screen: str) -> Path:
    if not SCREEN_RE.fullmatch(screen or ""):
        raise BadRequest(f"bad screen id {screen!r}")
    hit = next((s for s in screens() if s["screen"] == screen), None)
    if hit is None:
        raise FileNotFoundError(f"no run with client screen {screen!r}")
    return RUNS_DIR / hit["run"]


def get_rules(screen: str) -> dict:
    rd = _latest_run(screen)
    path = RULES_DIR / f"{screen}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    doc = _read_json(rd / "client_fused.json", {})
    return {"screen": screen, "run": rd.name, "file": _rel(path), "exists": path.is_file(),
            "rules": {"match_level": (data or {}).get("match_level"),
                      "regions": (data or {}).get("regions") or [],
                      "patterns": (data or {}).get("patterns") or {}},
            "image_size": [doc.get("image_width"), doc.get("image_height")]}


def validate_rules(data: dict) -> dict:
    """The rules as they will be written; BadRequest with the first problem found."""
    out = {}
    level = (data.get("match_level") or "").upper()
    if level:
        if level not in RECHECK_LEVELS:
            raise BadRequest(f"match level must be one of {', '.join(RECHECK_LEVELS)}")
        out["match_level"] = level
    regs = []
    for k, r in enumerate(data.get("regions") or []):
        name = str(r.get("name") or "").strip() or f"region_{k + 1}"
        kind = str(r.get("type") or "").upper()
        if kind not in regions.REGION_TYPES:
            raise BadRequest(f"region {name}: type must be one of {', '.join(regions.REGION_TYPES)}")
        try:
            x, y, w, h = (float(v) for v in r.get("bbox_norm"))
        except (TypeError, ValueError):
            raise BadRequest(f"region {name}: bbox_norm must be four numbers [x, y, w, h]")
        eps = 1e-6
        if not (x >= -eps and y >= -eps and w > 0 and h > 0 and x + w <= 1 + eps and y + h <= 1 + eps):
            raise BadRequest(f"region {name}: bbox_norm {[x, y, w, h]} is not inside [0, 1]")
        reg = {"name": name, "type": kind, "bbox_norm": [round(v, 4) for v in (x, y, w, h)]}
        if kind == "FLOATING":
            off = float(r.get("max_offset_norm", 0.02))
            if not 0 <= off <= 0.1:
                raise BadRequest(f"region {name}: max_offset_norm must be between 0 and 0.1")
            reg["max_offset_norm"] = round(off, 4)
        if r.get("min_overlap") is not None:
            mo = float(r["min_overlap"])
            if not 0 < mo <= 1:
                raise BadRequest(f"region {name}: min_overlap must be in (0, 1]")
            reg["min_overlap"] = mo
        regs.append(reg)
    if regs:
        out["regions"] = regs
    pats = {}
    for name, rx in (data.get("patterns") or {}).items():
        name = str(name).strip()
        if not name:
            raise BadRequest("every pattern needs a name")
        try:
            re.compile(rx)
        except (re.error, TypeError) as e:
            raise BadRequest(f"pattern {name}: {e}")
        pats[name] = rx
    if pats:
        out["patterns"] = pats
    return out


def save_rules(screen: str, data: dict) -> dict:
    if not SCREEN_RE.fullmatch(screen or ""):
        raise BadRequest(f"bad screen id {screen!r}")
    rules = validate_rules(data)
    path = RULES_DIR / f"{screen}.yaml"
    with write_lock:
        bak = _backup(path)
        _dump_yaml(path, rules)
    return {"file": _rel(path), "backup": bak.name if bak else None,
            "message": f"Saved {_rel(path)}" + (f" (previous version in {bak.name})" if bak else "")}


def test_pattern(screen: str, regex: str) -> dict:
    try:
        rx = re.compile(regex or "", re.IGNORECASE)
    except re.error as e:
        raise BadRequest(f"regex does not compile: {e}")
    doc = _read_json(_latest_run(screen) / "client_fused.json", {})
    texts = sorted({e["text"].strip() for e in doc.get("elements", []) if e.get("text") and e["text"].strip()})
    return {"matches": [t for t in texts if rx.fullmatch(t)], "total": len(texts)}


def try_rules(screen: str) -> dict:
    rd = _latest_run(screen)
    _, before = load_report(rd)
    result = recheck(rd)
    return {"run": rd.name, "before": counts(before), **result}


# ---- routing (server.py delegates here)

def _image(rd: Path, side: str) -> tuple[bytes, str]:
    name = _input_name(rd, side)
    if not name:
        raise FileNotFoundError(f"no {side} screenshot")
    p = rd / f"{side}_{name}"
    ext = p.suffix.lower()
    return p.read_bytes(), {".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, f"image/{ext[1:]}")


def handle_get(path: str, query: dict) -> tuple[int, object, str] | None:
    """(code, body, content type) for the routes below, or None if the path is not one of them.

    GET /api/runs/<run>/detail[?report=report_N.json]
    GET /api/runs/<run>/image/(production|client)
    GET /api/runs/<run>/json/report[_N].json      (download)
    GET /api/runs/<run>/tickets/report[_N].json   (CSV, generated now)
    GET /api/screens
    GET /api/rules/<screen>
    """
    try:
        if path == "/api/screens":
            return 200, screens(), "application/json"
        m = re.fullmatch(r"/api/rules/([^/]+)", path)
        if m:
            return 200, get_rules(m[1]), "application/json"
        m = re.fullmatch(r"/api/runs/([^/]+)/(detail|image|json|tickets)(?:/([^/]+))?", path)
        if not m:
            return None
        rd, kind, arg = run_dir(m[1]), m[2], m[3]
        if kind == "detail" and not arg:
            return 200, detail(rd, query.get("report") or None), "application/json"
        if kind == "image" and arg in ("production", "client"):
            body, ctype = _image(rd, arg)
            return 200, body, ctype
        if kind in ("json", "tickets") and arg and REPORT_RE.fullmatch(arg):
            if kind == "json":
                load_report(rd, arg)  # 404 unless it is one of this run's reports
                return 200, (rd / arg).read_bytes(), "application/json"
            return 200, tickets(rd, arg).read_bytes(), "text/csv; charset=utf-8"
        return 404, {"error": "not found"}, "application/json"
    except FileNotFoundError as e:
        return 404, {"error": str(e)}, "application/json"
    except BadRequest as e:
        return 400, {"error": str(e)}, "application/json"


def handle_post(path: str, body: dict) -> tuple[int, object, str] | None:
    """POST /api/runs/<run>/actions         {action, issue_id, report, note}
    POST /api/runs/<run>/actions/undo    {id}
    POST /api/runs/<run>/recheck         {match_level}
    POST /api/rules/<screen>             {match_level, regions, patterns}
    POST /api/rules/<screen>/test        {regex}
    POST /api/rules/<screen>/try         {}
    """
    try:
        m = re.fullmatch(r"/api/runs/([^/]+)/(actions|actions/undo|recheck)", path)
        if m:
            rd = run_dir(m[1])
            if m[2] == "actions":
                return 200, do_action(rd, body), "application/json"
            if m[2] == "actions/undo":
                return 200, undo(rd, body.get("id")), "application/json"
            return 200, recheck(rd, body.get("match_level")), "application/json"
        m = re.fullmatch(r"/api/rules/([^/]+)(/test|/try)?", path)
        if m:
            if m[2] == "/test":
                return 200, test_pattern(m[1], body.get("regex")), "application/json"
            if m[2] == "/try":
                return 200, try_rules(m[1]), "application/json"
            return 200, save_rules(m[1], body), "application/json"
        return None
    except FileNotFoundError as e:
        return 404, {"error": str(e)}, "application/json"
    except (BadRequest, ValueError) as e:
        return 400, {"error": str(e)}, "application/json"
