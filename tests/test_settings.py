"""Глобальные настройки маршрута: дефолты, валидация, устойчивость к порче файла."""
import json
import os

import pytest

import settings


def test_defaults_when_file_absent():
    assert settings.get() == settings.DEFAULTS
    assert settings.DEFAULTS["avg_route_speed_kmh"] == 25.0
    assert settings.DEFAULTS["wind_correction_enabled"] is True


def test_speed_round_trip():
    settings.set_speed(30.0)
    assert settings.get()["avg_route_speed_kmh"] == 30.0


def test_wind_correction_round_trip():
    settings.set_wind_correction(False)
    assert settings.get()["wind_correction_enabled"] is False
    assert settings.get()["avg_route_speed_kmh"] == 25.0   # соседнее поле не потеряно


@pytest.mark.parametrize("bad", [9.9, 45.1, 0.0, -5.0])
def test_speed_out_of_range_rejected(bad):
    with pytest.raises(ValueError) as e:
        settings.set_speed(bad)
    assert "средняя" in str(e.value).lower()


def test_corrupt_file_falls_back_to_defaults():
    with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write("{не json")
    assert settings.get() == settings.DEFAULTS


def test_unknown_keys_ignored():
    with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"avg_route_speed_kmh": 28.0, "мусор": 1}, f)
    got = settings.get()
    assert got["avg_route_speed_kmh"] == 28.0
    assert "мусор" not in got


def test_settings_file_lives_next_to_sites():
    import engine
    assert os.path.dirname(settings.SETTINGS_FILE) == os.path.dirname(engine.SITES)
