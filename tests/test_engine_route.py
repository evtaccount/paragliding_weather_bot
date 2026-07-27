"""Мульти-точечный URL и векторное осреднение ветра по рабочему слою."""
import pytest

import engine
from fixtures import om_1day

COORDS = [(42.4776, 44.4787), (42.3891, 44.5512), (42.2104, 44.6890)]


def test_url_lists_all_coordinates():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "latitude=42.4776,42.3891,42.2104" in url
    assert "longitude=44.4787,44.5512,44.6890" in url


def test_url_pins_timezone_explicitly():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "timezone=Asia%2FTbilisi" in url or "timezone=Asia/Tbilisi" in url
    assert "timezone=auto" not in url


def test_url_asks_one_day_with_the_full_variable_set():
    url = engine.route_weather_url(COORDS, "2026-07-28", "Asia/Tbilisi")
    assert "start_date=2026-07-28&end_date=2026-07-28" in url
    assert engine.H_1D in url


def test_mean_wind_vector_averages_levels_in_the_layer():
    data = om_1day(wind_speed_925hPa=6.0, wind_direction_925hPa=180.0,
                   wind_speed_850hPa=10.0, wind_direction_850hPa=180.0,
                   geopotential_height_925hPa=1500.0, geopotential_height_850hPa=2000.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert speed == pytest.approx(8.0, abs=0.1)
    assert deg == pytest.approx(180.0, abs=0.5)


def test_opposite_directions_cancel_vectorially():
    """Осреднение модулей дало бы 10 м/с; векторное — почти ноль. Именно в этом
    смысл требования осреднять u/v, а не скорости."""
    data = om_1day(wind_speed_925hPa=10.0, wind_direction_925hPa=0.0,
                   wind_speed_850hPa=10.0, wind_direction_850hPa=180.0,
                   geopotential_height_925hPa=1500.0, geopotential_height_850hPa=2000.0)
    speed, _ = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert speed == pytest.approx(0.0, abs=0.2)


def test_levels_below_the_layer_are_dropped():
    data = om_1day(wind_speed_10m=20.0, wind_direction_10m=90.0,
                   wind_speed_925hPa=5.0, wind_direction_925hPa=180.0,
                   geopotential_height_925hPa=1500.0,
                   geopotential_height_850hPa=2000.0, wind_speed_850hPa=5.0,
                   wind_direction_850hPa=180.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0)
    assert deg == pytest.approx(180.0, abs=1.0)   # приземный ветер не участвует
    assert speed == pytest.approx(5.0, abs=0.2)


def test_empty_layer_falls_back_to_nearest_level():
    data = om_1day(geopotential_height_925hPa=1500.0, geopotential_height_850hPa=3000.0)
    speed, deg = engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1900.0, 2000.0)
    assert speed is not None and deg is not None


def test_no_levels_at_all_gives_none():
    data = om_1day(wind_speed_10m=None, wind_speed_80m=None, wind_speed_120m=None,
                   wind_speed_925hPa=None, wind_speed_850hPa=None, wind_speed_700hPa=None)
    assert engine.mean_wind_vector(data["hourly"], 12, 1000.0, 1400.0, 2100.0) == (None, None)
