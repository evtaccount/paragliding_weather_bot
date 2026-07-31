"""Один тяжёлый запрос на пилота — на обе поверхности сразу."""
import asyncio

import pytest

import forecast
import guards
from tma import header


@pytest.fixture()
def slow(monkeypatch):
    """get_facts, который висит, пока тест не разрешит ему закончиться.

    `entered` вместо `asyncio.sleep(0)`: сколько шагов цикла нужно запросу,
    чтобы дойти до захвата слота, — деталь реализации FastAPI, и тест,
    угадывающий её, начнёт мигать при обновлении зависимостей.
    """
    class Gate:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

    gate = Gate()

    async def fake(site, rng, date=None, *, model):
        gate.entered.set()
        await gate.release.wait()
        return {"site": {"name": site}}

    monkeypatch.setattr(forecast, "get_facts", fake)
    return gate


async def test_a_second_request_while_the_first_runs_is_429(client, slow):
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    # wait_for, а не голый await: без троттлинга второй запрос уходит в тот же
    # висящий расчёт, и тест не падает, а зависает навсегда. Зависший тест хуже
    # упавшего — он не говорит, что сломалось, и не даёт красной фазы.
    second = await asyncio.wait_for(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)),
        timeout=5)
    assert second.status_code == 429
    slow.release.set()
    assert (await first).status_code == 200


async def test_the_slot_is_released_after_the_answer(client, slow):
    slow.release.set()
    for _ in range(3):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 200, "слот не освободился после успешного ответа"


async def test_the_slot_is_released_after_a_failure(client, monkeypatch):
    """Иначе одна ошибка запирает пилота до перезапуска процесса."""
    async def boom(site, rng, date=None, *, model):
        raise forecast.ForecastError("Диапазон не понят")

    monkeypatch.setattr(forecast, "get_facts", boom)
    for _ in range(2):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 400


async def test_another_pilot_is_not_blocked(client, slow):
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    slow.release.set()  # второму пилоту висеть незачем
    second = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=2))
    assert second.status_code == 200
    await first


async def test_light_endpoints_are_not_throttled(client, slow):
    """Настройки и список стартов не ходят в сеть: запирать их вместе с
    прогнозом значит гасить весь экран, пока грузится один график."""
    first = asyncio.create_task(
        client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1)))
    await asyncio.wait_for(slow.entered.wait(), timeout=5)
    assert (await client.get("/api/prefs", headers=header(uid=1))).status_code == 200
    assert (await client.get("/api/sites", headers=header(uid=1))).status_code == 200
    slow.release.set()
    await first


async def test_the_api_shares_the_registry_with_the_bot(client, slow):
    """Реестр общий по решению: открыть приложение, пока бот считает тот же
    прогноз, — это второй запрос того же пилота."""
    guards.INFLIGHT.acquire(1)
    try:
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 429
    finally:
        guards.INFLIGHT.release(1)


async def test_the_api_has_no_cooldown(client, monkeypatch):
    """10-секундная пауза между командами чата к приложению не применяется:
    там каждое действие — продолжение уже выданного результата."""
    monkeypatch.setenv("COOLDOWN_SEC", "60")

    async def fake(site, rng, date=None, *, model):
        return {"site": {"name": site}}

    monkeypatch.setattr(forecast, "get_facts", fake)
    for _ in range(3):
        r = await client.get("/api/forecast?site=Гудаури&range=1d", headers=header(uid=1))
        assert r.status_code == 200
