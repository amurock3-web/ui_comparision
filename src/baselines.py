"""Baseline library (phase 15.5): a client design run through detector + OCR once
and stored, so a comparison only pays for the production side.

    baselines/<screen_id>/<device>/<language>/
        client.<ext>        the design image (gitignored)
        client_fused.json   the fused UIDocument
        meta.json           created, source_file, config_hash, detector/OCR info (rules.md §15)

config_hash covers config/detector.yaml and the extraction sections of
config/config.yaml (ocr, fusion, vlm) - not the comparison thresholds. A baseline built
under other settings is stale: load_baseline refuses it (StaleBaselineError)
so it is re-added, never silently reused.
"""
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from src.schema.ui_element import UIDocument

ROOT = Path("baselines")
CONFIG_FILES = (Path("config/config.yaml"), Path("config/detector.yaml"))


class StaleBaselineError(RuntimeError):
    pass


@dataclass
class Baseline:
    key: str
    path: Path
    doc: UIDocument
    image: Path
    meta: dict


# Only what shapes the stored fused document: all of detector.yaml, and the
# ocr / fusion / vlm sections of config.yaml. Comparison thresholds change often
# and are applied at compare time, so they must not mark every baseline stale.
EXTRACTION_SECTIONS = ("ocr", "fusion", "vlm")


def config_hash(files=CONFIG_FILES) -> str:
    h = hashlib.sha256()
    for f in files:
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        if Path(f).name == "config.yaml":
            data = {k: data.get(k) for k in EXTRACTION_SECTIONS}
        h.update(json.dumps(data, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()


def infer_device(width: int, height: int) -> str:
    """h/w >= 1.6 phone, 1.0-1.6 tablet, landscape tv."""
    if width > height:
        return "tv"
    return "phone" if height / width >= 1.6 else "tablet"


def is_stale(meta: dict) -> bool:
    return meta.get("config_hash") != config_hash()


def _engine_info() -> dict:
    detector = yaml.safe_load(CONFIG_FILES[1].read_text(encoding="utf-8")) or {}
    config = yaml.safe_load(CONFIG_FILES[0].read_text(encoding="utf-8")) or {}
    card = Path(detector.get("bundle", "")) / "model_card.json"
    return {
        "detector": {"engine": detector.get("engine"), "bundle": detector.get("bundle"),
                     "model_card": json.loads(card.read_text(encoding="utf-8")) if card.is_file() else None},
        "ocr": {"engine": "PaddleOCR", "lang": "en", **(config.get("ocr") or {})},
    }


def add_baseline(image, screen: str, device=None, language=None, fused_doc: UIDocument = None,
                 root: Path = ROOT) -> Baseline:
    """Store `image` as the client baseline for `screen`. Runs the pipeline on it
    unless a fused_doc is passed. Re-adding the same key replaces it."""
    image = Path(image)
    if fused_doc is None:
        from src.pipeline import build_document  # paddleocr import; only when really needed
        fused_doc, _ = build_document(image, screen, "client")
    device = device or infer_device(fused_doc.image_width, fused_doc.image_height)
    language = language or "default"
    folder = Path(root) / screen / device / language
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    stored = folder / f"client{image.suffix.lower()}"
    shutil.copyfile(image, stored)
    fused_doc.save_json(folder / "client_fused.json")
    meta = {
        "screen_id": screen, "device": device, "language": language,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(image.resolve()),
        "image_size": [fused_doc.image_width, fused_doc.image_height],
        "config_hash": config_hash(),
        **_engine_info(),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return load_baseline(f"{screen}/{device}/{language}", root)


def list_baselines(root: Path = ROOT) -> list[dict]:
    """One row per stored baseline: key, path, stale, meta."""
    rows = []
    for meta_path in sorted(Path(root).glob("*/*/*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        folder = meta_path.parent
        rows.append({"key": folder.relative_to(root).as_posix(), "path": folder,
                     "stale": is_stale(meta), "meta": meta})
    return rows


def load_baseline(key: str, root: Path = ROOT, device=None, allow_stale=False) -> Baseline:
    """key = screen[/device[/language]]. A partial key must resolve to one
    baseline (`device` breaks a tie on a screen-only key). Raises StaleBaselineError
    for a stale one unless allow_stale."""
    parts = key.strip("/").split("/")
    pattern = "/".join(parts + ["*"] * (3 - len(parts)))
    folders = sorted(p.parent for p in Path(root).glob(f"{pattern}/meta.json"))
    if len(folders) > 1 and len(parts) == 1 and device:
        folders = [f for f in folders if f.parent.name == device]
    if len(folders) != 1:
        found = ", ".join(f.relative_to(root).as_posix() for f in folders) or "none"
        raise LookupError(f"baseline {key!r}: expected one match under {root}, found {found}")
    folder = folders[0]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    full_key = folder.relative_to(root).as_posix()
    if is_stale(meta) and not allow_stale:
        raise StaleBaselineError(f"baseline {full_key} is stale (config changed since {meta.get('created')}), "
                                 f"re-add it with scripts.add_baseline")
    doc = UIDocument.model_validate_json((folder / "client_fused.json").read_text(encoding="utf-8"))
    image = next(folder.glob("client.*"), None)  # gitignored: missing on a fresh clone
    if image is None:
        raise FileNotFoundError(f"baseline {full_key} has no client image, re-add it with scripts.add_baseline")
    return Baseline(full_key, folder, doc, image, meta)
