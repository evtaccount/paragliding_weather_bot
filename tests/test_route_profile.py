"""Сборка профиля маршрута: два запроса, кэш, форма результата, деградация."""
import datetime as dt

import pytest

import forecast
import route
import store
from fixtures import om_route

PTS = [route.Point(42.0, 44.0, "старт"), route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]
# Дата вычисляется, а не задаётся константой: get_route проверяет горизонт прогноза,
# и зафиксированная дата протухла бы через две недели после написания теста.
DATE = dt.date.today().isoformat()

REQUIRED_POINT_FIELDS = {
    "km", "leg_length_km", "role", "lat", "lon", "name", "track_bearing_deg",
    "eta", "eta_fixed", "terrain_m", "terrain_point_m", "is_terrain_peak",
    "cloud_base_m", "working_band_m", "wind_along_kmh", "wind_cross_kmh",
    "wind_working_alt_kmh", "wind_working_alt_dir", "effective_ground_speed_kmh",
    "crab_limited", "window", "time_margin_min", "w_star_ms", "site_match", "weather",
}


def _n(url):
    """Сколько локаций запрошено — ответ обязан совпасть по длине."""
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
    """Подменяет оба сетевых вызова; возвращает счётчики обращений."""
    calls = {"weather": 0, "terrain": 0}

    async def fake_weather(url):
        calls["weather"] += 1
        return om_route(_n(url))

    async def fake_terrain(coords):
        calls["terrain"] += 1
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    return calls


async def test_profile_shape(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert p["route"]["total_km"] == pytest.approx(40.0, abs=0.5)
    assert p["route"]["date"] == DATE
    assert p["route"]["sample_step_km"] == pytest.approx(10.0)
    assert p["route"]["avg_route_speed_kmh"] == 25.0
    assert len(p["points"]) == 5
    assert REQUIRED_POINT_FIELDS <= set(p["points"][0])


async def test_roles_assigned(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert p["points"][0]["role"] == "takeoff"
    assert p["points"][-1]["role"] == "goal"


async def test_second_call_is_served_from_cache(api):
    await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    await forecast.get_route(PTS, "Тест", DATE, departure_h=12.5, cfg=store.DEFAULT_PREFS)
    assert api["weather"] == 1
    assert api["terrain"] == 1


async def test_departure_defaults_to_window_start(api):
    p = await forecast.get_route(PTS, "Тест", DATE, cfg=store.DEFAULT_PREFS)
    assert p["route"]["departure"] is not None
    assert p["points"][0]["eta"] == p["route"]["departure"]


async def test_terrain_failure_degrades_loudly(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def failing_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", failing_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert all(pt["working_band_m"] is None for pt in p["points"])
    assert any("рельеф" in n.lower() for n in p["notes"])


async def test_no_thermal_window_at_start_is_reported(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url), boundary_layer_height=100.0, shortwave_radiation=10.0)

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    with pytest.raises(forecast.ForecastError) as e:
        await forecast.get_route(PTS, "Тест", DATE, cfg=store.DEFAULT_PREFS)
    assert "время" in str(e.value).lower()


async def test_date_beyond_forecast_horizon_rejected(api):
    far = (dt.date.today() + dt.timedelta(days=40)).isoformat()
    with pytest.raises(forecast.ForecastError) as e:
        await forecast.get_route(PTS, "Тест", far, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert "прогноз" in str(e.value).lower()


async def test_past_date_rejected(api):
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with pytest.raises(forecast.ForecastError):
        await forecast.get_route(PTS, "Тест", past, departure_h=11.5, cfg=store.DEFAULT_PREFS)


async def test_arrival_past_midnight_is_truncated_and_reported(api):
    import store
    slow = store.Prefs(avg_route_speed_kmh=10.0)   # 40 км от 23:00 уходят за полночь
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=23.0, cfg=slow)
    assert any("сутк" in n.lower() for n in p["notes"])
    assert p["points"][-1]["eta"] is None
    assert p["points"][-1]["weather"] == {}        # погода за границей не считается
    assert p["points"][0]["eta"] == "23:00"


async def test_permanent_model_reaches_the_route_weather_fetch(monkeypatch):
    """Regression for review finding 4. cfg.model_key должен доехать и до самого
    запроса погоды по маршруту (URL несёт models=<id выбранной модели>), и до
    подписи в карточке — иначе /model меняет галочку, а маршрут всегда
    считается по auto."""
    import store
    seen = {}

    async def fake_weather(url):
        seen["url"] = url
        return om_route(_n(url))

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    cfg = store.Prefs(model_key="gfs")
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=cfg)
    assert "models=gfs_seamless" in seen["url"]
    assert p["route"]["model"] == "GFS"
