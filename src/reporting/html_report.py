"""
One self-contained HTML page per comparison: what a QA reader needs first
(verdict, side-by-side, findings with before/after crops, test-case
coverage), and below it, folded, what a developer needs to judge the
verdict (extraction confidence, both layout trees, run settings).

Images are embedded as base64, so the page can be mailed or attached
without its folder. The side-by-side PNG is also left next to it.
"""

import base64
import hashlib
import html
import io
import json
from datetime import datetime
from pathlib import Path

import yaml
from PIL import Image

from src.graph.layout import SCREEN_ID, describe
from src.reporting.report import SUMMARY_FIELDS
from src.reporting.visualize import draw_comparison_result

ROOT = Path(__file__).resolve().parents[2]
VERDICT_COLORS = {"PASS": "#1f9d55", "REVIEW": "#d97706", "FAIL": "#dc2626"}

CSS = """
:root { --bg:#ffffff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --card:#f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --line:#30363d; --card:#161b22; }
}
body { background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,sans-serif; margin:0 auto; max-width:1200px; padding:16px; }
h1 { margin:0 0 4px; font-size:22px; } h2 { margin:28px 0 8px; font-size:17px; }
.muted { color:var(--muted); }
.verdict { display:inline-block; padding:4px 14px; border-radius:6px; color:#fff; font-weight:700; font-size:18px; }
.pill { display:inline-block; padding:1px 8px; border-radius:10px; color:#fff; font-size:12px; font-weight:600; }
.stats { display:flex; flex-wrap:wrap; gap:12px; margin:12px 0; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px 14px; }
.stat b { display:block; font-size:20px; }
table { border-collapse:collapse; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; vertical-align:top; }
th { background:var(--card); font-weight:600; }
img.shot { max-width:100%; border:1px solid var(--line); border-radius:6px; }
.crops img { max-height:180px; border:1px solid var(--line); margin-right:6px; }
.crops span { display:inline-block; text-align:center; font-size:11px; color:var(--muted); }
.note { background:var(--card); border-left:4px solid #d97706; padding:8px 12px; border-radius:4px; }
pre { background:var(--card); border:1px solid var(--line); border-radius:6px; padding:10px; overflow-x:auto; font-size:12px; }
.trees { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
@media (max-width:700px) { .trees { grid-template-columns:1fr; } }
details { margin-top:28px; } summary { cursor:pointer; font-weight:600; font-size:17px; }
.legend span { margin-right:14px; }
@media print {
  body { max-width:none; padding:0; }
  /* whole side-by-side fits under the header on page 1 instead of jumping to page 2 */
  img.shot { display:block; margin:0 auto; width:auto; height:auto; max-width:100%; max-height:62vh; object-fit:contain; }
  tr, .stats, .note { break-inside:avoid; }
  thead { display:table-header-group; }
  h2 { break-after:avoid; }
}
"""


