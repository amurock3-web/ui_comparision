# Tests for src/vlm/engine.py and src/vlm/prompts.py.
#
# No live model call is made anywhere here — ollama.chat is mocked
# throughout. analyze() (classify-only, default, used by fusion) and
# analyze_grounded_experimental() (bbox-requesting, NOT used by fusion)
# are tested separately since they parse different response shapes.

from unittest.mock import patch

from src.ocr.engine import OCRElement, OCRResult
from src.schema.ui_element import ALLOWED_CLASSES
from src.vlm import prompts
from src.vlm.engine import VLMEngine

W, H = 1000, 2000


def test_render_prompt_includes_all_taxonomy_classes():
    text = prompts.render_prompt("v2_qwen2.5vl_classify_only")
    for cls in ALLOWED_CLASSES:
        assert cls in text


def test_render_prompt_includes_ocr_hints():
    text = prompts.render_prompt("v2_qwen2.5vl_classify_only", ocr_hints=["Free", "Movies"])
    assert "Free" in text
    assert "Movies" in text


def test_render_prompt_ocr_elements_includes_ids_for_som():
    # SoM grounding (arXiv:2408.00203): the prompt must expose each OCR
    # box's id, not just its text, so the model can answer with the id.
    text = prompts.render_prompt(
        "v2_qwen2.5vl_classify_only",
        ocr_elements=[OCRElement(
            id="ocr_0006", text="Action Crime", bbox=[0, 0, 1, 1],
            normalized_bbox=[0, 0, 1, 1], center=[0, 0],
            confidence=1.0, confidence_tier="high",
        )],
    )
    assert "ocr_0006" in text
    assert "Action Crime" in text
    assert "ocr_ref_id" in text


def test_render_prompt_unknown_version_raises():
    import pytest
    with pytest.raises(ValueError):
        prompts.render_prompt("does_not_exist")


def test_grounded_prompt_still_includes_image_dims():
    # v1_qwen2.5vl (the experimental grounded prompt) still exists for
    # analyze_grounded_experimental() and still asks for pixel bbox.
    text = prompts.render_prompt("v1_qwen2.5vl", image_width=640, image_height=1280)
    assert "640x1280" in text


def _ocr_result():
    return OCRResult(
        screen="ss_test", image_path="fake.png",
        image_width=W, image_height=H, inference_time_seconds=0.1,
        elements=[OCRElement(
            id="ocr_0001", text="Free", bbox=[10, 10, 40, 20],
            normalized_bbox=[0.01, 0.005, 0.04, 0.01], center=[30, 20],
            confidence=0.9, confidence_tier="high",
        )],
    )


def _mock_response(content: str, done_reason: str = "stop"):
    return {"done_reason": done_reason, "message": {"content": content, "thinking": ""}}


def _fake_image_path():
    # A tiny real PNG so Image.open() in VLMEngine works without touching
    # the real ss012.png test asset.
    import tempfile
    from pathlib import Path

    from PIL import Image

    img = Image.new("RGB", (W, H), color="white")
    tmp_dir = Path(tempfile.gettempdir())
    path = tmp_dir / "ui_comparison_test_image.png"
    img.save(path)
    return path


# ---------------------------------------------------------------------------
# analyze() — default, classify-only
# ---------------------------------------------------------------------------

def test_analyze_parses_valid_classify_only_response():
    raw = ('[{"class": "overlay_badge", "text": "Free", "description": "a promo ribbon", '
           '"approximate_location": "top-left"}]')
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )

    assert result.done_reason == "stop"
    assert result.parse_error is None
    assert len(result.elements) == 1
    el = result.elements[0]
    assert el.class_ == "overlay_badge"
    assert el.text == "Free"
    assert el.description == "a promo ribbon"
    assert el.approximate_location == "top-left"
    assert el.ocr_ref_id is None


def test_analyze_parses_ocr_ref_id():
    # SoM grounding (arXiv:2408.00203): the VLM can answer with the exact
    # OCR box id instead of leaving fusion to guess the association.
    raw = ('[{"class": "section_title", "text": "Action Crime", "description": "a heading", '
           '"approximate_location": "top", "ocr_ref_id": "ocr_0001"}]')
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.elements[0].ocr_ref_id == "ocr_0001"


def test_analyze_missing_ocr_ref_id_defaults_to_none():
    raw = '[{"class": "icon", "text": null, "description": "x", "approximate_location": "top"}]'
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.elements[0].ocr_ref_id is None


def test_analyze_recovers_single_bare_object_response():
    # Observed in practice: instead of a JSON array, the model sometimes
    # returns one bare element object. This should be recovered as a
    # one-element list, not silently dropped.
    raw = '{"class": "icon", "text": null, "description": "search icon", "approximate_location": "top-right"}'
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.parse_error is None
    assert len(result.elements) == 1
    assert result.elements[0].class_ == "icon"


def test_analyze_drops_elements_with_unknown_class():
    raw = '[{"class": "not_a_real_class", "text": null, "description": "", "approximate_location": ""}]'
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.parse_error is None
    assert result.elements == []


