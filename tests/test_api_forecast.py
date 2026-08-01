"""Прогноз, сетка ветра и скан через HTTP."""
import datetime as dt

import pytest

import forecast
import store
from tma import header

TODAY = dt.date.today().isoformat()


@pytest.fixture()
def facts(monkeypatch):
    """Патчим get_facts: сам расчёт покрыт тестами домена, здесь проверяется
    адаптер — что доехало до вызова и что вернулось наружу."""
    calls = []

    async def fake(site, rng, date=None, *, model):
        calls.append((site, rng, date, model))
        return {"site": {"name": site}, "date": date or TODAY, "range": rng,
                "hourly_daytime": [{"time": "13:00", "temp_c": 21.0}]}

    monkeypatch.setattr(forecast, "get_facts", fake)
    return calls


async def test_forecast_returns_numbers(client, facts):
    body = (await client.get("/api/forecast?site=Гудаури&range=1d",
                             headers=header())).json()
    assert body["hourly_daytime"][0]["temp_c"] == 21.0


async def test_forecast_uses_the_pilots_permanent_model(client, facts):
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
    assert facts[-1][3] == "ecmwf"


async def test_query_model_overrides_the_permanent_one(client, facts):
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d&model=gfs",
                     headers=header(uid=1))
    assert facts[-1][3] == "gfs"


async def test_query_model_does_not_persist(client, facts):
    """Кнопка модели под прогнозом — разовый выбор, как в чате: она не должна
    менять постоянную настройку пилота."""
    store.set_model(1, "ecmwf")
    await client.get("/api/forecast?site=Гудаури&range=1d&model=gfs",
                     headers=header(uid=1))
    assert store.prefs(1).model_key == "ecmwf"


async def test_unknown_query_model_is_400(client, facts):
    r = await client.get("/api/forecast?site=Гудаури&range=1d&model=нет",
                         headers=header())
    assert r.status_code == 400
    assert not facts, "неизвестная модель не должна доехать до домена"


async def test_two_pilots_get_their_own_models(client, facts):
    store.set_model(1, "ecmwf")
    store.set_model(2, "icon")
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
    await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=2))
    assert [c[3] for c in facts] == ["ecmwf", "icon"]


async def test_unknown_site_is_404(client):
    r = await client.get("/api/forecast?site=нетутакого&range=1d", headers=header())
    assert r.status_code == 404


async def test_bad_range_is_400_with_the_domain_text(client, monkeypatch):
    async def boom(site, rng, date=None, *, model):
        raise forecast.ForecastError("Диапазон не понят: 5d")

    monkeypatch.setattr(forecast, "get_facts", boom)
    r = await client.get("/api/forecast?site=Гудаури&range=5d", headers=header())
    assert r.status_code == 400
    assert "5d" in r.json()["detail"]


async def test_upstream_failure_is_502(client, monkeypatch):
    import httpx

    async def boom(site, rng, date=None, *, model):
        raise httpx.ConnectError("open-meteo down")

    monkeypatch.setattr(forecast, "get_facts", boom)
    r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header())
    assert r.status_code == 502
    assert "open-meteo down" not in r.text, "внутренности наружу не отдаём"


async def test_wind_grid_returns_levels(client, monkeypatch):
    async def fake(site, date, *, model):
        return {"date": date, "launch_m": 2200, "hours": [10, 11],
                "levels": [{"label": "10m", "alt_m_msl": 2210, "is_launch": True,
                            "hourly": [{"hour": 10, "wind_ms": 3.0, "dir_deg": 180}]}]}

    monkeypatch.setattr(forecast, "wind_grid_data", fake)
    body = (await client.get(f"/api/forecast/wind-grid?site=Гудаури&date={TODAY}",
                             headers=header())).json()
    assert body["levels"][0]["hourly"][0]["wind_ms"] == 3.0


async def test_scan_returns_flyable_days(client, monkeypatch):
    async def fake(*, model):
        return {"sites": [{"name": "Гудаури", "aspect": 180.0, "days": []}],
                "empty": ["Лалискури"], "failed": []}

    monkeypatch.setattr(forecast, "scan_week", fake)
    body = (await client.get("/api/scan", headers=header())).json()
    assert body["empty"] == ["Лалискури"]


async def test_scan_uses_the_pilots_model(client, monkeypatch):
    seen = []

    async def fake(*, model):
        seen.append(model)
        return {"sites": [], "empty": [], "failed": []}

    monkeypatch.setattr(forecast, "scan_week", fake)
    store.set_model(1, "icon")
    await client.get("/api/scan", headers=header(uid=1))
    assert seen == ["icon"]


async def test_forecast_needs_authorization(client, facts):
    assert (await client.get("/api/forecast?site=Гудаури&range=1d")).status_code == 401


async def test_an_adhoc_point_is_a_site_for_the_endpoint_too(client, facts):
    """Разовая точка по координатам живёт в adhoc, а не в библиотеке стартов.
    Проверка существования только через find_site отдала бы 404 на законную
    точку ещё до вызова домена — тест на уровне forecast этого не поймал бы,
    он ходит мимо api.py."""
    name = forecast.register_adhoc(42.5, 44.5, 2000)
    r = await client.get(f"/api/forecast?site={name}&range=1d", headers=header())
    assert r.status_code == 200
    assert facts, "запрос должен был дойти до домена"
