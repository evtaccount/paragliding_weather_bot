#!/usr/bin/env python3
"""Настоящие ответы API в файлы, без сети.

Типы фронтенда и моки его тестов должны описывать то, что домен отдаёт на
самом деле. Написанные по памяти, они расходятся с бэкендом молча: экран
читает поле, которого нет, и показывает пустоту вместо числа.

Данные берутся из tests/fixtures.py — тех же, на которых стоят тесты домена.

    python scripts/dump_api_fixtures.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
from tests import fixtures as fx  # noqa: E402

OUT = ROOT / "webapp" / "test" / "fixtures"

SITE = {"name": "Гудаури", "lat": 42.47, "lon": 44.48, "elevation_m": 2200,
        "aspect": "Ю", "aspect_deg": 180.0, "slope_deg": 25.0, "route_top_m": 3000.0,
        "aliases": ["gudauri"], "notes": ""}

# Старт без размеченной экспозиции — Facts.site.aspect/aspect_deg реально бывают
# null (engine.py: facts_1day — `card(aspect) if aspect is not None else None`).
SITE_NO_ASPECT = {"name": "Плато", "lat": 42.30, "lon": 44.20, "elevation_m": 1800,
                  "aspect": None, "aspect_deg": None, "slope_deg": None, "route_top_m": None,
                  "aliases": [], "notes": "экспозиция не размечена"}

# Настоящие координаты Гудаури, но склон смотрит на север — реальный старт бота
# зимой, не искусственная широта.
SITE_NORTH = {"name": "Гудаури-Север", "lat": 42.47, "lon": 44.48, "elevation_m": 2200,
             "aspect": "С", "aspect_deg": 0.0, "slope_deg": 25.0, "route_top_m": 3000.0,
             "aliases": [], "notes": ""}


def _windy_day():
    """Задутый ветром обед + пропавший CIN утром + отсутствующий lifted_index.

    Даёт разом непустые assessment.warnings/vetoes_in_window/unchecked_vetoes,
    ключ "veto" в hourly_daytime (criteria.py:536-537 — compact() добавляет его
    только при непустых вето) и пропавший ключ в derived_peak_hour (engine.py:
    1070-1072 — словарь собирается через `if v is not None`, отсутствующий
    параметр не зануляется, а отсутствует). Пустые списки — тот же класс дыры
    в проверке типов, что never[]-совместимость массивов (см. task-3-report.md,
    Critical 2): без этого сценария assessment.warnings/vetoes_in_window/
    unchecked_vetoes в фикстурах всегда были бы [] и не ловили бы поломку типа.
    """
    n = 24
    wind = [2.0] * n
    gust = [4.0] * n
    cin = [60.0] * n
    for h in (12, 13, 14):          # обеденный порыв — вето gust_factor/gust_delta
        wind[h], gust[h] = 9.0, 16.0
    for h in (7, 8, 9, 10):         # CIN не пришёл — cape_cin уходит в unchecked
        cin[h] = None
    day = fx.om_1day(wind_speed_10m=wind, wind_gusts_10m=gust, convective_inhibition=cin)
    return fx.om_null(day, "lifted_index")   # параметр не посчитан — warnings: no_data:*


def _no_ceiling_day():
    """ECMWF (модель бота по умолчанию) не отдаёт boundary_layer_height и
    freezing_level_height — engine.py:_series_available видит пустой ряд, и
    facts_1day кладёт None в freezing_level_m/thermal_ceiling_m_agl/msl
    (engine.py:1005-1006,1050-1052)."""
    return fx.om_null(fx.om_1day(), "boundary_layer_height", "freezing_level_height")


def _december_day():
    """Декабрьский короткий день — солнце невысоко и в SITE_NORTH не набирается
    часов с нужной высотой: engine.sun_hours отдаёт термическое окно None
    (facts_1day кладёт его в thermal_window без проверки)."""
    return fx.om_1day(date="2026-12-15", sunrise="07:15", sunset="16:45")


def write(name: str, payload) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = fx.om_1day()
    week = fx.om_overview([f"2026-07-{d:02d}" for d in range(25, 32)])

    write("facts_1d", engine.facts_1day(day, SITE))
    write("facts_1d_windy", engine.facts_1day(_windy_day(), SITE))
    write("facts_1d_no_ceiling", engine.facts_1day(_no_ceiling_day(), SITE_NO_ASPECT))
    write("facts_1d_no_window", engine.facts_1day(_december_day(), SITE_NORTH))
    # GET /api/forecast?range=3d|week|2weeks — ДРУГАЯ форма ответа, чем range=1d:
    # forecast.py:347-349 зовёт engine.facts_overview, а не facts_1day. Без этой
    # фикстуры экран обзора (задача 10) типизировал бы диапазонный ответ формой
    # однодневного — поля бы не совпали (site без "model", days_daytime вместо
    # hourly_daytime, другой набор ключей дня).
    write("forecast_3d", engine.facts_overview(week, SITE, "3d"))
    write("wind_grid", engine.wind_grid(day, SITE))
    write("overview_3d", engine.overview_rows(week, SITE))
    write("sites", [SITE])
    write("prefs", {"avg_route_speed_kmh": 25.0, "wind_correction_enabled": True,
                    "model_key": "ecmwf",
                    "models": [{"key": k, "label": engine.model_label(k)} for k in engine.MODELS]})
    write("scan", {"sites": [{"name": SITE["name"], "aspect": SITE["aspect"],
                              "days": engine.overview_rows(week, SITE)[:2]}],
                   "empty": [], "failed": []})
    # Скан со стартом без лётных дней и стартом, который упал ошибкой — иначе
    # Scan.empty/Scan.failed всегда были бы [] и never[] тихо прошёл бы под
    # любой (в том числе неверный) тип элемента массива (см. Critical 2).
    write("scan_mixed", {"sites": [{"name": SITE["name"], "aspect": SITE["aspect"],
                                    "days": engine.overview_rows(week, SITE)[:2]}],
                         "empty": ["Лалискури"], "failed": ["Казбеги"]})
    write("routes", [{"name": "Гудаури — Коби",
                      "points": [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]],
                      "saved_at": "2026-07-25"}])


if __name__ == "__main__":
    main()
