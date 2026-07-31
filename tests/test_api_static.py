"""Статика и здоровье процесса."""
import pytest


async def test_health_needs_no_authorization(client):
    """Проверка живости не должна требовать initData: её дёргает Docker,
    у которого никакой подписи нет."""
    r = await client.get("/api/health")
    assert r.status_code == 200


async def test_health_says_which_db_is_open(client):
    """Самая частая ошибка раскатки — том не примонтирован и база пустая.
    Число стартов в ответе показывает это одной командой."""
    body = (await client.get("/api/health")).json()
    assert body["sites"] == 2


async def test_health_does_not_leak_the_absolute_db_path(client):
    """/api/health не требует авторизации — путь на диске сервера не отвечает
    ни на один вопрос, для которого этот эндпоинт существует, а посторонним
    в интернете (открытый режим) знать его незачем."""
    body = (await client.get("/api/health")).json()
    assert "db" not in body


async def test_the_smoke_page_is_served(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "telegram-web-app.js" in r.text


async def test_the_smoke_page_needs_no_authorization(client):
    """Страница обязана открыться без подписи — она её как раз и добывает."""
    assert (await client.get("/")).status_code == 200
