// ---- rules page: #/rules  (uses $, esc, api from app.js / results.js)
const RTYPE = {NONE: "#667085", FLOATING: "#9333ea", LAYOUT: "#2563eb", IGNORE_COLORS: "#0d9488", STRICT: "#dc2626"};
const RU = {screen: null, regions: [], sel: -1, img: null, drag: null};

async function loadRules() {
  const sel = $("rscreen");
  let list;
  try { list = await api("/api/screens"); } catch (e) { rmsg(esc(e.message), true); return; }
  if (!list.length) { sel.innerHTML = ""; rmsg("No run with saved OCR yet: compare a pair first."); return; }
  const keep = RU.screen && list.some(s => s.screen === RU.screen) ? RU.screen : list[0].screen;
  sel.innerHTML = list.map(s => `<option value="${esc(s.screen)}" ${s.screen === keep ? "selected" : ""}>${esc(s.screen)} (run ${esc(s.run)})</option>`).join("");
  sel.onchange = () => openScreen(sel.value);
  openScreen(keep);
}

async function openScreen(screen) {
  let d;
  try { d = await api(`/api/rules/${encodeURIComponent(screen)}`); } catch (e) { rmsg(esc(e.message), true); return; }
  Object.assign(RU, {screen, run: d.run, regions: d.rules.regions.map(r => ({...r})), sel: -1});
  $("rlevel").value = d.rules.match_level || "";
  $("rpats").innerHTML = "";
  for (const [n, rx] of Object.entries(d.rules.patterns)) addPattern(n, rx);
  rmsg(esc(d.exists ? `Editing ${d.file}` : `${d.file} does not exist yet; Save creates it.`));
  RU.img = new Image(); RU.img.onload = drawRules; RU.img.src = `/api/runs/${d.run}/image/client`;
  drawRules(); editor();
}

function rmsg(text, bad) { const m = $("rmsg"); m.className = bad ? "error" : "note"; m.innerHTML = text; }

function drawRules() {
  const cv = $("rcanvas"), img = RU.img;
  if (img && img.naturalWidth) {
    const h = Math.min(innerHeight * 0.75, cv.parentElement.clientWidth * img.naturalHeight / img.naturalWidth);
    cv.height = Math.round(h); cv.width = Math.round(h * img.naturalWidth / img.naturalHeight);
    const g = cv.getContext("2d");
    g.drawImage(img, 0, 0, cv.width, cv.height);
    RU.regions.forEach((r, k) => {
      const [x, y, w, h2] = r.bbox_norm, c = RTYPE[r.type] || "#667085";
      g.strokeStyle = c; g.lineWidth = k === RU.sel ? 3 : 2; g.fillStyle = c + "40";
      g.fillRect(x * cv.width, y * cv.height, w * cv.width, h2 * cv.height);
      g.strokeRect(x * cv.width, y * cv.height, w * cv.width, h2 * cv.height);
      g.fillStyle = c; g.font = "12px system-ui"; g.fillText(`${r.name} (${r.type})`, x * cv.width + 3, y * cv.height + 13);
      if (k === RU.sel) g.fillRect((x + w) * cv.width - 6, (y + h2) * cv.height - 6, 10, 10);  // resize handle
    });
  }
  $("rlist").innerHTML = RU.regions.map((r, k) => `<li class="${k === RU.sel ? "on" : ""}" data-k="${k}">
    <span class="swatch" style="background:${RTYPE[r.type]}"></span>${esc(r.name)} · ${esc(r.type)} · [${r.bbox_norm.map(v => v.toFixed(3)).join(", ")}]</li>`).join("")
    || `<li class="muted">No regions.</li>`;
  for (const li of $("rlist").querySelectorAll("[data-k]")) li.onclick = () => { RU.sel = +li.dataset.k; drawRules(); editor(); };
}

function editor() {
  const r = RU.regions[RU.sel], el = $("redit");
  if (!r) { el.className = "muted"; el.textContent = "Draw or click a region."; return; }
  el.className = "form";
  el.innerHTML = `<label>Name <input id="rname" value="${esc(r.name)}"></label>
   <label>Type <select id="rtype">${Object.keys(RTYPE).map(t => `<option ${t === r.type ? "selected" : ""}>${t}</option>`).join("")}</select></label>
   ${r.type === "FLOATING" ? `<label>Max offset <input id="roff" type="range" min="0" max="0.1" step="0.005" value="${r.max_offset_norm ?? 0.02}">
     <span id="roffv">${(r.max_offset_norm ?? 0.02).toFixed(3)}</span></label>` : ""}
   <button class="ghost sm" id="rdel">Delete region</button>`;
  $("rname").oninput = e => { r.name = e.target.value; drawRules(); };
  $("rtype").onchange = e => { r.type = e.target.value; if (r.type === "FLOATING") r.max_offset_norm ??= 0.02; else delete r.max_offset_norm; drawRules(); editor(); };
  if ($("roff")) $("roff").oninput = e => { r.max_offset_norm = +e.target.value; $("roffv").textContent = r.max_offset_norm.toFixed(3); };
  $("rdel").onclick = () => { RU.regions.splice(RU.sel, 1); RU.sel = -1; drawRules(); editor(); };
}

