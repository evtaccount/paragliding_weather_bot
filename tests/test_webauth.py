"""Проверка подписи Telegram Mini App."""
import json
import time
import urllib.parse

import pytest

import webauth
from tma import TOKEN, init_data, sign


def test_valid_init_data_yields_the_user():
    user = webauth.verify(init_data(uid=777), TOKEN)
    assert user.id == 777
    assert user.username == "pilot"


def test_forged_hash_is_rejected():
    raw = init_data()
    tampered = raw[:-1] + ("0" if raw[-1] != "0" else "1")
    with pytest.raises(webauth.AuthError):
        webauth.verify(tampered, TOKEN)


def test_another_bots_token_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(token="43:OTHER"), TOKEN)


def test_swapped_payload_is_rejected():
    """Подменить user, оставив чужой hash, не выходит."""
    raw = init_data(uid=1)
    pairs = dict(urllib.parse.parse_qsl(raw))
    pairs["user"] = json.dumps({"id": 2, "first_name": "Чужой"}, ensure_ascii=False,
                               separators=(",", ":"))
    with pytest.raises(webauth.AuthError):
        webauth.verify(urllib.parse.urlencode(pairs), TOKEN)


def test_expired_auth_date_is_rejected():
    old = int(time.time()) - webauth.MAX_AGE_SEC - 60
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(auth_date=old), TOKEN)


def test_auth_date_just_inside_the_window_passes():
    fresh = int(time.time()) - webauth.MAX_AGE_SEC + 60
    assert webauth.verify(init_data(auth_date=fresh), TOKEN).id == 1


def test_missing_hash_is_rejected():
    raw = urllib.parse.urlencode({"auth_date": str(int(time.time())),
                                  "user": '{"id":1}'})
    with pytest.raises(webauth.AuthError):
        webauth.verify(raw, TOKEN)


def test_empty_init_data_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify("", TOKEN)


def test_missing_user_is_rejected():
    """initData без user приходит из инлайн-режима; наши эндпоинты без id
    работать не могут, и молча подставлять ноль нельзя."""
    with pytest.raises(webauth.AuthError):
        webauth.verify(sign({"auth_date": str(int(time.time())), "query_id": "AAE"}),
                       TOKEN)


def test_empty_bot_token_is_rejected():
    """Пустой BOT_TOKEN даёт формально корректный секрет, и подпись, посчитанная
    тем же пустым токеном, сошлась бы: проверка превратилась бы в театр."""
    with pytest.raises(webauth.AuthError):
        webauth.verify(init_data(token=""), "")


def test_cyrillic_values_survive_percent_encoding():
    """Имя кириллицей и пробелы в подписи — типичный случай, и именно на нём
    ломается реализация, считающая hash по закодированной строке."""
    raw = init_data(uid=5, user_extra={"first_name": "Пётр Иванович",
                                       "last_name": "фон Дер Вааль"})
    assert webauth.verify(raw, TOKEN).id == 5


def test_field_order_does_not_matter():
    """Клиент вправе прислать поля в любом порядке — сортируем мы сами."""
    raw = init_data(uid=9)
    pairs = urllib.parse.parse_qsl(raw)
    shuffled = urllib.parse.urlencode(list(reversed(pairs)))
    assert webauth.verify(shuffled, TOKEN).id == 9


def test_duplicate_key_is_rejected():
    """Второй user= после подписанного: строка подписи и разбор полей взяли бы
    разные значения, если не запретить повтор явно."""
    raw = init_data(uid=1) + "&user=" + urllib.parse.quote('{"id":2}')
    with pytest.raises(webauth.AuthError):
        webauth.verify(raw, TOKEN)


def test_unparsable_auth_date_is_rejected():
    with pytest.raises(webauth.AuthError):
        webauth.verify(sign({"auth_date": "позавчера", "user": '{"id":1}'}), TOKEN)


def test_signature_field_stays_inside_the_checked_string():
    """Telegram добавляет signature (Ed25519 для сторонней проверки). Из
    HMAC-строки исключается только hash, поэтому подпись с signature обязана
    сходиться — иначе в проде каждый запрос получит 401."""
    raw = init_data(uid=3, signature="abcdef")
    assert webauth.verify(raw, TOKEN).id == 3
