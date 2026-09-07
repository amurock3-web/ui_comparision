# Tests for src/fusion/fuse.py — deterministic OCR<->VLM association
# (rules.md §14). The VLM is classify-only (no bbox) — these tests cover
# text-match grounding, grid-inferred content_card geometry, keyword-based
# badge promotion, zone disambiguation, and evidence preservation for
# elements neither side can fully ground.

from src.fusion.fuse import FusionEngine
from src.ocr.engine import OCRElement, OCRResult
from src.vlm.engine import VLMElement, VLMResult

W, H = 1000, 2000


def _ocr_result(elements):
    return OCRResult(
        screen="ss_test", image_path="fake.png",
        image_width=W, image_height=H, inference_time_seconds=0.1,
        elements=elements,
    )


def _vlm_result(elements):
    return VLMResult(
        screen="ss_test", image_path="fake.png",
        image_width=W, image_height=H, model="fake-model",
        prompt_version="v2_qwen2.5vl_classify_only", inference_time_seconds=0.1,
        done_reason="stop", raw_text="[]", elements=elements,
    )


def _ocr_el(id_, text, bbox, confidence=0.95, tier="high"):
    x, y, w, h = bbox
    return OCRElement(
        id=id_, text=text, bbox=bbox,
        normalized_bbox=[x / W, y / H, w / W, h / H],
        center=[x + w / 2, y + h / 2],
        confidence=confidence, confidence_tier=tier,
    )


def _vlm_el(id_, class_, text=None, description="", approximate_location="", ocr_ref_id=None):
    return VLMElement(
        id=id_, class_=class_, text=text,
        description=description, approximate_location=approximate_location,
        ocr_ref_id=ocr_ref_id,
    )


def test_text_matchable_class_grounded_by_ocr_bbox():
    ocr = _ocr_result([_ocr_el("ocr_0001", "Live TV", [50, 50, 100, 30])])
    vlm = _vlm_result([_vlm_el("vlm_0001", "tab_item", "Live TV", approximate_location="top")])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    assert len(doc.elements) == 1
    el = doc.elements[0]
    assert el.source == "fused"
    assert el.class_ == "tab_item"
    assert el.bbox == [50, 50, 100, 30]
    assert el.confidence == 0.95
    assert el.metadata["ocr_id"] == "ocr_0001"


def test_ungrounded_vlm_classification_kept_with_no_bbox():
    # "icon" has no OCR-matchable text and no grid rule — no geometry
    # source exists for it, but the classification must still survive.
    ocr = _ocr_result([])
    vlm = _vlm_result([_vlm_el("vlm_0001", "icon", None, description="search icon", approximate_location="top-right")])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    assert len(doc.elements) == 1
    el = doc.elements[0]
    assert el.source == "vlm"
    assert el.class_ == "icon"
    assert el.bbox is None
    assert el.metadata["description"] == "search icon"


def test_unmatched_ocr_kept_as_orphan_evidence():
    ocr = _ocr_result([_ocr_el("ocr_0001", "Bgaihnili", [800, 1800, 60, 15])])
    vlm = _vlm_result([])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    assert len(doc.elements) == 1
    el = doc.elements[0]
    assert el.source == "ocr"
    assert el.class_ is None
    assert el.text == "Bgaihnili"
    assert el.bbox == [800, 1800, 60, 15]


def test_content_card_grid_inference():
    # One section_title anchor followed by 3 content_cards with nothing
    # after it: the trailing-row branch should split the full image width
    # evenly across the 3 cards, below the title.
    title_bbox = [20, 100, 200, 30]
    ocr = _ocr_result([_ocr_el("ocr_title", "Trending", title_bbox)])
    vlm = _vlm_result([
        _vlm_el("vlm_title", "section_title", "Trending", approximate_location="top"),
        _vlm_el("vlm_card1", "content_card"),
        _vlm_el("vlm_card2", "content_card"),
        _vlm_el("vlm_card3", "content_card"),
    ])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    cards = [e for e in doc.elements if e.class_ == "content_card"]
    assert len(cards) == 3
    for c in cards:
        assert c.bbox is not None
        assert c.metadata["bbox_source"] == "inferred_grid"
        assert c.bbox[3] == H - (title_bbox[1] + title_bbox[3])  # row height = image bottom - title bottom

    col_width = W / 3
    xs = sorted(c.bbox[0] for c in cards)
    assert xs == [0, round(col_width, 2), round(2 * col_width, 2)]


