"""Статика и здоровье процесса."""
import os

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


def test_static_root_is_the_built_webapp():
    """Отдаётся собранное приложение из webapp/dist, а не заглушка static/.
    В Docker статику раздаёт сам pgbot (Caddy её больше не читает, см.
    tests/test_deploy_config.py), а на bare-metal-раскатке (README, вариант B)
    другого пути к странице нет вовсе: промах константы — 404 на корне при
    полностью здоровом /api/health."""
    import api
    assert api.STATIC_DIR.endswith(os.path.join("webapp", "dist"))


def test_a_missing_build_does_not_take_the_whole_process_down():
    """webapp/dist — артефакт сборки и лежит в .gitignore: на свежем клоне без
    `make webapp-build` каталога нет. StaticFiles проверяет каталог прямо в
    конструкторе и бросает RuntimeError, а монтируется он на импорте api.py,
    который app.py делает на старте (app.py:14) — то есть несобранное
    приложение уронило бы вместе с собой и чат по polling. Отказ должен
    остаться на одном URL, а не на всём процессе."""
    import api
    api._static_files(os.path.join(os.path.dirname(__file__), "no-such-build"))


async def test_the_built_page_is_served_at_the_root(client):
    """Корень открывается без подписи — страница её как раз и добывает,
    требовать initData тут не у кого. Проверка сквозная: точка монтирования в
    api.py и реальный результат `npm run build` должны сойтись, иначе клиент
    Telegram получит 404 на пустом месте."""
    import api
    if not os.path.isdir(api.STATIC_DIR):
        pytest.skip("webapp не собран — `make webapp-build`")
    r = await client.get("/")
    assert r.status_code == 200
    assert "telegram-web-app.js" in r.text
