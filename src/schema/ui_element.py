"""
Pydantic UIElement schema (design.md §5, architecture.md §7).

Canonical UIElement model shared by OCR, VLM, fusion, graph, and
comparison. `class_` is optional (aliased to the JSON field "class") so a
pure-OCR text detection with no matching VLM classification can still be
kept as evidence (source="ocr", class=None) instead of being dropped —
per rules.md §10, uncertain/incomplete observations are preserved, not
silently discarded.

`bbox`/`normalized_bbox`/`center` are optional for the same reason:
fusion's classify-only VLM design (see fusion/fuse.py) only produces real
geometry for classes it can ground deterministically via OCR text-match or
grid inference — a VLM classification like "icon" or "navigation_bar" with
no OCR-matchable text and no grid rule has no reliable geometry source at
all. Dropping it would destroy real classification evidence; keeping it
with bbox=None preserves it instead.
"""

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CLASSES_PATH = Path(__file__).resolve().parents[2] / "config" / "classes.json"
ALLOWED_CLASSES = frozenset(json.loads(_CLASSES_PATH.read_text())["classes"])


class UIElement(BaseModel):
    id: str
    class_: Optional[str] = Field(default=None, alias="class")
    text: Optional[str] = None
    bbox: Optional[list[float]] = None            # [x, y, w, h], pixel space
    normalized_bbox: Optional[list[float]] = None  # [x/W, y/H, w/W, h/H]
    center: Optional[list[float]] = None           # [cx, cy]
    confidence: float
    confidence_tier: Literal["high", "medium", "low"]
    source: Literal["ocr", "vlm", "fused"]
    parent_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("class_")
    @classmethod
    def _class_in_taxonomy(cls, v):
        if v is not None and v not in ALLOWED_CLASSES:
            raise ValueError(f"class {v!r} is not in the allowed taxonomy: {sorted(ALLOWED_CLASSES)}")
        return v

    @field_validator("bbox", "normalized_bbox")
    @classmethod
    def _four_numbers(cls, v):
        if v is not None and len(v) != 4:
            raise ValueError(f"expected 4 values [x, y, w, h], got {len(v)}")
        return v

    @field_validator("center")
    @classmethod
    def _two_numbers(cls, v):
        if v is not None and len(v) != 2:
            raise ValueError(f"expected 2 values [cx, cy], got {len(v)}")
        return v

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)


class UIDocument(BaseModel):
    """Top-level "UI JSON" per architecture.md §7."""

    screen_id: str
    source: Literal["production", "client", "fused"]
    image_width: int
    image_height: int
    elements: list[UIElement]

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True)

    def save_json(self, path: Path):
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