def test_analyze_nulls_non_english_text():
    raw = ('[{"class": "title", "text": "\\u0ba4\\u0bc7\\u0bb5\\u0bb0\\u0b9f\\u0bcd\\u0b9f\\u0bae\\u0bcd", '
           '"description": "a title", "approximate_location": "middle"}]')
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert len(result.elements) == 1
    assert result.elements[0].text is None


def test_analyze_sets_parse_error_distinct_from_empty_elements():
    # A caller must be able to tell "VLM found nothing" (valid empty
    # array, parse_error=None) apart from "VLM's response was garbage"
    # (parse_error set) — the two mean very different things to fusion.
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response("not json at all")):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.elements == []
    assert result.parse_error is not None
    assert result.raw_text == "not json at all"


def test_analyze_valid_empty_array_has_no_parse_error():
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response("[]")):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.elements == []
    assert result.parse_error is None


# ---------------------------------------------------------------------------
# use_json_schema / nullable_text_in_schema toggles — the fix for the
# VLM's "text" field coming back null for every element (see fuse.py's
# _match_for_class docstring / this fix's plan notes, arXiv:2408.02442).
# ---------------------------------------------------------------------------

def test_analyze_default_does_not_pass_format_to_ollama():
    raw = '[{"class": "icon", "text": null, "description": "", "approximate_location": ""}]'
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)) as mock_chat:
        VLMEngine(model="fake-model").analyze(_fake_image_path(), _ocr_result(), screen_id="ss_test")
    assert "format" not in mock_chat.call_args.kwargs


def test_analyze_free_form_recovers_array_wrapped_in_prose():
    # No schema means no structural guarantee — a model can still wrap
    # the array in a sentence despite being told not to.
    raw = 'Sure, here is the result:\n[{"class": "icon", "text": null, "description": "x", "approximate_location": "top"}]\nHope that helps!'
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = VLMEngine(model="fake-model").analyze(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.parse_error is None
    assert len(result.elements) == 1
    assert result.elements[0].class_ == "icon"


def test_analyze_with_schema_enabled_passes_format():
    raw = '[{"class": "icon", "text": null, "description": "", "approximate_location": ""}]'
    engine = VLMEngine(model="fake-model")
    engine.use_json_schema = True
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)) as mock_chat:
        engine.analyze(_fake_image_path(), _ocr_result(), screen_id="ss_test")
    assert "format" in mock_chat.call_args.kwargs
    assert mock_chat.call_args.kwargs["format"]["type"] == "array"


def test_schema_non_nullable_text_drops_null_from_type():
    from src.vlm.engine import _classify_response_schema
    nullable = _classify_response_schema(nullable_text=True)
    non_nullable = _classify_response_schema(nullable_text=False)
    assert nullable["items"]["properties"]["text"]["type"] == ["string", "null"]
    assert non_nullable["items"]["properties"]["text"]["type"] == "string"


def test_prompt_uses_empty_string_instruction_when_text_non_nullable():
    nullable_text = prompts.render_prompt("v2_qwen2.5vl_classify_only", nullable_text=True)
    non_nullable_text = prompts.render_prompt("v2_qwen2.5vl_classify_only", nullable_text=False)
    assert "ALWAYS use null" in nullable_text
    assert 'ALWAYS use ""' in non_nullable_text
    assert "null" not in non_nullable_text  # no stray "null" left in the instructions


# ---------------------------------------------------------------------------
# analyze_grounded_experimental() — NOT used by fusion, bbox-requesting
# ---------------------------------------------------------------------------

def test_grounded_experimental_parses_and_rescales_bbox():
    # bbox is pixel coordinates within the RESIZED image (see prompts.py) —
    # W,H=1000,2000 with max_image_dim=1280 (forced below) resizes to
    # 640x1280 (scale 0.64), so a resized-space bbox of [64, 128, 32, 20]
    # should rescale back to original-space [100.0, 200.0, 50.0, 31.25].
    raw = '[{"class": "overlay_badge", "text": "Free", "bbox": [64, 128, 32, 20], "confidence": 0.9}]'
    engine = VLMEngine(model="fake-model")
    engine.max_image_dim = 1280  # exercise the resize+rescale path regardless of config.yaml's current default
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response(raw)):
        result = engine.analyze_grounded_experimental(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )

    assert result.done_reason == "stop"
    assert len(result.elements) == 1
    el = result.elements[0]
    assert el.class_ == "overlay_badge"
    assert el.text == "Free"
    assert el.bbox == [100.0, 200.0, 50.0, 31.25]


def test_grounded_experimental_handles_invalid_json_gracefully():
    with patch("src.vlm.engine.ollama.chat", return_value=_mock_response("not json at all")):
        result = VLMEngine(model="fake-model").analyze_grounded_experimental(
            _fake_image_path(), _ocr_result(), screen_id="ss_test"
        )
    assert result.elements == []
    assert result.raw_text == "not json at all"
