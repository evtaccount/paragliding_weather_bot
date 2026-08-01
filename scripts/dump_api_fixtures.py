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


def write(name: str, payload) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path.relative_to(ROOT))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    day = fx.om_1day()
    week = fx.om_overview([f"2026-07-{d:02d}" for d in range(25, 32)])

    write("facts_1d", engine.facts_1day(day, SITE))
    write("wind_grid", engine.wind_grid(day, SITE))
    write("overview_3d", engine.overview_rows(week, SITE))
    write("sites", [SITE])
    write("prefs", {"avg_route_speed_kmh": 25.0, "wind_correction_enabled": True,
                    "model_key": "ecmwf",
                    "models": [{"key": k, "label": engine.model_label(k)} for k in engine.MODELS]})
    write("scan", {"sites": [{"name": SITE["name"], "aspect": SITE["aspect"],
                              "days": engine.overview_rows(week, SITE)[:2]}],
                   "empty": [], "failed": []})
    write("routes", [{"name": "Гудаури — Коби",
                      "points": [[42.47, 44.48, "старт"], [42.53, 44.51, "Коби"]],
                      "saved_at": "2026-07-25"}])


if __name__ == "__main__":
    main()
