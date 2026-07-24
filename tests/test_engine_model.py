"""engine model registry + persisted global setting + build_url &models=."""
import os

import engine


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def _clear():
    if os.path.exists(engine.MODEL_FILE):
        os.remove(engine.MODEL_FILE)


def test_default_model_is_ecmwf():
    _clear()
    assert engine.get_model_key() == "ecmwf"
    assert engine.model_id("ecmwf") == "ecmwf_ifs025"
    assert engine.model_label("ecmwf") == "ECMWF"


def test_set_and_get_roundtrip():
    _clear()
    engine.set_model_key("gfs")
    assert engine.get_model_key() == "gfs"
    assert engine.model_id(engine.get_model_key()) == "gfs_seamless"


def test_set_rejects_unknown_key():
    _clear()
    import pytest
    with pytest.raises(ValueError):
        engine.set_model_key("nope")
    assert engine.get_model_key() == "ecmwf"  # unchanged


def test_corrupt_model_file_falls_back_to_default():
    with open(engine.MODEL_FILE, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert engine.get_model_key() == "ecmwf"


def test_build_url_includes_current_model():
    _clear()
    assert "models=ecmwf_ifs025" in engine.build_url(_site(), "week")
    engine.set_model_key("icon")
    assert "models=icon_seamless" in engine.build_url(_site(), "1d", "2026-07-25")
    _clear()
