"""
VLM abstraction (architecture.md §5): VLMEngine.analyze(image, ocr_result).

Everything else in the app should call this instead of touching Ollama
directly, so the underlying model stays swappable (rules.md §3).

analyze() is the DEFAULT path used by fusion — classify-only: class, text,
description, and a coarse approximate_location zone. No bbox. Real
geometry comes from OCR/fusion instead (see src/fusion/fuse.py).

analyze_grounded_experimental() is a separate, NOT-default path that asks
the model for a real pixel bbox per element. Testing showed it produces
duplicate boxes double-labeled with two different classes and wildly
oversized boxes for small elements (e.g. an "overlay_badge" box spanning
most of a card) even once the JSON array shape itself was forced via a
schema. Kept available, clearly separated, in case a future determinism
fix (verified low-temperature behavior, a different model, or a
purpose-trained detector per phases.md Phase 10) makes it viable again —
NOT wired into fusion or main.py.
"""

import io
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import ollama
import yaml
from ollama import ResponseError
from PIL import Image

from src.ocr.engine import confidence_tier
from src.schema.ui_element import ALLOWED_CLASSES
from src.vlm.prompts import render_prompt

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

# A "clearly legible English" text should be mostly printable ASCII. This
# is defense-in-depth on top of the prompt instruction (docs: qwen2.5vl
# hallucinated plausible-looking but fabricated non-English text) — never
# trust the model's text field on its own for non-English/stylized text.
_ASCII_TEXT_RE = re.compile(r"^[\x20-\x7E]+$")


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text


def _extract_json(text: str):
    """Parse text as JSON, with a fallback for the free-form (no schema)
    path where there's no structural guarantee: if the whole string
    doesn't parse, try slicing from the first "[" to the last "]" — a
    model asked to "return ONLY a JSON array" sometimes still wraps it in
    a sentence or two despite the instruction."""
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1]), None
            except json.JSONDecodeError:
                pass
        return None, f"invalid JSON: {e}"


def _looks_like_english(text: str) -> bool:
    return bool(text) and bool(_ASCII_TEXT_RE.match(text))


