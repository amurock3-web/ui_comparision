# Phase 15 + 16: new Applitools-style checks, and an easier web app (Claude Code prompts)

## The plan in one page

**Part A (Phase 15), new checks.** Each one adds an Applitools idea or fills an unbuilt row in
`docs/test_cases_pass_fail.md`:

| Prompt | Feature | Spec rows | Depends on |
|---|---|---|---|
| 15.0 | Screen rules file + **match levels** (Strict / Layout / Ignore Colors) per screen and per region | all | 14.1 (ignore regions) |
| 15.1 | **Dynamic text patterns** (duration, episode, price, rating…) + **floating regions** | E1, C1 | 15.0 |
| 15.2 | **Contrast Advisor**: WCAG contrast + text colour | D7, D3 | — |
| 15.3 | **Localization**: wrong script/language | E4 | — |
| 15.4 | **Logo / icon correct + broken image** | F1, F2, F3 | — |
| 15.5 | **Baseline library** (screen × device × language), **batch runner**, **run history** (new / fixed / still open) | A5, B9 | 15.0 |
| 15.6 | **Ticket export** (CSV) | — | 14.3 |

**Part B (Phase 16), web app changes** (`src/app.py`, http://127.0.0.1:8765):

| Prompt | Change | Why it makes the tool easier |
|---|---|---|
| 16.0 | **One-click start** (`UI Compare.bat` + desktop shortcut), health check chips, free-port pick | No terminal, no env vars to remember; problems show with the fix command |
| 16.1 | Split the app into pages with a **top menu** (Compare · Results · History · Batch · Baselines · Rules · Help) + a **History** page | Every past run is one click away |
| 16.2 | **Results page**: issue cards, click-to-highlight on the image, filters, Accept / Ignore buttons, **quick re-run in seconds**, downloads | Review, decide and re-check without leaving the page |
| 16.3 | **Baselines** and **Batch** pages | Pick a saved client design instead of uploading it (about half the run time saved); drop many screenshots at once |
| 16.4 | **Rules editor**: draw ignore / floating / layout regions on the image, set the match level | Testers tune a screen without editing YAML |

**Before you start:** do Phase 14 first. 15.0 extends 14.1's ignore regions, 16.2 uses
14.3's issues and 14.4's accepted differences. If one isn't done, the prompt tells Claude
Code to stop and say so.

**Suggested order** (quick wins first, each step usable on its own):
16.0 → 15.0 → 15.1 → 16.1 → 16.2 → 15.2 → 15.3 → 15.4 → 15.5 → 16.3 → 15.6 → 16.4

**How to use.** Paste one prompt at a time into Claude Code. Read its plan, say "go", run the
commands it gives, and check the result before the next one.

**Stays true throughout:**
- Everything local (rules.md §2).
- Standard-library web server, no CDN / Google Fonts.
- Thresholds in `config/`.
- Every feature has an `enabled` switch, and off = today's output.
- Self-compare stays 100% PASS.

---

## Part A: new checks

### Prompt 15.0: screen rules + match levels

```
Task: Applitools-style match levels. Let a screen (and a region of it) choose how strict the
comparison is, via one rules mechanism.

Read first: CLAUDE.md, docs/rules.md, docs/test_cases_pass_fail.md, docs/memory.md (Phase 14),
config/config.yaml, src/comparison/differ.py, src/comparison/regions.py (from 14.1; if 14.1 is
not done, stop and tell me), src/reporting/report.py (coverage), scripts/rematch.py, src/app.py.
Use graphify query where it helps.

Design (discuss first; push back if the code suggests a better hook):
1. Match levels, applied per element (the client element decides):
     STRICT        every check (today's behaviour)
     LAYOUT        structure + geometry only: A*, B*, C1-C4. Skip E* text, D* colour, F*.
     IGNORE_COLORS everything except D*.
     NONE          nothing, same as an ignore region (use only inside regions)
   The mapping level -> spec families lives in config, not code.
2. Where a level comes from, most specific wins:
     region (by >= min_overlap of the client element's area) > screen rules file >
     config default comparison.match_level (default STRICT = today)
3. Screen rules file: config/screen_rules/<client_screen_id>.yaml, e.g.
     match_level: LAYOUT
     regions:
       - {name: status_bar, type: NONE, bbox_norm: [0, 0, 1, 0.04]}
       - {name: hero, type: LAYOUT, bbox_norm: [0, 0.06, 1, 0.30]}
   14.1's ignore_regions become regions of type NONE: one mechanism, not two. Keep the
   14.1 config working (read it as a default region list).
   rematch, run_comparison and the app take an optional --rules <file> / --match-level
   override; otherwise the file is looked up by client screen id.
4. The report records, per finding and in summary, which level applied, and coverage marks
   checks skipped by the level as "skipped (LAYOUT)" instead of "PASS". Skipped is not passed.

Tests (tests/test_match_levels.py, hand-made docs, no images):
- LAYOUT: a text change -> no E1 finding; a moved button -> C1 still fires
- IGNORE_COLORS: colour change skipped, text change still fires
- a LAYOUT region inside a STRICT screen only relaxes elements inside it
- coverage says "skipped", not "PASS"
- no rules file + default STRICT -> identical to today; self-compare 100% PASS

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch (seconds, no
OCR). Do not run the detector, OCR, run_comparison or the benchmark. Give me the commands and
the expected finding counts for the lang pair under STRICT and LAYOUT. Add a Phase 15 section
to docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```

### Prompt 15.1: dynamic text patterns + floating regions

```
Task: two Applitools ideas on top of 15.0's rules.
(a) Dynamic text: some static-looking labels legitimately change value but must keep their
    FORMAT (prices on a plan screen, durations, episode numbers). Compare the pattern, not the
    value.
(b) Floating regions: an element may move inside an allowed box without a C1 finding.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md (E1, C1, §H), src/comparison/differ.py
(E1 block, C1 block), src/comparison/matcher.py (_normalize_text), config/config.yaml,
config/screen_rules/ (15.0; stop if missing).

(a) Design:
- config comparison.dynamic_text: {enabled, classes: [<defaults to static_text_classes>],
  patterns: {name: regex}}. Starting patterns (case-insensitive, full match after trim);
  CHECK them against the OCR text in the saved fused JSONs and tell me which fire:
    duration: '^\d{1,2}\s?h(\s?\d{1,2}\s?m)?$|^\d{1,3}\s?(m|min|mins)$'
    episode:  '^S\d{1,2}\s?E\d{1,3}$'
    price:    '^(₹|Rs\.?)\s?\d{1,3}(,\d{3})*(\.\d{1,2})?(\s?/\s?(month|mo|year|yr))?$'
    rating:   '^(U|UA|U/A|A|S)(\s?\d{1,2}\+)?$'
    date:     '^\d{1,2}\s(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(\s\d{4})?$'
    count:    '^\d+(\.\d)?\s?[km]?\s?(views|likes)?$'
- E1 rule: both texts fully match the SAME pattern -> PASS, details.pattern = name.
  Client matches a pattern but production matches none -> E1 FAIL as today, with
  details.expected_format = name ("format broken").
- Screen rules may add patterns: patterns: {plan_name: '...'}.
- Never applies inside content cards (§H stays as is).

(b) Design:
- New region type FLOATING in the screen rules: {name, type: FLOATING, bbox_norm,
  max_offset_norm}. For a client element inside it, C1 uses max_offset_norm as its PASS band
  (REVIEW/FAIL above it as today). Residual after group shift, as today.

Tests (tests/test_dynamic_text.py, tests/test_floating.py): "₹199/month" vs "₹299/month" ->
PASS; "₹199/month" vs "199" -> FAIL format broken; "S1 E3" vs "S2 E10" -> PASS; a pattern
name that matches only one side -> FAIL; floating element moved 0.02 within max 0.03 -> PASS,
0.05 -> finding; enabled:false / no FLOATING region -> identical to today.

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch. No detector,
OCR, run_comparison or benchmark. Give me the commands and which patterns fired on the real
pairs. Add a line to docs/memory.md (Phase 15). Run `graphify update .`, list the files changed,
and stop.
```

### Prompt 15.2: contrast (D7) + text colour (D3)

```
Task: an Applitools "Contrast Advisor"-style check, all local image math. For each static-text
element, split its OCR box into text pixels and background pixels, then measure
(D7) the WCAG contrast ratio, and (D3) the text colour against the client's.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md (D3, D7, §H), src/comparison/color_checks.py
(style: pure functions returning measurements; bands applied in differ), src/comparison/differ.py
(_element_color, _shows_artwork_through), config/config.yaml (comparison.color).

Design (discuss first):
- color_checks.py: split_text_background(crop) -> (text ColorSample, background ColorSample,
  text_fraction). cv2.kmeans with k=2 on the crop; the SMALLER cluster is text (the spec's
  method). reliable=False when the clusters are too close (dE < a config floor) or
  text_fraction is outside a sane range.
- wcag_contrast(rgb_a, rgb_b): relative luminance per WCAG 2.x, ratio (L1+0.05)/(L2+0.05).
- D7 (per matched static-text pair, production side, compared to the client):
    PASS if ratio >= 4.5, or production ratio >= client ratio - tolerance ("same as template")
    REVIEW 3-4.5, FAIL < 3 (Major). Large text (box height >= config large_text_height_norm)
    uses 3.0 as the PASS line, per WCAG. All numbers in config comparison.contrast.
- D3: dE2000 between production and client text colour, bands 5 / 10 from the spec.
- Scope: static_text_classes + OCR text outside cards. Never inside content/cast/celebrity
  cards (§H). Skip when _shows_artwork_through is true (text over a poster) or reliable=False,
  and count those as "not measured" in coverage.
- Respect 15.0 match levels (D* is skipped under LAYOUT / IGNORE_COLORS).
- Update SPEC_BY_TYPE / IMPLEMENTED in report.py, HTML wording e.g.
  "'Save' text contrast 2.8:1 (client 7.1:1)".

Tests (tests/test_contrast.py, synthetic crops): white text on black -> 21:1; the WCAG
reference pair #777777 on white = 4.48:1 (within 0.01); grey on grey -> FAIL; production equal
to a low-contrast client -> PASS ("same as template"); noisy crop -> not measured; off -> today.

Plan first and wait for my OK. After my OK you may run pytest and scripts.rematch with
--production-image/--client-image. No detector, OCR, run_comparison or benchmark. Show me a
table of measured ratios on both real pairs before any threshold is final. Record it in
docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```

### Prompt 15.3: localization (E4)

```
Task: detect a wrong language on screen (E4, Critical). SunNXT ships Tamil/Telugu/Kannada/
Malayalam/Hindi builds; OCR already returns those scripts.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md (E4, E1), src/comparison/differ.py (E1),
src/comparison/matcher.py (_normalize_text, _text_score), the saved fused JSONs of both pairs
(the lang screen shows language names in their own scripts on purpose).

Design (discuss first):
- New pure module src/comparison/script_checks.py: dominant_script(text) from Unicode ranges
  (Latin, Devanagari, Bengali, Tamil, Telugu, Kannada, Malayalam, other), ignoring digits,
  punctuation and symbols like ₹; returns (script, share).
- Per matched static-text pair: different dominant scripts (both shares >= config min_share)
  -> E4 LANGUAGE_DIFFERENCE, FAIL Critical, and NO E1 finding for the same pair.
- Screen-level: dominant script over all static text on each side; different ->
  one E4 screen finding naming both scripts.
- Screens that are multi-script by design (language picker): the screen rules file (15.0) can
  set expected_scripts: any. Check the lang pair and tell me if it needs that.
- Record each side's dominant script in report["confidence"] (useful for 15.5 baselines).

Tests (tests/test_script_checks.py): "Movies" vs "திரைப்படங்கள்" -> E4, no E1; Latin vs Latin ->
no E4; "₹199" -> script ignored; mixed text below min_share -> no finding; expected_scripts: any
-> no screen finding; self-compare unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch. No detector,
OCR, run_comparison or benchmark. Give me the commands and what the lang pair shows. Add a line
to docs/memory.md. Run `graphify update .`, list the files changed, and stop.
```

### Prompt 15.4: logo / icon correct (F1, F2) + broken image (F3)

```
Task: three image checks from the spec, all local.
  F1 logo correct   crop SSIM >= 0.90 PASS, < 0.75 FAIL Critical, between REVIEW
  F2 icon correct   crop SSIM >= 0.85 PASS, else FAIL Major (or a perceptual hash distance)
  F3 broken / placeholder image: a card area that is almost flat (low variance) = image did
     not load. This is a PRESENCE check on the container, allowed by §H; never compare what
     the poster shows.

Read first: CLAUDE.md, docs/test_cases_pass_fail.md (F, §H), src/comparison/color_checks.py
(module style), src/comparison/differ.py, config/config.yaml, requirements.txt.

Design (discuss first):
- New pure module src/comparison/image_checks.py:
    ssim(crop_a, crop_b): grayscale, resize both to the client crop size, standard Gaussian
      SSIM with numpy + cv2 (no new dependency; tell me if scikit-image is already installed)
    dhash(crop) + hamming distance, as a second opinion for tiny icons
    flatness(crop): luminance std + edge density; flat = below config thresholds
- F1 on matched logo pairs, F2 on matched icon pairs (use whatever class names the 16-class
  taxonomy has; tell me). F3 on every content/cast/celebrity card on the PRODUCTION side
  (client may be a mockup with grey placeholders: if the client card is flat too -> PASS).
- Resize-then-SSIM is right here (identity of the picture, not its size; size is C2's job).
- All thresholds in config comparison.image. Respect 15.0 match levels (F* skipped under LAYOUT).

Tests (tests/test_image_checks.py, synthetic): identical crops -> SSIM 1.0; a different shape
-> F2 FAIL; a flat grey card -> F3 FAIL; flat on both sides -> PASS; off -> today.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch with images.
No detector, OCR, run_comparison or benchmark. Show me the measured SSIM / flatness values on
both real pairs before thresholds are final; record them in docs/memory.md. Run
`graphify update .`, list the files changed, and stop.
```

### Prompt 15.5: baseline library + batch runner + run history

```
Task: three things that make the tool usable every day.
(a) Baseline library: save a client design ONCE (its fused JSON + graph), keyed by
    screen × device × language. Later runs reuse it, so only the production side needs the
    detector + OCR (about half the run time).
(b) Batch runner: many production screenshots in one go.
(c) History: compare a run with the previous run of the same screen -> new / fixed / still open.

Read first: CLAUDE.md, README.md, src/pipeline.py, src/app.py, scripts/run_comparison.py,
scripts/rematch.py, src/reporting/report.py, src/reporting/grouping.py (14.3),
config/screen_rules/ (15.0), docs/rules.md §15 (reproducibility).

Design (discuss first):
(a) baselines/<screen_id>/<device>/<language>/ with client.<ext>, client_fused.json,
    meta.json (created date, source file, detector/OCR versions, config hash) and optionally
    rules.yaml (the 15.0 screen rules live here once a baseline exists).
    device = "phone" / "tablet" / "tv" (inferred from aspect ratio, overridable);
    language from 15.3's dominant script if available, else "default".
    scripts/add_baseline.py <client_image> --screen <id> [--device] [--language]
    scripts/run_comparison.py gains --baseline <screen>[/<device>/<language>].
    baselines/ images are NOT committed (add to .gitignore like input/output); JSON may be.
    A baseline whose meta config hash differs from the current detector/OCR config is flagged
    "stale, re-add" (never silently reused).
(b) scripts/run_batch.py <folder> [--baseline-by filename|screen-id]: pairs each production
    screenshot with a baseline, runs one at a time, is resumable (skips finished items), and
    writes output/batch/testN_<name>/summary.json + summary.html (screen, verdict, similarity,
    issues, link to each report). One item failing never stops the batch.
(c) src/reporting/history.py: finding identity = type + client element id (stable, because
    the client side comes from the baseline) + a signature (text / colour / direction).
    previous run = latest earlier run with the same baseline key. report["history"] =
    {previous_run, new: [...], fixed: [...], still_open: [...]}.

Tests: baseline add/load round-trip; stale-hash detection; batch resumes after an item fails;
history new/fixed/open on hand-made reports; no baseline -> today's upload flow unchanged.

Plan first, wait for my OK. After my OK you may run pytest and scripts.rematch. Ask before any
command that runs the detector or OCR (e.g. add_baseline or a batch): tell me how long it
will take. Give me the commands. Add a line to docs/memory.md. Run `graphify update .`, list the
files changed, and stop.
```

### Prompt 15.6: ticket export

```
Task: export findings as ticket rows so testers stop re-typing them.

Read first: CLAUDE.md, src/reporting/report.py, src/reporting/grouping.py (14.3; stop if
missing), src/app.py.

Design:
- src/reporting/export.py: to_ticket_rows(report, run_dir) -> list of dicts, one row per ISSUE
  (not per finding): run id, date, screen, baseline key, spec id, severity, verdict, element
  class + text, one-sentence description (same wording as the HTML), count, report path.
- Column names and order in config/ticket_export.yaml so they can match our existing ticket
  sheet; ask me for the sheet's columns before finalising defaults.
- CSV with the stdlib csv module, UTF-8 with BOM (so Excel shows Tamil/₹ correctly).
  XLSX only if openpyxl is already installed; don't add a dependency without asking.
- Only verdicts FAIL and REVIEW; accepted (14.4) and ignored findings excluded.
- CLI: python -m scripts.export_tickets <report.json> [--out file.csv]
- No screenshots embedded; the row points to the local report path.

Tests: row count = issue count; accepted excluded; Tamil text survives a CSV round-trip.
Plan first, wait for my OK. You may run pytest. Give me the command for the latest lang report.
Run `graphify update .`, list the files changed, and stop.
```

---

## Part B: web app changes

### Prompt 16.0: one-click start + health check

```
Task: make the web app start with one double-click and say clearly what is wrong if it can't
work. No UI redesign yet.

Read first: CLAUDE.md (Environment traps), README.md (Setup, Web UI), src/app.py,
config/detector.yaml, src/detector/engine.py (how UI_DETECTOR_PYTHON / python_path are
resolved), .env.example if present.

1. Launcher at the project root: "UI Compare.bat" (Windows) and start.sh (Linux/Docker).
   It: cd's to the project, activates .venv if present, loads UI_DETECTOR_PYTHON from a local
   .env or config (never hard-code my path), runs python -m src.app, and keeps the window
   open with the error if the app dies.
   scripts/make_shortcut.ps1 puts a "UI Compare" shortcut on the Windows desktop.
2. src/app.py:
   - --port (default 8765); if taken, try the next 10 ports and print the one used.
   - --no-browser flag.
   - GET /health -> checks, each {name, ok, message, fix}: detector python exists, detector
     weights exist, paddleocr importable, config files parse, output/ writable,
     Edge found (PDF), Ollama reachable ONLY if the VLM is enabled in config.
     Cheap checks only (no model loading); cache for 30 s.
   - The page shows the checks as small green/amber/red chips at the top; a red one disables
     Compare and shows its fix command.
3. LAN access stays OFF. Add a --lan flag that is refused unless config app.allow_lan: true
   (default false); when on, bind 0.0.0.0, require a random access token in the URL, print a
   warning that screenshots leave this PC for the company network (rules.md §2: my manager
   must approve). Describe it, but don't enable it.
4. README "Web UI" section: double-click launcher first, command line second.

Tests: port fallback picks a free port; /health returns the documented shape; a missing
detector python gives ok=false with a fix; --lan refused when allow_lan is false.
Plan first, wait for my OK. You may run pytest. Do not start the app or the pipeline. Give me
the exact steps to try the launcher. Add a line to docs/memory.md (Phase 16). Run
`graphify update .`, list the files changed, and stop.
```

### Prompt 16.1: pages, menu and a History page

```
Task: restructure the single-page app into a small multi-page local app with a top menu,
and add a History page. Keep the stdlib http.server (no Flask/Gradio, no CDN, no web fonts).

Read first: CLAUDE.md, src/app.py (whole file), README.md (Web UI), output/app/ (what a run
folder holds), src/reporting/html_report.py.

1. Turn src/app.py into a package src/app/ (python -m src.app must still work):
     __main__.py      entry point + CLI flags (from 16.0)
     server.py        routes, JSON API, one-job-at-a-time runner (today's lock/state)
     runs.py          list/read run folders (report.json, inputs, fused JSONs)
     static/          index.html, app.css, app.js (vanilla JS, hash-router: #/compare,
                      #/results/<run>, #/history, #/batch, #/baselines, #/rules, #/help)
   Move the existing PAGE/CSS/JS there unchanged first, then add pages.
   Only serve files from static/ and from output/app/<run>/ via whitelisted names
   (keep today's path regex approach; no directory traversal).
2. Top menu on every page: Compare · History · Batch · Baselines · Rules · Help, plus the
   health chips from 16.0. Batch / Baselines / Rules show "coming soon" until 16.3 / 16.4.
3. Compare page = today's drag-and-drop flow; when a run finishes it goes to #/results/<run>
   (for now the existing iframe report there; 16.2 replaces it).
4. History page: GET /api/runs -> newest first: run id, date, production name, client name,
   verdict, similarity, findings count, has_pdf. Table with a search box and verdict filter;
   click a row -> #/results/<run>; per row: open HTML, download PDF. Handles old run
   folders that lack newer fields.
5. Help page: what each verdict means, the spec families A–G in one line each, where
   runs are stored, how to start the app.
6. Light/dark follow the system theme (keep today's CSS variables). Works at phone width.

Tests: /api/runs on a temp folder with a new and an old-format run; path traversal
(/run/../../x) refused; python -m src.app --help still works.
Plan first, wait for my OK. You may run pytest. Do not start the pipeline. Tell me how to start
the app to click through it myself. Run `graphify update .`, list the files changed, and stop.
```

### Prompt 16.2: results page

```
Task: replace the results iframe with a proper review page, so a tester can understand,
decide and re-check without opening files.

Read first: CLAUDE.md, src/app/ (16.1; stop if missing), src/reporting/report.py,
src/reporting/grouping.py (14.3), accepted differences (14.4), src/comparison/regions.py and
config/screen_rules/ (14.1 / 15.0), scripts/rematch.py, src/reporting/html_report.py
(what it already draws). If any of 14.3 / 14.4 / 15.0 is missing, build what you can and list
what is disabled.

Page #/results/<run>:
1. Header: verdict badge, the existing headline ("Matched X of Y …"), match level used,
   and counts per verdict. History strip if 15.5 exists (new / fixed / still open).
2. Side-by-side viewer: production and client images with boxes drawn on a <canvas>.
   Clicking an issue highlights its boxes on both sides and scrolls the image to them;
   hovering a box shows the element class + text. Zoom buttons. The findings need bboxes:
   add production_bbox_norm / client_bbox_norm to each finding in report.py if missing.
3. Issue list (from 14.3), sorted Critical > Major > Minor > REVIEW; filter chips by verdict
   and by spec family (A–G); each card shows the one-sentence description and its findings.
4. Actions per issue (POST /api/runs/<run>/actions, all local files):
     Accept         -> 14.4 accepted_differences entry with a note
     Ignore region  -> adds a NONE region around the element to the screen rules file (15.0)
     Mark as bug    -> stored in <run>/review.json (issue id, note, time); shown as a tag
   Every action shows what file it changed and can be undone from the page.
5. "Re-check" button: re-runs matching → differ → report from the run's saved fused JSONs
   (same code path as scripts.rematch, in-process, seconds, no OCR), with an optional match
   level dropdown. Writes a new numbered report in the same run folder and switches to it;
   older reports stay (never overwrite).
6. Downloads: PDF (existing Edge path), HTML, report.json, tickets CSV (15.6 if present).

Tests: actions write the expected files and undo restores them; re-check produces a new report
and keeps the old one; a finding without bboxes still renders; old run folders still open.
Plan first, wait for my OK. You may run pytest and scripts.rematch. Do not run the detector or
OCR. Tell me how to try it on an existing output/app run. Add a line to docs/memory.md. Run
`graphify update .`, list the files changed, and stop.
```

### Prompt 16.3: Baselines and Batch pages

```
Task: web pages for 15.5's baseline library and batch runner (stop if 15.5 is missing).

Read first: CLAUDE.md, src/app/ (16.1/16.2), scripts/add_baseline.py, scripts/run_batch.py,
src/reporting/history.py.

1. Baselines page: table of baselines (screen, device, language, created, stale flag,
   thumbnail); "Add baseline": drop a client design + screen / device / language fields ->
   runs detector + OCR for the client side once (show progress, one job at a time, same queue
   as Compare); delete-with-confirm (the image is removed, meta is kept in an archive/ folder).
2. Compare page: a toggle "Client: upload an image | use a saved baseline" with a searchable
   baseline dropdown. With a baseline, only production runs through detector + OCR; show the
   expected time saving.
3. Batch page: drop many production screenshots (or pick a folder); each row auto-pairs with
   a baseline by file name / screen id, editable per row; Start runs them in the shared queue;
   live table (queued / running / done / failed, verdict, similarity, issues); a finished row
   opens #/results/<run>; download the batch summary.
4. The queue: replace today's 409 "already running" with a visible queue (position shown),
   still one job at a time (CPU OCR / 8 GB VRAM).

Tests: baseline list with a stale entry; queue ordering; a batch row with no baseline is
flagged, not run. Plan first, wait for my OK. You may run pytest. Ask before anything that runs
the detector or OCR. Run `graphify update .`, list the files changed, and stop.
```

### Prompt 16.4: rules editor

```
Task: let a tester tune a screen in the browser: draw regions on the client image and pick
the match level, saved to that screen's rules file (15.0; stop if missing).

Read first: CLAUDE.md, config/screen_rules/ format (15.0/15.1), src/comparison/regions.py,
src/app/ (16.1–16.3).

1. Rules page: choose a screen (from baselines, or from recent runs' client screen ids).
   Shows the client image with the existing regions drawn in colours by type.
2. Draw a rectangle with the mouse -> pick type: NONE (ignore), FLOATING (+ max offset
   slider), LAYOUT, IGNORE_COLORS, STRICT -> name it. Move/resize/delete regions. Screen-level
   match level dropdown. Extra dynamic_text patterns (15.1) as simple name + regex rows with a
   "test against this screen's OCR text" button that lists what matches.
3. Save writes the YAML (bbox_norm, i.e. fractions of width/height) with a backup of the
   previous version; the page validates before saving (regions inside the image, regex
   compiles).
4. "Try on last run": re-check (16.2) the latest run of this screen with the new rules and
   show the before/after finding count.

Tests: saved YAML round-trips through 15.0's loader; invalid regex refused; backup created.
Plan first, wait for my OK. You may run pytest and scripts.rematch. Run `graphify update .`,
list the files changed, add a line to docs/memory.md, and stop.
```
