"""Разбор дня и профиль маршрута через HTTP."""
import pytest

import forecast
import store
from tma import header

ROWS = [[42.4776, 44.4787, "старт"], [42.1176, 44.4787, "финиш"]]
BODY = {"points": ROWS, "name": "Гудаури", "date": "2026-08-01", "departure": "11:30"}


async def test_analysis_returns_text(client, monkeypatch):
    async def fake(site, rng, date=None, deep=False, *, model):
        return "РАЗБОР"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    r = await client.post("/api/analysis",
                          json={"site": "Гудаури", "range": "1d"}, headers=header())
    assert r.json()["text"] == "РАЗБОР"


async def test_analysis_passes_deep_through(client, monkeypatch):
    seen = []

    async def fake(site, rng, date=None, deep=False, *, model):
        seen.append(deep)
        return "РАЗБОР"

    monkeypatch.setattr(forecast, "get_analysis", fake)
    await client.post("/api/analysis",
                      json={"site": "Гудаури", "range": "1d", "deep": True},
                      headers=header())
    assert seen == [True]


async def test_route_returns_a_profile(client, monkeypatch):
    async def fake(points, name, date, departure_h=None, *, cfg):
        return {"route": {"name": name, "total_km": 40.0}, "points": [],
                "verdict": {"score": 70}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    body = (await client.post("/api/route", json=BODY, headers=header())).json()
    assert body["route"]["total_km"] == 40.0


async def test_route_uses_the_pilots_own_settings(client, monkeypatch):
    """cfg резолвит адаптер: домену user_id недоступен."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    store.set_speed(1, 33.0)
    store.set_model(1, "icon")
    await client.post("/api/route", json=BODY, headers=header(uid=1))
    assert seen[0].avg_route_speed_kmh == 33.0
    assert seen[0].model_key == "icon"


async def test_two_pilots_get_their_own_settings(client, monkeypatch):
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg.avg_route_speed_kmh)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    store.set_speed(1, 20.0)
    store.set_speed(2, 40.0)
    await client.post("/api/route", json=BODY, headers=header(uid=1))
    await client.post("/api/route", json=BODY, headers=header(uid=2))
    assert seen == [20.0, 40.0]


async def test_departure_time_reaches_the_domain(client, monkeypatch):
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(departure_h)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    await client.post("/api/route", json=BODY, headers=header())
    assert seen == [11.5], "11:30 — это 11.5 часа"


async def test_route_without_departure_lets_the_domain_choose(client, monkeypatch):
    """Без времени вылета домен берёт начало термического окна — подставлять
    здесь свой полдень значило бы спорить с расчётом."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(departure_h)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    await client.post("/api/route", json={k: v for k, v in BODY.items()
                                          if k != "departure"}, headers=header())
    assert seen == [None]


async def test_a_single_point_route_is_400(client):
    r = await client.post("/api/route", json={**BODY, "points": ROWS[:1]},
                          headers=header())
    assert r.status_code == 400


async def test_too_many_points_is_400(client):
    import route
    many = [[42.0 + i / 1000.0, 44.0, ""] for i in range(route.MAX_POINTS + 1)]
    r = await client.post("/api/route", json={**BODY, "points": many},
                          headers=header())
    assert r.status_code == 400


async def test_route_analysis_returns_text(client, monkeypatch):
    async def fake(points, name, date, departure_h=None, *, cfg):
        return "РАЗБОР МАРШРУТА"

    monkeypatch.setattr(forecast, "get_route_analysis", fake)
    r = await client.post("/api/route/analysis", json=BODY, headers=header())
    assert r.json()["text"] == "РАЗБОР МАРШРУТА"


async def test_route_needs_authorization(client):
    assert (await client.post("/api/route", json=BODY)).status_code == 401


@pytest.fixture()
def route_cfg(monkeypatch):
    """Записывает cfg, с которым позвали расчёт маршрута."""
    seen = []

    async def fake(points, name, date, departure_h=None, *, cfg):
        seen.append(cfg)
        return {"route": {}, "points": [], "verdict": {}, "terrain": None, "notes": []}

    monkeypatch.setattr(forecast, "get_route", fake)
    return seen


async def test_route_model_overrides_the_permanent_one(client, route_cfg):
    store.set_model(1, "ecmwf")
    await client.post("/api/route", json={**BODY, "model": "gfs"}, headers=header(uid=1))
    assert route_cfg[0].model_key == "gfs"


async def test_route_model_does_not_persist(client, route_cfg):
    """Разовый выбор модели не должен менять постоянную настройку пилота."""
    store.set_model(1, "ecmwf")
    await client.post("/api/route", json={**BODY, "model": "gfs"}, headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_an_unknown_route_model_is_400(client, route_cfg):
    r = await client.post("/api/route", json={**BODY, "model": "нет-такой"},
                          headers=header(uid=1))
    assert r.status_code == 400
    assert not route_cfg, "неизвестная модель не должна доехать до домена"
