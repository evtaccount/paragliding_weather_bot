"""engine.overview_rows: per-day flyability assessment shared by the card and scan."""
import engine


def _week_data():
    """Minimal 2-day open-meteo-shaped response: day 0 calm/flyable, day 1 windy."""
    days = ["2026-07-25", "2026-07-26"]
    hours = []
    for d in days:
        hours += [f"{d}T{h:02d}:00" for h in range(24)]

    def per_hour(day0_val, day1_val):
        return [day0_val if t[:10] == days[0] else day1_val for t in hours]

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {
            "time": days,
            "sunrise": [f"{d}T05:00" for d in days],
            "sunset": [f"{d}T20:00" for d in days],
            "temperature_2m_max": [22.0, 21.0],
            "temperature_2m_min": [10.0, 9.0],
            "wind_speed_10m_max": [4.0, 12.0],
            "wind_gusts_10m_max": [7.0, 16.0],
            "wind_direction_10m_dominant": [180.0, 180.0],
            "precipitation_sum": [0.0, 0.0],
            "weather_code": [0, 3],
            "sunshine_duration": [40000.0, 20000.0],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": per_hour(20.0, 19.0),
            "wind_speed_10m": per_hour(4.0, 12.0),
            "wind_gusts_10m": per_hour(7.0, 16.0),
            "wind_direction_10m": per_hour(180.0, 180.0),
        },
    }


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


import asyncio

import forecast


def test_scan_week_filters_flyable_and_reports_empty(monkeypatch):
    # Two saved sites; site A has one flyable day, site B has none.
    monkeypatch.setattr(forecast.engine, "load_sites", lambda: [
        {"name": "A", "aspect_deg": 180.0}, {"name": "B", "aspect_deg": 180.0},
    ])
    rows_by_site = {
        "A": [
            {"date": "2026-07-25", "emoji": "✅", "label": "лётный", "score": 90,
             "wmax": 4, "gmax": 7, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 20},
            {"date": "2026-07-26", "emoji": "⚠️", "label": "маргинальный", "score": 40,
             "wmax": 8, "gmax": 13, "dom": 200, "precip": 0.0, "wc": 3, "tmax": 19},
        ],
        "B": [
            {"date": "2026-07-25", "emoji": "❌", "label": "нелётный (ветер)", "score": 5,
             "wmax": 14, "gmax": 18, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 18},
        ],
    }

    async def fake_ensure(site, rng, date, key):
        return "card", [], {}, "fb", rows_by_site[site["name"]]

    monkeypatch.setattr(forecast, "_ensure", fake_ensure)
    result = asyncio.run(forecast.scan_week())
    assert [s["name"] for s in result["sites"]] == ["A"]
    # маргинальный is excluded — only the "лётный" day survives
    assert [d["date"] for d in result["sites"][0]["days"]] == ["2026-07-25"]
    assert result["empty"] == ["B"]
    assert result["failed"] == []


def test_scan_week_records_failed_fetch(monkeypatch):
    monkeypatch.setattr(forecast.engine, "load_sites", lambda: [{"name": "X", "aspect_deg": None}])

    async def boom(site, rng, date, key):
        raise RuntimeError("open-meteo down")

    monkeypatch.setattr(forecast, "_ensure", boom)
    result = asyncio.run(forecast.scan_week())
    assert result["sites"] == [] and result["empty"] == [] and result["failed"] == ["X"]


def test_overview_rows_flags_flyable_and_windy_days():
    rows = engine.overview_rows(_week_data(), _site())
    assert [r["date"] for r in rows] == ["2026-07-25", "2026-07-26"]
    assert rows[0]["label"] == "лётный" and rows[0]["emoji"] == "✅"
    # 12 m/s wind + 16 m/s gust into a headwind slope → not flyable
    assert rows[1]["label"].startswith("нелётный")
    assert rows[0]["score"] > rows[1]["score"]
    for key in ("wmax", "gmax", "dom", "precip", "wc", "tmax"):
        assert key in rows[0]
