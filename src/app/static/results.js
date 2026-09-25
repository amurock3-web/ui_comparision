// ---- results page: #/results/<run>  (helpers $, esc, badge, VERDICT come from app.js)
const SEV_RANK = {Critical: 0, Major: 1, Minor: 2};
const rank = i => i.verdict === "FAIL" ? (SEV_RANK[i.severity] ?? 3) : i.verdict === "REVIEW" ? 4 : 5;
const api = async (url, body) => {
  const r = await fetch(url, body === undefined ? {} : {method: "POST", body: JSON.stringify(body)});
  const j = await r.json().catch(() => ({error: `HTTP ${r.status}`}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
};
const RS = {run: null, d: null, sel: null, vf: new Set(), ff: new Set(), zoom: 1, imgs: {}};

async function showResults(run, reportName) {
  const el = $("page-results");
  if (RS.run !== run) Object.assign(RS, {run, sel: null, vf: new Set(), ff: new Set(), zoom: 1, imgs: {}});
  el.innerHTML = `<p class="muted">Loading ${esc(run)}...</p>`;
  try {
    RS.d = await api(`/api/runs/${encodeURIComponent(run || "")}/detail` + (reportName ? `?report=${encodeURIComponent(reportName)}` : ""));
  } catch (e) { el.innerHTML = `<p class="error">Run ${esc(run)}: ${esc(e.message)}</p>`; return; }
  for (const side of ["production", "client"]) if (!RS.imgs[side]) {
    const img = new Image(); img.onload = drawBoxes; img.src = `/api/runs/${run}/image/${side}`; RS.imgs[side] = img;
  }
  renderResults();
}

function renderResults() {
  const {meta: m, report: rep, counts, report_name: name, reports} = RS.d;
  const s = rep.summary || {}, stem = name.replace(/\.json$/, ""), run = m.run;
  const vc = counts.issues, fams = [...new Set(rep.issues.map(i => (i.spec_id || "?")[0]))].sort();
  const bugs = new Set(RS.d.review.map(b => b.issue_id));
  const el = $("page-results");
  el.innerHTML = `<h1>Run ${esc(run)}</h1>
   <div class="muted">${esc(m.date)} · ${esc(m.production || "?")} vs ${esc(m.client || "?")}</div>
   <div class="rhead">${badge(rep.verdict)}
    ${["FAIL", "REVIEW", "PASS"].filter(v => vc[v]).map(v => `<span class="pill" style="border-color:${VERDICT[v]}">${vc[v]} ${v}</span>`).join("")}
    ${s.accepted ? `<span class="pill">${s.accepted} accepted</span>` : ""}
    <span class="muted">match level ${esc(s.match_level || "STRICT")}</span></div>
   <div>${esc(RS.d.headline)}</div>
   ${RS.d.history ? `<div class="hstrip"><span class="muted">Since <a href="#/results/${esc(RS.d.history.previous)}">run ${esc(RS.d.history.previous)}</a> (same client screen):</span>
    <span class="pill" style="border-color:${VERDICT.FAIL}">${RS.d.history.new} new</span>
    <span class="pill" style="border-color:${VERDICT.PASS}">${RS.d.history.fixed} fixed</span>
    <span class="pill">${RS.d.history.still_open} still open</span></div>` : ""}
   <div class="actions">
    <label>Report <select id="rep">${reports.map(r => `<option ${r === name ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></label>
    <select id="lvl" aria-label="Match level"><option value="">screen default</option><option>STRICT</option><option>LAYOUT</option><option>IGNORE_COLORS</option></select>
    <button id="recheck" class="ghost" title="Redo matching and the report from the saved OCR (seconds)">Re-check</button>
    <span class="sep"></span>
    ${RS.d.has_pdf ? `<a class="btn" href="/run/${run}/${stem}.pdf" download="${stem}_${run}.pdf">PDF</a>` : ""}
    ${RS.d.has_html ? `<a class="btn ghost" href="/run/${run}/${stem}.html" target="_blank">HTML</a>` : ""}
    <a class="btn ghost" href="/api/runs/${run}/json/${name}" download="${stem}_${run}.json">report.json</a>
    <a class="btn ghost" href="/api/runs/${run}/tickets/${name}" download="tickets_${stem}_${run}.csv">Tickets CSV</a>
   </div>
   <div id="msg"></div>
   <div class="actions"><span class="muted">Zoom</span><button class="ghost sm" id="zout">−</button><button class="ghost sm" id="zin">+</button></div>
   <div class="viewer">
    ${["production", "client"].map(side => `<div class="shot"><b>${side === "client" ? "Client design" : "Production"}</b>
      <div class="scroll"><canvas id="cv-${side}"></canvas></div></div>`).join("")}
   </div>
   <div id="tip" hidden></div>
   <div class="filters">
    ${["FAIL", "REVIEW", "PASS"].filter(v => vc[v]).map(v => `<button class="chipbtn ${RS.vf.has(v) ? "on" : ""}" data-v="${v}">${v}</button>`).join("")}
    <span class="sep"></span>
    ${fams.map(f => `<button class="chipbtn ${RS.ff.has(f) ? "on" : ""}" data-f="${esc(f)}">${esc(f)}</button>`).join("")}
   </div>
   <div id="issues"></div>
   ${RS.d.actions.length ? `<h2>Changes made from this page</h2><ul class="plain" id="changes">${RS.d.actions.slice().reverse().map(a =>
     `<li class="${a.undone ? "undone" : ""}"><b>${esc(a.action)}</b> ${esc(a.issue_id)} · ${esc(a.message)} · <code>${esc(a.file)}</code>
      ${a.undone ? "(undone)" : `<button class="ghost sm" data-undo="${esc(a.id)}">Undo</button>`}</li>`).join("")}</ul>` : ""}`;

  const issues = rep.issues.filter(i => (!RS.vf.size || RS.vf.has(i.verdict)) && (!RS.ff.size || RS.ff.has((i.spec_id || "?")[0])))
    .sort((a, b) => rank(a) - rank(b));
  $("issues").innerHTML = issues.length ? issues.map(i => `<details class="issue ${i.issue_id === RS.sel ? "sel" : ""}" data-id="${esc(i.issue_id)}" ${i.issue_id === RS.sel ? "open" : ""}>
    <summary>${badge(i.verdict)} <b>${esc(i.severity || "")}</b> <code>${esc(i.spec_id || "")}</code> ${esc(i.summary)}
     ${bugs.has(i.issue_id) ? `<span class="tag">bug</span>` : ""}</summary>
    <ul>${i.finding_indices.map(k => rep.findings[k]).filter(Boolean).map(f => `<li>${esc(f.reason)}
      ${f.client_bbox_norm || f.production_bbox_norm ? "" : `<span class="muted">(no box)</span>`}</li>`).join("")}</ul>
    <div class="actions"><button class="ghost sm" data-act="accept">Accept</button>
     <button class="ghost sm" data-act="ignore_region">Ignore region</button>
     <button class="ghost sm" data-act="bug">Mark as bug</button></div></details>`).join("")
    : `<p class="muted">No issues${RS.vf.size || RS.ff.size ? " for this filter" : ""}.</p>`;

  $("rep").onchange = e => showResults(run, e.target.value);
  $("recheck").onclick = async e => {
    e.target.disabled = true; say("Re-checking...");
    try { const j = await api(`/api/runs/${run}/recheck`, {match_level: $("lvl").value}); await showResults(run, j.report); say(j.message); }
    catch (err) { say(err.message, true); e.target.disabled = false; }
  };
  $("zin").onclick = () => { RS.zoom = Math.min(4, RS.zoom * 1.25); drawBoxes(); };
  $("zout").onclick = () => { RS.zoom = Math.max(0.5, RS.zoom / 1.25); drawBoxes(); };
  for (const b of el.querySelectorAll(".filters [data-v],.filters [data-f]")) b.onclick = () => {
    const set = b.dataset.v ? RS.vf : RS.ff, k = b.dataset.v || b.dataset.f;
    set.has(k) ? set.delete(k) : set.add(k); renderResults();
  };
  for (const d of el.querySelectorAll("details.issue")) d.querySelector("summary").onclick = () => {
    RS.sel = RS.sel === d.dataset.id ? null : d.dataset.id;
    for (const o of el.querySelectorAll("details.issue")) o.classList.toggle("sel", o.dataset.id === RS.sel);
    drawBoxes();
  };
  for (const b of el.querySelectorAll("[data-act]")) b.onclick = () => act(b.dataset.act, b.closest("details").dataset.id);
  for (const b of el.querySelectorAll("[data-undo]")) b.onclick = async () => {
    try { const j = await api(`/api/runs/${run}/actions/undo`, {id: b.dataset.undo}); await showResults(run, name); say(j.message); }
    catch (err) { say(err.message, true); }
  };
  for (const side of ["production", "client"]) {
    const cv = $("cv-" + side);
    cv.onmousemove = e => hover(side, e);
    cv.onmouseleave = () => { $("tip").hidden = true; };
    cv.onclick = e => { const h = hit(side, e); if (h) { RS.sel = h.issue.issue_id; renderResults();
      document.querySelector(`details.issue[data-id="${CSS.escape(RS.sel)}"]`)?.scrollIntoView({block: "nearest"}); } };
  }
  drawBoxes();
}

function say(text, bad) { const m = $("msg"); if (m) { m.className = bad ? "error" : "note"; m.textContent = text; } }

async function act(kind, issueId) {
  let note = "";
  if (kind !== "ignore_region") { note = prompt(kind === "accept" ? "Why is this difference expected?" : "Bug note (optional)"); if (note === null) return; }
  try {
    const j = await api(`/api/runs/${RS.run}/actions`, {action: kind, issue_id: issueId, report: RS.d.report_name, note});
    await showResults(RS.run, RS.d.report_name);
    say(j.message + (kind === "bug" ? "" : " - press Re-check to see it applied."));
  } catch (e) { say(e.message, true); }
}

// every finding box on one side: [{box, f, issue}], filtered like the list
function boxes(side) {
  const rep = RS.d.report, key = side + "_bbox_norm", out = [];
  for (const i of rep.issues) {
    if ((RS.vf.size && !RS.vf.has(i.verdict)) || (RS.ff.size && !RS.ff.has((i.spec_id || "?")[0]))) continue;
    for (const k of i.finding_indices) { const f = rep.findings[k]; if (f && f[key]) out.push({box: f[key], f, issue: i}); }
  }
  return out;
}

function drawBoxes() {
  if (!RS.d) return;
  for (const side of ["production", "client"]) {
    const cv = $("cv-" + side), img = RS.imgs[side];
    if (!cv || !img || !img.naturalWidth) continue;
    const w = Math.round(cv.parentElement.clientWidth * RS.zoom), h = Math.round(w * img.naturalHeight / img.naturalWidth);
    cv.width = w; cv.height = h;
    const g = cv.getContext("2d");
    g.drawImage(img, 0, 0, w, h);
    const all = boxes(side);
    for (const pass of [false, true]) for (const {box: [x, y, bw, bh], issue} of all) {
      const on = issue.issue_id === RS.sel;
      if (on !== pass) continue;  // selected boxes last, on top
      g.strokeStyle = VERDICT[issue.verdict] || "#667085";
      g.lineWidth = on ? 4 : RS.sel ? 1 : 2;
      g.globalAlpha = RS.sel && !on ? 0.35 : 1;
      if (on) { g.fillStyle = g.strokeStyle + "33"; g.fillRect(x * w, y * h, bw * w, bh * h); }
      g.strokeRect(x * w, y * h, bw * w, bh * h);
    }
    g.globalAlpha = 1;
  }
}

function hit(side, e) {
  const cv = e.currentTarget, x = e.offsetX / cv.clientWidth, y = e.offsetY / cv.clientHeight;
  const inside = boxes(side).filter(({box: [bx, by, bw, bh]}) => x >= bx && x <= bx + bw && y >= by && y <= by + bh);
  return inside.sort((a, b) => a.box[2] * a.box[3] - b.box[2] * b.box[3])[0];  // smallest on top
}

function hover(side, e) {
  const h = hit(side, e), tip = $("tip");
  if (!h) { tip.hidden = true; return; }
  tip.hidden = false;
  tip.textContent = `${h.f.class || "element"}${h.f.text ? ` "${h.f.text}"` : ""} · ${h.f.spec_id || ""} ${h.f.verdict}`;
  tip.style.left = (e.clientX + 12) + "px"; tip.style.top = (e.clientY + 12) + "px";
}
addEventListener("resize", drawBoxes);
