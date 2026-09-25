// ---- baselines (#/baselines), the Compare page's baseline picker, batch (#/batch[/<id>])
// uses $, esc, badge from app.js and api from results.js
const LIB = {list: [], upload: null, batch: [], batchId: null, timer: null};
const inferDevice = (w, h) => w > h ? "tv" : h / w >= 1.6 ? "phone" : "tablet";
const keyUrl = k => "/api/baselines/" + k.split("/").map(encodeURIComponent).join("/");
const readImage = f => new Promise(ok => {
  const r = new FileReader();
  r.onload = () => { const img = new Image(); img.onload = () => ok({name: f.name, data: r.result, width: img.naturalWidth, height: img.naturalHeight}); img.src = r.result; };
  r.readAsDataURL(f);
});
function dropZone(zone, take) {
  const input = zone.querySelector("input");
  const imgs = fl => [...fl].filter(f => f.type.startsWith("image/"));
  input.onchange = () => take(imgs(input.files));
  zone.ondragover = e => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = e => { e.preventDefault(); zone.classList.remove("over"); take(imgs(e.dataTransfer.files)); };
}
// wait for a queued job: onTick(job) every second until it is done or failed
async function waitJob(id, onTick) {
  const job = (await api("/api/jobs")).find(j => j.id === id);
  onTick(job);
  if (job && (job.status === "queued" || job.status === "running")) setTimeout(() => waitJob(id, onTick), 1000);
}
const jobText = j => !j ? "" : j.status === "queued" ? `queued (#${j.position})` : j.status;

// ---- compare page picker
async function loadBaselinePicker() {
  try { LIB.list = await api("/api/baselines"); } catch { LIB.list = []; }
  drawPicker();
}
function drawPicker() {
  const q = $("bsearch").value.trim().toLowerCase(), sel = $("bselect"), keep = sel.value;
  const shown = LIB.list.filter(b => !q || b.key.toLowerCase().includes(q));
  sel.innerHTML = shown.length ? shown.map(b => `<option value="${esc(b.key)}" ${b.stale ? "disabled" : ""} ${b.key === keep ? "selected" : ""}>${esc(b.key)}${b.stale ? " (stale - re-add on Baselines)" : ""}</option>`).join("")
    : `<option value="">${LIB.list.length ? "no match" : "no baselines yet - add one on Baselines"}</option>`;
  if (sel.selectedOptions[0]?.disabled) sel.value = shown.find(b => !b.stale)?.key || "";
  $("go").disabled = !ready();
}
$("bsearch").oninput = drawPicker;

// ---- baselines page
async function loadBaselines() {
  try { LIB.list = await api("/api/baselines"); } catch (e) { bmsg(e.message, true); return; }
  $("blist").innerHTML = LIB.list.length ? LIB.list.map(b => `<tr>
    <td>${b.has_image ? `<img class="thumb" loading="lazy" alt="" src="${keyUrl(b.key)}/image">` : ""}</td>
    <td>${esc(b.screen)}</td><td>${esc(b.device)}</td><td>${esc(b.language)}</td><td>${esc((b.created || "").replace("T", " "))}</td>
    <td>${b.stale ? `<span class="tag" title="built under other detector/OCR settings">stale - re-add</span>` : "ok"}</td>
    <td><button class="ghost sm" data-del="${esc(b.key)}">Delete</button></td></tr>`).join("")
    : `<tr><td colspan="7" class="muted">No baselines yet.</td></tr>`;
  for (const b of $("blist").querySelectorAll("[data-del]")) b.onclick = async e => {
    e.stopPropagation();
    if (!confirm(`Delete baseline ${b.dataset.del}? The image is removed; meta.json and client_fused.json are kept in baselines/_archive/.`)) return;
    try { bmsg((await api("/api/baselines/delete", {key: b.dataset.del})).message); } catch (err) { bmsg(err.message, true); }
    loadBaselines();
  };
}
function bmsg(text, bad) { const m = $("bmsg"); m.className = bad ? "error" : "note"; m.textContent = text; }
dropZone($("drop-baseline"), async ([f]) => {
  if (!f) return;
  const up = LIB.upload = await readImage(f), zone = $("drop-baseline");
  zone.querySelectorAll("img,.muted").forEach(e => e.remove());
  const img = document.createElement("img"); img.src = up.data; zone.append(img);
  $("bdevice").options[0].textContent = `auto (${inferDevice(up.width, up.height)})`;
  if (!$("bscreen").value) $("bscreen").value = f.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_.-]+/g, "_");
  $("badd").disabled = false;
});
$("badd").onclick = async () => {
  const {name, data} = LIB.upload;
  $("badd").disabled = true;
  try {
    const job = await api("/api/baselines", {name, data, screen: $("bscreen").value.trim(), device: $("bdevice").value, language: $("blang").value.trim()});
    waitJob(job.id, j => {
      if (!j) return;
      if (j.status === "done") { bmsg(`Added ${j.screen}.`); loadBaselines(); $("badd").disabled = false; }
      else if (j.status === "failed") { bmsg(j.error, true); $("badd").disabled = false; }
      else bmsg(`Adding ${j.screen}: ${jobText(j)} (detector + OCR, about a minute)`);
    });
  } catch (e) { bmsg(e.message, true); $("badd").disabled = false; }
};

