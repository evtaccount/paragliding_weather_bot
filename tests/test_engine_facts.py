"""facts_1day: the LLM payload must include upper-level (600/500 hPa) wind direction,
now that H_1D fetches wind_direction_600hPa / _500hPa."""
import engine


def _full_1d():
    """A complete one-day open-meteo response with every field facts_1day reads."""
    hours = [f"2026-07-25T{h:02d}:00" for h in range(24)]
    n = len(hours)

    def c(v):
        return [v] * n

    return {
        "timezone": "Asia/Tbilisi",
        "daily": {
            "time": ["2026-07-25"],
            "sunrise": ["2026-07-25T05:00"], "sunset": ["2026-07-25T20:00"],
            "temperature_2m_max": [22.0], "temperature_2m_min": [10.0],
            "precipitation_sum": [0.0], "weather_code": [0],
            "sunshine_duration": [40000.0], "wind_speed_10m_max": [4.0],
            "wind_gusts_10m_max": [7.0], "wind_direction_10m_dominant": [180.0],
        },
        "hourly": {
            "time": hours,
            "temperature_2m": c(20.0), "dew_point_2m": c(8.0),
            "wind_speed_10m": c(2.0), "wind_gusts_10m": c(4.0), "wind_direction_10m": c(180.0),
            "precipitation": c(0.0), "cape": c(50.0),
            "cloud_cover_low": c(10.0), "cloud_cover_mid": c(10.0),
            "boundary_layer_height": c(1200.0), "freezing_level_height": c(4000.0),
            "wind_speed_925hPa": c(3.0), "wind_direction_925hPa": c(190.0), "geopotential_height_925hPa": c(760.0),
            "wind_speed_850hPa": c(4.0), "wind_direction_850hPa": c(200.0), "geopotential_height_850hPa": c(1500.0),
            "wind_speed_700hPa": c(6.0), "wind_direction_700hPa": c(210.0), "geopotential_height_700hPa": c(3000.0),
            "wind_speed_600hPa": c(9.0), "wind_direction_600hPa": c(220.0), "geopotential_height_600hPa": c(4200.0),
            "wind_speed_500hPa": c(13.0), "wind_direction_500hPa": c(230.0), "geopotential_height_500hPa": c(5600.0),
        },
    }


def _site():
    return {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}


def test_facts_1day_carries_the_thermal_window_and_per_hour_sun():
    f = engine.facts_1day(_full_1d(), _site())
    w = f["thermal_window"]
    assert w["start_hour"] >= 7 and w["end_hour"] <= 19   # sunrise 05:00 / sunset 20:00
    hours = {h["time"]: h for h in f["hourly_daytime"]}
    assert hours["12:00"]["slope_sun_index"] > hours["06:00"]["slope_sun_index"]
    assert 165 < hours["12:00"]["sun_az_deg"] < 195       # south slope, sun on the face


def test_facts_overview_carries_a_thermal_window_per_day():
    data = _full_1d()
    f = engine.facts_overview(data, _site(), "3d")
    assert f["days_daytime"][0]["thermal_window"]["start_hour"] >= 7


def test_facts_1day_includes_upper_level_directions():
    f = engine.facts_1day(_full_1d(), _site())
    prof = {r["level"]: r for r in f["wind_profile_peak_hour"]}
    # the two top levels now carry a direction (previously hard-coded None → key absent)
    assert prof["600hPa"]["dir_deg"] == 220
    assert prof["500hPa"]["dir_deg"] == 230
    # lower levels unchanged
    assert prof["700hPa"]["dir_deg"] == 210
    assert prof["10m"]["dir_deg"] == 180
