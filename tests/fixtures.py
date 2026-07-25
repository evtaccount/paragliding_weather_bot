"""Builders for open-meteo-shaped responses used across the engine tests.

The bot never mocks HTTP: engine functions are handed a dict shaped exactly like an
open-meteo JSON body. Those dicts used to be re-typed in four test files, so adding one
hourly variable meant four near-identical edits that drifted apart. Everything lives here
instead.

Every hourly variable defaults to a plausible constant; `overrides` accepts either a
scalar (broadcast over all hours) or an explicit list.

  om_1day()                              # one calm summer day, every field present
  om_1day(wind_speed_10m=9.0)            # same day, blown out
  om_1day(boundary_layer_height=None)    # a model that omits the series (ECMWF)
  om_overview(["2026-07-25", "2026-07-26"], wind_speed_10m=[4.0, 12.0])
"""

DATE = "2026-07-25"
SUNRISE = "05:00"
SUNSET = "20:00"

# One entry per hourly variable engine may read. Keep in sync with engine.H_1D — a
# variable requested from the API but missing here means the tests never exercise it.
HOURLY_DEFAULTS = {
    "temperature_2m": 20.0,
    "dew_point_2m": 8.0,
    "relative_humidity_2m": 45.0,
    "wind_speed_10m": 2.0,
    "wind_gusts_10m": 4.0,
    "wind_direction_10m": 180.0,
    "wind_speed_80m": 3.0,
    "wind_direction_80m": 185.0,
    "wind_speed_120m": 3.5,
    "wind_direction_120m": 188.0,
    "precipitation": 0.0,
    "precipitation_probability": 0.0,
    "cape": 50.0,
    "lifted_index": 2.0,
    "convective_inhibition": 60.0,
    "visibility": 30000.0,
    "shortwave_radiation": 700.0,
    "cloud_cover_low": 10.0,
    "cloud_cover_mid": 10.0,
    "cloud_cover_high": 5.0,
    "boundary_layer_height": 1200.0,
    "freezing_level_height": 4000.0,
    "temperature_850hPa": 12.0,
    "temperature_700hPa": 3.0,
    "relative_humidity_925hPa": 55.0,
    "wind_speed_925hPa": 3.0,
    "wind_direction_925hPa": 190.0,
    "geopotential_height_925hPa": 760.0,
    "wind_speed_850hPa": 4.0,
    "wind_direction_850hPa": 200.0,
    "geopotential_height_850hPa": 1500.0,
    "wind_speed_700hPa": 6.0,
    "wind_direction_700hPa": 210.0,
    "geopotential_height_700hPa": 3000.0,
    "wind_speed_600hPa": 9.0,
    "wind_direction_600hPa": 220.0,
    "geopotential_height_600hPa": 4200.0,
    "wind_speed_500hPa": 13.0,
    "wind_direction_500hPa": 230.0,
    "geopotential_height_500hPa": 5600.0,
}

DAILY_DEFAULTS = {
    "temperature_2m_max": 22.0,
    "temperature_2m_min": 10.0,
    "precipitation_sum": 0.0,
    "precipitation_probability_max": 0.0,
    "weather_code": 0,
    "sunshine_duration": 40000.0,
    "shortwave_radiation_sum": 25.0,
    "wind_speed_10m_max": 4.0,
    "wind_gusts_10m_max": 7.0,
    "wind_direction_10m_dominant": 180.0,
}


def _series(value, n):
    """Scalar → n copies; list → used as given (already per-hour)."""
    return list(value) if isinstance(value, (list, tuple)) else [value] * n


def om_1day(date=DATE, sunrise=SUNRISE, sunset=SUNSET, timezone="Asia/Tbilisi", **overrides):
    """A complete single-day response, 24 hourly steps.

    Unknown keys in `overrides` raise — a typo would otherwise silently leave the
    default in place and make the test assert the wrong thing.
    """
    hours = [f"{date}T{h:02d}:00" for h in range(24)]
    hourly = {"time": hours}
    for key, default in HOURLY_DEFAULTS.items():
        hourly[key] = _series(overrides.pop(key, default), len(hours))
    daily = {"time": [date], "sunrise": [f"{date}T{sunrise}"], "sunset": [f"{date}T{sunset}"]}
    for key, default in DAILY_DEFAULTS.items():
        daily[key] = [overrides.pop(key, default)]
    if overrides:
        raise TypeError(f"unknown fixture field(s): {', '.join(sorted(overrides))}")
    return {"timezone": timezone, "hourly": hourly, "daily": daily}


def om_overview(dates, sunrise=SUNRISE, sunset=SUNSET, timezone="Asia/Tbilisi", **overrides):
    """A multi-day response. Overrides are given PER DAY (one value per date) and
    broadcast over that day's 24 hours; a bare scalar applies to every day."""
    n = len(dates)

    def per_day(value):
        return list(value) if isinstance(value, (list, tuple)) else [value] * n

    hours = [f"{d}T{h:02d}:00" for d in dates for h in range(24)]
    hourly = {"time": hours}
    for key, default in HOURLY_DEFAULTS.items():
        by_day = per_day(overrides.pop(key, default))
        hourly[key] = [v for v in by_day for _ in range(24)]
    daily = {"time": list(dates),
             "sunrise": [f"{d}T{sunrise}" for d in dates],
             "sunset": [f"{d}T{sunset}" for d in dates]}
    for key, default in DAILY_DEFAULTS.items():
        daily[key] = per_day(overrides.pop(key, default))
    if overrides:
        raise TypeError(f"unknown fixture field(s): {', '.join(sorted(overrides))}")
    return {"timezone": timezone, "hourly": hourly, "daily": daily}


def om_null(data, *fields):
    """Null out hourly series in place — models a meteo model that omits them
    (open-meteo answers with a null series rather than an error)."""
    n = len(data["hourly"]["time"])
    for f in fields:
        data["hourly"][f] = [None] * n
    return data


def ideal_hour(**overrides):
    """Плоский словарь для criteria.score_hour, где КАЖДЫЙ параметр идеален.

    Тесты вето и штрафов портят ровно одно поле и смотрят, что изменилось —
    так видно, что сработало именно проверяемое правило, а не соседнее.
    """
    raw = {
        # параметры со шкалой
        "wind_10m": 3.0, "wind_925": 4.0, "wind_850": 5.0,
        "gust_factor": 1.15, "gust_delta": 1.0,
        "dir_offset": 10.0,
        "w_star": 2.5, "bl_depth": 1500.0, "thermal_index": -4.0,
        "cape": 200.0, "lifted_index": 3.0,
        "cloud_low": 20.0, "base_clearance": 800.0,
        "precip_prob": 0.0, "visibility": 30000.0,
        "shear_100m": 1.5, "spread": 5.0, "window_hours": 6.0,
        # входы правил, у которых нет собственной шкалы
        "precip_mm": 0.0, "cin": 100.0, "wind_at_base": 6.0,
        "base_over_route": 500.0, "dir_misalign": 10.0,
    }
    raw.update(overrides)
    return raw


def site(**overrides):
    """A saved-site dict as engine functions expect it (south-facing, 1500 m)."""
    s = {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
         "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}
    s.update(overrides)
    return s
