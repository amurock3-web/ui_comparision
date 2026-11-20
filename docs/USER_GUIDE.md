# User guide (for testers)

## What the tool does

- You give it two pictures of the same OTT app screen: the **production** screenshot (the real app)
  and the **client** design (the mockup the client approved).
- It finds every UI element on both (buttons, tabs, rails, cards, labels) and compares their
  position, size, shape, colour and static text.
- It gives one verdict for the screen, **PASS**, **REVIEW** or **FAIL**, and a list of findings
  with boxes drawn on both pictures.
- Everything runs on your computer. Nothing is uploaded anywhere.

**What you need:** setup is already done on this computer (`setup.bat` / `setup.sh` was run once).
If it was not, see [HOW_TO_SETUP.md](HOW_TO_SETUP.md). The start-up messages and the coloured chips
at the top of the app tell you if something is missing.

## Using the drag-and-drop app

### 1. Start it

- **Windows:** double-click `UI Compare.bat` in the project folder.
- **Ubuntu:** run `bash start.sh` in the project folder.

A black console window opens and stays open while you work. Your browser opens
**http://127.0.0.1:8765** (or the next free port, up to 8775; see the [FAQ](#faq)). To stop the app, close the console window (or press `Ctrl+C` in it).

If the console says "Setup has not been run on this computer", run `setup.bat` / `bash setup.sh`
first (see [HOW_TO_SETUP.md](HOW_TO_SETUP.md)).

![Drag-and-drop page](images/app_home.png)

The menu at the top has six pages: **Compare**, **History**, **Baselines**, **Batch**, **Rules**,
**Help**. Next to it are the health chips: ✓ (green) means the check passed; ✗ means it failed. A red
✗ is a required check and disables the **Compare** button; the line under the menu says how to fix it.
An amber ✗ (for example Edge for PDFs) is optional.

### 2. Compare one screen

