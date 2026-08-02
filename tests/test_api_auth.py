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


async def test_empty_allowlist_closes_the_http_surface(client, allowlist):
    """Единственное место, где HTTP строже чата.

    В чате пустой список означает «кто нашёл моего бота» — надо знать имя бота
    в Telegram. У HTTP то же умолчание означает «кто нашёл мой сайт», а домен
    публикуется сам: Let's Encrypt отдаёт каждое имя в Certificate
    Transparency, и оно ищется на crt.sh. На сервере, поднятом ровно с
    умолчанием из .env.example, подпись постороннего id получала 200 на
    GET /api/sites с координатами и заметками, 201 на POST и 204 на DELETE
    чужого старта — библиотека общая (финальное ревью ветки, безопасность, I2).
    """
    allowlist("")
    assert (await client.get("/api/prefs", headers=header(uid=99))).status_code == 403


async def test_the_closed_surface_names_the_variable_to_fill(client, allowlist):
    """Отказ читает владелец, а не посторонний: молчаливый 403 выглядит как
    поломка приложения, и чинить его пойдут в код, а не в .env."""
    allowlist("")
    r = await client.get("/api/prefs", headers=header(uid=99))
    assert "ALLOWED_USER_IDS" in r.text


async def test_an_empty_allowlist_closes_the_chat_too(allowlist):
    """Пустой список закрывает ОБЕ поверхности, а не одну.

    Раньше чат на пустом списке пускал кого угодно — на том доводе, что до
    него надо знать имя бота в Telegram. Довод перестал работать, когда
    появилось приложение: библиотека стартов у них ОДНА, и пущенный в чат
    посторонний читает, заводит и удаляет старты пилота ровно так же. Отказ по
    умолчанию ошибается в безопасную сторону: запертый владелец правит .env и
    перезапускает, а открытый бот находят раньше него.
    """
    import guards
    allowlist("")

    async def handler(event, data):
        raise AssertionError("чат пропустил постороннего при пустом списке")

    refusals = []

    class _Stranger:
        from_user = type("U", (), {"id": 999999, "username": "stranger"})()

        async def answer(self, text, *args, **kwargs):
            refusals.append(text)

    assert await guards.WhitelistMiddleware()(handler, _Stranger(), {}) is None
    # Отказ называет id: посторонний пересылает его владельцу, владелец
    # вписывает в .env — единственный путь внутрь, когда список пуст.
    assert "999999" in refusals[0]


async def test_the_owner_is_refused_too_when_the_list_is_empty(allowlist):
    """Пустой список не значит «пускать своих»: своих в нём просто нет.

    Проверяется отдельно от постороннего, потому что соблазн сделать исключение
    возникает именно здесь — «ну хотя бы владельца». Исключения нет: id
    владельца отличается от чужого только тем, что он вписан в .env.
    """
    import guards
    allowlist("")

    async def handler(event, data):
        raise AssertionError("чат пропустил владельца при пустом списке")

    class _Owner:
        from_user = type("U", (), {"id": 1, "username": "owner"})()

        async def answer(self, *args, **kwargs):
            pass

    assert await guards.WhitelistMiddleware()(handler, _Owner(), {}) is None


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
