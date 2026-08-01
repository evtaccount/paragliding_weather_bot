"""Точка входа: бот и API живут в одном процессе."""
import asyncio
import importlib
import os

import pytest


async def test_both_surfaces_start(monkeypatch):
    """Если одна из двух корутин не запущена, приложение молча работает
    наполовину: бот отвечает, приложение белое (или наоборот)."""
    import app

    started = []

    async def fake_polling():
        started.append("polling")
        await asyncio.sleep(0)

    async def fake_serve():
        started.append("http")
        await asyncio.sleep(0)

    monkeypatch.setattr(app, "_run_polling", fake_polling)
    monkeypatch.setattr(app, "_run_http", fake_serve)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    await app.main()
    assert sorted(started) == ["http", "polling"]


async def test_a_dead_bot_takes_the_process_down(monkeypatch):
    """Иначе контейнер выглядит живым, а бот в нём молчит: restart не сработает,
    потому что процесс не упал."""
    import app

    async def boom():
        raise RuntimeError("polling умер")

    async def forever():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app, "_run_polling", boom)
    monkeypatch.setattr(app, "_run_http", forever)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(app.main(), timeout=5)


async def test_a_dead_api_takes_the_process_down(monkeypatch):
    import app

    async def boom():
        raise RuntimeError("uvicorn умер")

    async def forever():
        await asyncio.sleep(3600)

    monkeypatch.setattr(app, "_run_polling", forever)
    monkeypatch.setattr(app, "_run_http", boom)
    monkeypatch.setattr(app, "_bootstrap", lambda: {})

    with pytest.raises(BaseExceptionGroup):
        await asyncio.wait_for(app.main(), timeout=5)


async def test_storage_is_migrated_before_either_surface_starts(monkeypatch):
    """Первый запрос не должен успеть прийти в пустую базу."""
    import app

    order = []
    monkeypatch.setattr(app, "_bootstrap", lambda: order.append("bootstrap"))

    async def note_polling():
        order.append("polling")

    async def note_http():
        order.append("http")

    monkeypatch.setattr(app, "_run_polling", note_polling)
    monkeypatch.setattr(app, "_run_http", note_http)

    await app.main()
    assert order[0] == "bootstrap"


def test_api_binds_loopback_by_default():
    """Дефолт — bare metal: перед процессом никто не стоит, и loopback —
    единственная граница. Compose переопределяет его на 0.0.0.0, см.
    test_api_host_can_be_overridden_for_docker."""
    import app
    assert app.API_HOST == "127.0.0.1"


def test_api_host_can_be_overridden_for_docker():
    """pgbot и caddy — разные контейнеры с разными сетевыми пространствами:
    сокет на loopback внутри pgbot снаружи контейнера не виден, и
    reverse_proxy pgbot:8080 в Caddy упирался бы в ECONNREFUSED на КАЖДЫЙ
    запрос. docker-compose.yml поэтому кладёт API_HOST=0.0.0.0 в environment
    pgbot — граница «наружу не выходим» держит раскладка портов (expose без
    ports), а не бинд.
    """
    import app

    old = os.environ.get("API_HOST")
    os.environ["API_HOST"] = "0.0.0.0"
    try:
        importlib.reload(app)
        assert app.API_HOST == "0.0.0.0"
    finally:
        # Реестр модулей общий на весь тестовый процесс: не откатить —
        # значит, что все тесты после этого увидят app.API_HOST == "0.0.0.0",
        # включая test_api_binds_loopback_by_default при другом порядке сбора.
        if old is None:
            os.environ.pop("API_HOST", None)
        else:
            os.environ["API_HOST"] = old
        importlib.reload(app)