def _as_list(parsed, element_keys: tuple[str, ...]):
    """Recover a list of element dicts from whatever JSON shape the model
    actually returned. Handles the degenerate case (a bare single element
    object instead of a one-item list) and the {"elements": [...]} wrapper
    some models use, on top of the well-formed array case."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if all(k in parsed for k in element_keys):
            return [parsed]
        return parsed.get("elements", [])
    return None


# ---------------------------------------------------------------------------
# Default path: classify-only (no bbox)
# ---------------------------------------------------------------------------

@dataclass
class VLMElement:
    id: str
    class_: str
    text: Optional[str]
    description: str
    approximate_location: str
    # SoM-style grounding (arXiv:2408.00203, OmniParser): the OCR box id
    # (e.g. "ocr_0006") this element corresponds to, per the model's own
    # answer — None when no OCR box matches (e.g. content_card, icon) or
    # the prompt didn't offer OCR ids. See prompts.py's _render_v2
    # docstring for why this replaces guessing the association from text
    # similarity + a coarse position zone alone.
    ocr_ref_id: Optional[str] = None
    source: str = "vlm"

    def to_dict(self):
        return {
            "id": self.id,
            "class": self.class_,
            "text": self.text,
            "description": self.description,
            "approximate_location": self.approximate_location,
            "ocr_ref_id": self.ocr_ref_id,
            "source": self.source,
        }


@dataclass
class VLMResult:
    screen: str
    image_path: str
    image_width: int
    image_height: int
    model: str
    prompt_version: str
    inference_time_seconds: float
    done_reason: str
    raw_text: str
    parse_error: Optional[str] = None
    elements: list = field(default_factory=list)

    def to_dict(self):
        return {
            "screen": self.screen,
            "image": self.image_path,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "inference_time_seconds": round(self.inference_time_seconds, 3),
            "done_reason": self.done_reason,
            "parse_error": self.parse_error,
            "element_count": len(self.elements),
            "elements": [e.to_dict() for e in self.elements],
            "raw_text": self.raw_text,
        }

    def save_json(self, path: Path):
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _classify_response_schema(nullable_text: bool = True) -> dict:
    """JSON schema for Ollama's structured-output `format` param.

    format="json" alone only guarantees SOME valid JSON value — in
    testing, qwen2.5vl:7b collapsed to a single object (or "[]") instead
    of the array the prompt asked for. A schema with type "array" forces
    the array shape at the grammar level; constraining "class" via enum
    to the taxonomy also stops the model inventing out-of-taxonomy
    classes (observed under format="json": a stray "text" class).

    Separately: research on schema-constrained decoding (see this
    project's fix notes / arXiv:2408.02442) documents that a NULLABLE
    field biases the model toward its null branch even when it could
    report a real value — observed here as "text" coming back null for
    every element, including ones OCR read fine. nullable_text=False
    drops null from the schema entirely, pairing with prompts.py's
    matching "use an empty string" instruction, as one mitigation.
    VLMEngine.use_json_schema=False (the default) sidesteps this whole
    mechanism by not using a schema at all."""
    text_type = ["string", "null"] if nullable_text else "string"
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "class": {"type": "string", "enum": sorted(ALLOWED_CLASSES)},
                "text": {"type": text_type},
                "description": {"type": "string"},
                "approximate_location": {"type": "string"},
                "ocr_ref_id": {"type": ["string", "null"]},
            },
            "required": ["class", "description", "approximate_location"],
        },
    }


class VLMEngine:
    """Thin, swappable wrapper around a local Ollama vision model."""

    def __init__(self, model: str = None, prompt_version: str = None, config_path: Path = DEFAULT_CONFIG_PATH):
        cfg = yaml.safe_load(Path(config_path).read_text()).get("vlm", {})
        self.model = model or cfg.get("model", "qwen2.5vl:7b")
        self.prompt_version = prompt_version or cfg.get("prompt_version", "v2_qwen2.5vl_classify_only")
        self.max_image_dim = cfg.get("max_image_dim", 1280)  # None/0 = no downscale, send native resolution
        self.num_predict = cfg.get("num_predict", 4096)
        self.num_ctx = cfg.get("num_ctx", 8192)
        # Default False: schema-constrained decoding was found to bias
        # "text" toward null even for elements OCR read fine (see
        # _classify_response_schema's docstring). Free-form + robust
        # parsing avoids that mechanism entirely.
        self.use_json_schema = cfg.get("use_json_schema", False)
        # Only consulted when use_json_schema is True.
        self.nullable_text_in_schema = cfg.get("nullable_text_in_schema", True)

    def _resize_image(self, image_path: Path) -> tuple[bytes, int, int]:
        """Returns (png_bytes, resized_width, resized_height)."""
        image = Image.open(image_path).convert("RGB")
        scale = 1.0 if not self.max_image_dim else min(1.0, self.max_image_dim / max(image.width, image.height))
        new_w, new_h = image.width, image.height
        if scale < 1.0:
            new_w, new_h = round(image.width * scale), round(image.height * scale)
            image = image.resize((new_w, new_h))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue(), new_w, new_h

    def analyze(self, image_path: Path, ocr_result, screen_id: str = None) -> VLMResult:
        """Classify UI elements in an image. DEFAULT path used by fusion.
        Returns class + text + description + approximate_location, no
        bbox — see module docstring for why."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Screenshot not found:\n{image_path.resolve()}")

        source_image = Image.open(image_path)
        W, H = source_image.width, source_image.height
        screen_id = screen_id or image_path.stem

        image_bytes, resized_w, resized_h = self._resize_image(image_path)

        prompt = render_prompt(
            self.prompt_version, ocr_elements=getattr(ocr_result, "elements", []),
            image_width=resized_w, image_height=resized_h,
            nullable_text=self.nullable_text_in_schema,
        )

        print(f"[VLM] Starting VLM analysis on {image_path.name} with model {self.model!r}... "
              f"(schema={'on' if self.use_json_schema else 'off'}) please wait, this can take a "
              "while, especially on CPU.")

        chat_kwargs = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt, "images": [image_bytes]}],
            "options": {
                "temperature": 0,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            },
        }
        if self.use_json_schema:
            chat_kwargs["format"] = _classify_response_schema(nullable_text=self.nullable_text_in_schema)

        start = time.time()
        try:
            response = ollama.chat(**chat_kwargs)
        except ResponseError as e:
            raise RuntimeError(f"Ollama API error while running model {self.model!r}: {e}") from e
        elapsed = time.time() - start

        done_reason = response.get("done_reason", "")
        if done_reason != "stop":
            print(f"[warn] VLM generation did not finish normally (done_reason={done_reason!r}); "
                  "output is likely incomplete.")

        message = response["message"]
        raw_text = message.get("content", "") or ""
        thinking = message.get("thinking", "") or ""
        if not raw_text.strip() and thinking.strip():
            print("[warn] 'content' is empty but 'thinking' has text - JSON masking likely never "
                  "engaged. Falling back to raw thinking text.")
            raw_text = thinking

        elements, parse_error = self._parse_elements(raw_text)

        if parse_error:
            print(f"[warn] VLM response could not be parsed: {parse_error}")
        print(f"[VLM] Done in {elapsed:.2f}s - {len(elements)} elements found.")

        return VLMResult(
            screen=screen_id,
            image_path=str(image_path),
            image_width=W,
            image_height=H,
            model=self.model,
            prompt_version=self.prompt_version,
            inference_time_seconds=elapsed,
            done_reason=done_reason,
            raw_text=raw_text,
            parse_error=parse_error,
            elements=elements,
        )

    def _parse_elements(self, raw_text: str) -> tuple[list, Optional[str]]:
        cleaned = _strip_json_fence(raw_text)
        parsed, error = _extract_json(cleaned)
        if error:
            # Distinct from "parsed fine, zero elements" — a caller (e.g.
            # fusion) can check parse_error to tell "VLM found nothing" apart
            # from "VLM's response was garbage," which a bare [] can't do.
            return [], error

        recovered = _as_list(parsed, element_keys=("class", "description"))
        if recovered is None:
            return [], f"parsed JSON was not a list or object: {type(parsed).__name__}"

        elements = []
        for i, raw_el in enumerate(recovered):
            if not isinstance(raw_el, dict):
                continue

            class_ = raw_el.get("class")
            if class_ not in ALLOWED_CLASSES:
                print(f"[warn] Dropping VLM element with class {class_!r} (not in taxonomy).")
                continue

            text = raw_el.get("text")
            if text is not None and not _looks_like_english(str(text)):
                text = None

            ocr_ref_id = raw_el.get("ocr_ref_id")
            if ocr_ref_id is not None:
                ocr_ref_id = str(ocr_ref_id).strip() or None

            elements.append(
                VLMElement(
                    id=f"vlm_{i + 1:04d}",
                    class_=class_,
                    text=text,
                    description=str(raw_el.get("description", "")),
                    approximate_location=str(raw_el.get("approximate_location", "")),
                    ocr_ref_id=ocr_ref_id,
                )
            )
        return elements, None

    # -----------------------------------------------------------------
    # Experimental grounded path — NOT used by default. See module
    # docstring for why.
    # -----------------------------------------------------------------

    def analyze_grounded_experimental(self, image_path: Path, ocr_result, screen_id: str = None) -> "VLMGroundedResult":
        """EXPERIMENTAL — not called by fusion or main.py. Asks the model
        for a real pixel bbox per element via prompt "v1_qwen2.5vl". Kept
        for future revisiting; see module docstring."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Screenshot not found:\n{image_path.resolve()}")

        source_image = Image.open(image_path)
        W, H = source_image.width, source_image.height
        screen_id = screen_id or image_path.stem

        image_bytes, resized_w, resized_h = self._resize_image(image_path)

        ocr_hints = [e.text for e in getattr(ocr_result, "elements", [])]
        prompt = render_prompt("v1_qwen2.5vl", ocr_hints=ocr_hints, image_width=resized_w, image_height=resized_h)

        print(f"[VLM-EXPERIMENTAL] Starting grounded VLM analysis on {image_path.name} with model "
              f"{self.model!r}... please wait, this can take a while, especially on CPU.")

        start = time.time()
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
                format=_grounded_response_schema(),
                options={
                    "temperature": 0,
                    "num_predict": self.num_predict,
                    "num_ctx": self.num_ctx,
                },
            )
        except ResponseError as e:
            raise RuntimeError(f"Ollama API error while running model {self.model!r}: {e}") from e
        elapsed = time.time() - start

        done_reason = response.get("done_reason", "")
        message = response["message"]
        raw_text = message.get("content", "") or ""
        thinking = message.get("thinking", "") or ""
        if not raw_text.strip() and thinking.strip():
            raw_text = thinking

        elements = self._parse_grounded_elements(raw_text, W, H, resized_w, resized_h)
        print(f"[VLM-EXPERIMENTAL] Done in {elapsed:.2f}s - {len(elements)} elements found.")

        return VLMGroundedResult(
            screen=screen_id, image_path=str(image_path), image_width=W, image_height=H,
            model=self.model, prompt_version="v1_qwen2.5vl", inference_time_seconds=elapsed,
            done_reason=done_reason, raw_text=raw_text, elements=elements,
        )

    def _parse_grounded_elements(self, raw_text: str, W: int, H: int, resized_w: int, resized_h: int) -> list:
        cleaned = _strip_json_fence(raw_text)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return []

        recovered = _as_list(parsed, element_keys=("class", "bbox"))
        if recovered is None:
            return []

        scale_x = W / resized_w if resized_w else 1.0
        scale_y = H / resized_h if resized_h else 1.0

        elements = []
        for i, raw_el in enumerate(recovered):
            if not isinstance(raw_el, dict):
                continue
            class_ = raw_el.get("class")
            if class_ not in ALLOWED_CLASSES:
                continue
            text = raw_el.get("text")
            if text is not None and not _looks_like_english(str(text)):
                text = None
            raw_bbox = raw_el.get("bbox")
            if not (isinstance(raw_bbox, list) and len(raw_bbox) == 4):
                continue
            rx, ry, rw, rh = (float(v) for v in raw_bbox)
            x = max(0.0, min(rx * scale_x, W))
            y = max(0.0, min(ry * scale_y, H))
            w = max(0.0, min(rw * scale_x, W - x))
            h = max(0.0, min(rh * scale_y, H - y))
            bbox = [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]
            normalized_bbox = [round(x / W, 5), round(y / H, 5), round(w / W, 5), round(h / H, 5)]
            center = [round(x + w / 2, 2), round(y + h / 2, 2)]
            confidence = min(max(float(raw_el.get("confidence", 0.5)), 0.0), 1.0)
            elements.append(
                VLMGroundedElement(
                    id=f"vlmg_{i + 1:04d}", class_=class_, text=text, bbox=bbox,
                    normalized_bbox=normalized_bbox, center=center,
                    confidence=round(confidence, 4), confidence_tier=confidence_tier(confidence),
                )
            )
        return elements

    def ground_content_cards_experimental(self, image_path: Path, screen_id: str = None) -> "VLMGroundedResult":
        """EXPERIMENTAL — not called by fusion or main.py. A narrow,
        single-purpose grounding call for content_card only, via prompt
        "v3_qwen2.5vl_ground_content_cards", using Qwen2.5-VL's native
        bbox_2d/[x1,y1,x2,y2] grounding format — not the generic
        [x,y,w,h] schema analyze_grounded_experimental() uses. Kept
        separate from classification: combining classification + grounding
        in one prompt produced worse results (missed cards). Badges/icons/
        nav items are deliberately NOT grounded here — testing showed VLM
        grounding is unreliable for anything but content_card-sized boxes;
        those stay on fusion's deterministic OCR-match/grid path."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Screenshot not found:\n{image_path.resolve()}")

        source_image = Image.open(image_path)
        W, H = source_image.width, source_image.height
        screen_id = screen_id or image_path.stem

        image_bytes, resized_w, resized_h = self._resize_image(image_path)
        prompt = render_prompt("v3_qwen2.5vl_ground_content_cards", image_width=resized_w, image_height=resized_h)

        print(f"[VLM-EXPERIMENTAL] Starting content_card grounding on {image_path.name} with model "
              f"{self.model!r}... please wait, this can take a while, especially on CPU.")

        start = time.time()
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
                options={"temperature": 0, "num_predict": self.num_predict, "num_ctx": self.num_ctx},
            )
        except ResponseError as e:
            raise RuntimeError(f"Ollama API error while running model {self.model!r}: {e}") from e
        elapsed = time.time() - start

        done_reason = response.get("done_reason", "")
        message = response["message"]
        raw_text = message.get("content", "") or ""
        thinking = message.get("thinking", "") or ""
        if not raw_text.strip() and thinking.strip():
            raw_text = thinking

        elements = self._parse_bbox_2d_elements(raw_text, W, H, resized_w, resized_h)
        print(f"[VLM-EXPERIMENTAL] Done in {elapsed:.2f}s - {len(elements)} content_card(s) found.")

        return VLMGroundedResult(
            screen=screen_id, image_path=str(image_path), image_width=W, image_height=H,
            model=self.model, prompt_version="v3_qwen2.5vl_ground_content_cards", inference_time_seconds=elapsed,
            done_reason=done_reason, raw_text=raw_text, elements=elements,
        )

    def _parse_bbox_2d_elements(self, raw_text: str, W: int, H: int, resized_w: int, resized_h: int) -> list:
        """Parses Qwen2.5-VL's native grounding format —
        {"bbox_2d": [x1, y1, x2, y2], "label": ...}, corner-to-corner, in
        RESIZED-image pixel space — not the [x,y,w,h] schema
        _parse_grounded_elements() expects."""
        cleaned = _strip_json_fence(raw_text)
        parsed, error = _extract_json(cleaned)
        if error:
            return []

        recovered = _as_list(parsed, element_keys=("bbox_2d", "label"))
        if recovered is None:
            return []

        scale_x = W / resized_w if resized_w else 1.0
        scale_y = H / resized_h if resized_h else 1.0

        elements = []
        for i, raw_el in enumerate(recovered):
            if not isinstance(raw_el, dict):
                continue
            raw_bbox = raw_el.get("bbox_2d")
            if not (isinstance(raw_bbox, list) and len(raw_bbox) == 4):
                continue
            x1, y1, x2, y2 = (float(v) for v in raw_bbox)
            x = max(0.0, min(x1 * scale_x, W))
            y = max(0.0, min(y1 * scale_y, H))
            w = max(0.0, min((x2 - x1) * scale_x, W - x))
            h = max(0.0, min((y2 - y1) * scale_y, H - y))
            bbox = [round(x, 2), round(y, 2), round(w, 2), round(h, 2)]
            normalized_bbox = [round(x / W, 5), round(y / H, 5), round(w / W, 5), round(h / H, 5)]
            center = [round(x + w / 2, 2), round(y + h / 2, 2)]
            # This focused prompt doesn't ask for a confidence value (Qwen's
            # native grounding format has none) — fixed at 1.0 just so
            # draw_vlm_result's confidence_tier coloring still works.
            elements.append(
                VLMGroundedElement(
                    id=f"vlmg_{i + 1:04d}", class_="content_card", text=None, bbox=bbox,
                    normalized_bbox=normalized_bbox, center=center,
                    confidence=1.0, confidence_tier=confidence_tier(1.0),
                )
            )
        return elements