// ---- batch page
async function loadBatch(id) {
  clearTimeout(LIB.timer);
  try { LIB.list = await api("/api/baselines"); } catch { LIB.list = []; }
  LIB.batchId = id || null;
  $("bsummary").hidden = !id;
  if (id) { $("bsummary").href = `/api/batch/${encodeURIComponent(id)}/summary`; $("bsummary").download = `batch_${id}.json`; return pollBatch(); }
  drawDraft();
}
dropZone($("drop-batch"), async fs => {
  if (!fs.length) return;
  if (LIB.batchId) location.hash = "#/batch";  // a new batch
  const items = await Promise.all(fs.map(readImage));
  let pairs = [];
  try { pairs = await api("/api/batch/pair", {by: $("bby").value, items: items.map(({name, width, height}) => ({name, width, height}))}); }
  catch (e) { pairs = items.map(() => ({baseline: null, error: e.message})); }
  LIB.batch = LIB.batch.concat(items.map((it, k) => ({...it, baseline: pairs[k].baseline, why: pairs[k].error})));
  drawDraft();
});
$("bby").onchange = async () => {
  if (!LIB.batch.length) return;
  const pairs = await api("/api/batch/pair", {by: $("bby").value, items: LIB.batch.map(({name, width, height}) => ({name, width, height}))});
  LIB.batch.forEach((it, k) => Object.assign(it, {baseline: pairs[k].baseline, why: pairs[k].error}));
  drawDraft();
};
function drawDraft() {
  if (LIB.batchId) return;
  const opts = sel => `<option value="">- no baseline -</option>` + LIB.list.map(b =>
    `<option value="${esc(b.key)}" ${b.stale ? "disabled" : ""} ${b.key === sel ? "selected" : ""}>${esc(b.key)}${b.stale ? " (stale)" : ""}</option>`).join("");
  $("brows").innerHTML = LIB.batch.map((it, k) => `<tr class="${it.baseline ? "" : "flag"}"><td class="name">${esc(it.name)}</td>
    <td><select data-k="${k}">${opts(it.baseline)}</select></td>
    <td>${it.baseline ? "ready" : `<span class="error" title="${esc(it.why || "")}">no baseline: not run</span>`}</td><td></td><td></td><td></td>
    <td><button class="ghost sm" data-rm="${k}">Remove</button></td></tr>`).join("")
    || `<tr><td colspan="7" class="muted">Drop screenshots above.</td></tr>`;
  for (const s of $("brows").querySelectorAll("select")) s.onchange = () => { LIB.batch[s.dataset.k].baseline = s.value || null; drawDraft(); };
  for (const b of $("brows").querySelectorAll("[data-rm]")) b.onclick = () => { LIB.batch.splice(+b.dataset.rm, 1); drawDraft(); };
  $("bstart").disabled = !LIB.batch.some(it => it.baseline);
}
$("bstart").onclick = async () => {
  $("bstart").disabled = true;
  try {
    const b = await api("/api/batch", {items: LIB.batch.map(({name, data, baseline}) => ({name, data, baseline}))});
    LIB.batch = [];
    location.hash = "#/batch/" + b.id;
  } catch (e) { alert(e.message); $("bstart").disabled = false; }
};
async function pollBatch() {
  let b;
  try { b = await api(`/api/batch/${encodeURIComponent(LIB.batchId)}`); }
  catch (e) { $("brows").innerHTML = `<tr><td colspan="7" class="error">${esc(e.message)}</td></tr>`; return; }
  $("bstart").disabled = true;
  $("brows").innerHTML = b.rows.map(r => `<tr class="${r.status === "not run" ? "flag" : ""}" ${r.status === "done" ? `data-run="${esc(r.run)}"` : ""}>
    <td class="name">${esc(r.file)}</td><td>${esc(r.baseline || "-")}</td>
    <td>${r.status === "queued" ? `queued (#${r.position})` : esc(r.status)}${r.error ? ` <span class="error">${esc(r.error)}</span>` : ""}</td>
    <td>${badge(r.verdict)}</td><td>${r.similarity == null ? "-" : esc(r.similarity) + "%"}</td><td>${r.issues ?? "-"}</td>
    <td>${r.status === "done" ? `<a href="#/results/${esc(r.run)}">results</a>` : ""}</td></tr>`).join("");
  if (b.rows.some(r => r.status === "queued" || r.status === "running") && location.hash.startsWith("#/batch/"))
    LIB.timer = setTimeout(pollBatch, 2000);
}