// mouse: drag empty area = new region, drag a region = move, drag its corner = resize
const clamp = v => Math.max(0, Math.min(1, v));
function pos(e) { const cv = $("rcanvas"); return [clamp(e.offsetX / cv.clientWidth), clamp(e.offsetY / cv.clientHeight)]; }
$("rcanvas").onmousedown = e => {
  const [x, y] = pos(e), cv = $("rcanvas"), tol = 8 / cv.clientWidth, s = RU.regions[RU.sel];
  if (s && Math.abs(x - s.bbox_norm[0] - s.bbox_norm[2]) < tol && Math.abs(y - s.bbox_norm[1] - s.bbox_norm[3]) < tol * cv.clientWidth / cv.clientHeight) {
    RU.drag = {mode: "resize", k: RU.sel}; return;
  }
  const k = RU.regions.map((r, i) => [r, i]).filter(([r]) => x >= r.bbox_norm[0] && x <= r.bbox_norm[0] + r.bbox_norm[2]
    && y >= r.bbox_norm[1] && y <= r.bbox_norm[1] + r.bbox_norm[3])
    .sort((a, b) => a[0].bbox_norm[2] * a[0].bbox_norm[3] - b[0].bbox_norm[2] * b[0].bbox_norm[3])[0]?.[1];
  if (k !== undefined) { RU.sel = k; RU.drag = {mode: "move", k, x, y, box: [...RU.regions[k].bbox_norm]}; drawRules(); editor(); return; }
  RU.regions.push({name: `region_${RU.regions.length + 1}`, type: "NONE", bbox_norm: [x, y, 0, 0]});
  RU.sel = RU.regions.length - 1; RU.drag = {mode: "new", k: RU.sel, x, y};
};
$("rcanvas").onmousemove = e => {
  const d = RU.drag; if (!d) return;
  const [x, y] = pos(e), r = RU.regions[d.k], b = r.bbox_norm;
  if (d.mode === "new") r.bbox_norm = [Math.min(x, d.x), Math.min(y, d.y), Math.abs(x - d.x), Math.abs(y - d.y)];
  if (d.mode === "resize") r.bbox_norm = [b[0], b[1], Math.max(0.005, x - b[0]), Math.max(0.005, y - b[1])];
  if (d.mode === "move") {
    const [bx, by, bw, bh] = d.box;
    r.bbox_norm = [Math.min(1 - bw, Math.max(0, bx + x - d.x)), Math.min(1 - bh, Math.max(0, by + y - d.y)), bw, bh];
  }
  drawRules();
};
addEventListener("mouseup", () => {
  const d = RU.drag; RU.drag = null;
  if (d && d.mode === "new") {
    const b = RU.regions[d.k].bbox_norm;
    if (b[2] < 0.005 || b[3] < 0.005) { RU.regions.splice(d.k, 1); RU.sel = -1; }  // a click, not a drag
    drawRules(); editor();
  }
});

function addPattern(name = "", rx = "") {
  const row = document.createElement("div"); row.className = "patrow";
  row.innerHTML = `<input class="pname" placeholder="name" value="${esc(name)}"><input class="prx" placeholder="regex, e.g. \\d+ min" value="${esc(rx)}">
   <button type="button" class="ghost sm ptest">Test</button><button type="button" class="ghost sm pdel">×</button><div class="pout muted"></div>`;
  row.querySelector(".pdel").onclick = () => row.remove();
  row.querySelector(".ptest").onclick = async () => {
    const out = row.querySelector(".pout");
    try {
      const j = await api(`/api/rules/${encodeURIComponent(RU.screen)}/test`, {regex: row.querySelector(".prx").value});
      out.className = "pout muted";
      out.textContent = j.matches.length ? `Matches ${j.matches.length} of ${j.total} texts: ${j.matches.join(" | ")}` : `Matches none of ${j.total} texts.`;
    } catch (e) { out.className = "pout error"; out.textContent = e.message; }
  };
  $("rpats").append(row);
}
$("raddpat").onclick = () => addPattern();

function rulesBody() {
  const patterns = {};
  for (const row of $("rpats").querySelectorAll(".patrow")) {
    const n = row.querySelector(".pname").value.trim(), rx = row.querySelector(".prx").value;
    if (n || rx) patterns[n] = rx;
  }
  return {match_level: $("rlevel").value, regions: RU.regions, patterns};
}
async function saveRules() {
  const j = await api(`/api/rules/${encodeURIComponent(RU.screen)}`, rulesBody());
  rmsg(esc(j.message)); return j;
}
$("rsave").onclick = () => saveRules().catch(e => rmsg(esc(e.message), true));
$("rtry").onclick = async () => {
  try {
    await saveRules();
    rmsg("Saved; re-checking the last run...");
    const j = await api(`/api/rules/${encodeURIComponent(RU.screen)}/try`, {});
    const row = (label, c) => `<tr><td>${label}</td><td>${esc(c.verdict)}</td>${["FAIL", "REVIEW", "PASS"].map(v => `<td>${c.findings[v] || 0}</td>`).join("")}</tr>`;
    rmsg(`${esc(j.message)} · <a href="#/results/${esc(j.run)}">open run ${esc(j.run)}</a>
      <table><thead><tr><th></th><th>Verdict</th><th>FAIL</th><th>REVIEW</th><th>PASS</th></tr></thead>
      <tbody>${row("Before", j.before)}${row("After", j.counts)}</tbody></table>`);
  } catch (e) { rmsg(esc(e.message), true); }
};
