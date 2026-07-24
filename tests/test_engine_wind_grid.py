"""engine.wind_grid: altitude × hour wind table extracted from the 1d response."""
import engine


def _day_data():
    """One-day open-meteo-shaped response, hours 04..20, with pressure-level winds.
    Geopotential heights are constant across hours here (real data varies slightly)."""
    hours = [f"2026-07-25T{h:02d}:00" for h in range(24)]
    n = len(hours)

    def const(v):
        return [v] * n

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {"time": ["2026-07-25"], "sunrise": ["2026-07-25T05:00"],
                  "sunset": ["2026-07-25T20:00"]},
        "hourly": {
            "time": hours,
            "wind_speed_10m": const(2.0), "wind_direction_10m": const(180.0),
            "wind_speed_925hPa": const(3.0), "wind_direction_925hPa": const(190.0),
            "geopotential_height_925hPa": const(760.0),
            "wind_speed_850hPa": const(4.0), "wind_direction_850hPa": const(200.0),
            "geopotential_height_850hPa": const(1500.0),
            "wind_speed_700hPa": const(6.0), "wind_direction_700hPa": const(210.0),
            "geopotential_height_700hPa": const(3000.0),
            "wind_speed_600hPa": const(9.0), "wind_direction_600hPa": const(220.0),
            "geopotential_height_600hPa": const(4200.0),
            "wind_speed_500hPa": const(13.0), "wind_direction_500hPa": const(230.0),
            "geopotential_height_500hPa": const(5600.0),
        },
    }


def _high_site():  # launch above 850hPa — 925/850 are below launch
    return {"name": "Гудаури", "lat": 42.47, "lon": 44.48,
            "elevation_m": 2685, "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def _low_site():  # launch below every pressure level
    return {"name": "Лалискури", "lat": 42.1, "lon": 45.3,
            "elevation_m": 400, "aspect": "ЮЗ", "aspect_deg": 225.0, "notes": ""}


def test_wind_grid_hours_are_daylight_hourly():
    g = engine.wind_grid(_day_data(), _high_site())
    assert g["hours"] == list(range(5, 21))  # sunrise 05 .. sunset 20 inclusive
    assert g["date"] == "2026-07-25" and g["launch_m"] == 2685


def test_wind_grid_high_launch_drops_sub_launch_levels_keeps_one_context():
    g = engine.wind_grid(_day_data(), _high_site())
    alts = [lv["alt_m_msl"] for lv in g["levels"]]
    # 925 (760) is the sub-launch level dropped; 850 (1500) is the ONE context row kept.
    assert 760 not in alts
    assert 1500 in alts               # nearest-below-launch context row
    assert alts == sorted(alts)       # ascending by altitude
    # 10m (~2695) + 700/600/500 above launch are present
    assert 2695 in alts and 3000 in alts and 4200 in alts and 5600 in alts


def test_wind_grid_marks_launch_surface_and_fills_cells():
    g = engine.wind_grid(_day_data(), _high_site())
    launch_rows = [lv for lv in g["levels"] if lv["is_launch"]]
    assert len(launch_rows) == 1 and launch_rows[0]["label"].startswith("10")
    top = g["levels"][-1]             # 500hPa row
    assert len(top["hourly"]) == len(g["hours"])
    cell = top["hourly"][0]
    assert cell["hour"] == 5 and round(cell["wind_ms"]) == 13 and cell["dir_deg"] == 230


def test_wind_grid_low_launch_keeps_all_levels():
    g = engine.wind_grid(_day_data(), _low_site())
    alts = [lv["alt_m_msl"] for lv in g["levels"]]
    assert 760 in alts and 5600 in alts and len(g["levels"]) == 6


import os

import charts


def test_wind_grid_png_writes_file(tmp_path):
    g = engine.wind_grid(_day_data(), _high_site())
    path = charts.wind_grid_png(g, _high_site(), str(tmp_path))
    assert os.path.exists(path) and path.endswith(".png")
    assert os.path.getsize(path) > 1000  # a real image, not an empty stub


import asyncio

import forecast


def test_get_wind_grid_uses_cache_and_returns_png(monkeypatch):
    # warm cache: a 7-tuple whose grid is a real engine.wind_grid dict
    g = engine.wind_grid(_day_data(), _high_site())
    _site, _date, key = forecast._resolve("Гудаури", "1d", "2026-07-25")
    import time
    forecast._fcache[key] = (time.monotonic() + 999, "card", [], {}, "fb", [], g)

    async def boom(*a, **k):  # must NOT re-fetch when the cache is warm
        raise AssertionError("re-fetched despite warm cache")

    monkeypatch.setattr(forecast, "_fetch_build", boom)
    png = asyncio.run(forecast.get_wind_grid("Гудаури", "2026-07-25"))
    assert isinstance(png, (bytes, bytearray)) and len(png) > 1000