1. Open **Compare**.
2. Choose where the client side comes from:
   - **Client: upload an image**: you drop the client design yourself, or
   - **Client: use a saved baseline**: pick a stored client design from the list (type in
     **Search baselines** to filter). Only the production side then needs detector + OCR, so it
     takes about half the time. See [Baselines](#baselines-store-a-client-design-once).
3. Drop the production screenshot on the **Production** box (or click it to browse).
4. Drop the client design on the **Client design** box (not shown when you use a baseline).
5. Press **Compare**.

Tip: name the client file after the screen (for example `home.png`). The file name becomes the
screen id, and the [screen rules](#rules-page-for-the-person-who-tunes-a-screen) for that screen are
picked by it.

### 3. Wait

A progress bar shows the steps: Detector, OCR, Fusion and Graph for production, the same for the
client, then Matching, Report and PDF. A full pair takes about **2 minutes** on a normal laptop
(about 1 minute with a baseline). Almost all of that time is the text reader (OCR), which takes
about 45 s per screenshot because it runs on the CPU, not a graphics card.

Only one heavy job runs at a time. If someone else (or another tab) is already running one, yours
shows **Queued (#n)** and starts by itself.

### 4. Look at the result

When it finishes, the **Results** page opens.

![A finished run](images/app_result.png)

- At the top: the verdict, how many issues are FAIL / REVIEW / PASS, and the match level used.
  If the same client screen was compared before, a line shows **new**, **fixed** and **still open**
  issues since that run.
- The two pictures side by side (**Production** and **Client design**) with a box for every
  finding. Click an issue in the list to highlight its boxes; hover a box to see its class and
  text. **−** / **+** zoom.
- Filter buttons: by verdict (FAIL, REVIEW, PASS) and by spec family (A to G).
- The issues list, worst first: FAIL Critical, Major, Minor, then REVIEW. Click one to see its
  findings.
- Downloads: **PDF**, **HTML** (the full report, opens in a new tab), **report.json** and
  **Tickets CSV** (one row per issue, opens in Excel).

### 5. Act on an issue

Each issue has three buttons. Every change says which file it wrote, is listed under **Changes made
from this page**, and has an **Undo** button.

| Button | Use it when | What it does |
|---|---|---|
| **Accept** | The difference is on purpose (the client asked for it). You type a reason. | Saves it in `baselines/accepted_differences.yaml`. Later runs show it as PASS (accepted) until that element changes again. |
| **Ignore region** | That area of the screen should never be compared (for example a promo banner). | Adds an ignore (NONE) region to `config/screen_rules/<client screen>.yaml`. |
| **Mark as bug** | It is a real defect you will report. | Tags it in the run's `review.json`. |

After **Accept** or **Ignore region**, press **Re-check**. It redoes the matching and the report
from the saved OCR in a few seconds and saves `report_2.json` / `.html` next to the first one
(nothing is overwritten). The dropdown next to **Re-check** lets you try another
[match level](#match-levels). Use the **Report** dropdown to switch between `report.json`,
`report_2.json` and so on.

### History

**History** lists every run, newest first: run name, date, both file names, verdict, similarity,
number of findings and issues, and links to the HTML / PDF report. Type in the search box (run, date
or file name) or filter by verdict. Click a row to open its Results page. Runs are stored in
`output/app/<YYYYMMDD_HHMMSS>/`.

### Baselines: store a client design once

A baseline is a client design that was read once (detector + OCR, about 1 minute) and stored in
`baselines/<screen>/<device>/<language>/`. After that, every comparison against it only reads the
production screenshot.

On **Baselines**: drop the client design, fill **Screen id** (for example `home`), leave **Device**
on **auto** (or pick phone / tablet / tv) and **Language** empty (= `default`), press
**Add baseline**. The table lists all baselines; **State** shows `ok` or **stale - re-add**.
**Delete** removes one (its data is kept in `baselines/_archive/`).

### Batch: many production screenshots

On **Batch**: drop many production screenshots. Each one is paired with a baseline by **Pair by**:

- **file name = screen id**: `home.png` uses the baseline `home`.
- **screen id prefix**: `home_2026-09-25.png` uses the longest baseline id the name starts with.

You can change the baseline per row. Rows with no baseline are not run. Press **Start**; the table
fills in live (status, verdict, similarity, issues). **Download summary (JSON)** saves the table.
Every item is also a normal run in **History**. The table itself is lost when the app restarts.

### Rules page (for the person who tunes a screen)

**Rules** edits `config/screen_rules/<screen>.yaml` for one client screen: drag on the screenshot
to draw a region, set the **Screen match level**, add **Dynamic text patterns**, then **Save rules**
(the old file is kept as `.bak`). **Try on last run** shows how the counts would change. Most
testers only need **Ignore region** on the Results page instead.

## Reading the report

![Sample report](images/sample_report.png)

The HTML report (and the PDF, which is the same page printed) has these parts, top to bottom:

| Part | What it tells you |
|---|---|
| Verdict | PASS, REVIEW or FAIL for the whole screen. The note under it says how many test cases are built: a PASS means "passed those checks", not "nothing else can be wrong". |
| Stats | Matched elements out of comparable ones (the similarity %), plus clean, missing, extra and ignored counts, number of findings and minor warnings. |
| Side by side | Both pictures. Green box = matched, grey = skipped (dynamic content or ignored), thick coloured box = a finding, labelled with its type. A note appears if the two pictures have very different shapes (aspect ratio). |
| Issues | Shown when several findings are one problem repeated (for example every card in a rail moved). One row per problem. |
| Findings | Every finding: spec id, verdict, severity, what is wrong in plain words, and small crops from production and design. |
| Coverage | Every test case in the spec, whether it is built ("checked") or "not built", and its result here. "not built" means the report says nothing about it. |
| Pipeline details (folded) | For developers: what the tool was unsure of, both layout trees, run settings, the raw report. |

**Severity** (how bad a failure is):

- **Critical**: breaks the brand or makes the screen unusable (wrong orientation, missing Play button, wrong brand colour).
- **Major**: a normal user would see it (missing section, wrong tab highlighted, truncated title).
- **Minor**: only a designer would notice (a 2-3% shift, slightly different spacing).

**Spec ids** start with a letter for the family of check:

| Family | What it checks |
|---|---|
| A | Screen level: orientation, blank or broken screen. A Critical A failure skips B to G. |
| B | Layout and structure: missing or extra elements, section and tab order, alignment, spacing, overlap, clipping, cards per rail. |
| C | Position and size of each matched element, as a % of the screen. |
| D | Colour: brand, background, text, selected state, badges, contrast. |
| E | Static text only (tabs, buttons, section titles): wording, truncation, case, script, font size. |
| F | Logo and icons; broken or stretched images. Never poster artwork. |
| G | Interaction state: same tab selected, focus ring, enabled/disabled look. |

**What the verdict means:**

| Verdict | Meaning | What you do |
|---|---|---|
| PASS | Every check is within tolerance. | Nothing. |
| REVIEW | Borderline, or the tool is not sure (low confidence, ambiguous match, text it could not read, an element cut off by the screen edge). Also given when the worst finding is a Minor FAIL. | A person looks at the findings and decides: Accept, Ignore region or Mark as bug. |
| FAIL | At least one Critical or Major failure: a real layout defect. | Check the finding, then report it (Mark as bug, Tickets CSV). |

The full rules for every check are in [test_cases_pass_fail.md](test_cases_pass_fail.md).

## What is never compared (on purpose)

These parts change every day on a live OTT app. They are content, not design, so a different value
is never a defect:

- Poster and thumbnail artwork inside cards, and the hero banner image (only its container,
  gradient and buttons are checked).
- Movie and show titles and their details inside rails (year, duration, rating).
- The status bar at the top: time, battery, network. It is always an ignore region.
- Continue-watching progress (only that the bar is there), rank number values (only presence and
  style), ads and promo content.
- Badges and labels sitting on a poster card (Free, Most Viewed, premium crown), because they depend
  on the title.

The tool still checks the **container**: that the card is there, has the right shape and is in the
right place. Full list: [test_cases_pass_fail.md, section H](test_cases_pass_fail.md#h-ignore-list-always-pass-never-compare-content).

## Commands

Run these in a terminal opened in the project folder. On Windows use `.venv\Scripts\python.exe`;
on Ubuntu replace it with `.venv/bin/python` (same arguments). Every command writes a new numbered
`testN_*` output and never overwrites an earlier run.

**Compare a pair** (~2 min). Output: `output/comparison/testN_<screen>_report.html` (open this),
plus `_report.json`, `_report.png`, `_comparison.json` and the two `_fused.json` files.

```
.venv\Scripts\python.exe -m scripts.run_comparison <production.png> <client.png>
```

**Store a baseline, then compare against it** (~1 min each). `--device phone|tablet|tv` and
`--language <code>` are optional (default: device from the picture's shape, language `default`).
`--list` shows every stored baseline.

```
.venv\Scripts\python.exe -m scripts.add_baseline <client_image> --screen <id>
.venv\Scripts\python.exe -m scripts.add_baseline --list
.venv\Scripts\python.exe -m scripts.run_comparison <production.png> --baseline <id>
```

`--baseline` also takes `screen/device/language` when a screen has several baselines.

**Batch a folder** of production screenshots against stored baselines (~45 s per screenshot). By
default the file name is the screen id (`home.png` -> baseline `home`); add
`--baseline-by screen-id` to use the longest baseline id the name starts with. Output:
`output/batch/testN_<folder>/` with one report per screenshot and `summary.html`. A batch that
stopped can continue with `--resume output/batch/testN_<folder>`.

```
.venv\Scripts\python.exe -m scripts.run_batch <folder>
.venv\Scripts\python.exe -m scripts.run_batch <folder> --baseline-by screen-id
```

**Accept a finding** that is on purpose. `N` is the finding's position in the `findings` list of
`report.json`, counting from 0. Or accept a whole issue with `--issue issue_003`. `--note` is
required; `--by <name>` is optional. Saved in `baselines/accepted_differences.yaml`; re-run the
comparison (for example with `rematch`) to see it as PASS (accepted).

```
.venv\Scripts\python.exe -m scripts.accept_finding <report.json> --finding N --note "client asked for this"
```

**Export tickets** (FAIL and REVIEW issues, one row each). Output: `<report>_tickets.csv` next to the
report, or `--out file.csv`.

```
.venv\Scripts\python.exe -m scripts.export_tickets <report.json>
```

**Re-run the comparison from saved results** (seconds, no detector, no OCR). Use it after accepting
a finding, changing screen rules or trying a match level. It needs the two `_fused.json` files a
run saved (`output/comparison/testN_<screen>_production_fused.json` and `..._client_fused.json`,
or `production_fused.json` / `client_fused.json` in an `output/app/<run>/` folder). Output:
`output/rematch/testN_<screen>_report.html`. Giving the same file twice is a self-check: it should PASS.

```
.venv\Scripts\python.exe -m scripts.rematch <production_fused.json> <client_fused.json>
.venv\Scripts\python.exe -m scripts.rematch <production_fused.json> <client_fused.json> --match-level LAYOUT
.venv\Scripts\python.exe -m scripts.rematch <production_fused.json> <client_fused.json> --rules my_rules.yaml
```

### Match levels

A match level says which families of checks may report. `--match-level` and `--rules` are options of
`scripts.rematch` (not of `run_comparison`). In the app use the dropdown next to **Re-check**; to make
it permanent for a screen, set it on the **Rules** page.

| Level | What is compared |
|---|---|
| STRICT | Every check (A to G). The default. |
| LAYOUT | Structure and geometry only: skips D colour, E text and F images. |
| IGNORE_COLORS | Everything except D colour. |
| NONE | Nothing. Only used for regions (an ignore region), not for a whole screen. |

`--rules <yaml>` uses that screen rules file instead of `config/screen_rules/<client screen id>.yaml`.
A skipped finding is not deleted: it becomes PASS (ignored) and the report's Coverage shows the family
as skipped.

For all other commands (one stage at a time, benchmark, evaluation) see
[HANDOVER.md, section 6](HANDOVER.md#6-how-to-use-it).

## FAQ

**Why REVIEW and not PASS or FAIL?**
REVIEW means "a person should look". The tool gives it when a difference is borderline, when it is
not sure (it could not read a label on one side, an element is cut off by the screen edge, a match is
ambiguous), or when the worst finding is only Minor. It never turns doubt into a silent PASS.

**Why is it so slow?**
The text reader (OCR) takes about 45 s per screenshot on the CPU. A pair is about 2 minutes. To save
time: store the client design as a baseline (only production is read), and use **Re-check** /
`scripts.rematch`, which reuse the saved OCR and take seconds.

**Where are my old reports?**
- App runs: `output/app/<YYYYMMDD_HHMMSS>/` (`report.html`, `report.pdf`, `report.json`, the two
  screenshots). The **History** page lists them.
- Command-line runs: `output/comparison/testN_*`, `output/batch/testN_*`, `output/rematch/testN_*`.
- Which old runs matter: [output/INDEX.md](../output/INDEX.md).

**The screens look identical, so why is there a finding?**
The tool measures things the eye misses: a 2-3% shift, a slightly different colour, a different font
size, or one character OCR read differently. Click the finding to see its boxes and the crops in the
HTML report. If it is real but on purpose, **Accept** it. If that area should never be compared,
use **Ignore region**. If the tool is plainly wrong, tell the developer (see
[HANDOVER.md, section 9](HANDOVER.md#9-known-issues-and-limits) for known limits). Also check that the
two pictures are the same screen in the same state (same tab selected, same scroll position).

**Can I upload the screenshots to ChatGPT or another cloud tool?**
No. The screenshots and reports are client material and internal only. Everything in this tool runs
on your computer on purpose; do not upload, email outside the company or share them anywhere
([rules.md, section 2](rules.md)).

**The app opened on 8766 (or another number), not 8765.**
Port 8765 was already in use (often by an app that is still open in another console). The app takes
the next free port up to 8775 and prints the address in the console. To pick one yourself:
`"UI Compare.bat" --port 8800`.

**A baseline says "stale".**
It was stored under different detector or OCR settings, so it can no longer be trusted and cannot be
picked. Add it again from the same client design: on **Baselines** drop the image with the same
**Screen id**, or run `scripts.add_baseline <client_image> --screen <id>`. A report can also list
*stale acceptances*: accepted differences that matched nothing in this run. That is fine if the
element was removed or fixed; otherwise ask the developer to clean up
`baselines/accepted_differences.yaml`.

**There is no PDF button.**
The PDF is made with Microsoft Edge. Without Edge, open **HTML** and use the browser's
Print > Save as PDF. Only the first report of a run (not `report_2` and later) has a PDF.

**The Compare button stays grey.**
Either a file is missing (production, and client or a baseline), or a required health check failed:
read the red line under the menu. More fixes: [HANDOVER.md, section 12](HANDOVER.md#12-troubleshooting).
