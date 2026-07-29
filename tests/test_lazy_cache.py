"""Кэш держит сырьё; текст, PNG и факты считаются только тогда, когда их просят.

До этого _fetch_build рендерил 2-3 PNG через Pillow на каждый промах кэша —
и рендерил бы их на каждый запрос из приложения, где они не нужны.
"""
import pytest

import asyncio

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
