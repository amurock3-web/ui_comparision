"""
Versioned VLM prompt templates (design.md §3: "the prompt should be
versioned").

Taxonomy is loaded from config/classes.json at render time rather than
hardcoded in the template string — the old ad-hoc test_vlm.py script hand-typed the now-
superseded 22-class list directly into its prompt, which is exactly the
kind of drift this avoids.
"""

import json
from pathlib import Path

_CLASSES_PATH = Path(__file__).resolve().parents[2] / "config" / "classes.json"

# One concrete example per class — v2 (no examples) misclassified nearly
# everything as content_card; v3 (examples + explicit "list every repeated
# element separately") fixed it. See docs/memory.md VLM benchmark section.
_CLASS_EXAMPLES = {
    "content_card": "a movie/show poster tile in a horizontal row or grid",
    "tab_item": "a small tappable label like 'Movies', 'Live TV', 'Home' in a nav bar or filter row",
    "overlay_badge": "a small tag overlaid on a card corner, e.g. a 'Free' ribbon, episode number, or duration",
    "section_title": "a heading above a row of cards, e.g. 'Action Comedy'",
    "button": "a tappable action control, e.g. 'Play', 'Subscribe'",
    "cast_card": "a small circular headshot with a name/credits row, on a detail screen",
    "icon": "a small standalone glyph, e.g. search, profile, or download icon",
    "metadata_text": "small descriptive text near a title, e.g. year, rating, duration text",
    "navigation_bar": "the bar containing the main nav items (Home, Movies, Search, ...)",
    "celebrity_card": "a full-width rectangular promo banner featuring a person, on the home/browse screen",
    "title": "a bold movie or series name caption",
    "description": "a paragraph of synopsis/summary text",
    "search_bar": "a text search input field, often with a magnifying-glass icon",
    "rank_number": "a large number indicating rank, e.g. in a Top 10 list",
    "text_input": "a login/signup form field",
    "logo": "the app or brand logo",
}


def _render_taxonomy_block() -> str:
    classes = json.loads(_CLASSES_PATH.read_text())["classes"]
    lines = [f"- {c}: {_CLASS_EXAMPLES.get(c, '')}" for c in classes]
    return "\n".join(lines)


_V1_TEMPLATE = """You are analyzing a screenshot of an OTT streaming application.

Identify every visible UI element in the screenshot. Use ONLY these UI classes:

{taxonomy}

Important rules:
- Do not invent elements that are not visible.
- List every repeated/duplicate element separately — do not collapse
  repeated elements (e.g. multiple movie cards) into a single entry.
- Set "text" to null unless the text is clearly legible English. Do not
  guess, transliterate, or invent text for non-English or stylized text —
  exact text transcription is handled separately by OCR, not by you.
- Distinguish real UI components from decorative artwork or poster imagery.
- bbox must be [x, y, width, height] in PIXEL coordinates within the image
  shown to you above{dims_hint}.
{ocr_hints_block}
Return a JSON array of objects, each with fields "class", "text", "bbox",
"confidence" (0 to 1). No other text.
"""


def render_prompt(
    version: str,
    ocr_hints: list[str] | None = None,
    ocr_elements: list | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    nullable_text: bool = True,
) -> str:
    if version not in PROMPT_VERSIONS:
        raise ValueError(f"Unknown prompt version: {version!r}. Known: {sorted(PROMPT_VERSIONS)}")
    return PROMPT_VERSIONS[version](
        ocr_hints=ocr_hints, ocr_elements=ocr_elements,
        image_width=image_width, image_height=image_height, nullable_text=nullable_text,
    )


def _render_v1(ocr_hints: list[str] | None = None, ocr_elements: list | None = None,
                image_width: int | None = None, image_height: int | None = None, nullable_text: bool = True) -> str:
    ocr_hints_block = ""
    if ocr_hints:
        unique_hints = [t for t in dict.fromkeys(ocr_hints) if t.strip()]
        if unique_hints:
            hint_list = ", ".join(f'"{t}"' for t in unique_hints)
            ocr_hints_block = (
                "\nOCR detected the following text fragments on this screen: "
                f"{hint_list}. Use them to help you locate elements, but "
                "classify based on what you see, not just this list.\n"
            )

    # A vision model reliably following a "give bbox as a 0-1 fraction"
    # instruction turned out not to hold in practice for qwen2.5vl:7b — it
    # consistently emitted pixel coordinates of the image it was shown
    # instead, regardless of the instruction. Asking for pixel coordinates
    # directly (and stating the exact image size when known) matches
    # observed behavior instead of fighting it; VLMEngine deterministically
    # rescales from these pixel coordinates back to the original image's
    # resolution afterward.
    dims_hint = f" (this image is exactly {image_width}x{image_height} pixels)" if image_width and image_height else ""

    return _V1_TEMPLATE.format(taxonomy=_render_taxonomy_block(), ocr_hints_block=ocr_hints_block, dims_hint=dims_hint)


