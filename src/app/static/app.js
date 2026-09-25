const $ = id => document.getElementById(id);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const VERDICT = {PASS:"#1f9d55", REVIEW:"#d97706", FAIL:"#dc2626"};
const badge = v => v ? `<span class="verdict" style="background:${VERDICT[v] || "#667085"}">${esc(v)}</span>`
                     : `<span class="muted">-</span>`;

// ---- router: #/compare, #/results/<run>, #/history, #/baselines, #/batch[/<id>], #/rules, #/help
function route() {
  const [, page, arg] = location.hash.split("/");
  const name = ["compare", "results", "history", "baselines", "batch", "rules", "help"].includes(page) ? page : "compare";
  for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== "page-" + name;
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("on", a.dataset.page === name);
  if (name === "results") showResults(arg);
  if (name === "history") loadHistory();
  if (name === "rules") loadRules();
  if (name === "baselines") loadBaselines();
  if (name === "batch") loadBatch(arg);
  if (name === "compare") loadBaselinePicker();
}
addEventListener("hashchange", route);

// ---- health chips (every page)
const files = {};
let blocked = false;
const useBaseline = () => document.querySelector("input[name=cmode]:checked").value === "baseline";
const ready = () => !!(files.production && (useBaseline() ? $("bselect").value : files.client)) && !blocked;
fetch("/health").then(r => r.json()).then(checks => {
  const chips = $("chips"), fixes = $("fixes");
  for (const c of checks) {
    const chip = document.createElement("span");
    chip.className = "chip" + (c.ok ? "" : c.required ? " bad" : " warn");
    chip.textContent = (c.ok ? "✓ " : "✗ ") + c.name; chip.title = c.message;
    chips.append(chip);
    if (!c.ok) {
      const p = document.createElement("p"); p.className = c.required ? "error" : "muted";
      p.textContent = `${c.name}: ${c.message} - ${c.fix}`; fixes.append(p);
    }
  }
  blocked = checks.some(c => c.required && !c.ok);
  $("go").disabled = !ready();
});

// ---- compare
for (const side of ["production", "client"]) {
  const zone = $("drop-" + side), input = zone.querySelector("input");
  const take = f => {
    if (!f || !f.type.startsWith("image/")) return;
    const r = new FileReader();
    r.onload = () => {
      files[side] = {name: f.name, data: r.result};
      zone.querySelectorAll("img,.muted").forEach(e => e.remove());
      const img = document.createElement("img"); img.src = r.result; zone.append(img);
      const n = document.createElement("span"); n.className = "muted"; n.textContent = f.name; zone.append(n);
      $("go").disabled = !ready();
    };
    r.readAsDataURL(f);
  };
  input.onchange = () => take(input.files[0]);
  zone.ondragover = e => { e.preventDefault(); zone.classList.add("over"); };
  zone.ondragleave = () => zone.classList.remove("over");
  zone.ondrop = e => { e.preventDefault(); zone.classList.remove("over"); take(e.dataTransfer.files[0]); };
}
for (const r of document.querySelectorAll("input[name=cmode]")) r.onchange = () => {
  $("bpick").hidden = !useBaseline(); $("drop-client").hidden = useBaseline(); $("go").disabled = !ready();
};
$("bselect").onchange = () => { $("go").disabled = !ready(); };
let myRun = null;
$("go").onclick = async () => {
  const go = $("go"); go.disabled = true;
  $("result").hidden = true;
  $("progress").hidden = false;
  const body = useBaseline() ? {production: files.production, baseline: $("bselect").value} : files;
  const r = await fetch("/compare", {method: "POST", body: JSON.stringify(body)});
  const j = await r.json();
  if (!r.ok) { showError(j.error); go.disabled = !ready(); $("progress").hidden = true; return; }
  myRun = j.run;
  poll(true);
};
function showError(msg) {
  const res = $("result"); res.hidden = false;
  res.innerHTML = ""; const p = document.createElement("p"); p.className = "error"; p.textContent = msg; res.append(p);
}
async function poll(started) {
  const s = await (await fetch("/status")).json();
  const mine = myRun && s.jobs.find(j => j.run === myRun);
  if (!started && (!s.run || s.done) && !mine) return;  // page load with nothing running
  $("progress").hidden = false; $("go").disabled = true;
  if (mine && s.run !== myRun) {  // not started yet: waiting behind another job
    if (mine.status === "failed") { $("go").disabled = !ready(); return showError(mine.error); }
    $("fill").style.width = "0%";
    const ahead = s.jobs.find(j => j.status === "running");
    $("stage").textContent = mine.position ? `Queued (#${mine.position})` + (ahead ? ` - running now: ${ahead.label}` : "") : "Starting...";
    return setTimeout(() => poll(true), 1000);
  }
  $("fill").style.width = (100 * s.step / s.total) + "%";
  $("stage").textContent = s.done ? "Done" : `Step ${s.step} of ${s.total}: ${s.stage}...`;
  if (!s.done) return setTimeout(() => poll(true), 1000);
  $("go").disabled = !ready();
  if (s.error) return showError(s.error);
  if (!$("page-compare").hidden) location.hash = "#/results/" + s.run;
}

// ---- results: see results.js

// ---- history
let runs = [];
async function loadHistory() {
  $("runs-note").textContent = "Loading...";
  runs = await (await fetch("/api/runs")).json();
  drawHistory();
}
function drawHistory() {
  const q = $("search").value.trim().toLowerCase(), v = $("vfilter").value;
  const shown = runs.filter(m =>
    (!v || (m.verdict || "-") === v) &&
    (!q || [m.run, m.date, m.production, m.client].join(" ").toLowerCase().includes(q)));
  const num = x => x == null ? "-" : esc(x);
  $("runs").innerHTML = shown.map(m => {
    const base = "/run/" + m.run + "/report";
    return `<tr data-run="${esc(m.run)}"><td>${esc(m.run)}</td><td>${esc(m.date)}</td>
     <td class="name" title="${esc(m.production)}">${esc(m.production || "-")}</td>
     <td class="name" title="${esc(m.client)}">${esc(m.client || "-")}</td>
     <td>${badge(m.verdict)}</td><td>${m.similarity == null ? "-" : esc(m.similarity) + "%"}</td>
     <td>${num(m.findings)}</td><td>${num(m.issues)}</td>
     <td>${m.has_html ? `<a href="${base}.html" target="_blank">HTML</a>` : ""}
      ${m.has_pdf ? ` <a href="${base}.pdf" download="report_${m.run}.pdf">PDF</a>` : ""}</td></tr>`;
  }).join("");
  $("runs-note").textContent = `${shown.length} of ${runs.length} runs, stored in output/app/`;
}
$("search").oninput = drawHistory;
$("vfilter").onchange = drawHistory;
$("runs").onclick = e => {
  if (e.target.closest("a")) return;
  const tr = e.target.closest("tr");
  if (tr) location.hash = "#/results/" + tr.dataset.run;
};

addEventListener("load", () => { route(); poll(false); });  // a comparison started before a reload keeps showing its progress
