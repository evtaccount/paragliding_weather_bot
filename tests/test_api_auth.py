"""Ворота HTTP-поверхности: подпись и список допущенных."""
import logging
import time

import pytest

from tma import TOKEN, header, init_data


async def test_valid_init_data_gets_through(client):
    r = await client.get("/api/prefs", headers=header(uid=1))
    assert r.status_code == 200


async def test_missing_header_is_401(client):
    assert (await client.get("/api/prefs")).status_code == 401


async def test_wrong_scheme_is_401(client):
    """Bearer <initData> — типичная ошибка клиента; молча принимать её нельзя,
    иначе схема авторизации перестаёт что-либо значить."""
    r = await client.get("/api/prefs",
                         headers={"Authorization": "Bearer " + init_data()})
    assert r.status_code == 401


async def test_forged_hash_is_401(client):
    raw = init_data()
    bad = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    r = await client.get("/api/prefs", headers={"Authorization": "tma " + bad})
    assert r.status_code == 401


async def test_expired_auth_date_is_401(client):
    old = int(time.time()) - 25 * 3600
    r = await client.get("/api/prefs", headers=header(auth_date=old))
    assert r.status_code == 401


async def test_401_does_not_explain_why(client):
    """Причина отказа уходит в лог. Ответ, объясняющий «просрочено» против
    «подпись не сошлась», помогает подбирать подпись."""
    raw = init_data()
    bad = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    r = await client.get("/api/prefs", headers={"Authorization": "tma " + bad})
    body = r.text.lower()
    assert "подпись" not in body and "просроч" not in body


async def test_user_outside_the_allowlist_is_403(client, allowlist):
    allowlist("1")
    r = await client.get("/api/prefs", headers=header(uid=2))
    assert r.status_code == 403
    assert "2" in r.text, "пилот должен увидеть свой id, чтобы попросить доступ"


async def test_user_inside_the_allowlist_passes(client, allowlist):
    allowlist("1,2")
    assert (await client.get("/api/prefs", headers=header(uid=2))).status_code == 200


async def test_empty_allowlist_lets_everyone_in(client, allowlist):
    """Открытый режим — тот же, что у бота: пустой список никого не отсекает."""
    allowlist("")
    assert (await client.get("/api/prefs", headers=header(uid=99))).status_code == 200


async def test_a_403_refusal_is_logged(client, allowlist, caplog):
    """guards.WhitelistMiddleware логирует отказ чату (log.info("refused user
    %s ...")). Здесь пришелец предъявляет ВАЛИДНУЮ подпись Telegram — это
    ровно то событие, которое стоит видеть в логе новой публичной
    поверхности, а не только молчаливый 403 в ответе."""
    allowlist("1")
    with caplog.at_level(logging.INFO, logger="pgbot.api"):
        r = await client.get("/api/prefs", headers=header(uid=2))
    assert r.status_code == 403
    assert any("2" in rec.message for rec in caplog.records)


async def test_the_api_uses_the_same_allowlist_as_the_bot(client, allowlist):
    """Два независимых списка разъехались бы в первый же день: пилота добавили
    в бот, а приложение его не пускает."""
    import guards
    allowlist("7")
    assert guards.allowed_ids() == frozenset({7})
    assert (await client.get("/api/prefs", headers=header(uid=7))).status_code == 200
