"""Подписанная initData для тестов.

Живёт отдельным модулем, потому что нужен и тестам самой проверки, и каждому
тесту эндпоинта: без него в половине файлов завелась бы своя копия формулы
подписи, и опечатка в копии выглядела бы как баг сервера.
"""
import hashlib
import hmac
import json
import time
import urllib.parse

TOKEN = "42:TEST"  # тот же, что conftest кладёт в BOT_TOKEN


def sign(fields: dict, token: str = TOKEN) -> str:
    """Собрать initData с корректным hash.

    Значения подписываются РАСКОДИРОВАННЫМИ, а в строку уходят
    percent-encoded — ровно так делает Telegram, и ровно на этом ломаются
    наивные реализации: подпись считают по уже закодированной строке.
    """
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode({**fields, "hash": digest})


def init_data(uid: int = 1, token: str = TOKEN, *, auth_date: int | None = None,
              user_extra: dict | None = None, **fields) -> str:
    user = {"id": uid, "first_name": "Пилот", "username": "pilot",
            "language_code": "ru", **(user_extra or {})}
    base = {"auth_date": str(int(time.time()) if auth_date is None else auth_date),
            "query_id": "AAE",
            "user": json.dumps(user, ensure_ascii=False, separators=(",", ":"))}
    return sign({**base, **fields}, token)


def header(uid: int = 1, token: str = TOKEN, **kw) -> dict:
    return {"Authorization": "tma " + init_data(uid, token, **kw)}
