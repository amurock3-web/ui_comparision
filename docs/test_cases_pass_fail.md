# UI Comparison — Pass / Fail Test Cases (v0 draft)

Written from the view of a QA / UI tester at a large OTT company.
Status: **proposed defaults**. No spec was provided by the manager, so every threshold here is a starting point to confirm, not a final rule.

---

## 0. Ground rules (read first)

**Inputs:** Template (client design) + Production screenshot of the same screen.

**Three verdicts, not two:**
- **PASS**: within tolerance.
- **REVIEW**: borderline, or the system is unsure (low detection confidence, ambiguous match). A human looks at it.
- **FAIL**: clearly outside tolerance.

**Severity:**
- **Critical**: breaks the brand or makes the screen unusable (wrong orientation, missing Play button, wrong brand color).
- **Major**: clearly visible to a normal user (missing section, wrong tab highlighted, truncated title).
- **Minor**: only a designer would notice (2–3% shift, slightly different spacing).

**Screen verdict:** any Critical or Major FAIL → screen FAILS. Only Minor fails → PASS with warnings. Any REVIEW and no FAIL → REVIEW.

**Normalize first:** template and production may come from different devices, so compare positions and sizes as a **% of screen width/height**, never raw pixels.

**Ignore dynamic content (very important):** real OTT screens change every day. Poster artwork, movie/show names inside rails, "Continue watching" progress, ranks, clock, battery and the status bar are **live data**, not design. A tester never fails a build because today's poster is different. Check the **container** (card exists, right shape, right place), not what's inside it.

---

## A. Screen-level

| ID | Check | How to measure | PASS | FAIL | Severity |
|---|---|---|---|---|---|
| A1 | Orientation | Image aspect ratio (w > h = landscape) | Same orientation | Different orientation | Critical |
| A2 | Blank / broken screen | % of pixels near one color; element count | Normal content | >90% single color, or 0 detected elements | Critical |
| A3 | Theme (dark vs light) | Mean brightness of background region | Same theme | Dark ↔ light swapped | Critical |
| A4 | Safe area / notch | Any element box inside top/bottom system-bar zone | Nothing overlaps system bars | Button/text under notch or nav bar | Major |
| A5 | Screen scaling | Ratio of key element sizes vs screen width | Within ±5% | UI zoomed/shrunk >15% overall | Major |

A Critical FAIL here (A1, A2) means the screens are not comparable element by element: the report says so once and skips sections B–G.

## B. Layout & structure

| ID | Check | How to measure | PASS | FAIL | Severity |
|---|---|---|---|---|---|
| B1 | Missing element | Template element with no match in production | All matched | Unmatched (button, tab, section title, logo, search bar) | Critical if button/nav/logo, else Major |
| B2 | Extra element | Production element with no template match | None | Unexpected button/banner/popup | Major |
| B3 | Section order | Order of `section_title` top→bottom | Same order | Rails swapped (e.g. "Trending" above "Continue Watching") | Major |
| B4 | Tab / nav order | Order of `tab_item` left→right | Same order | Tabs reordered | Major |
| B5 | Alignment | Left edges of items in a column/row (x variance) | Aligned within 0.5% width | One item sticks out >1.5% | Minor |
| B6 | Spacing | Gap between neighbors vs template gap | Within ±20% of template gap | >40% different | Minor |
| B7 | Overlap | IoU between elements that don't overlap in template | No new overlap | Text on text, badge covering title | Major |
| B8 | Clipping / cut off | Element box touches screen edge when template doesn't | Fully visible | Button/text cut by screen edge | Major |
| B9 | Cards visible per rail | Count of `content_card` per row | Same, or differs only because the screen is wider/narrower | Rail shows 1 card where template shows 3+ at same width | Minor (REVIEW if device differs) |

B4 also covers two tabs that swapped labels in place (same boxes, texts exchanged). B5 is not reported for an element already reported missing, extra, moved or resized — the misalignment is a side effect of that finding.

