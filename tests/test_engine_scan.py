"""engine.overview_rows: per-day flyability assessment shared by the card and scan."""
import criteria
import engine
from fixtures import om_overview, site as _site


def _week_data():
    """Two days: day 0 calm/flyable, day 1 windy."""
    return om_overview(
        ["2026-07-25", "2026-07-26"],
        temperature_2m=[20.0, 19.0],
        wind_speed_10m=[4.0, 12.0],
        wind_gusts_10m=[7.0, 16.0],
        temperature_2m_max=[22.0, 21.0], temperature_2m_min=[10.0, 9.0],
        wind_speed_10m_max=[4.0, 12.0], wind_gusts_10m_max=[7.0, 16.0],
        weather_code=[0, 3], sunshine_duration=[40000.0, 20000.0],
    )


import asyncio

import forecast


def test_scan_week_filters_flyable_and_reports_empty(monkeypatch):
    # Two saved sites; site A has one flyable day, site B has none.
    monkeypatch.setattr(forecast.store, "load_sites", lambda: [
        {"name": "A", "aspect_deg": 180.0}, {"name": "B", "aspect_deg": 180.0},
    ])
    rows_by_site = {
        "A": [
            {"date": "2026-07-25", "emoji": "🟢", "label": "отличная лётная", "score": 78,
             "category": "excellent", "limiting": None,
             "wmax": 4, "gmax": 7, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 20},
            {"date": "2026-07-26", "emoji": "🟠", "label": "маргинальная", "score": 44,
             "category": "marginal", "limiting": "ветер у земли",
             "wmax": 8, "gmax": 13, "dom": 200, "precip": 0.0, "wc": 3, "tmax": 19},
        ],
        "B": [
            {"date": "2026-07-25", "emoji": "⛔", "label": "опасная", "score": 0,
             "category": "danger", "limiting": "ветер у земли",
             "wmax": 14, "gmax": 18, "dom": 180, "precip": 0.0, "wc": 0, "tmax": 18},
        ],
    }

    async def fake_ensure(site, rng, date, key, model=None):
        return {}, None, {"rows": rows_by_site[site["name"]]}

    monkeypatch.setattr(forecast, "_ensure", fake_ensure)
    result = asyncio.run(forecast.scan_week(model=engine.DEFAULT_MODEL_KEY))
    assert [s["name"] for s in result["sites"]] == ["A"]
    # маргинальный день отсеян — в /scan попадают категории от «удовлетворительной»
    assert [d["date"] for d in result["sites"][0]["days"]] == ["2026-07-25"]
    assert result["empty"] == ["B"]
    assert result["failed"] == []


def test_scan_week_records_failed_fetch(monkeypatch):
    monkeypatch.setattr(forecast.store, "load_sites", lambda: [{"name": "X", "aspect_deg": None}])

    async def boom(site, rng, date, key, model=None):
        raise RuntimeError("open-meteo down")

    monkeypatch.setattr(forecast, "_ensure", boom)
    result = asyncio.run(forecast.scan_week(model=engine.DEFAULT_MODEL_KEY))
    assert result["sites"] == [] and result["empty"] == [] and result["failed"] == ["X"]


def test_overview_rows_flags_flyable_and_windy_days():
    rows = engine.overview_rows(_week_data(), _site())
    assert [r["date"] for r in rows] == ["2026-07-25", "2026-07-26"]
    assert criteria.flyable(rows[0]["category"])
    # 12 м/с у земли с порывами 16 — выше trim крыла, это вето
    assert rows[1]["category"] == "danger"
    assert rows[0]["score"] > rows[1]["score"]
    assert rows[1]["limiting"], "у нелётного дня должен быть назван лимит-фактор"
    for key in ("wmax", "gmax", "dom", "precip", "wc", "tmax"):
        assert key in rows[0]