def _grounded_response_schema() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "class": {"type": "string", "enum": sorted(ALLOWED_CLASSES)},
                "text": {"type": ["string", "null"]},
                "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "confidence": {"type": "number"},
            },
            "required": ["class", "bbox", "confidence"],
        },
    }


@dataclass
class VLMGroundedElement:
    id: str
    class_: str
    text: Optional[str]
    bbox: list
    normalized_bbox: list
    center: list
    confidence: float
    confidence_tier: str
    source: str = "vlm_grounded_experimental"

    def to_dict(self):
        return {
            "id": self.id, "class": self.class_, "text": self.text, "bbox": self.bbox,
            "normalized_bbox": self.normalized_bbox, "center": self.center,
            "confidence": self.confidence, "confidence_tier": self.confidence_tier,
            "source": self.source,
        }


@dataclass
class VLMGroundedResult:
    screen: str
    image_path: str
    image_width: int
    image_height: int
    model: str
    prompt_version: str
    inference_time_seconds: float
    done_reason: str
    raw_text: str
    elements: list = field(default_factory=list)

    def to_dict(self):
        return {
            "screen": self.screen, "image": self.image_path, "image_width": self.image_width,
            "image_height": self.image_height, "model": self.model, "prompt_version": self.prompt_version,
            "inference_time_seconds": round(self.inference_time_seconds, 3), "done_reason": self.done_reason,
            "element_count": len(self.elements), "elements": [e.to_dict() for e in self.elements],
            "raw_text": self.raw_text,
        }

    def save_json(self, path: Path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