_V2_TEMPLATE = """You are analyzing a screenshot of an OTT streaming application.

Identify EVERY UI element visible in the image individually. Do not
summarize repeated elements — if you see 4 movie poster cards in a row,
output 4 separate entries, one per card.

Use ONLY these UI classes:

{taxonomy}

For each element, output:
- class: one of the classes above.
- text: ONLY for real UI text/labels (nav labels, section titles, buttons).
  For content_card, ALWAYS use {empty_value} — do not attempt to read or
  transcribe the poster artwork's title design, it is decorative artwork,
  not UI text. For any other class, set text to {empty_value} unless it is
  clearly legible English — do not guess, transliterate, or invent text
  for non-English or stylized text; exact text transcription is OCR's
  job, not yours.
- description: a short description (one sentence max).
- approximate_location: one of "top", "middle", "bottom", "left",
  "center", "right", combined if needed (e.g. "top-left").
- ocr_ref_id: {ocr_ref_id_instruction}
{ocr_hints_block}
Rules:
- Do not invent elements that are not visibly present.
- List EVERY repeated element (e.g. every movie card in a row) as its own
  separate entry — this is critical, do not skip any.
- Distinguish real UI components from decorative artwork or poster imagery.
- Do not deliberate or second-guess — describe what you see directly and
  move on quickly.

Return a JSON array of objects, each with fields "class", "text",
"description", "approximate_location", "ocr_ref_id". No other text.
"""


def _render_v2(ocr_hints: list[str] | None = None, ocr_elements: list | None = None,
                image_width: int | None = None, image_height: int | None = None, nullable_text: bool = True) -> str:
    # SoM-style grounding (arXiv:2408.00203, OmniParser): give the VLM each
    # OCR detection's exact id alongside its text, and ask it to answer
    # WITH that id (ocr_ref_id) instead of re-describing the element in
    # free text and leaving fusion to guess which OCR box it meant. Text
    # similarity + a coarse approximate_location zone was found to
    # mis-associate near-identical strings (e.g. two "Action *" section
    # titles) purely from a title sitting a few px on the wrong side of a
    # rigid zone boundary — see src/fusion/fuse.py's _match_for_class
    # docstring. An id match sidesteps that guesswork entirely: fusion can
    # look the id up directly instead of re-deriving the association.
    # Paired with VLMEngine's nullable_text_in_schema: when the schema (if
    # used at all) makes "text" non-nullable, the prompt must say "" not
    # null, or the two would disagree with each other. ocr_ref_id shares
    # this same empty-value convention.
    empty_value = "null" if nullable_text else '""'
    ocr_hints_block = ""
    ocr_ref_id_instruction = f"{empty_value} — no OCR box list was provided for this call."
    if ocr_elements:
        lines = [f'  {e.id}: "{e.text}"' for e in ocr_elements if getattr(e, "text", None) and e.text.strip()]
        if lines:
            ocr_hints_block = (
                "\nOCR detected the following text boxes on this screen (id: text):\n"
                + "\n".join(lines) + "\n"
            )
            ocr_ref_id_instruction = (
                "if this element's text/label matches one of the OCR boxes listed above, "
                f'the exact id of that box (e.g. "ocr_0006"); otherwise {empty_value}. Do not '
                "guess an id for an element with no matching OCR box (e.g. content_card, icon)."
            )
    elif ocr_hints:
        unique_hints = [t for t in dict.fromkeys(ocr_hints) if t.strip()]
        if unique_hints:
            hint_list = ", ".join(f'"{t}"' for t in unique_hints)
            ocr_hints_block = (
                "\nOCR detected the following text fragments on this screen: "
                f"{hint_list}. Use them to help you locate elements, but "
                "classify based on what you see, not just this list.\n"
            )
            ocr_ref_id_instruction = f"{empty_value} — no OCR box ids were provided for this call."
    return _V2_TEMPLATE.format(
        taxonomy=_render_taxonomy_block(), ocr_hints_block=ocr_hints_block, empty_value=empty_value,
        ocr_ref_id_instruction=ocr_ref_id_instruction,
    )


_CONTENT_CARD_GROUNDING_PROMPT = """Locate every movie/show poster card (content_card) visible in this image, individually.

Output ALL of them as a JSON array of objects: {"bbox_2d": [x1, y1, x2, y2], "label": "content_card"}

Do not skip any, including partial cards cut off at the screen edge. Output ONLY the JSON array, no other text, no markdown fences.
"""


def _render_v3(ocr_hints: list[str] | None = None, ocr_elements: list | None = None,
                image_width: int | None = None, image_height: int | None = None, nullable_text: bool = True) -> str:
    # A narrow, single-class prompt using bbox_2d/[x1,y1,x2,y2] — Qwen2.5-VL's
    # own native grounding output format — instead of the generic [x,y,w,h]
    # schema v1 uses. Deliberately does NOT ask for every class at once:
    # combining classification + grounding in one prompt was found to
    # produce worse results (missed cards) than a focused single-class call.
    return _CONTENT_CARD_GROUNDING_PROMPT


PROMPT_VERSIONS = {
    # EXPERIMENTAL / not the default — asks the VLM for a pixel bbox per
    # element, ALL classes at once, via a generic [x,y,w,h] schema. Testing
    # showed this is unreliable (duplicate boxes double-labeled with
    # different classes, wildly oversized boxes for small elements like
    # badges) even once the JSON array shape itself was fixed. Kept for
    # VLMEngine.analyze_grounded_experimental() only.
    "v1_qwen2.5vl": _render_v1,
    # Default. Classify-only: class + text + description + a coarse
    # approximate_location zone, no bbox at all. Real geometry comes from
    # OCR/fusion instead (src/fusion/fuse.py) — see that module's docstring
    # for why: VLM-provided bboxes were found non-deterministic across
    # repeated calls on the identical image/prompt.
    "v2_qwen2.5vl_classify_only": _render_v2,
    # EXPERIMENTAL — content_card-only grounding, native bbox_2d format.
    # See VLMEngine.ground_content_cards_experimental().
    "v3_qwen2.5vl_ground_content_cards": _render_v3,
}
