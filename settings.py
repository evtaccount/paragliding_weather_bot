"""Глобальные настройки маршрута — один файл на бота, как выбор метеомодели.

Настройка метеомодели живёт в engine.py и сюда не переезжает: там она оправдана
тем, что build_url использует её напрямую. У маршрутных настроек такой привязки
нет, поэтому им отдельный файл.
"""
import json
import os

import engine

SETTINGS_FILE = (os.environ.get("SETTINGS_FILE")
                 or os.path.join(os.path.dirname(engine.SITES) or ".", "settings.json"))

# 25 км/ч — разумный дефолт для уверенного XC-пилота на B+. Реальный разброс:
# 18–22 в слабый день, 25–30 в рабочий, 30–35 у сильных пилотов на коротком маршруте.
DEFAULTS = {"avg_route_speed_kmh": 25.0, "wind_correction_enabled": True}
SPEED_MIN, SPEED_MAX = 10.0, 45.0


def get():
    """Текущие настройки; дефолты при отсутствии, порче или чужих ключах."""
    out = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    for key in DEFAULTS:
        if key in raw:
            out[key] = raw[key]
    return out


def _save(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def set_speed(value):
    """Средняя маршрутная скорость в км/ч. ValueError вне допустимого диапазона."""
    value = float(value)
    if not SPEED_MIN <= value <= SPEED_MAX:
        raise ValueError(
            f"средняя маршрутная скорость должна быть от {SPEED_MIN:.0f} до {SPEED_MAX:.0f} км/ч. "
            "Это средняя по маршруту с учётом наборов в термиках, а не скорость крыла.")
    data = get()
    data["avg_route_speed_kmh"] = value
    _save(data)


def set_wind_correction(on):
    data = get()
    data["wind_correction_enabled"] = bool(on)
    _save(data)