def test_badge_promoted_via_keyword_and_card_containment():
    title_bbox = [20, 100, 200, 30]
    row_top = title_bbox[1] + title_bbox[3]
    # Inside where the single inferred card's bbox will be: full width,
    # from row_top to image bottom.
    badge_bbox = [10, row_top + 10, 40, 15]

    ocr = _ocr_result([
        _ocr_el("ocr_title", "Trending", title_bbox),
        _ocr_el("ocr_badge", "Free", badge_bbox),
    ])
    vlm = _vlm_result([
        _vlm_el("vlm_title", "section_title", "Trending", approximate_location="top"),
        _vlm_el("vlm_card1", "content_card"),
    ])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    badges = [e for e in doc.elements if e.class_ == "overlay_badge"]
    assert len(badges) == 1
    assert badges[0].text == "Free"
    assert badges[0].bbox == badge_bbox
    assert badges[0].source == "fused"


def test_badge_keyword_outside_low_confidence_not_promoted():
    title_bbox = [20, 100, 200, 30]
    row_top = title_bbox[1] + title_bbox[3]
    badge_bbox = [10, row_top + 10, 40, 15]

    ocr = _ocr_result([
        _ocr_el("ocr_title", "Trending", title_bbox),
        _ocr_el("ocr_badge", "Free", badge_bbox, confidence=0.3, tier="low"),
    ])
    vlm = _vlm_result([
        _vlm_el("vlm_title", "section_title", "Trending", approximate_location="top"),
        _vlm_el("vlm_card1", "content_card"),
    ])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    assert not any(e.class_ == "overlay_badge" for e in doc.elements)
    # Still preserved as unmatched OCR evidence, not dropped.
    assert any(e.text == "Free" and e.source == "ocr" for e in doc.elements)


def test_duplicate_text_disambiguated_by_approximate_location():
    # "Free" appears twice: once as a poster badge (top) and once as the
    # real bottom-nav tab. Text similarity alone can't tell them apart —
    # approximate_location must pick the bottom one.
    ocr = _ocr_result([
        _ocr_el("ocr_badge_free", "Free", [10, 50, 40, 15]),      # top zone
        _ocr_el("ocr_navtab_free", "Free", [10, 1900, 40, 15]),   # bottom zone
    ])
    vlm = _vlm_result([_vlm_el("vlm_navtab", "tab_item", "Free", approximate_location="bottom")])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    matched = [e for e in doc.elements if e.source == "fused"]
    assert len(matched) == 1
    assert matched[0].metadata["ocr_id"] == "ocr_navtab_free"


# ---------------------------------------------------------------------------
# SoM id grounding (arXiv:2408.00203, OmniParser): the VLM answers with the
# OCR box id it means, instead of leaving fusion to re-derive the
# association from text similarity + a coarse position zone.
# ---------------------------------------------------------------------------

def test_som_id_match_resolves_collision_text_similarity_gets_wrong():
    # Regression case: real ss012 run. "Action Drama" (y=763) sits just
    # outside the "middle" zone's lower bound (y=800), so zone-filtered
    # text-similarity matched the VLM's "Action Drama" classification to
    # OCR's "Action Comedy" box instead (score 0.609, both clear the 0.6
    # threshold since all "Action *" titles share a common prefix). An
    # ocr_ref_id match must not fall into that trap: it grounds directly
    # to the box the VLM actually named, bypassing text/zone matching.
    ocr = _ocr_result([
        _ocr_el("ocr_drama", "Action Drama", [24, 763, 256, 38]),
        _ocr_el("ocr_comedy", "Action Comedy", [22, 1343, 292, 46]),
    ])
    vlm = _vlm_result([_vlm_el(
        "vlm_title", "section_title", "Action Drama",
        approximate_location="middle", ocr_ref_id="ocr_drama",
    )])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    matched = [e for e in doc.elements if e.source == "fused"]
    assert len(matched) == 1
    assert matched[0].metadata["ocr_id"] == "ocr_drama"
    assert matched[0].metadata["match_method"] == "som_id"
    assert matched[0].text == "Action Drama"
    assert matched[0].bbox == [24, 763, 256, 38]


def test_som_id_unknown_falls_back_to_text_similarity():
    # A hallucinated/stale ocr_ref_id must not ground the element to a
    # wrong or nonexistent box — fall back to the existing matching chain.
    ocr = _ocr_result([_ocr_el("ocr_live_tv", "Live TV", [50, 1900, 100, 30])])
    vlm = _vlm_result([_vlm_el(
        "vlm_tab", "tab_item", "Live TV",
        approximate_location="bottom", ocr_ref_id="ocr_does_not_exist",
    )])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    matched = [e for e in doc.elements if e.source == "fused"]
    assert len(matched) == 1
    assert matched[0].metadata["match_method"] == "text_similarity"
    assert matched[0].metadata["ocr_id"] == "ocr_live_tv"