def _b64_png(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _crop(img, bbox, pad=40, max_h=180):
    if bbox is None:
        return None
    x, y, w, h = bbox
    box = (max(0, int(x - pad)), max(0, int(y - pad)),
           min(img.width, int(x + w + pad)), min(img.height, int(y + h + pad)))
    crop = img.crop(box)
    if crop.height > max_h:
        crop = crop.resize((max(1, int(crop.width * max_h / crop.height)), max_h))
    return _b64_png(crop)


def _rank(f) -> int:
    """Worst first, the same order as the app's Results page (static/results.js rank)."""
    if f["verdict"] == "FAIL":
        return {"Critical": 0, "Major": 1, "Minor": 2}.get(f.get("severity"), 3)
    return 4 if f["verdict"] == "REVIEW" else 5


def _pill(verdict):
    if not verdict:
        return ""
    return f'<span class="pill" style="background:{VERDICT_COLORS.get(verdict, "#888")}">{verdict}</span>'


def _reason(f) -> str:
    """One plain-English line per finding."""
    d, what = f["details"], f["class"] or "element"
    if f["text"]:
        what += f' "{f["text"]}"'
    t = f["type"]
    if t == "MISSING_IN_PRODUCTION":
        return f"{what} is in the client design but was not found in production."
    if t == "EXTRA_IN_PRODUCTION":
        return f"{what} is in production but not in the client design."
    if t == "CLASS_DIFFERENCE":
        return f"Detected as {d['production_class']} in production, {d['client_class']} in the design."
    if t == "LANGUAGE_DIFFERENCE":
        return (f'Wrong language: "{d["production_text"]}" ({d["production_script"]}) in production, '
                f'"{d["client_text"]}" ({d["client_script"]}) in the design.')
    if t == "CONTRAST_DIFFERENCE":
        return (f"Text contrast {d['production_ratio']}:1 in production "
                f"(design {d['client_ratio']}:1, WCAG AA needs 4.5:1).")
    if t == "TEXT_COLOR_DIFFERENCE":
        return (f"Text colour differs by dE {d['delta_e']}: rgb{tuple(d['production_rgb'])} "
                f"in production vs rgb{tuple(d['client_rgb'])} in the design.")
    if t in ("LOGO_DIFFERENCE", "ICON_DIFFERENCE"):
        what = "Logo" if t == "LOGO_DIFFERENCE" else "Icon"
        return f"{what} looks different from the design (SSIM {d['ssim']})."
    if t == "BROKEN_IMAGE":
        return "Card image looks empty or failed to load (almost flat area)."
    if t == "ELEMENT_COMPARISON_SKIPPED":
        why = ", ".join(x.replace("_", " ").lower() for x in d["because"])
        return (f"Elements were not compared: the two screens are not comparable ({why}). "
                f"Production has {d['production_elements']} elements, the design "
                f"{d['client_elements']}.")
    if t == "ORIENTATION_DIFFERENCE":
        return (f"Screen orientation differs: {d['production']['orientation']} in production, "
                f"{d['client']['orientation']} in the design.")
    if t == "BLANK_SCREEN":
        side = "production" if d["production"]["blank"] else "client"
        return (f"The {side} screenshot looks blank or broken "
                f"({100 * d[side]['dominant_colour_fraction']:.0f}% one colour).")
    if t == "THEME_DIFFERENCE":
        return (f"Theme differs: {d['production']['theme']} in production, "
                f"{d['client']['theme']} in the design.")
    if t == "SCALING_DIFFERENCE":
        return (f"The UI is stretched: aspect ratio differs by "
                f"{100 * d['aspect_ratio_difference']:.1f}%.")
    if t in ("COLOR_DIFFERENCE", "BADGE_COLOR_DIFFERENCE"):
        return (f"{what} colour differs by dE {d['delta_e']}: rgb{tuple(d['production_rgb'])} "
                f"in production vs rgb{tuple(d['client_rgb'])} in the design.")
    if t == "BACKGROUND_COLOR_DIFFERENCE":
        return (f"Page background differs by dE {d['delta_e']}: rgb{tuple(d['production_rgb'])} "
                f"in production vs rgb{tuple(d['client_rgb'])} in the design.")
    if t == "TAB_ORDER_DIFFERENCE" and d.get("swapped_labels"):
        pairs = "; ".join(f'"{a}" and "{b}" have traded places' for a, b in d["swapped_labels"])
        return f"Tabs are swapped: {pairs}."
    if t == "SIZE_DIFFERENCE" and (d.get("pixel_check") or {}).get("confirmed"):
        pc = d["pixel_check"]
        return (f"Size differs, confirmed by pixels: width {pc['width_ratio_diff']:.0%}, "
                f"height {pc['height_ratio_diff']:.0%} apart.")
    if t in ("SECTION_ORDER_DIFFERENCE", "TAB_ORDER_DIFFERENCE"):
        moved = ", ".join(
            f'"{m["label"]}" is #{m["client_index"] + 1} in the design but '
            f'#{m["production_index"] + 1} in production' for m in d["moved"])
        what_moved = "Sections" if t.startswith("SECTION") else "Tabs"
        return f"{what_moved} are in a different order: {moved}."
    if t == "ALIGNMENT_DIFFERENCE":
        pair = " and ".join(f'"{x}"' for x in d["labels"] if x) or "two elements"
        return (f"{pair} share a {d['axis'].replace('_', ' ')} edge in the design; in production "
                f"they are {100 * d['production_offset_norm']:.1f}% apart.")
    if t == "CLIPPING_DIFFERENCE":
        side = d["clipped_in"]
        tail = f" {d['note']}" if d.get("note") else ""
        return f"{what} is cut off in the {side} but fully visible in the other.{tail}"
    if t == "TEXT_STYLE_DIFFERENCE":
        return (f'Same wording, different style: "{d["production_text"]}" in production '
                f'vs "{d["client_text"]}" in the design.')
    if t == "TEXT_DIFFERENCE":
        return f'Label reads "{d["production_text"]}" in production, "{d["client_text"]}" in the design.'
    if t == "GROUP_SHIFT":
        name = d["label"] or "A group of elements"
        way = "up" if d["dy_px"] < 0 else "down"
        moved = f"{way} {abs(d['dy_px']):.0f} px" if abs(d["dy_px"]) >= abs(d["dx_px"]) else                 f"sideways {abs(d['dx_px']):.0f} px"
        return (f"{name} moved {moved} as one piece "
                f"({100 * d['distance_of_diagonal']:.1f}% of the diagonal, "
                f"{d['anchors']} anchors, {len(d['members'])} members).")
    if t == "POSITION_DIFFERENCE":
        return f"{what} moved {100 * d['distance_of_diagonal']:.1f}% of the screen diagonal, relative to its group."
    if t == "SIZE_DIFFERENCE":
        return (f"{what} size differs: width {100 * d['width_ratio_diff']:.0f}%, "
                f"height {100 * d['height_ratio_diff']:.0f}%.")
    if t == "STRUCTURAL_DIFFERENCE":
        return f"{what} has different layout neighbours (context similarity {d['context_similarity']:.2f})."
    return json.dumps(d, ensure_ascii=False)


def _node_flag(graph, node_id) -> str:
    if graph is None or node_id not in graph:
        return ""
    data = graph.nodes[node_id]
    if data.get("clipped"):
        return " Cut off by the screen edge, nav bar or an overlay, so this may be a false alarm."
    return ""


def _run_meta() -> dict:
    detector = yaml.safe_load((ROOT / "config" / "detector.yaml").read_text())
    config_text = (ROOT / "config" / "config.yaml").read_bytes()
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "detector": f"{detector.get('engine')} / {detector.get('bundle')}",
        "config.yaml md5": hashlib.md5(config_text).hexdigest()[:10],
    }


