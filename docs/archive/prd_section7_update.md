7. UI taxonomy (v2 — reduced ontology, locked 2026-09-02)

Reduced from the original 22-class taxonomy (see "Superseded" below) to 16 classes, based on visual/functional analysis of the 103-image labeled benchmark set. Rationale: several original classes were either visually indistinguishable, or functionally redundant, making multi-class classification unnecessarily hard for the VLM without adding real diagnostic value to the comparison engine.

Final 16-class taxonomy
Class	Source class(es)	Sample count (n=103 imgs)
content_card	content_card	657
tab_item	nav_item + category_tab + detail_tab + carousel_filter	459
overlay_badge	badge + episode_badge + duration	302
section_title	section_title	193
button	button	105
cast_card	cast_card	95
icon	icon	94
metadata_text	metadata_text	88
navigation_bar	navigation_bar	71
celebrity_card	celebrity_card	47
title	movie_title + series_title	28
description	description	21
search_bar	search_bar	13
rank_number	rank_number	4
text_input	text_input	4
logo	logo	6
Merge/keep/drop decisions and rationale
tab_item (merged): nav_item, category_tab, detail_tab, carousel_filter are all small tappable label/tab elements, differentiated mainly by screen position (already captured by bbox/geometry comparison), not by visual appearance. Merging reduces classification difficulty without losing diagnostic signal, since position is preserved separately.
overlay_badge (merged): badge, episode_badge, duration are all small tags overlaid on a card corner (e.g. "Free" ribbon, episode number, runtime). Same visual pattern, differ by text content (preserved via OCR fusion, not by class).
title (merged): movie_title and series_title are visually identical (same bold white-on-black caption style); no reliable visual cue distinguishes a movie name from a series name in the crop alone.
cast_card vs. celebrity_card (kept separate — do NOT merge): visually distinct (cast_card = small circular headshot + name, credits row; celebrity_card = full-width rectangular promo banner) AND contextually distinct (cast_card appears on movie/show detail screens; celebrity_card appears on the home/browse screen). This distinction is needed to correctly diagnose differences like "wrong card type shown for this screen."
rank_number, text_input (kept, low-confidence flag): both in scope per product decision (Top-10/ranked-list rows and login/signup screens are valid comparison targets), but only 4 labeled examples each exist in the current 103-image set. Treat any eval/fine-tuning result on these two classes as directional, not statistically reliable, until more labeled examples are collected.
Superseded — original 22-class taxonomy (2026-xx-xx, pre-reduction)

content_card, nav_item, badge, section_title, button, cast_card, icon, metadata_text, category_tab, navigation_bar, celebrity_card, detail_tab, duration, carousel_filter, movie_title, description, search_bar, episode_badge, logo, rank_number, text_input, series_title

Kept here for historical reference and because the original 103-image label set (YOLO format, Label Studio export, classes.txt/notes.json) uses this 22-class id scheme. The class-remap mapping (old → new) must be applied at UI-JSON conversion time; original label files are not re-annotated in place.

The earlier work referenced 32 GT rules from the previous SunNXT project; per rules.md §1/§11, that set remains reference/evaluation material only and is not part of this taxonomy

### Proposed v3 — three-layer ontology (2026-09-21, UNDER DISCUSSION, NOT LOCKED)

The v2 16-class taxonomy above remains the locked taxonomy. v3 is a
proposal to revisit **after the MVP runs end-to-end**.

**Principle:** the detector learns only what things *look like*.
Meaning, position and text become attributes or rules.

| Layer | Holds | Produced by |
|---|---|---|
| 1. Visual classes | `navigation_bar`, `tab_item`, `card`, `overlay_badge`, `button`, `icon`, `logo`, `text`, `input_field` | YOLO |
| 2. Attributes | card `style` (portrait / landscape / circular / banner), card `rank`, text `role` (section_title / title / metadata / description), badge text, tab `selected` | rules on geometry, OCR, context |
| 3. Structure | sections, rows, grids, parent/child, screen type (home / detail / search / login) | graph (Phase 4) |

**Mapping from existing labels (no re-annotation needed):**
- `content_card` → `card` (style portrait/landscape by aspect ratio)
- `cast_card` → `card` (style circular)
- `celebrity_card` → `card` (style banner)
- `section_title`, `title`, `metadata_text`, `description` → `text`
  (role kept as attribute from the original label)
- `search_bar`, `text_input` → `input_field`
- `rank_number` → dropped as a class; becomes `card.rank` from rank
  boxes overlapping cards (design.md §20)
- `tab.selected` → needs new labels; start as a color-contrast rule

**Why:** fewer classes → more samples per class (e.g. `text` gets
hundreds, reducing the `metadata_text` 0.71 problem); generalizes
across OTT apps; `cast_card` vs `celebrity_card` difference is still
reported as an attribute difference, so the "wrong card type for this
screen" diagnosis is preserved.

**Cost:** PRD update, new remap in `UI_Detection_model_training`,
YOLO retrain, attribute rules to write.

### rank_number decision note (2026-09-21)

Proposed: remove `rank_number` as a detector class (4 samples, cannot
be learned reliably) but keep the information as a card attribute
derived by rule (only in Top-10 rows). Pending approval together with
v3.