# ---------------------------------------------------------------------------
# Zone-only fallback: grounding when the VLM gives no text at all (the
# "always null text" problem — see the fix's plan notes / arXiv:2408.02442).
# ---------------------------------------------------------------------------

def test_zone_only_fallback_grounds_element_with_no_text():
    ocr = _ocr_result([_ocr_el("ocr_tab", "Live TV", [50, 1900, 100, 30])])
    vlm = _vlm_result([_vlm_el("vlm_tab", "tab_item", text=None, approximate_location="bottom")])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    matched = [e for e in doc.elements if e.source == "fused"]
    assert len(matched) == 1
    el = matched[0]
    assert el.metadata["match_method"] == "zone_only_fallback"
    assert el.bbox == [50, 1900, 100, 30]
    # No text comparison happened — don't claim the OCR text as verified.
    assert el.text is None


def test_zone_only_fallback_discounts_confidence_vs_text_match():
    ocr_bbox = [50, 1900, 100, 30]
    # Same OCR element/confidence in both scenarios; only whether the VLM
    # provides matching text differs.
    ocr_with_text = _ocr_result([_ocr_el("ocr_tab", "Live TV", ocr_bbox, confidence=0.9)])
    vlm_with_text = _vlm_result([_vlm_el("vlm_tab", "tab_item", "Live TV", approximate_location="bottom")])
    doc_text_match = FusionEngine().fuse(ocr_with_text, vlm_with_text, screen_id="ss_test")

    ocr_no_text_match = _ocr_result([_ocr_el("ocr_tab", "Live TV", ocr_bbox, confidence=0.9)])
    vlm_no_text = _vlm_result([_vlm_el("vlm_tab", "tab_item", text=None, approximate_location="bottom")])
    doc_zone_only = FusionEngine().fuse(ocr_no_text_match, vlm_no_text, screen_id="ss_test")

    text_match_el = [e for e in doc_text_match.elements if e.source == "fused"][0]
    zone_only_el = [e for e in doc_zone_only.elements if e.source == "fused"][0]

    assert text_match_el.confidence == 0.9
    assert zone_only_el.confidence < text_match_el.confidence
    assert zone_only_el.confidence == round(0.9 * 0.5, 4)


def test_section_titles_with_no_text_still_split_cards_into_rows():
    # This is the exact bug this fix addresses: with zero row anchors
    # found, ALL cards used to fall into one giant row spanning the full
    # image height. With zone-only fallback, anchors are found from
    # approximate_location alone, and cards split into real rows again.
    title1_bbox = [20, 50, 200, 30]     # top zone (y < H/3)
    title2_bbox = [20, 1400, 200, 30]   # bottom zone (y > 2H/3)

    ocr = _ocr_result([
        _ocr_el("ocr_title1", "Trending", title1_bbox),
        _ocr_el("ocr_title2", "Popular", title2_bbox),
    ])
    vlm = _vlm_result([
        _vlm_el("vlm_title1", "section_title", text=None, approximate_location="top"),
        _vlm_el("vlm_card1", "content_card"),
        _vlm_el("vlm_card2", "content_card"),
        _vlm_el("vlm_title2", "section_title", text=None, approximate_location="bottom"),
        _vlm_el("vlm_card3", "content_card"),
    ])

    doc = FusionEngine().fuse(ocr, vlm, screen_id="ss_test")

    cards_by_id = {e.metadata["vlm_id"]: e for e in doc.elements if e.class_ == "content_card"}
    assert cards_by_id["vlm_card1"].bbox[3] != H
    assert cards_by_id["vlm_card1"].bbox[3] == cards_by_id["vlm_card2"].bbox[3]
    # First row: bounded between title1's bottom (80) and title2's top
    # (1400) — 1320, not the full 2000px image height a naive
    # zero-anchors fallback would have produced.
    assert cards_by_id["vlm_card1"].bbox[3] == title2_bbox[1] - (title1_bbox[1] + title1_bbox[3])
    # Trailing row: bounded between title2's bottom (1430) and the image
    # bottom (2000) — 570, also not the full 2000px height.
    assert cards_by_id["vlm_card3"].bbox[3] == H - (title2_bbox[1] + title2_bbox[3])
