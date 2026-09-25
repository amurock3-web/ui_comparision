import json

import pytest
from PIL import Image

from src.baselines import StaleBaselineError, add_baseline, infer_device, list_baselines, load_baseline
from src.schema.ui_element import UIDocument


def _doc(w=1080, h=2400):
    return UIDocument(screen_id="home", source="client", image_width=w, image_height=h, elements=[])


def _image(tmp_path, w=108, h=240, name="design.png"):
    path = tmp_path / name
    Image.new("RGB", (w, h)).save(path)
    return path


def test_infer_device():
    assert infer_device(1080, 2400) == "phone"
    assert infer_device(1000, 1600) == "phone"
    assert infer_device(1536, 2048) == "tablet"
    assert infer_device(1000, 1000) == "tablet"
    assert infer_device(1920, 1080) == "tv"


def test_add_load_round_trip(tmp_path):
    root = tmp_path / "baselines"
    added = add_baseline(_image(tmp_path), "home", fused_doc=_doc(), root=root)
    assert added.key == "home/phone/default"
    folder = root / "home" / "phone" / "default"
    assert {p.name for p in folder.iterdir()} == {"client.png", "client_fused.json", "meta.json"}
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["source_file"].endswith("design.png") and len(meta["config_hash"]) == 64
    assert "detector" in meta and "ocr" in meta

    for key in ("home", "home/phone", "home/phone/default"):
        loaded = load_baseline(key, root)
        assert loaded.doc == _doc() and loaded.image.name == "client.png"
    assert [r["key"] for r in list_baselines(root)] == ["home/phone/default"]


def test_overrides_and_ambiguous_key(tmp_path):
    root = tmp_path / "baselines"
    add_baseline(_image(tmp_path), "home", fused_doc=_doc(), root=root)
    add_baseline(_image(tmp_path, 192, 108, "tv.png"), "home", language="ta",
                 fused_doc=_doc(1920, 1080), root=root)
    add_baseline(_image(tmp_path), "home", device="tablet", fused_doc=_doc(), root=root)
    assert [r["key"] for r in list_baselines(root)] == ["home/phone/default", "home/tablet/default", "home/tv/ta"]
    with pytest.raises(LookupError):
        load_baseline("home", root)
    assert load_baseline("home", root, device="tv").key == "home/tv/ta"
    with pytest.raises(LookupError):
        load_baseline("missing", root)


def test_stale_hash_is_refused(tmp_path):
    root = tmp_path / "baselines"
    add_baseline(_image(tmp_path), "home", fused_doc=_doc(), root=root)
    meta_path = root / "home" / "phone" / "default" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["config_hash"] = "0" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert list_baselines(root)[0]["stale"] is True
    with pytest.raises(StaleBaselineError, match="re-add"):
        load_baseline("home", root)
    assert load_baseline("home", root, allow_stale=True).key == "home/phone/default"
