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
]
# get_facts появляется в задаче 11 и дописывается в этот список там же.
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
# тихих отката `model or engine.DEFAULT_MODEL_KEY` (`_resolve`, `_fetch_build`,
# `_ensure_route_weather`) плюс собственный `model=None` у `cached_dates` —
# та же форма бага, что и до этой задачи, просто на уровень глубже. Если
# дефолт вернётся в любом из этих мест, тесты ниже должны упасть.

NO_DEFAULT_ONLY = [
    (forecast._resolve,             "model"),
    (forecast._fetch_build,         "model"),
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