## C. Position & size (per matched element)

| ID | Check | How to measure | PASS | REVIEW | FAIL | Severity |
|---|---|---|---|---|---|---|
| C1 | Position shift | Center distance as % of screen diagonal | ≤1% | 1–3% | >3% | Minor → Major if >6% |
| C2 | Size change | Width & height ratio vs template | within ±5% | 5–15% | >15% | Minor / Major |
| C3 | Shape / aspect distortion | Box aspect ratio vs template | within ±5% | 5–10% | >10% (stretched poster, oval avatar) | Major |
| C4 | Wrong card type | Matched region class differs (`cast_card` vs `celebrity_card`) | Same class | Low confidence | Different class | Major |

## D. Color

Measure in **Lab color space using ΔE2000**, not RGB (RGB distance doesn't match what the eye sees).
Take the **dominant color** of the element box and ignore text pixels (k-means with k=2 and take the larger cluster, or sample the box border).

Rough meaning of ΔE: <2 nobody notices · 2–5 noticeable side by side · >5 obviously different.

| ID | Check | Region | PASS | REVIEW | FAIL | Severity |
|---|---|---|---|---|---|---|
| D1 | Brand / accent color | Primary buttons (Play, Subscribe), logo | ΔE ≤ 3 | 3–6 | >6 | Critical |
| D2 | Background color | Screen bg, nav bar bg | ΔE ≤ 3 | 3–6 | >6 | Major |
| D3 | Text color | Text pixels (smaller k-means cluster) of labels/titles | ΔE ≤ 5 | 5–10 | >10 | Major |
| D4 | Selected-state color | Active tab highlight / underline vs inactive tabs | Right tab highlighted, color ΔE ≤ 5 | — | Wrong tab highlighted, or no highlight | Major |
| D5 | Badge color | `overlay_badge` ("Free", "New", "Premium") | ΔE ≤ 5 | 5–10 | >10 | Minor/Major |
| D6 | Gradient / scrim | Dark fade over hero banner bottom (brightness profile) | Same direction and strength ±15% | — | Missing, so text becomes unreadable | Major |
| D7 | Contrast / readability | Text vs its background contrast ratio | ≥ 4.5:1 (WCAG AA) or same as template | 3–4.5 | <3:1 | Major |

## E. Text & typography (static UI text only)

Static text = tabs, buttons, section titles, menu labels ("Home", "Movies", "Play", "Trending Now"). **Not** movie names in rails.

| ID | Check | How to measure | PASS | FAIL | Severity |
|---|---|---|---|---|---|
| E1 | Wrong label text | OCR text after normalizing (trim, lowercase) | Exact match (or edit distance ≤1 to allow an OCR slip → REVIEW) | Different word ("Movie" vs "Movies") | Major |
| E2 | Truncation | Text ends in "…" or OCR text shorter than template | Full text | "Action Dra…" | Major |
| E3 | Case / style | Raw OCR text, case-sensitive | Same case | "HOME" vs "Home" | Minor |
| E4 | Language / localization | Script detection (Latin vs Devanagari etc.) | Same language | Wrong language shown | Critical |
| E5 | Font size | Text box height as % of screen height | within ±10% | >20% | Minor/Major |
| E6 | Text overflow | Text box extends outside its parent container | Inside | Spills out | Major |
| E7 | Text alignment | Text left/center/right within its container | Same | Centered vs left-aligned | Minor |

## F. Images, icons & logo

| ID | Check | How to measure | PASS | FAIL | Severity |
|---|---|---|---|---|---|
| F1 | Logo correct | Crop compare with SSIM / template matching | SSIM ≥ 0.90 | <0.75 (old/wrong logo) | Critical |
| F2 | Icon correct | Crop SSIM or perceptual hash | SSIM ≥ 0.85 | Different icon (e.g. download vs share) | Major |
| F3 | Broken / placeholder image | Card area almost flat grey/black (low variance) | Real image texture | Empty grey box, broken-image icon | Major |
| F4 | Image stretched | See C3 | — | — | Major |

## G. Interaction state (visible in a still screenshot)

| ID | Check | PASS | FAIL | Severity |
|---|---|---|---|---|
| G1 | Correct tab selected | Same tab active as template | Different tab active | Major |
| G2 | Focus ring (TV apps) | Focus on same element, same style | Missing or on wrong element | Major |
| G3 | Disabled vs enabled look | Same state styling | Enabled button looks greyed out (or reverse) | Major |

## H. Ignore list (always PASS, never compare content)

- Poster / thumbnail artwork inside cards
- Movie/show titles and metadata inside rails (year, duration, rating)
- Continue-watching progress bars (check presence only)
- Rank numbers' values (check presence and style only)
- Status bar: time, battery, network
- Hero banner image (check container, gradient D6, and button presence only)
- Ads / promo content

Implement as **mask regions**: after matching, skip content checks inside these element classes.

## I. Uncertainty → REVIEW (never silent PASS)

- Detection or OCR confidence below threshold (e.g. <0.5)
- One template element matches two production elements equally well
- Screens differ so much that <50% of elements match (probably wrong screen pair, so report "cannot compare")

---

## Suggested v0 scope (build these first)

The smallest set that answers the client's actual complaint (color, orientation) plus the most common real-world failures:

1. **A1** Orientation
2. **A3** Theme
3. **B1** Missing element
4. **B2** Extra element
5. **C1** Position shift
6. **D1** Brand/button color
7. **D2** Background color
8. **E1** Wrong static label text

Everything else comes later.

## Coverage vs current pipeline

| Needs | Cases | Status |
|---|---|---|
| Just image math, no detection | A1, A2, A3, A5 | Built (`src/comparison/screen_checks.py`) |
| Detection + matching (YOLO + OCR, VLM fallback) | B1-B5, B8, B9, C1, C2, C4, E1, E3 | Built. YOLO `ui16_v1` gives class + bbox, OCR gives text, uncertain elements → REVIEW |
| Language | E4 | Built (`script_checks.py`): Unicode script of matched labels |
| Matching + pixel check (colour, contrast) | D1, D2, D3, D5, D7 | Built (`color_checks.py`, `contrast_checks.py`) |
| Picture identity / presence | F1, F2, F3 | Built (`image_checks.py`). F1/F2 idle until the detector finds `logo` / `icon` |
| Not built | A4, B6, B7, C3, D4, D6, E2, E5-E7, F4, G* | — |

The report's Coverage table lists every row as checked, "skipped (LEVEL)" when the screen's match
level turned its family off, or not built. Skipped is never shown as PASS.

## Match levels, regions and accepted differences

Not spec rows, but they decide which rows report:
- **Match level** per screen (`config/screen_rules/<client screen id>.yaml`) or per region: STRICT
  (every check), LAYOUT (no D, E, F), IGNORE_COLORS (no D), NONE (ignore region). The status bar is
  always a NONE region (§H).
- **FLOATING region**: an element inside it may move up to `max_offset_norm` (of the diagonal)
  before C1 reports.
- **Dynamic text patterns** (E1): a label whose value may change but whose format must not (price,
  duration, episode, date) is compared by format.
- **Accepted differences**: a finding a human accepted once comes back as PASS (accepted), until the
  element, its text or its colour changes.

## How to get fail cases without client data (mutation testing)

Take a correct template screenshot and edit copies to create known defects:
rotate it (A1), invert/darken the background (A3, D2), shift the hue of the Play button (D1), paint over a tab or button (B1), paste an extra button (B2), move a section title 5% down (C1), change "Movies" to "Movie" (E1), squash a poster (C3).

Each edited image = a labeled FAIL case with a known answer. The unedited pair = a PASS case. That's your first test set, and it lets you measure whether the system actually works.
