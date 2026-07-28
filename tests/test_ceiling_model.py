"""Потолок термиков всегда считается по GFS.

У ECMWF и ICON серии пограничного слоя нет вовсе, а под best_match её отдаёт
неизвестно какая подложка. Узкий побочный запрос к GFS подставляется в ответ
выбранной модели по индексу — но только если сетка часов совпала.
"""
import forecast
from fixtures import om_1day


def _gfs(times, values=1400.0):
    """Ответ побочного запроса: одна серия и массив времён."""
    return {"hourly": {"time": list(times),
                       "boundary_layer_height": [values] * len(times)}}


def test_splice_replaces_the_series():
    body = om_1day(boundary_layer_height=None)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, _gfs(times)) is True
    assert body["hourly"]["boundary_layer_height"] == [1400.0] * len(times)


def test_splice_overrides_even_a_present_series():
    """Под auto серия есть, но неизвестно от какой подложки — всё равно заменяем."""
    body = om_1day(boundary_layer_height=900.0)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, _gfs(times)) is True
    assert body["hourly"]["boundary_layer_height"][0] == 1400.0


def test_splice_refuses_on_time_mismatch():
    """Разъехавшаяся сетка часов дала бы потолок не от того часа."""
    body = om_1day(boundary_layer_height=None)
    shifted = [t.replace("T0", "T1") for t in body["hourly"]["time"]]
    assert forecast._splice_ceiling(body, _gfs(shifted)) is False
    assert all(v is None for v in body["hourly"]["boundary_layer_height"])


def test_splice_refuses_on_empty_or_broken_response():
    body = om_1day(boundary_layer_height=None)
    times = body["hourly"]["time"]
    assert forecast._splice_ceiling(body, {"hourly": {"time": list(times)}}) is False
    assert forecast._splice_ceiling(body, {}) is False
    assert forecast._splice_ceiling(body, None) is False


def test_route_splice_is_all_or_nothing():
    """Частичная подстановка смешала бы модели по участкам маршрута, и разрыв в
    профиле потолка читался бы как метеорология, а не как артефакт запроса."""
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    times = a["hourly"]["time"]
    good, bad = _gfs(times), _gfs([t.replace("T0", "T1") for t in times])
    assert forecast._splice_ceiling_all([a, b], [good, bad]) is False
    assert all(v is None for v in a["hourly"]["boundary_layer_height"])  # и первая не тронута


def test_route_splice_refuses_on_point_count_mismatch():
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    assert forecast._splice_ceiling_all([a, b], [_gfs(a["hourly"]["time"])]) is False
    assert forecast._splice_ceiling_all([a, b], None) is False


def test_route_splice_applies_to_every_point():
    a, b = om_1day(boundary_layer_height=None), om_1day(boundary_layer_height=None)
    times = a["hourly"]["time"]
    assert forecast._splice_ceiling_all([a, b], [_gfs(times), _gfs(times)]) is True
    assert a["hourly"]["boundary_layer_height"][0] == 1400.0
    assert b["hourly"]["boundary_layer_height"][0] == 1400.0


async def test_route_weather_splices_ceiling_from_gfs(monkeypatch):
    """На маршруте потолок должен быть из той же модели, что и на старте —
    иначе «потолок» значит разное в двух частях одного ответа."""
    import engine
    from route import Sample

    times = om_1day()["hourly"]["time"]
    calls = []

    async def fake_weather(url):
        calls.append(url)
        return [om_1day(boundary_layer_height=None)]

    async def fake_ceiling(url):
        calls.append(url)
        return [_gfs(times)]

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "_fetch_ceiling", fake_ceiling)
    monkeypatch.setattr(engine, "get_model_key", lambda: "ecmwf")
    forecast._rcache.clear()

    samples = [Sample(km=0.0, lat=42.0, lon=44.0)]
    bodies = await forecast._ensure_route_weather(samples, "2026-07-29")

    assert bodies[0]["hourly"]["boundary_layer_height"][0] == 1400.0
    assert any("models=gfs_seamless" in u for u in calls)


async def test_route_weather_skips_side_request_when_gfs_selected(monkeypatch):
    import engine
    from route import Sample

    async def fake_weather(url):
        return [om_1day()]

    async def fail_ceiling(url):
        raise AssertionError("побочный запрос не нужен, когда выбрана сама GFS")

    monkeypatch.setattr(forecast, "_fetch_route_weather", fake_weather)
    monkeypatch.setattr(forecast, "_fetch_ceiling", fail_ceiling)
    monkeypatch.setattr(engine, "get_model_key", lambda: "gfs")
    forecast._rcache.clear()

    await forecast._ensure_route_weather([Sample(km=0.0, lat=42.0, lon=44.0)], "2026-07-29")
