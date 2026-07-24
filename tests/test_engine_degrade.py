"""report_1day / facts_1day degrade gracefully when the model omits
boundary_layer_height and freezing_level_height (e.g. ECMWF)."""
import os
import tempfile

import engine


def _data(blh=1200.0, frz=4000.0):
    """One complete day; blh/frz=None models a ceiling-less model (ECMWF)."""
    hours = [f"2026-07-25T{h:02d}:00" for h in range(24)]
    n = len(hours)

    def c(v):
        return [v] * n

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {
            "time": ["2026-07-25"], "sunrise": ["2026-07-25T05:00"], "sunset": ["2026-07-25T20:00"],
            "temperature_2m_max": [22.0], "temperature_2m_min": [10.0], "precipitation_sum": [0.0],
            "weather_code": [0], "sunshine_duration": [40000.0], "wind_speed_10m_max": [4.0],
            "wind_gusts_10m_max": [7.0], "wind_direction_10m_dominant": [180.0],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": c(20.0), "dew_point_2m": c(8.0),
            "wind_speed_10m": c(2.0), "wind_gusts_10m": c(4.0), "wind_direction_10m": c(180.0),
            "precipitation": c(0.0), "cape": c(50.0),
            "cloud_cover_low": c(10.0), "cloud_cover_mid": c(10.0),
            "boundary_layer_height": c(blh), "freezing_level_height": c(frz),
            "wind_speed_925hPa": c(3.0), "wind_direction_925hPa": c(190.0), "geopotential_height_925hPa": c(760.0),
            "wind_speed_850hPa": c(4.0), "wind_direction_850hPa": c(200.0), "geopotential_height_850hPa": c(1500.0),
            "wind_speed_700hPa": c(6.0), "wind_direction_700hPa": c(210.0), "geopotential_height_700hPa": c(3000.0),
            "wind_speed_600hPa": c(9.0), "wind_direction_600hPa": c(220.0), "geopotential_height_600hPa": c(4200.0),
            "wind_speed_500hPa": c(13.0), "wind_direction_500hPa": c(230.0), "geopotential_height_500hPa": c(5600.0),
        },
    }


def _null_data():
    d = _data()
    d["hourly"]["boundary_layer_height"] = [None] * 24
    d["hourly"]["freezing_level_height"] = [None] * 24
    return d


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def test_report_1day_full_has_ceiling_and_chart():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_data(), _site(), out)
    assert "Потолок:" in text and "н/д" not in text
    assert any("ceiling" in os.path.basename(p) for p in pngs)  # 02_ceiling.png present


def test_report_1day_degrades_without_blh():
    out = tempfile.mkdtemp()
    text, pngs, _card = engine.report_1day(_null_data(), _site(), out)
    assert "Потолок: н/д" in text            # no crash, explicit н/д
    assert not any("ceiling" in os.path.basename(p) for p in pngs)  # ceiling chart skipped
    assert any("meteogram" in os.path.basename(p) for p in pngs)    # other charts still there
    assert any("windprofile" in os.path.basename(p) for p in pngs)


def test_facts_1day_nulls_missing_and_reports_model():
    f = engine.facts_1day(_null_data(), _site())
    assert f["thermal_ceiling_m_agl"] is None and f["thermal_ceiling_m_msl"] is None
    assert f["freezing_level_m"] is None
    assert f["site"]["model"]  # model label present


def test_facts_1day_full_keeps_ceiling():
    f = engine.facts_1day(_data(), _site())
    assert f["thermal_ceiling_m_agl"] is not None and f["freezing_level_m"] is not None
