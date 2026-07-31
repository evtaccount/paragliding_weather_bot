"""Скоринг точек маршрута, скан времени вылета и обратное направление."""
import datetime as dt

import pytest

import criteria
import forecast
import route
import store
from fixtures import om_route

PTS = [route.Point(42.0, 44.0, "старт"), route.Point(42.0 + 40.0 / 111.195, 44.0, "финиш")]
DATE = dt.date.today().isoformat()


def _n(url):
    return url.split("latitude=")[1].split("&")[0].count(",") + 1


@pytest.fixture()
def api(monkeypatch):
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


# ---------------------------------------------------------------- скоринг точек
async def test_every_point_gets_a_score_and_a_role_profile(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert all(pt["score"] is not None for pt in p["points"])
    assert p["points"][0]["profile"] == "takeoff"
    assert p["points"][-1]["profile"] == "goal"
    assert {pt["profile"] for pt in p["points"][1:-1]} == {"enroute"}


async def test_verdict_block_is_present(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    v = p["verdict"]
    assert set(v) >= {"score", "category", "feasibility", "bottleneck",
                      "flyable_until_km", "blocked_at_km"}
    assert v["feasibility"] in criteria.FEASIBILITY


def test_derived_inputs_match_the_engine_on_a_whole_hour():
    """Синтетический одночасовой блок должен давать те же производные, что и
    настоящий: иначе интерполяция спеки 1 меняет физику, а не только момент."""
    import engine
    from fixtures import om_1day, site

    data = om_1day()
    s = site()
    ctx = engine.day_context(data, s)
    real = engine.derive_hour(data["hourly"], 12, s, ctx)
    synth = {k: [v[12]] for k, v in data["hourly"].items()}
    assert engine.derive_hour(synth, 0, s, ctx) == real


async def test_storm_ahead_is_attached_to_points(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert all("storm_ahead" in pt for pt in p["points"])


async def test_a_blocked_point_does_not_zero_its_neighbours(monkeypatch):
    """Вето на одной точке — это «обрывается на N-м км», а не «весь день нелётный»."""
    async def fake_weather(url):
        n = _n(url)
        bodies = om_route(n)
        bodies[-1]["hourly"]["visibility"] = [500.0] * 24   # туман только на финише
        return bodies

    async def fake_terrain(coords):
        return [1000.0] * len(coords)

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert p["points"][0]["score"] > 0
    assert p["points"][-1]["score"] == 0
    assert p["verdict"]["feasibility"] == "blocked_at_km"
    assert p["verdict"]["score"] > 0


# ---------------------------------------------------------------- скан вылета
async def test_departure_scan_costs_no_extra_requests(api):
    p = await forecast.get_route(PTS, "Тест", DATE, cfg=store.DEFAULT_PREFS)
    assert api["weather"] == 1
    assert api["terrain"] == 1
    assert len(p["departure_scan"]) >= 2


async def test_scan_entries_carry_time_score_and_feasibility(api):
    p = await forecast.get_route(PTS, "Тест", DATE, cfg=store.DEFAULT_PREFS)
    assert set(p["departure_scan"][0]) == {"departure", "score", "feasibility"}


async def test_best_departure_is_the_best_completable(api):
    p = await forecast.get_route(PTS, "Тест", DATE, cfg=store.DEFAULT_PREFS)
    ok = [e for e in p["departure_scan"] if e["feasibility"] == "completable"]
    if ok:
        assert p["best_departure"]["score"] == max(e["score"] for e in ok)


async def test_best_departure_is_none_when_nothing_is_completable(monkeypatch, api):
    """Показать «лучший из непроходимых» значит предложить пилоту выбрать,
    каким способом не долететь."""
    monkeypatch.setattr(forecast, "_score_samples",
                        lambda samples, bodies, date: criteria.RouteAssessment(
                            30.0, "no_fly", "🔴", "нелётно", "blocked_at_km"))
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert p["best_departure"] is None


# ---------------------------------------------------------------- обратный маршрут
async def test_reverse_direction_is_computed_without_new_requests(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert api["weather"] == 1
    assert set(p["reverse"]) == {"score", "feasibility", "better"}


async def test_reverse_is_flagged_better_only_past_the_threshold(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    gain = (p["reverse"]["score"] or 0) - (p["verdict"]["score"] or 0)
    assert p["reverse"]["better"] is (gain >= criteria.REVERSE_GAIN)


# ---------------------------------------------------------------- поля для спеки 3
async def test_profile_carries_the_fine_terrain_grid(api):
    """Разрезу нужен рельеф МЕЖДУ расчётными точками, а не только под ними."""
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    t = p["terrain"]
    assert len(t["km"]) == len(t["elevations"])
    assert t["km"][0] == 0.0
    assert t["km"] == sorted(t["km"])
    assert t["km"][-1] == pytest.approx(p["route"]["total_km"], rel=1e-3)


async def test_terrain_grid_is_finer_than_the_weather_points(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert len(p["terrain"]["km"]) > len(p["points"])


async def test_no_terrain_means_no_grid(monkeypatch):
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert p["terrain"] is None


async def test_points_carry_turnpoint_ceiling_and_subscores(api):
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    first, middle = p["points"][0], p["points"][1]
    assert first["is_turnpoint"] is True
    assert middle["is_turnpoint"] is False
    assert first["thermal_ceiling_m"] > first["terrain_m"]
    assert first["subs"] and first["groups"]


async def test_ceiling_is_none_without_terrain(monkeypatch):
    """Потолок считается ОТ рельефа: нет рельефа — нет и потолка, а не ноль."""
    async def fake_weather(url):
        return om_route(_n(url))

    async def fake_terrain(coords):
        return None

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "fetch_terrain", fake_terrain)
    p = await forecast.get_route(PTS, "Тест", DATE, departure_h=11.5, cfg=store.DEFAULT_PREFS)
    assert all(pt["thermal_ceiling_m"] is None for pt in p["points"])