def _layout_counts(graph) -> dict:
    if graph is None:
        return {}
    nodes = [d for _, d in graph.nodes(data=True)]
    return {"clipped": sum(1 for d in nodes if d.get("clipped") and not d.get("occluded_by")),
            "hidden-card placeholders": sum(1 for d in nodes if d.get("occluded_by"))}


def write_html_report(report, production_image, client_image, production_doc, client_doc,
                      differences, output_path: Path, production_graph=None, client_graph=None) -> Path:
    output_path = Path(output_path)
    side_by_side = output_path.with_suffix(".png")
    draw_comparison_result(production_image, client_image, production_doc, client_doc,
                           differences, side_by_side, show_matches=True)
    prod_img = Image.open(production_image).convert("RGB")
    client_img = Image.open(client_image).convert("RGB")
    prod_by_id = {e.id: e for e in production_doc.elements}
    client_by_id = {e.id: e for e in client_doc.elements}
    esc = html.escape

    coverage = report["coverage"]
    checked = [c for c in coverage if c["status"] == "checked"]
    specced = [c for c in coverage if c["status"] != "applied"]
    verdict = report["verdict"]
    s = report["summary"]
    counts = {k: v for k, v in s.items() if k not in SUMMARY_FIELDS}

    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>UI Comparison {esc(report['screen'])}</title><style>{CSS}</style></head><body>"]

    # --- Result -----------------------------------------------------------
    out.append(f"<h1>UI comparison: {esc(report['screen'])}</h1>"
               f"<div class='muted'>Production: {esc(str(production_image))} &middot; "
               f"Client design: {esc(str(client_image))}</div>")
    out.append(f"<p><span class='verdict' style='background:{VERDICT_COLORS[verdict]}'>{verdict}</span></p>")
    out.append(f"<div class='note'>This verdict covers the <b>{len(checked)} of {len(specced)}</b> "
               f"test cases that are built (listed under Coverage). A PASS means the screen passed "
               f"those checks, not that nothing else is wrong.</div>")
    # Elements, not Difference records: one pair with three sub-differences is one element.
    out.append("<div class='stats'>"
               f"<div class='stat'><b>Matched {s['matched_pairs']} of {s['comparable']} elements "
               f"({s['similarity_percent']}%)</b>clean {s['clean_pairs']} &middot; "
               f"missing {s['missing']} &middot; extra {s['extra']} &middot; ignored {s['ignored']}</div>"
               f"<div class='stat'><b>{len(report['findings'])}</b>findings</div>"
               f"<div class='stat'><b>{report['warnings']}</b>minor warnings</div></div>")
    if s.get("warning"):
        out.append(f"<div class='note'>{esc(s['warning'])}</div>")
    out.append("<div class='muted'>" + " &middot; ".join(f"{esc(k)}: {v}" for k, v in counts.items()) + "</div>")

    out.append("<h2>Side by side</h2><div class='legend muted'>"
               "<span style='color:#22cc55'>&#9632; matched</span>"
               "<span style='color:#888'>&#9632; skipped (dynamic content / ignored)</span>"
               "<span>thick coloured box = finding, labelled with its type</span></div>")
    out.append(f"<img class='shot' src='{_b64_png(Image.open(side_by_side))}' alt='production and client side by side'>")

    issues = report.get("issues")
    if issues and len(issues) < len(report["findings"]):
        out.append(f"<h2>Issues</h2><p class='muted'>{len(report['findings'])} findings in "
                   f"{len(issues)} issues. Repeats of one difference are grouped here; "
                   "every finding is still listed below.</p>"
                   "<table><thead><tr><th>Test</th><th>Verdict</th><th>Issue</th></tr></thead>")
        for i in sorted(issues, key=_rank):
            sev = f" &middot; {esc(i['severity'])}" if i["severity"] else ""
            out.append(f"<tr><td><b>{esc(str(i['spec_id']))}</b></td>"
                       f"<td>{_pill(i['verdict'])}{sev}</td><td>{esc(i['summary'])}</td></tr>")
        out.append("</table>")

    out.append("<h2>Findings</h2>")
    if not report["findings"]:
        out.append("<p class='muted'>No REVIEW or FAIL findings.</p>")
    else:
        out.append("<table><thead><tr><th>Test</th><th>Verdict</th><th>What</th><th>Production &middot; Design</th></tr></thead>")
        for f in sorted(report["findings"], key=_rank):
            p = prod_by_id.get(f["production_id"])
            c = client_by_id.get(f["client_id"])
            crops = ""
            for label, img, el in (("production", prod_img, p), ("design", client_img, c)):
                src = _crop(img, el.bbox if el else None)
                crops += (f"<span><img src='{src}' alt='{label} crop'><br>{label}</span>" if src
                          else f"<span>(none in {label})</span> ")
            flag = _node_flag(production_graph, f["production_id"]) or _node_flag(client_graph, f["client_id"])
            if (f.get("details") or {}).get("capped"):
                flag += f" Capped to REVIEW (was {f['details'].get('original_verdict')} " \
                        f"{f['details'].get('original_severity') or ''}): element is cut off."
            sev = f" &middot; {esc(f['severity'])}" if f["severity"] else ""
            out.append(f"<tr><td><b>{esc(f['spec_id'])}</b></td><td>{_pill(f['verdict'])}{sev}</td>"
                       f"<td>{esc(_reason(f))}<span class='muted'>{esc(flag)}</span><br>"
                       f"<span class='muted'>{esc(f['type'])} &middot; prod {esc(str(f['production_id']))} "
                       f"&middot; design {esc(str(f['client_id']))}</span></td>"
                       f"<td class='crops'>{crops}</td></tr>")
        out.append("</table>")

    out.append("<h2>Coverage</h2><p class='muted'>Every test case in docs/test_cases_pass_fail.md. "
               "\"not built\" means this report says nothing about it.</p>"
               "<table><thead><tr><th>ID</th><th>Check</th><th>Status</th><th>Result here</th></tr></thead>")
    for c in coverage:
        status_color = {"checked": "#1f9d55", "applied": "#2563eb"}.get(c["status"], "#8d96a0")
        out.append(f"<tr><td>{esc(c['id'])}</td><td>{esc(c['check'])}</td>"
                   f"<td><span class='pill' style='background:{status_color}'>{esc(c['status'])}</span></td>"
                   f"<td>{_pill(c['result'])}</td></tr>")
    out.append("</table>")

    # --- Pipeline details (folded) ----------------------------------------
    out.append("<details><summary>Pipeline details (for judging the verdict)</summary>")
    out.append("<h2>What the pipeline was unsure of</h2><p class='muted'>High numbers here weaken the verdict: "
               "uncertain elements become REVIEW, ignored and clipped ones are not fully compared.</p>")
    conf = report["confidence"]
    rows = {"production": {**conf["production"], **_layout_counts(production_graph)},
            "client design": {**conf["client"], **_layout_counts(client_graph)}}
    keys = list(rows["production"])
    out.append("<table><thead><tr><th></th>" + "".join(f"<th>{esc(k)}</th>" for k in keys) + "</tr></thead>")
    for side, vals in rows.items():
        out.append(f"<tr><td><b>{side}</b></td>" + "".join(f"<td>{vals.get(k, '')}</td>" for k in keys) + "</tr>")
    out.append("</table>")

    if production_graph is not None and SCREEN_ID in production_graph and client_graph is not None:
        out.append("<h2>Layout trees</h2><div class='trees'>"
                   f"<div><b>Production</b><pre>{esc(describe(production_graph))}</pre></div>"
                   f"<div><b>Client design</b><pre>{esc(describe(client_graph))}</pre></div></div>")

    out.append("<h2>Run</h2><table>" + "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(str(v))}</td></tr>" for k, v in _run_meta().items()) + "</table>")
    out.append(f"<h2>Raw report</h2><pre>{esc(json.dumps(report, indent=2, ensure_ascii=False))}</pre>")
    out.append("</details></body></html>")

    output_path.write_text("\n".join(out), encoding="utf-8")
    return output_path
