"""Кэш держит сырьё; текст, PNG и факты считаются только тогда, когда их просят.

До этого _fetch_build рендерил 2-3 PNG через Pillow на каждый промах кэша —
и рендерил бы их на каждый запрос из приложения, где они не нужны.
"""
import asyncio
import pathlib

import pytest

import charts
import engine
import forecast
from fixtures import DATE, om_1day


@pytest.fixture()
def net(monkeypatch):
    """Подменяет сетевой запрос ответом-фикстурой и считает обращения.

    Тот же приём, что в tests/test_engine_model.py: бот не мокает HTTP целиком,
    а подменяет forecast._fetch_main. Побочный запрос за потолком уже заглушён
    автофикстурой no_ceiling_request из conftest.
    """
    calls = []

    async def fake(url):
        calls.append(url)
        return om_1day()

    monkeypatch.setattr(forecast, "_fetch_main", fake)
    return calls


@pytest.fixture()
def count_png(monkeypatch):
    """Считает, сколько раз рисовалась метеограмма.

    Патчится charts, а не engine: engine импортирует функцию внутри report_1day
    (`from charts import meteogram_png`), то есть достаёт её из charts на каждом
    вызове.
    """
    calls = []
    real = charts.meteogram_png

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(charts, "meteogram_png", counting)
    return calls


def test_get_facts_does_not_render_png(net, count_png):
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    assert count_png == []


def test_get_forecast_renders_png_once(net, count_png):
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(count_png) == 1


def test_facts_then_forecast_hits_network_once(net):
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(net) == 1


def test_assess_day_computed_once_per_entry(net, monkeypatch):
    calls = []
    real = engine.assess_day

    def counting(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(engine, "assess_day", counting)
    asyncio.run(forecast.get_facts("Гудаури", "1d", DATE, model="auto"))
    asyncio.run(forecast.get_forecast("Гудаури", "1d", DATE, model="auto"))
    assert len(calls) == 1


async def test_wind_grid_data_returns_numbers_not_a_picture(net, monkeypatch):
    """Приложение рисует графики само. get_wind_grid отдаёт PNG — он остаётся
    чату; для HTTP нужен тот же словарь до отрисовки."""
    drawn = []
    monkeypatch.setattr(charts, "wind_grid_png",
                        lambda *a, **kw: drawn.append(1) or "/dev/null")

    grid = await forecast.wind_grid_data("Гудаури", DATE, model="auto")

    assert not drawn, "числа не должны стоить отрисовки PNG"
    assert grid["hours"], "часы светового дня"
    assert grid["levels"][0]["hourly"][0]["wind_ms"] is not None


async def test_wind_grid_png_and_data_share_the_warm_cache(net, monkeypatch):
    """Кнопка в чате и экран в приложении не должны стоить двух запросов
    к open-meteo: сетка берётся из того же тёплого кэша 1d."""
    monkeypatch.setattr(charts, "wind_grid_png", lambda *a, **kw: "/dev/null")
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: b"png")

    await forecast.wind_grid_data("Гудаури", DATE, model="auto")
    await forecast.get_wind_grid("Гудаури", DATE, model="auto")

    assert len(net) == 1, f"сходили в сеть {len(net)} раза вместо одного"
