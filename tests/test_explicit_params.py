"""Модель и настройки приходят параметром: домен не должен знать, кто спрашивает.

Проверяется сигнатура, а не вызов: корутина с недостающим keyword-only
аргументом падает ещё до await, и оборачивать это в asyncio.run незачем.
"""
import inspect

import pytest

import forecast

REQUIRED = [
    (forecast.get_forecast,  "model"),
    (forecast.get_wind_grid, "model"),
    (forecast.get_analysis,  "model"),
    (forecast.scan_week,     "model"),
    (forecast.get_route,     "cfg"),
    (forecast.get_facts,     "model"),
]
#
# forecast.get_route НЕ получает отдельный параметр model, в отличие от брифа
# задачи 9: модель маршрута выводится из cfg.model_key (упрощение задачи 7,
# см. task-7-report.md, отклонение №3). Отдельной проверки на "model" здесь
# нет — она дублировала бы cfg и такого параметра у функции не существует.


def test_required_params_have_no_default():
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: {name} с дефолтом"


def test_required_params_are_keyword_only():
    """Позиционными их делать нельзя: у get_route перед ними стоит
    departure_h со значением по умолчанию."""
    for fn, name in REQUIRED:
        p = inspect.signature(fn).parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: {name}"


# ---------------------------------------------------------------- fix round 1
#
# Пять публичных функций выше защищены, но одним слоем ниже оставались три
# тихих отката `model or engine.DEFAULT_MODEL_KEY` (`_resolve`, `_fetch_build` —
# переименована в задаче 11 в `_fetch_raw`, `_ensure_route_weather`) плюс
# собственный `model=None` у `cached_dates` — та же форма бага, что и до этой
# задачи, просто на уровень глубже. Если дефолт вернётся в любом из этих мест,
# тесты ниже должны упасть.

NO_DEFAULT_ONLY = [
    (forecast._resolve,             "model"),
    (forecast._fetch_raw,           "model"),
    (forecast._ensure,              "model"),
    (forecast._ensure_route_weather, "model"),
]
# Приватные хелперы одним уровнем ниже пяти публичных функций: keyword-only
# для них не требуется (план явно даёт `_resolve(site_name, rng, date, model)`
# без `*` — единственный вызывающий передаёт model и позиционно, и именованно),
# но default-заглушки None быть не должно — иначе `or engine.DEFAULT_MODEL_KEY`
# может тихо вернуться.


def test_private_fetch_helpers_have_no_default_model():
    for fn, name in NO_DEFAULT_ONLY:
        p = inspect.signature(fn).parameters[name]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: {name} с дефолтом"


def test_cached_dates_model_is_mandatory_and_keyword_only():
    p = inspect.signature(forecast.cached_dates).parameters["model"]
    assert p.default is inspect.Parameter.empty, "cached_dates: model с дефолтом"
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, "cached_dates: model не keyword-only"
    with pytest.raises(TypeError):
        forecast.cached_dates("Гудаури", "1d")


# ---------------------------------------------------------------- fix round 2
#
# Раунд 1 проверял только сигнатуру (`p.default is empty`) — она не видит
# фолбэк, вернувшийся в ТЕЛЕ функции. Ре-ревью это показал: подставил обратно
# `model or engine.DEFAULT_MODEL_KEY` в `return` у `_resolve` и отдельно в
# тело `_ensure_route_weather`, сигнатуры не трогал — весь набор остался
# зелёным (801 passed) оба раза. Тесты ниже реально вызывают функции с
# `model=None` (мандаторный keyword-only параметр это по-прежнему разрешает)
# и проверяют, что значение доходит до URL-строителя НЕПОДМЕНЁННЫМ.


def test_resolve_propagates_none_instead_of_substituting_default():
    """Если бы _resolve подставляла DEFAULT_MODEL_KEY, вызов с model=None и
    вызов с model="auto" схлопнулись бы в один и тот же ключ кэша — один
    пилот получил бы прогноз, посчитанный для другого."""
    _site, _date, key = forecast._resolve("Гудаури", "1d", "2026-07-29", model=None)
    assert key[3] is None


async def test_fetch_path_propagates_none_instead_of_substituting_default(monkeypatch):
    """_ensure → _fetch_raw → engine.build_url. engine.model_id(None) кидает
    KeyError ДО любого сетевого запроса; если бы _fetch_raw подменяла
    model=None на DEFAULT_MODEL_KEY, build_url собрал бы валидный URL под
    best_match и тест ничего бы не заметил. _fetch_main/_fetch_ceiling
    подмоканы на AssertionError — если фолбэк всё же вернётся, тест обязан
    упасть сразу, а не зависнуть на настоящем HTTP-запросе."""
    async def boom(*a, **k):
        raise AssertionError("сетевой запрос не должен был случиться раньше KeyError")

    monkeypatch.setattr(forecast, "_fetch_main", boom)
    monkeypatch.setattr(forecast, "_fetch_ceiling", boom)
    site = {"name": "Тест", "lat": 42.0, "lon": 44.0, "elevation_m": 1500,
            "aspect": "Ю", "aspect_deg": 180.0, "notes": ""}
    with pytest.raises(KeyError):
        await forecast._ensure(site, "1d", "2026-07-29",
                               ("Тест", "1d", "2026-07-29", None), model=None)


async def test_ensure_route_weather_propagates_none_instead_of_substituting_default(monkeypatch):
    """Тот же трюк для маршрута: engine.route_weather_url(model=None) кидает
    KeyError раньше сети — если бы _ensure_route_weather подменяла None на
    DEFAULT_MODEL_KEY, запрос ушёл бы под best_match незаметно."""
    from route import Sample

    async def boom(*a, **k):
        raise AssertionError("сетевой запрос не должен был случиться раньше KeyError")

    monkeypatch.setattr(forecast, "_fetch_route_weather", boom)
    monkeypatch.setattr(forecast, "_fetch_ceiling", boom)
    forecast._rcache.clear()
    with pytest.raises(KeyError):
        await forecast._ensure_route_weather([Sample(km=0.0, lat=42.0, lon=44.0)],
                                             "2026-07-29", model=None)


# ---------------------------------------------------------------- fix round 3
#
# Обёртки вокруг get_route объявляли `cfg=None` позиционно и передавали дальше.
# Все вызывающие cfg передают, поэтому дефолт был недостижим — но пропуск в
# будущем всплыл бы AttributeError'ом в глубине _evaluate вместо TypeError'а на
# границе, ровно того, ради чего cfg делали обязательным.

WRAPPERS = [
    (forecast.get_route_section,  "cfg"),
    (forecast.get_route_analysis, "cfg"),
]


def test_route_wrappers_require_cfg():
    for fn, name in WRAPPERS:
        p = inspect.signature(fn).parameters[name]
        assert p.default is inspect.Parameter.empty, f"{fn.__name__}: {name} с дефолтом"
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}: {name} не keyword-only"


def test_route_wrappers_raise_type_error_without_cfg():
    """Именно TypeError на границе, а не падение внутри скоринга."""
    for fn, _name in WRAPPERS:
        with pytest.raises(TypeError):
            fn([], None, "2026-07-29")


def test_send_route_requires_cfg():
    """bot._send_route — та же обёртка одним слоем выше."""
    import bot as botmod
    p = inspect.signature(botmod._send_route).parameters["cfg"]
    assert p.default is inspect.Parameter.empty, "_send_route: cfg с дефолтом"
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, "_send_route: cfg не keyword-only"
    with pytest.raises(TypeError):
        botmod._send_route(None, [], None, "2026-07-29", None)
